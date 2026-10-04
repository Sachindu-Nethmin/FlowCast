import AppKit
import CoreImage.CIFilterBuiltins
import Foundation
import Network
import Observation
import SwiftUI
import SystemConfiguration

/// The doc cards on your phone: pick a page to record, watch progress, and
/// answer "FlowCast needs you" without touching the Mac — whose screen is busy
/// being filmed.
///
/// Like src/phone.py it listens on the LAN, so anything on the same Wi-Fi can
/// reach it, and it can start recordings that drive the mouse. Every request
/// therefore needs the token in the link; without it the answer is 403. The
/// token is kept between launches (a saved link keeps working after the app
/// restarts or updates) until you press "New link".
@Observable
final class PhoneBridge {
    var isRunning = false
    var url: String?
    /// Other ways to reach this Mac: the same server by its Bonjour name, which
    /// hostel / office proxies usually send direct, and other interfaces.
    var alternates: [(label: String, url: String)] = []
    var error: String?
    /// Phones that have opened the page this session (address → last seen).
    var devices: [String: Date] = [:]
    var lastDevice: String? { devices.max { $0.value < $1.value }?.key }
    /// Phones that reached the Mac with an old link (address → when).
    var staleLinks: [String: Date] = [:]
    /// The HTTP proxy this Mac's network uses, if any — phones on such networks
    /// often send the Mac's address to the proxy, which cannot reach it.
    var proxy: String?
    private(set) var token: String
    @ObservationIgnored private var listener: NWListener?
    @ObservationIgnored private weak var studio: Studio?
    @ObservationIgnored private var port = 8766
    @ObservationIgnored private let monitor = NWPathMonitor()

    init(studio: Studio) {
        self.studio = studio
        let d = UserDefaults.standard
        if let saved = d.string(forKey: "phoneToken"), saved.count == 32 {
            token = saved
        } else {
            token = Self.newToken()
            d.set(token, forKey: "phoneToken")
        }
        // Wi-Fi changed (hotspot joined, cable plugged in): new address, new QR.
        monitor.pathUpdateHandler = { [weak self] _ in
            DispatchQueue.main.async { self?.refreshAddresses() }
        }
        monitor.start(queue: .global(qos: .utility))
    }

    private static func newToken() -> String {
        (0..<16).map { _ in String(format: "%02x", UInt8.random(in: 0...255)) }.joined()
    }

    /// Revoke every link handed out so far.
    func resetLink() {
        token = Self.newToken()
        UserDefaults.standard.set(token, forKey: "phoneToken")
        devices = [:]
        refreshAddresses()
    }

    func refreshAddresses() {
        proxy = Self.systemProxy()
        guard isRunning else { return }
        let ips = Self.addresses()
        let primary = ips.first?.ip ?? "localhost"
        url = "http://\(primary):\(port)/?t=\(token)"
        var alt: [(String, String)] = []
        if let name = Self.bonjourName() {
            alt.append(("Mac name (\(name).local) — try this if the first one will not open",
                        "http://\(name).local:\(port)/?t=\(token)"))
        }
        for x in ips.dropFirst() {
            alt.append(("\(x.label) (\(x.ip))", "http://\(x.ip):\(port)/?t=\(token)"))
        }
        alternates = alt
    }

