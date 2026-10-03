import Foundation

/// One `@@studio {json}` progress line from tools/studio.py or tools/autopilot.py.
struct StudioEvent {
    let name: String
    let data: [String: Any]

    init?(line: String) {
        guard line.hasPrefix("@@studio "),
              let json = line.dropFirst(9).data(using: .utf8),
              let obj = try? JSONSerialization.jsonObject(with: json) as? [String: Any],
              let name = obj["event"] as? String else { return nil }
        self.name = name
        self.data = obj
    }

    func string(_ k: String) -> String? { data[k] as? String }
    func int(_ k: String) -> Int? { (data[k] as? NSNumber)?.intValue }
    func bool(_ k: String) -> Bool? { (data[k] as? NSNumber)?.boolValue }
    func strings(_ k: String) -> [String] { data[k] as? [String] ?? [] }
}

/// Runs `uv run python tools/<script> …` in the FlowCast checkout, streaming
/// its output line by line. Recording needs Screen Recording + Accessibility;
/// macOS grants those to this app, and the python child inherits them.
final class StudioProcess {
    private let process = Process()
    private let output = Pipe()
    private let input = Pipe()
    private var buffer = Data()
    private let lock = NSLock()
    /// Held from start() until the exit callback has run. Callers often keep no
    /// reference (a Settings button firing a one-off command), and the pipe and
    /// termination handlers only hold this weakly — without it the output and
    /// the exit of such a run are silently dropped.
    private var keepAlive: StudioProcess?

    var onLine: (String) -> Void = { _ in }
    var onEvent: (StudioEvent) -> Void = { _ in }
    var onExit: (Int32) -> Void = { _ in }

    init(settings: AppSettings, script: String, arguments: [String], extraEnv: [String: String] = [:]) {
        process.executableURL = URL(fileURLWithPath: settings.uvPath)
        process.arguments = ["run", "--project", settings.projectRoot, "python", script] + arguments
        process.currentDirectoryURL = settings.rootURL
        process.environment = settings.environment.merging(extraEnv) { $1 }
        process.standardOutput = output
        process.standardError = output
        process.standardInput = input
    }

    var isRunning: Bool { process.isRunning }

    func start() throws {
        output.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let chunk = handle.availableData
            guard let self, !chunk.isEmpty else { return }
            self.consume(chunk)
        }
        process.terminationHandler = { [weak self] proc in
            guard let self else { return }
            self.output.fileHandleForReading.readabilityHandler = nil
            let rest = self.output.fileHandleForReading.readDataToEndOfFile()
            if !rest.isEmpty { self.consume(rest) }
            self.flush()
            let code = proc.terminationStatus
            DispatchQueue.main.async {
                self.onExit(code)
                self.keepAlive = nil
            }
        }
        keepAlive = self
        do {
            try process.run()
        } catch {
            keepAlive = nil
            throw error
        }
    }

    /// Answer a prompt (tools/autopilot.py reads one line per help event).
    func send(_ text: String) {
        let line = text.replacingOccurrences(of: "\n", with: " ") + "\n"
        try? input.fileHandleForWriting.write(contentsOf: Data(line.utf8))
    }

    /// Background QoS for this process and everything it started (efficiency
    /// cores, throttled I/O) — so voicing a video cannot slow a recording.
    /// Children started later inherit it.
    func setBackground(_ on: Bool) {
        guard on != background, process.isRunning else { return }
        background = on
        let root = process.processIdentifier
        DispatchQueue.global(qos: .utility).async {
            for pid in Self.tree(root) {
                let t = Process()
                t.executableURL = URL(fileURLWithPath: "/usr/sbin/taskpolicy")
                t.arguments = [on ? "-b" : "-B", "-p", String(pid)]
                t.standardOutput = FileHandle.nullDevice
                t.standardError = FileHandle.nullDevice
                try? t.run()
                t.waitUntilExit()
            }
        }
    }
    private var background = false

    /// root and all its descendants.
    private static func tree(_ root: Int32) -> [Int32] {
        let ps = Process()
        ps.executableURL = URL(fileURLWithPath: "/bin/ps")
        ps.arguments = ["-A", "-o", "pid=,ppid="]
        let out = Pipe()
        ps.standardOutput = out
        guard (try? ps.run()) != nil else { return [root] }
        let data = out.fileHandleForReading.readDataToEndOfFile()
        ps.waitUntilExit()
        var children: [Int32: [Int32]] = [:]
        for line in String(decoding: data, as: UTF8.self).split(separator: "\n") {
            let f = line.split(separator: " ").compactMap { Int32($0) }
            if f.count == 2 { children[f[1], default: []].append(f[0]) }
        }
        var all = [root], i = 0
        while i < all.count {
            all += children[all[i]] ?? []
            i += 1
        }
        return all
    }

    func terminate() {
        guard process.isRunning else { return }
        send("abort")
        process.interrupt()
        DispatchQueue.global().asyncAfter(deadline: .now() + 3) { [process] in
            if process.isRunning { process.terminate() }
        }
    }

    private func consume(_ chunk: Data) {
        lock.lock()
        buffer.append(chunk)
        var lines: [String] = []
        while let nl = buffer.firstIndex(of: 0x0A) {
            let lineData = buffer[buffer.startIndex..<nl]
            buffer.removeSubrange(buffer.startIndex...nl)
            lines.append(String(decoding: lineData, as: UTF8.self))
        }
        lock.unlock()
        deliver(lines)
    }

    private func flush() {
        lock.lock()
        let rest = buffer
        buffer.removeAll()
        lock.unlock()
        if !rest.isEmpty { deliver([String(decoding: rest, as: UTF8.self)]) }
    }

    private func deliver(_ lines: [String]) {
        guard !lines.isEmpty else { return }
        DispatchQueue.main.async {
            for raw in lines {
                let line = raw.replacingOccurrences(of: "\r", with: "")
                if let ev = StudioEvent(line: line) {
                    self.onEvent(ev)
                } else if !line.trimmingCharacters(in: .whitespaces).isEmpty {
                    self.onLine(line)
                }
            }
        }
    }
}