    /// Starts listening; while the port is still held (the copy of the app this
    /// one replaced has not quit yet) it keeps retrying for ~15 s.
    func start(port: Int, attempt: Int = 0) {
        stop()
        self.port = port
        do {
            let params = NWParameters.tcp
            params.allowLocalEndpointReuse = true
            let l = try NWListener(using: params, on: NWEndpoint.Port(rawValue: UInt16(port))!)
            l.newConnectionHandler = { [weak self] conn in self?.accept(conn) }
            l.stateUpdateHandler = { [weak self] state in
                guard let self else { return }
                switch state {
                case .ready:
                    self.isRunning = true
                    self.error = nil
                    self.refreshAddresses()
                    print("phone link: \(self.url ?? "")"); fflush(stdout)
                case .failed(let e):
                    self.isRunning = false
                    self.error = e.localizedDescription
                    if attempt < 10 {
                        DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) { [weak self] in
                            guard let self, !self.isRunning else { return }
                            self.start(port: port, attempt: attempt + 1)
                        }
                    }
                case .cancelled:
                    self.isRunning = false
                default: break
                }
            }
            l.start(queue: .main)
            listener = l
        } catch {
            self.error = error.localizedDescription
            if attempt < 10 {
                DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) { [weak self] in
                    self?.start(port: port, attempt: attempt + 1)
                }
            }
        }
    }

    func stop() {
        listener?.cancel()
        listener = nil
        isRunning = false
        url = nil
    }

    // ── HTTP ─────────────────────────────────────────────────────────────────

    private func accept(_ conn: NWConnection) {
        conn.start(queue: .main)
        receive(conn, buffer: Data())
    }

    private func receive(_ conn: NWConnection, buffer: Data) {
        conn.receive(minimumIncompleteLength: 1, maximumLength: 65536) { [weak self] data, _, done, err in
            guard let self else { return }
            var buf = buffer
            if let data { buf.append(data) }
            if let req = Request(buf), req.path == "/api/screen", req.query["t"] == self.token {
                // The current screen, captured now (step prompts no longer
                // save one) — a JPEG, small enough for the phone.
                DispatchQueue.global(qos: .userInitiated).async {
                    let file = FileManager.default.temporaryDirectory
                        .appendingPathComponent("flowcast-screen-\(UUID().uuidString).jpg")
                    let p = Process()
                    p.executableURL = URL(fileURLWithPath: "/usr/sbin/screencapture")
                    p.arguments = ["-x", "-t", "jpg", file.path]
                    try? p.run()
                    p.waitUntilExit()
                    let data = (try? Data(contentsOf: file)) ?? Data()
                    try? FileManager.default.removeItem(at: file)
                    DispatchQueue.main.async {
                        self.respond(conn, data.isEmpty ? .text("cannot capture the screen", code: 404)
                                     : Response(code: 200, type: "image/jpeg", body: data))
                    }
                }
                return
            }
            if let req = Request(buf) {
                if case let .hostPort(host, _) = conn.endpoint {
                    let addr = "\(host)".replacingOccurrences(of: "::ffff:", with: "")
                    if addr != "127.0.0.1" && addr != "::1" && !addr.hasPrefix("fe80") {
                        if req.query["t"] == self.token {
                            self.devices[addr] = Date()
                            self.staleLinks[addr] = nil
                        } else if req.query["t"] != nil {
                            self.staleLinks[addr] = Date()
                        }
                    }
                }
                self.respond(conn, self.route(req))
            } else if done || err != nil || buf.count > 1_000_000 {
                conn.cancel()
            } else {
                self.receive(conn, buffer: buf)
            }
        }
    }

    private func respond(_ conn: NWConnection, _ r: Response) {
        let reason = [200: "OK", 206: "Partial Content", 403: "Forbidden", 404: "Not Found",
                      416: "Range Not Satisfiable"][r.code] ?? "Error"
        var head = "HTTP/1.1 \(r.code) \(reason)\r\n"
        head += "Content-Type: \(r.type)\r\nContent-Length: \(r.body.count)\r\n"
        for (k, v) in r.extra { head += "\(k): \(v)\r\n" }
        head += "Cache-Control: no-store\r\nConnection: close\r\n\r\n"
        conn.send(content: Data(head.utf8) + r.body, completion: .contentProcessed { _ in conn.cancel() })
    }

    private func route(_ req: Request) -> Response {
        guard req.query["t"] == token else { return .text("forbidden", code: 403) }
        guard let studio else { return .text("gone", code: 500) }
        switch (req.method, req.path) {
        case ("GET", "/"):
            return Response(code: 200, type: "text/html; charset=utf-8", body: Data(phonePage.utf8))
        case ("GET", "/api/pages"):
            let pages = studio.pages(for: nil).map { p -> [String: Any] in
                ["slug": p.slug, "title": p.displayTitle, "area": p.area, "verdict": p.verdict,
                 "description": String(p.description.prefix(160)), "steps": p.stepCount,
                 "actions": p.actionCount, "coverage": p.coverage,
                 "blockers": (p.blockers + p.notes).map(blockerLabel),
                 "recorded": p.verified != nil || studio.video(for: p) != nil, "url": p.url,
                 "needsKeys": studio.inputs.missing(for: p).count,
                 "proven": studio.proven[p.slug] != nil,
                 "unfinished": studio.unfinishedRecording(p)?.clips ?? 0,
                 "mode": Self.modeText(studio.mode(p))]
            }
            let s = studio.catalog?.summary
            var summary: [String: Int] = [:]
            summary["total"] = s?.total ?? 0
            summary["walkthroughs"] = s?.walkthroughs ?? 0
            summary["ready"] = s?.ready ?? 0
            summary["auto"] = s?.auto ?? 0
            summary["keys"] = s?.keys ?? 0
            summary["setup"] = s?.setup ?? 0
            summary["partial"] = s?.partial ?? 0
            let mac: String = Host.current().localizedName ?? "your Mac"
            return .json(["pages": pages, "mac": mac, "summary": summary])
        case ("GET", "/api/jobs"):
            let jobs = studio.jobs.reversed().map { j -> [String: Any] in
                var o: [String: Any] = ["id": j.id.uuidString, "slug": j.page.slug, "title": j.page.displayTitle,
                                        "guided": j.guided, "screen": j.stage.usesScreen,
                                        "recording": j.stage == .record && j.status.isActive,
                                        "task": j.task, "eta": studio.etaText(j),
                                        "canMake": j.stage == .record && (j.status == .failed || j.status == .cancelled)
                                            && studio.recordedClips(j) > 0,
                                        "status": j.status.label, "active": j.status.isActive,
                                        "stage": j.stage.title, "progress": j.progress,
                                        "error": j.error ?? "",
                                        "notes": j.notes.suffix(3).map(\.text)]
                if let h = j.help, j.status == .needsHelp {
                    o["help"] = ["label": h.label, "reason": h.reason, "step": h.step, "seq": h.seq,
                                 "shot": h.screenshot != nil, "manual": h.isManual,
                                 "tried": h.tried, "screen": h.screen,
                                 "kind": h.kind, "stepTitle": h.stepTitle, "actions": h.actions,
                                 "done": h.done, "next": h.next ?? -1, "canUndo": h.canUndo]
                }
                return o
            }
            return .json(["jobs": Array(jobs)])
        case ("GET", "/api/shot"):
            guard let id = req.query["id"], let job = studio.jobs.first(where: { $0.id.uuidString == id }),
                  let path = job.help?.screenshot, let data = FileManager.default.contents(atPath: path)
            else { return .text("no screenshot", code: 404) }
            return Response(code: 200, type: "image/png", body: data)
        case ("GET", "/api/videos"):
            let videos: [[String: Any]] = studio.library.map { v in
                ["id": v.folderName, "title": v.title, "duration": v.duration,
                 "made": v.modified.formatted(date: .abbreviated, time: .omitted),
                 "size": ByteCountFormatter.string(fromByteCount: v.bytes, countStyle: .file),
                 "thumb": v.thumbnail != nil, "description": descriptionText(v)]
            }
            return .json(["videos": videos])
        case ("GET", "/media/video"), ("GET", "/media/thumb"):
            // Only folders the Library lists — an id is never used as a path.
            guard let id = req.query["id"], let v = studio.library.first(where: { $0.folderName == id }) else {
                return .text("unknown video", code: 404)
            }
            if req.path == "/media/thumb" {
                guard let t = v.thumbnail, let data = FileManager.default.contents(atPath: t) else {
                    return .text("no thumbnail", code: 404)
                }
                return Response(code: 200, type: "image/png", body: data)
            }
            return Self.ranged(URL(fileURLWithPath: v.video), range: req.headers["range"])
        case ("POST", "/api/make"):
            guard let slug = req.json["slug"] as? String,
                  let page = studio.catalog?.pages.first(where: { $0.slug == slug }) else {
                return .text("unknown page", code: 404)
            }
            if req.json["mode"] as? String == "recording" {      // no screen, no keys needed
                return studio.makeVideo(fromRecordingOf: page) != nil
                    ? .json(["ok": true]) : .json(["ok": false, "error": "No unfinished recording of this page."])
            }
            // Keys are entered on the Mac only (this page is plain HTTP on the
            // LAN); without them the page is recorded with placeholders.
            let mode = req.json["mode"] as? String
            // Say why when nothing was queued: the phone used to show
            // "Starting on your Mac…" forever.
            guard page.isRecordable else {
                return .json(["ok": false, "error": "FlowCast cannot record this page."])
            }
            guard studio.enqueue([page], mode: mode == "guided" || mode == "auto" ? mode : nil) != nil else {
                return .json(["ok": false, "error": "Could not queue it — see FlowCast Studio on the Mac."])
            }
            return .json(["ok": true])
        case ("POST", "/api/control"):
            guard let id = req.json["id"] as? String, let action = req.json["action"] as? String,
                  let job = studio.jobs.first(where: { $0.id.uuidString == id }) else {
                return .text("unknown job", code: 404)
            }
            switch action {
            case "restart": studio.restart(job)
            case "stop": studio.cancel(job, show: false)
            case "finish": studio.finishNow(job)
            case "make": studio.makeVideo(fromRecordingOf: job)
            default: return .text("unknown action", code: 400)
            }
            return .json(["ok": true])
        case ("POST", "/api/answer"):
            guard let id = req.json["id"] as? String, let text = req.json["text"] as? String,
                  let job = studio.jobs.first(where: { $0.id.uuidString == id }) else {
                return .text("unknown job", code: 404)
            }
            studio.answer(job, text)
            return .json(["ok": true])
        default:
            return .text("not found", code: 404)
        }
    }

    // ── helpers ──────────────────────────────────────────────────────────────

    /// A video in pieces: phones (Safari above all) stream with Range requests
    /// and will not play a file served whole. Never more than 4 MB in memory.
    fileprivate static func ranged(_ url: URL, range: String?) -> Response {
        let size = (try? url.resourceValues(forKeys: [.fileSizeKey]).fileSize).map(Int64.init) ?? 0
        guard size > 0, let fh = try? FileHandle(forReadingFrom: url) else {
            return .text("cannot read video", code: 404)
        }
        defer { try? fh.close() }
        let chunk: Int64 = 4 << 20
        var start: Int64 = 0
        var end: Int64 = min(size, chunk) - 1
        var partial = false
        if let r = range, r.hasPrefix("bytes=") {
            let spec = r.dropFirst(6).split(separator: "-", omittingEmptySubsequences: false)
            if spec.count == 2 {
                if spec[0].isEmpty, let suffix = Int64(spec[1]) {          // bytes=-500: the last 500
                    start = max(0, size - suffix)
                } else {
                    start = Int64(spec[0]) ?? 0
                }
                end = min(Int64(spec[1]) ?? (start + chunk - 1), start + chunk - 1, size - 1)
                partial = true
            }
        }
        guard start < size, start <= end else {
            return Response(code: 416, type: "text/plain", body: Data(),
                            extra: ["Content-Range": "bytes */\(size)"])
        }
        try? fh.seek(toOffset: UInt64(start))
        let data = (try? fh.read(upToCount: Int(end - start + 1))) ?? Data()
        var extra = ["Accept-Ranges": "bytes"]
        if partial || data.count < size {
            extra["Content-Range"] = "bytes \(start)-\(start + Int64(data.count) - 1)/\(size)"
            return Response(code: 206, type: "video/mp4", body: data, extra: extra)
        }
        return Response(code: 200, type: "video/mp4", body: data, extra: extra)
    }

    static func modeText(_ m: Studio.RunMode) -> String {
        switch m {
        case .firstRun: return "First run · step by step on your phone"
        case .learned: return "Path proven · runs automatically"
        case .handsFree: return "Hands-free ✓"
        }
    }

    /// IPv4 addresses a phone could use, Wi-Fi first.
    static func addresses() -> [(label: String, ip: String)] {
        var ifaddr: UnsafeMutablePointer<ifaddrs>?
        guard getifaddrs(&ifaddr) == 0, let first = ifaddr else { return [] }
        defer { freeifaddrs(ifaddr) }
        var out: [(String, String)] = []
        for ptr in sequence(first: first, next: { $0.pointee.ifa_next }) {
            let ifa = ptr.pointee
            guard let addr = ifa.ifa_addr, addr.pointee.sa_family == UInt8(AF_INET),
                  ifa.ifa_flags & UInt32(IFF_UP) != 0 else { continue }
            let name = String(cString: ifa.ifa_name)
            guard name.hasPrefix("en") || name.hasPrefix("bridge") else { continue }
            var host = [CChar](repeating: 0, count: Int(NI_MAXHOST))
            getnameinfo(addr, socklen_t(addr.pointee.sa_len), &host, socklen_t(host.count), nil, 0, NI_NUMERICHOST)
            let ip = String(cString: host)
            if ip.hasPrefix("169.254.") { continue }
            let label = name == "en0" ? "Wi-Fi" : ip.hasPrefix("172.20.10.") ? "iPhone hotspot / USB" : name
            out.append((label, ip))
        }
        return out.sorted { a, _ in a.0 == "Wi-Fi" }
    }

    static func bonjourName() -> String? {
        SCDynamicStoreCopyLocalHostName(nil) as String?
    }

    static func systemProxy() -> String? {
        guard let p = CFNetworkCopySystemProxySettings()?.takeRetainedValue() as? [String: Any] else { return nil }
        if (p["HTTPEnable"] as? Int) == 1, let host = p["HTTPProxy"] as? String {
            return host + ((p["HTTPPort"] as? Int).map { ":\($0)" } ?? "")
        }
        if (p["ProxyAutoConfigEnable"] as? Int) == 1 {
            return (p["ProxyAutoConfigURLString"] as? String) ?? "an automatic proxy"
        }
        return nil
    }

    static func lanAddress() -> String? {
        var ifaddr: UnsafeMutablePointer<ifaddrs>?
        guard getifaddrs(&ifaddr) == 0, let first = ifaddr else { return nil }
        defer { freeifaddrs(ifaddr) }
        var best: String?
        for ptr in sequence(first: first, next: { $0.pointee.ifa_next }) {
            let ifa = ptr.pointee
            guard let addr = ifa.ifa_addr, addr.pointee.sa_family == UInt8(AF_INET) else { continue }
            let name = String(cString: ifa.ifa_name)
            guard name.hasPrefix("en") else { continue }
            var host = [CChar](repeating: 0, count: Int(NI_MAXHOST))
            getnameinfo(addr, socklen_t(addr.pointee.sa_len), &host, socklen_t(host.count), nil, 0, NI_NUMERICHOST)
            let ip = String(cString: host)
            if name == "en0" { return ip }
            best = best ?? ip
        }
        return best
    }

    func qrImage(for link: String? = nil) -> NSImage? {
        guard let url = link ?? url else { return nil }
        let f = CIFilter.qrCodeGenerator()
        f.message = Data(url.utf8)
        f.correctionLevel = "M"
        guard let out = f.outputImage?.transformed(by: CGAffineTransform(scaleX: 8, y: 8)),
              let cg = CIContext().createCGImage(out, from: out.extent) else { return nil }
        return NSImage(cgImage: cg, size: NSSize(width: out.extent.width / 2, height: out.extent.height / 2))
    }
}

private struct Request {
    let method: String
    let path: String
    let query: [String: String]
    let json: [String: Any]
    let headers: [String: String]

    /// nil until the whole request (headers + Content-Length body) has arrived.
    init?(_ data: Data) {
        guard let sep = data.range(of: Data("\r\n\r\n".utf8)) else { return nil }
        let head = String(decoding: data[..<sep.lowerBound], as: UTF8.self)
        let lines = head.components(separatedBy: "\r\n")
        let parts = lines.first?.split(separator: " ") ?? []
        guard parts.count >= 2 else { return nil }
        var hdrs: [String: String] = [:]
        for l in lines.dropFirst() {
            guard let i = l.firstIndex(of: ":") else { continue }
            hdrs[l[..<i].lowercased()] = l[l.index(after: i)...].trimmingCharacters(in: .whitespaces)
        }
        headers = hdrs
        let length = Int(hdrs["content-length"] ?? "") ?? 0
        let body = data[sep.upperBound...]
        guard body.count >= length else { return nil }
        method = String(parts[0])
        let comps = URLComponents(string: String(parts[1]))
        path = comps?.path ?? "/"
        var q: [String: String] = [:]
        for item in comps?.queryItems ?? [] { q[item.name] = item.value ?? "" }
        query = q
        json = (try? JSONSerialization.jsonObject(with: Data(body.prefix(length)))) as? [String: Any] ?? [:]
    }
}

private struct Response {
    let code: Int
    let type: String
    let body: Data
    var extra: [String: String] = [:]

    static func json(_ obj: Any) -> Response {
        Response(code: 200, type: "application/json",
                 body: (try? JSONSerialization.data(withJSONObject: obj)) ?? Data("{}".utf8))
    }

    static func text(_ s: String, code: Int) -> Response {
        Response(code: code, type: "text/plain", body: Data(s.utf8))
    }
}

struct PhonePopover: View {
    @Environment(PhoneBridge.self) private var phone
    @Environment(AppSettings.self) private var settings

    var body: some View {
        VStack(spacing: 12) {
            Text("FlowCast on your phone").font(.headline)
            if phone.isRunning, let url = phone.url {
                if let qr = phone.qrImage() {
                    Image(nsImage: qr).interpolation(.none).resizable().frame(width: 200, height: 200)
                }
                Text("Scan with your phone's camera. Same Wi-Fi as this Mac.")
                    .font(.caption).foregroundStyle(.secondary).multilineTextAlignment(.center)
                Text(url).font(.caption2.monospaced()).textSelection(.enabled).lineLimit(2)
                HStack {
                    Button("Copy link") {
                        NSPasteboard.general.clearContents()
                        NSPasteboard.general.setString(url, forType: .string)
                    }
                    Button("Stop", role: .destructive) { phone.stop() }
                }
                Text("The link drives this Mac — do not share it. It changes every launch.")
                    .font(.caption2).foregroundStyle(.secondary).multilineTextAlignment(.center)
            } else {
                Text("Browse the doc cards, start videos and answer FlowCast's questions from your phone while the Mac records.")
                    .font(.callout).foregroundStyle(.secondary).multilineTextAlignment(.center)
                Button("Start phone link") { phone.start(port: settings.phonePort) }
                    .buttonStyle(.borderedProminent)
                Toggle("Start it whenever the app opens", isOn: Binding(
                    get: { settings.phoneAtLaunch }, set: { settings.phoneAtLaunch = $0 }))
                    .font(.caption)
                if let e = phone.error { Text(e).font(.caption).foregroundStyle(.red) }
            }
        }
        .padding(18)
        .frame(width: 300)
    }
}

// The phone page. One file, no external assets; talks to the /api routes above.
private let phonePage = #"""
<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>FlowCast Studio</title>
<style>
:root{--bg:#f4f5f7;--card:#fff;--fg:#15171a;--dim:#6b7280;--line:#e5e7eb;--accent:#2563eb;
 --ready:#16a34a;--setup:#ea580c;--partial:#2563eb;--warn:#ea580c;color-scheme:light dark}
@media (prefers-color-scheme:dark){:root{--bg:#0f1115;--card:#181b21;--fg:#e8eaed;--dim:#9aa3ad;--line:#2a2f37}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);
 font:15px/1.45 -apple-system,BlinkMacSystemFont,system-ui,sans-serif;padding-bottom:env(safe-area-inset-bottom)}
header{position:sticky;top:0;z-index:2;background:var(--bg);padding:calc(env(safe-area-inset-top) + 12px) 16px 8px;border-bottom:1px solid var(--line)}
h1{font-size:20px;margin:0 0 2px}.sub{color:var(--dim);font-size:13px}
.chips{display:flex;gap:6px;overflow-x:auto;padding:10px 0 4px;scrollbar-width:none}
.chip{flex:none;border:1px solid var(--line);background:var(--card);color:var(--fg);border-radius:999px;padding:6px 12px;font-size:13px}
.chip.on{background:var(--fg);color:var(--bg);border-color:var(--fg)}
input[type=search]{width:100%;margin-top:8px;padding:9px 12px;border-radius:10px;border:1px solid var(--line);background:var(--card);color:var(--fg);font-size:15px}
main{padding:12px 16px;display:grid;gap:12px}#list{display:grid;gap:12px}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px}
.badge{display:inline-block;font-size:12px;font-weight:600;border-radius:999px;padding:2px 9px}
.ready{color:var(--ready);background:color-mix(in srgb,var(--ready) 14%,transparent)}
.setup{color:var(--setup);background:color-mix(in srgb,var(--setup) 14%,transparent)}
.partial{color:var(--partial);background:color-mix(in srgb,var(--partial) 14%,transparent)}
.auto{color:#0d9488;background:color-mix(in srgb,#0d9488 14%,transparent)}
.keys{color:#6366f1;background:color-mix(in srgb,#6366f1 14%,transparent)}
button.make.auto{background:#0d9488}button.make.keys{background:#6366f1}
.rec{color:#9333ea;background:color-mix(in srgb,#9333ea 14%,transparent);margin-left:4px}
.area{color:var(--dim);font-size:12px;margin-top:8px}.title{font-weight:600;font-size:16px;margin:2px 0 4px}
.desc{color:var(--dim);font-size:13px}.meta{display:flex;gap:12px;color:var(--dim);font-size:12px;margin-top:10px;align-items:center}
.meta .sp{flex:1}button.make{border:0;border-radius:9px;padding:8px 12px;font-weight:600;color:#fff;background:var(--accent);font-size:14px}
button.make.ready{background:var(--ready);color:#fff}
button.make.alt{background:transparent;color:var(--fg);border:1px solid var(--line);margin-right:6px}
.acts{list-style:none;padding:0;margin:8px 0}.acts li{padding:9px 10px;border:1px solid var(--line);border-radius:9px;margin:5px 0;font-size:14px}
.acts li.done{color:var(--dim);text-decoration:line-through}.acts li .again{display:inline-block;float:right;font-size:12px;color:var(--accent);text-decoration:none;font-weight:600}
.row.run{margin-top:14px;padding-top:10px;border-top:1px solid var(--line)}
.task{font-size:14px;margin:6px 0 2px}.eta{font-size:13px;color:var(--dim);margin-top:4px}
.bgjob{border:1px solid var(--line);border-radius:12px;padding:10px 12px;margin:8px 0;font-size:13px}.bgjob .bar{margin:6px 0 4px}.row.run button[data-r=stop]{color:#dc2626}.acts li.next{border-color:var(--accent);background:color-mix(in srgb,var(--accent) 12%,transparent);font-weight:600}
button.doit{width:100%;border:0;border-radius:12px;padding:14px;font-size:17px;font-weight:700;color:#fff;background:var(--accent);margin-top:6px}
.tags{margin-top:8px;display:flex;gap:4px;flex-wrap:wrap}.tag{font-size:11px;color:var(--warn);background:color-mix(in srgb,var(--warn) 12%,transparent);border-radius:999px;padding:1px 7px}
#job{display:none}.job{border:2px solid var(--accent)}.job.help{border-color:var(--warn)}
.bar{height:6px;background:var(--line);border-radius:3px;overflow:hidden;margin:8px 0}.bar>div{height:100%;background:var(--accent)}
.job img{width:100%;border-radius:8px;margin:8px 0;border:1px solid var(--line)}
.row{display:flex;gap:6px;flex-wrap:wrap;margin-top:8px}.row button{flex:1;border:1px solid var(--line);background:var(--card);color:var(--fg);border-radius:9px;padding:9px;font-size:14px}
.row input{flex:3;min-width:0;padding:9px 10px;border-radius:9px;border:1px solid var(--line);background:var(--bg);color:var(--fg);font-size:15px}
.row button.go{flex:1;background:var(--warn);color:#fff;border:0;font-weight:600}
.empty{color:var(--dim);text-align:center;padding:40px 0}
.shotwrap{position:relative}.shotwrap img{display:block}
.mark{position:absolute;width:12px;height:12px;margin:-6px 0 0 -6px;border:1.5px solid #ef4444;border-radius:50%;pointer-events:none;box-shadow:0 0 0 1px rgba(255,255,255,.9)}
.mark::after{content:'';position:absolute;left:50%;top:50%;width:2px;height:2px;margin:-1px 0 0 -1px;background:#ef4444}
.loupe{position:relative;height:160px;margin-top:8px;border:1px solid var(--line);border-radius:10px;background-color:#000;background-repeat:no-repeat;overflow:hidden;touch-action:manipulation}
.loupe::before{content:'';position:absolute;left:50%;top:0;bottom:0;width:1px;background:rgba(239,68,68,.75)}
.loupe::after{content:'';position:absolute;top:50%;left:0;right:0;height:1px;background:rgba(239,68,68,.75)}
.loupe .ring{position:absolute;left:50%;top:50%;width:14px;height:14px;margin:-7px 0 0 -7px;border:1.5px solid #ef4444;border-radius:50%;box-shadow:0 0 0 1px rgba(255,255,255,.8)}
#alerts{margin-top:8px;border:1px solid var(--line);background:var(--card);color:var(--fg);border-radius:9px;padding:7px 10px;font-size:13px}
.note{font-size:12px;color:var(--dim);margin-top:2px}
.mode{font-size:12px;margin-top:6px;color:var(--dim)}.mode.hf{color:var(--ready)}
#conn{font-size:12px;color:var(--ready);margin-top:2px}
</style></head><body>
<header>
 <h1>FlowCast Studio</h1>
 <div class="sub" id="sum">Loading the docs catalog…</div>
 <div id="conn"></div>
 <div class="chips" id="chips"></div>
 <input type="search" id="q" placeholder="Search docs">
 <button id="alerts">🔔 Turn on alerts — chime when a run needs me</button>
</header>
<main>
 <div id="job" class="card job"></div>
 <div id="bg" class="note"></div>
 <div id="list"></div>
</main>
<script>
const T = new URLSearchParams(location.search).get('t');
const api = (p, body) => fetch(p + (p.includes('?') ? '&' : '?') + 't=' + T, body ? {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)} : {}).then(r => r.ok ? r.json() : Promise.reject(r.status));
const LABEL = {ready:'100% followable', auto:'Auto setup', keys:'Needs your keys', setup:'After setup', partial:'Needs a person'};
let pages = [], filter = 'ready', jobs = [];
const esc = s => String(s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));

function chips(s){
  const opts = [['videos', '🎬 Videos'], ['ready', `100% followable · ${s.ready}`], ['auto', `Auto setup · ${s.auto}`], ['keys', `Needs your keys · ${s.keys}`], ['setup', `After setup · ${s.setup}`], ['partial', `Needs a person · ${s.partial}`], ['all', `All · ${s.walkthroughs}`]];
  document.getElementById('chips').innerHTML = opts.map(([k, l]) => `<button class="chip ${k===filter?'on':''}" data-k="${k}">${l}</button>`).join('');
  document.querySelectorAll('.chip').forEach(b => b.onclick = () => { filter = b.dataset.k; chips(s); render(); });
}
let videos = null;
function copyText(t){
  const a = document.createElement('textarea'); a.value = t; a.setAttribute('readonly', '');
  a.style.position = 'fixed'; a.style.opacity = '0'; document.body.appendChild(a);
  a.select(); a.setSelectionRange(0, t.length); let ok = false;
  try { ok = document.execCommand('copy'); } catch (e) {}
  document.body.removeChild(a); return ok;
}
function renderVideos(){
  const el = document.getElementById('list');
  if (!videos) { el.innerHTML = '<div class="empty">Loading videos…</div>';
    api('/api/videos').then(d => { videos = d.videos; renderVideos(); }); return; }
  el.innerHTML = videos.length ? videos.map((v, i) => `
   <div class="card">
    <video controls playsinline preload="none" style="width:100%;border-radius:8px;background:#000"
      ${v.thumb ? `poster="/media/thumb?id=${encodeURIComponent(v.id)}&t=${T}"` : ''}
      src="/media/video?id=${encodeURIComponent(v.id)}&t=${T}"></video>
    <div class="title" style="margin-top:8px">${esc(v.title)}</div>
    <div class="desc">${esc(v.made)} · ${esc(v.duration)} · ${esc(v.size)}</div>
    <div class="row"><button data-copy="${i}">Copy description</button><button data-show="${i}">Show text</button></div>
    <pre id="txt${i}" style="display:none;white-space:pre-wrap;font:13px/1.4 -apple-system;color:var(--dim)">${esc(v.description)}</pre>
   </div>`).join('') : '<div class="empty">No finished videos yet.</div>';
  el.querySelectorAll('[data-copy]').forEach(b => b.onclick = () => {
    b.textContent = copyText(videos[+b.dataset.copy].description) ? 'Copied ✓' : 'Select the text to copy'; });
  el.querySelectorAll('[data-show]').forEach(b => b.onclick = () => {
    const p = document.getElementById('txt' + b.dataset.show); p.style.display = p.style.display === 'none' ? 'block' : 'none'; });
}
function render(){
  if (filter === 'videos') { renderVideos(); return; }
  const q = document.getElementById('q').value.trim().toLowerCase();
  const busy = new Set(jobs.filter(j => j.active || j.status === 'Queued').map(j => j.slug));
  const list = pages.filter(p => (filter === 'all' || p.verdict === filter) && (!q || (p.title + ' ' + p.area + ' ' + p.description).toLowerCase().includes(q)))
    .sort((a, b) => (b.recorded - a.recorded) || (b.coverage - a.coverage) || (b.actions - a.actions)).slice(0, 150);
  document.getElementById('list').innerHTML = list.length ? list.map(p => `
   <div class="card">
    <span class="badge ${p.verdict}">${LABEL[p.verdict]}</span>${p.recorded ? '<span class="badge rec">Recorded</span>' : ''}
    <div class="area">${esc(p.area)}</div><div class="title">${esc(p.title)}</div>
    <div class="desc">${esc(p.description)}</div>
    <div class="mode ${p.mode.startsWith('Hands') ? 'hf' : ''}">${esc(p.mode)}</div>
    ${p.blockers.length ? `<div class="tags">${[...new Set(p.blockers)].map(b => `<span class="tag">${esc(b)}</span>`).join('')}</div>` : ''}
    <div class="meta"><span>${p.steps} steps</span><span>${p.actions} actions</span><span>${Math.round(p.coverage*100)}%</span><span class="sp"></span>
     ${!busy.has(p.slug) && p.unfinished ? `<button class="make alt" data-s="${p.slug}" data-m="recording">🎬 Make video from last recording</button>` : ''}
     ${p.needsKeys && !busy.has(p.slug) ? '<span title="Keys show as placeholders; the video ends before the run step until you add yours on the Mac">🔑 placeholders</span>' : ''}
     ${busy.has(p.slug) ? '<span>In queue</span>'
       : p.proven ? `<button class="make alt" data-s="${p.slug}" data-m="guided">Step by step</button><button class="make ${p.verdict}" data-s="${p.slug}" data-m="auto">▶ Auto</button>`
       : `<button class="make ${p.verdict}" data-s="${p.slug}" data-m="guided">▶ Start step by step</button>`}</div>
   </div>`).join('') : '<div class="empty">Nothing here.</div>';
  document.querySelectorAll('button.make').forEach(b => b.onclick = () => {
    const label = b.textContent, slug = b.dataset.s;
    const reset = msg => { b.disabled = false; b.textContent = msg ? msg + ' — tap to try again' : label; };
    b.disabled = true; b.textContent = 'Starting on your Mac…';
    api('/api/make', {slug, mode: b.dataset.m}).then(r => {
      if (r.ok === false) { reset(r.error); return; }
      window.scrollTo({top: 0, behavior: 'smooth'}); poll();
      // A run shows up within a second or two; if not, say so instead of waiting forever.
      setTimeout(() => { if (!jobs.some(j => j.slug === slug && (j.active || j.status === 'Queued' || j.status === 'Waiting to process'))) reset('Did not start'); }, 10000);
    }).catch(() => reset('Could not reach your Mac'));
  });
}
let audio = null, lastSeq = null;
document.getElementById('alerts').onclick = () => {
  try { audio = new (window.AudioContext || window.webkitAudioContext)(); beep(); } catch (e) {}
  document.getElementById('alerts').textContent = '🔔 Alerts on — keep this page open';
};
function beep(){
  if (!audio) return;
  [0, 0.25, 0.5].forEach((t, i) => { const o = audio.createOscillator(), g = audio.createGain();
    o.frequency.value = [880, 660, 990][i]; g.gain.value = 0.15; o.connect(g); g.connect(audio.destination);
    o.start(audio.currentTime + t); o.stop(audio.currentTime + t + 0.18); });
}
function alertNeed(j){
  beep(); if (navigator.vibrate) navigator.vibrate([200, 100, 200]);
  let n = 0; const base = 'FlowCast Studio';
  const t = setInterval(() => { document.title = (n++ % 2) ? base : '⚠ FlowCast needs you'; if (n > 12) { clearInterval(t); document.title = base; } }, 700);
}
function showJob(){
  const el = document.getElementById('job');
  // The recording (it needs you) first; videos being voiced and mastered run
  // alongside and are listed under it.
  const j = jobs.find(j => j.help) || jobs.find(j => j.active && j.screen) || jobs.find(j => j.active) || jobs.find(j => j.status === 'Queued') || jobs.find(j => j.canMake);
  const bg = jobs.filter(x => x !== j && ((x.active && !x.screen) || x.status === 'Waiting to process'));
  document.getElementById('bg').innerHTML = bg.map(x => `<div class="bgjob">⚙︎ <b>${esc(x.title)}</b><br>${x.status === 'Running' ? esc(x.task || x.stage) : esc(x.status)}
    <div class="bar"><div style="width:${Math.round(x.progress * 100)}%"></div></div>${Math.round(x.progress * 100)}%${x.eta ? ' · ' + esc(x.eta) : ''}</div>`).join('');
  if (!j) { el.style.display = 'none'; return; }
  el.style.display = 'block';
  el.className = 'card job' + (j.help ? ' help' : '');
  if (el.dataset.seq === String(j.help ? j.help.seq : 'none') && el.dataset.id === j.id && j.help) return;
  el.dataset.seq = j.help ? j.help.seq : 'none'; el.dataset.id = j.id;
  if (j.help && lastSeq !== j.help.seq) { lastSeq = j.help.seq; if (j.help.kind !== 'step') alertNeed(j); }
  if (j.help && j.help.kind === 'step') { showStep(el, j); return; }
  if (j.canMake) {
    el.className = 'card job';
    el.innerHTML = `<div class="sub">Recording stopped</div><div class="title">${esc(j.title)}</div>
     <div class="desc">What was recorded can still become the YouTube video: script, voice and master run in the background.</div>
     <div class="row run"><button class="go" data-r="make" data-c="Make the YouTube video from what was recorded?">🎬 Make video from what's recorded</button><button data-r="restart" data-c="Record “${esc(j.title)}” again from step 1?">⏮ Start over</button></div>`;
    wireRun(el, j);
    return;
  }
  el.innerHTML = `<div class="sub">${j.help ? (j.help.manual ? 'Your turn' : 'FlowCast needs you') : (doing && j.guided ? '⏳ Doing: ' + esc(doing) + '…' : esc(j.stage) + ' · ' + Math.round(j.progress*100) + '%')}</div>
   <div class="title">${esc(j.title)}</div>
   ${j.task && !j.help ? `<div class="task">${esc(j.task)}</div>` : ''}
   <div class="bar"><div style="width:${Math.round(j.progress*100)}%"></div></div>
   ${j.eta ? `<div class="eta">⏱ ${esc(j.eta)}</div>` : ''}
   ${(j.notes || []).map(n => `<div class="note">✓ ${esc(n)}</div>`).join('')}
   ${j.help ? `<div>Step ${j.help.step}: <b>${esc(j.help.label)}</b></div><div class="desc">${esc(j.help.reason)}</div>
    ${j.help.tried && j.help.tried.length ? `<div class="note">Local AI tried: ${esc(j.help.tried.join(', '))}</div>` : ''}
    ${j.help.shot ? `<div class="shotwrap"><img id="shot" src="/api/shot?id=${j.id}&t=${T}&s=${j.help.seq}"><div class="mark" id="mark" style="display:none"></div></div>
     <div class="note">Tap the screenshot where FlowCast should click, then confirm.</div>
     <div class="loupe" id="loupe" style="display:none"><div class="ring"></div></div>
     <div class="note" id="aimNote" style="display:none">Zoomed 4× — tap it to fine-tune. Clicks at <b id="at"></b></div>
     <div class="row" id="tapRow" style="display:none"><button class="go" id="tapGo">Click there</button><button id="tapNo">Cancel</button></div>` : ''}
    <div class="row"><input id="cmd" placeholder="e.g. click Create" autocapitalize="off"><button class="go" id="go">Do it</button></div>
    ${j.help.manual ? '<div class="row"><button data-a="next">Continue</button><button data-a="skip">Skip line</button></div>' : '<div class="row"><button data-a="retry">Retry</button><button data-a="skip">Skip</button><button data-a="ok">Finish step</button></div>'}` : ''}
   ${j.active ? runRow(j) : ''}`;
  const send = t => api('/api/answer', {id: j.id, text: t}).then(() => { el.dataset.seq = ''; poll(); });
  el.querySelectorAll('[data-a]').forEach(b => b.onclick = () => send(b.dataset.a));
  wireRun(el, j);
  const go = el.querySelector('#go'); if (go) go.onclick = () => { const v = el.querySelector('#cmd').value.trim(); if (v) send(v); };
  const img = el.querySelector('#shot');
  if (img && j.help.screen && j.help.screen.length === 2) aim(el, img, j.help.screen, (x, y) => send(`at ${x},${y}`));
}
// Tap the screenshot to aim: a small crosshair marks the spot and the box below
// shows it 4× larger; tap inside that box to move the point to the exact
// pixel. The click goes to the point shown, in screen points.
function aim(el, img, screen, go){
  const mark = el.querySelector('#mark'), row = el.querySelector('#tapRow'),
        loupe = el.querySelector('#loupe'), note = el.querySelector('#aimNote'), Z = 4;
  let nx = null, ny = null;
  const clamp = v => Math.min(1, Math.max(0, v));
  const draw = () => {
    mark.style.left = (nx * 100) + '%'; mark.style.top = (ny * 100) + '%'; mark.style.display = 'block';
    const w = img.clientWidth * Z, hh = img.clientHeight * Z;
    loupe.style.display = 'block'; note.style.display = 'block'; row.style.display = 'flex';
    loupe.style.backgroundImage = `url("${img.src}")`;
    loupe.style.backgroundSize = `${w}px ${hh}px`;
    loupe.style.backgroundPosition = `${loupe.clientWidth / 2 - nx * w}px ${loupe.clientHeight / 2 - ny * hh}px`;
    el.querySelector('#at').textContent = `${Math.round(nx * screen[0])}, ${Math.round(ny * screen[1])}`;
  };
  img.onclick = ev => { const r = img.getBoundingClientRect(); nx = clamp((ev.clientX - r.left) / r.width); ny = clamp((ev.clientY - r.top) / r.height); draw(); };
  loupe.onclick = ev => {
    if (nx === null) return;
    const r = loupe.getBoundingClientRect();
    nx = clamp(nx + (ev.clientX - r.left - r.width / 2) / (img.clientWidth * Z));
    ny = clamp(ny + (ev.clientY - r.top - r.height / 2) / (img.clientHeight * Z));
    draw();
  };
  el.querySelector('#tapGo').onclick = () => { if (nx !== null) go(Math.round(nx * screen[0]), Math.round(ny * screen[1])); };
  el.querySelector('#tapNo').onclick = () => { nx = ny = null; [mark, loupe, note, row].forEach(x => x.style.display = 'none'); };
}
let doing = null;   // what you just tapped, shown until the next prompt arrives
// The whole video: record it again from step 1, or stop and pick another.
function runRow(j){
  return `${j.recording ? `<div class="row run"><button class="go" data-r="finish" data-c="Finish here and make the YouTube video from the steps recorded so far?">🎬 Finish &amp; make video</button></div>` : ''}<div class="row${j.recording ? '' : ' run'}"><button data-r="restart" data-c="Start “${esc(j.title)}” again from step 1? The project built so far is moved aside to WSO2Integrator-archive.">⏮ Start over</button><button data-r="stop" data-c="Stop “${esc(j.title)}”? Then pick another video below.">■ Stop · pick another</button></div>`;
}
function wireRun(el, j){
  el.querySelectorAll('[data-r]').forEach(b => b.onclick = () => {
    if (!confirm(b.dataset.c)) return;
    el.querySelectorAll('button').forEach(x => x.disabled = true);
    b.textContent = {restart: '⏳ Starting over…', finish: '⏳ Finishing — making the video…', make: '⏳ Making the video…'}[b.dataset.r] || '⏳ Stopping…';
    api('/api/control', {id: j.id, action: b.dataset.r}).then(() => {
      el.dataset.seq = ''; poll();
      if (b.dataset.r === 'stop') { const l = document.getElementById('q'); if (l) l.scrollIntoView({behavior: 'smooth'}); }
    });
  });
}
function showStep(el, j){
  doing = null;
  const h = j.help, done = new Set(h.done);
  el.className = 'card job';
  el.innerHTML = `<div class="sub">Step by step · ${esc(j.title)}${j.eta ? ' · ' + esc(j.eta) : ''}</div>
   <div class="bar"><div style="width:${Math.round(j.progress*100)}%"></div></div>
   <div class="title">Step ${h.step}: ${esc(h.stepTitle)}</div>
   <ul class="acts">${h.actions.map((a, i) => `<li data-i="${i}" class="${done.has(i) ? 'done' : (i === h.next ? 'next' : '')}">${done.has(i) ? '✓ ' : (i === h.next ? '▶ ' : '')}${esc(a)}${done.has(i) ? '<span class="again">↻ again</span>' : ''}</li>`).join('')}</ul>
   <button class="doit" id="doit">${h.next >= 0 ? '▶ Do it: ' + esc(h.actions[h.next]) : 'Step done — continue ▶'}</button>
   <div class="row"><button data-a="skip">Skip</button><button data-a="ok">Finish step</button></div>
   <div class="row">${h.canUndo ? `<button data-a="undo">↶ Undo last</button><button data-a="step over" data-c="Start step ${h.step} over? What it recorded so far leaves the video (the screen stays as it is).">⟲ Step ${h.step} again</button>` : ''}${h.step > 1 ? `<button data-a="back" data-c="Go back to step ${h.step - 1}? Steps ${h.step - 1} and ${h.step} are recorded again (the screen stays as it is).">◀ Back to step ${h.step - 1}</button>` : ''}</div>
   <div class="row"><input id="cmd" placeholder="Something else first — e.g. click onModify" autocapitalize="off"><button class="go" id="go">Do</button></div>
   <details id="scr"><summary class="note">Screen now — tap to click there</summary><div class="shotwrap"><img id="shot" alt="loading the Mac's screen…"><div class="mark" id="mark" style="display:none"></div></div>
     <div class="loupe" id="loupe" style="display:none"><div class="ring"></div></div>
     <div class="note" id="aimNote" style="display:none">Zoomed 4× — tap it to fine-tune. Clicks at <b id="at"></b></div>
     <div class="row" id="tapRow" style="display:none"><button class="go" id="tapGo">Click there</button><button id="tapNo">Cancel</button></div></details>
   ${runRow(j)}
   <div class="note">Shows ✓ but did not happen? Tap it to do it again — the earlier try leaves the video. ↶ Undo takes back the last action (and presses ⌘Z if it typed).</div>
   <div class="note">Every step working? This path is saved and the next run is automatic.</div>`;
  const send = (t, what) => {
    doing = what || t;
    el.querySelectorAll('button').forEach(b => b.disabled = true);
    const d = el.querySelector('#doit'); if (d) d.textContent = '⏳ Doing: ' + doing + '…';
    api('/api/answer', {id: j.id, text: t}).then(() => { el.dataset.seq = ''; poll(); });
  };
  el.querySelector('#doit').onclick = () => send('next', h.next >= 0 ? h.actions[h.next] : 'continue');
  el.querySelectorAll('[data-a]').forEach(b => b.onclick = () => { if (b.dataset.c && !confirm(b.dataset.c)) return; send(b.dataset.a, b.textContent); });
  el.querySelectorAll('li[data-i]').forEach(li => li.onclick = () => {
    const i = +li.dataset.i;
    if (done.has(i) && !confirm('Do “' + h.actions[i] + '” again? The earlier try leaves the video.')) return;
    send('#action:' + i, h.actions[i]);
  });
  wireRun(el, j);
  el.querySelector('#go').onclick = () => { const v = el.querySelector('#cmd').value.trim(); if (v) send(v); };
  const img = el.querySelector('#shot');
  el.querySelector('#scr').ontoggle = ev => { if (ev.target.open) img.src = `/api/screen?t=${T}&n=${Date.now()}`; };
  if (img && h.screen && h.screen.length === 2) aim(el, img, h.screen, (x, y) => send(`at ${x},${y}`, 'click there'));
}
function poll(){ api('/api/jobs').then(d => { jobs = d.jobs; showJob(); }).catch(() => {}); }
api('/api/pages').then(d => {
  pages = d.pages; const s = d.summary;
  document.getElementById('conn').textContent = `● Connected to ${d.mac} — pick a video and press Start`;
  document.getElementById('sum').textContent = `${s.total} docs pages · ${s.walkthroughs} walkthroughs · ${s.ready} followable 100%`;
  chips(s); render();
}).catch(e => { document.getElementById('sum').textContent = e === 403 ? 'This link has expired — scan the QR code again.' : 'Cannot reach the Mac.'; });
document.getElementById('q').oninput = render;
// Every 0.25 s while a recording runs (a tap shows its result at once),
// otherwise every 1.5 s.
(function loop(){ poll(); setTimeout(loop, jobs.some(j => j.active && j.screen) ? 250 : 1500); })();
</script></body></html>
"""#
