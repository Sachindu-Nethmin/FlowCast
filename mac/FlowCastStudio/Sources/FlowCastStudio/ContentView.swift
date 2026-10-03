import SwiftUI

enum SidebarItem: Hashable {
    case phone
    case docs(Verdict?)          // nil = every walkthrough
    case runs
    case library
}

struct ContentView: View {
    @Environment(Studio.self) private var studio
    @Environment(PhoneBridge.self) private var phone
    @State private var selection: SidebarItem? = ContentView.initialSection()
    @State private var inspected: DocPage?
    @State private var showPhone = false

    /// `-FCSection ready|setup|partial|all|runs|library` and `-FCInspect <slug>`
    /// open the window on a given view (handy for screenshots and deep links).
    static func initialSection() -> SidebarItem {
        let fallback = UserDefaults.standard.object(forKey: "phoneAtLaunch") as? Bool ?? true ? "phone" : "ready"
        switch UserDefaults.standard.string(forKey: "FCSection") ?? fallback {
        case "phone": return .phone
        case "setup": return .docs(.setup)
        case "auto": return .docs(.auto)
        case "keys": return .docs(.keys)
        case "partial": return .docs(.partial)
        case "all": return .docs(nil)
        case "runs": return .runs
        case "library": return .library
        default: return .docs(.ready)
        }
    }

    var body: some View {
        NavigationSplitView {
            Sidebar(selection: $selection)
                .navigationSplitViewColumnWidth(min: 220, ideal: 240)
        } detail: {
            switch selection ?? .docs(.ready) {
            case .phone:
                PhoneView(openDocs: { selection = .docs(.ready) })
            case .docs(let verdict):
                // A plain side panel rather than .inspector: the inspector beside a
                // split view and a toolbar search field can send AppKit into an
                // endless constraint pass that aborts the app.
                HStack(spacing: 0) {
                    DocsBrowser(verdict: verdict, inspected: $inspected, openRuns: { selection = .runs })
                        .frame(minWidth: 340)
                    if let page = inspected {
                        Divider()
                        DocDetail(page: page, openRuns: { selection = .runs }, close: { inspected = nil })
                            .frame(width: 400)
                            .transition(.move(edge: .trailing))
                    }
                }
                .animation(.easeOut(duration: 0.18), value: inspected?.slug)
            case .runs:
                RunsView()
            case .library:
                LibraryView()
            }
        }
        .onAppear {
            if inspected == nil, let slug = UserDefaults.standard.string(forKey: "FCInspect") {
                inspected = studio.catalog?.pages.first { $0.slug == slug }
            }
        }
        .toolbar {
            ToolbarItemGroup(placement: .primaryAction) {
                Button {
                    studio.refreshCatalog()
                } label: {
                    Label(studio.refreshing ? "Refreshing…" : "Refresh docs",
                          systemImage: "arrow.triangle.2.circlepath")
                }
                .help("Pull the latest WSO2 Integrator docs and re-check which ones FlowCast can follow")
                .disabled(studio.refreshing)

                Button { showPhone.toggle() } label: {
                    Label("Phone", systemImage: phone.isRunning ? "iphone.radiowaves.left.and.right" : "iphone")
                }
                .help("Pick docs and answer FlowCast from your phone")
                .popover(isPresented: $showPhone, arrowEdge: .bottom) { PhonePopover() }

                SettingsLink { Label("Settings", systemImage: "gearshape") }
            }
        }
    }
}

struct Sidebar: View {
    @Environment(Studio.self) private var studio
    @Environment(PhoneBridge.self) private var phone
    @Binding var selection: SidebarItem?

    var body: some View {
        List(selection: $selection) {
            Section {
                Label {
                    HStack {
                        Text("Phone")
                        Spacer()
                        if phone.lastDevice != nil {
                            Image(systemName: "checkmark.circle.fill").foregroundStyle(.green).font(.caption)
                        }
                    }
                } icon: { Image(systemName: "qrcode") }
                .tag(SidebarItem.phone)
            }
            Section("Documentation") {
                row(.ready)
                row(.auto)
                row(.keys)
                row(.setup)
                row(.partial)
                Label {
                    HStack {
                        Text("All walkthroughs")
                        Spacer()
                        count(studio.catalog?.summary.walkthroughs)
                    }
                } icon: { Image(systemName: "square.grid.2x2") }
                .tag(SidebarItem.docs(nil))
            }
            Section("Videos") {
                Label {
                    HStack {
                        Text("Runs")
                        Spacer()
                        if let active = studio.activeJob ?? studio.processingJob {
                            if active.status == .needsHelp {
                                Image(systemName: "exclamationmark.circle.fill").foregroundStyle(.orange)
                            } else {
                                ProgressView().controlSize(.mini)
                            }
                        } else if !studio.jobs.isEmpty {
                            count(studio.jobs.count)
                        }
                    }
                } icon: { Image(systemName: "record.circle") }
                .tag(SidebarItem.runs)
                Label {
                    HStack {
                        Text("Library")
                        Spacer()
                        count(studio.library.count)
                    }
                } icon: { Image(systemName: "play.rectangle.on.rectangle") }
                .tag(SidebarItem.library)
            }
            if let cat = studio.catalog {
                Section("Source") {
                    VStack(alignment: .leading, spacing: 4) {
                        Text("\(cat.summary.total) docs pages")
                            .font(.callout)
                        Text("wso2/docs-integrator @ \(cat.commit ?? "?")")
                            .font(.caption).foregroundStyle(.secondary)
                            .textSelection(.enabled)
                    }
                    .padding(.vertical, 2)
                }
            }
        }
        .listStyle(.sidebar)
    }

    private func row(_ v: Verdict) -> some View {
        Label {
            HStack {
                Text(v.label)
                Spacer()
                count(value(v))
            }
        } icon: {
            Image(systemName: v.symbol).foregroundStyle(v.tint)
        }
        .tag(SidebarItem.docs(v))
    }

    private func value(_ v: Verdict) -> Int? {
        guard let s = studio.catalog?.summary else { return nil }
        switch v {
        case .ready: return s.ready
        case .auto: return s.auto ?? 0
        case .keys: return s.keys ?? 0
        case .setup: return s.setup
        case .partial: return s.partial
        case .none: return s.none
        }
    }

    @ViewBuilder private func count(_ n: Int?) -> some View {
        if let n {
            Text("\(n)").font(.caption.monospacedDigit()).foregroundStyle(.secondary)
        }
    }
}


/// The first thing you see: scan, then drive everything from the phone.
struct PhoneView: View {
    @Environment(PhoneBridge.self) private var phone
    @Environment(AppSettings.self) private var settings
    let openDocs: () -> Void
    @State private var choice = 0

    private var links: [(label: String, url: String)] {
        guard let url = phone.url else { return [] }
        return [("Wi-Fi address", url)] + phone.alternates
    }

    var body: some View {
        ScrollView {
            VStack(spacing: 18) {
                if phone.isRunning, !links.isEmpty {
                    let link = links[min(choice, links.count - 1)]
                    if let qr = phone.qrImage(for: link.url) {
                        Image(nsImage: qr).interpolation(.none).resizable().frame(width: 240, height: 240)
                            .padding(14).background(.white, in: RoundedRectangle(cornerRadius: 16))
                    }
                    if links.count > 1 {
                        Picker("Link", selection: $choice) {
                            ForEach(Array(links.enumerated()), id: \.offset) { i, l in
                                Text(i == 0 ? "Wi-Fi address" : "Option \(i + 1)").tag(i)
                            }
                        }
                        .pickerStyle(.segmented).frame(maxWidth: 360)
                        Text(link.label).font(.caption).foregroundStyle(.secondary)
                    }
                    status
                    Text(link.url).font(.caption.monospaced()).foregroundStyle(.tertiary).textSelection(.enabled)
                    HStack {
                        Button("Copy link") {
                            NSPasteboard.general.clearContents()
                            NSPasteboard.general.setString(link.url, forType: .string)
                        }
                        Button("New link") { phone.resetLink() }
                            .help("Old links stop working — use if you shared one by mistake")
                        Button("Browse docs on this Mac", action: openDocs)
                    }
                    if let proxy = phone.proxy, phone.lastDevice == nil {
                        ProxyHelp(proxy: proxy, hasAlternate: links.count > 1, useAlternate: { choice = 1 })
                    }
                    VStack(spacing: 4) {
                        Text("First run of a video: step by step from your phone. After a run that works: automatic.")
                        Text("The link stays the same when the app restarts. It drives this Mac — do not share it.")
                            .font(.caption).foregroundStyle(.tertiary)
                    }
                    .font(.callout).foregroundStyle(.secondary).multilineTextAlignment(.center)
                } else {
                    Image(systemName: "iphone.slash").font(.system(size: 48)).foregroundStyle(.secondary)
                    Text("The phone link is off").font(.title2.weight(.semibold))
                    if let e = phone.error { Text(e).foregroundStyle(.red) }
                    Button("Start phone link") { phone.start(port: settings.phonePort) }
                        .buttonStyle(.borderedProminent).controlSize(.large)
                }
            }
            .padding(30)
            .frame(maxWidth: .infinity)
        }
        .navigationTitle("Phone")
        .onAppear { phone.refreshAddresses() }
    }

    @ViewBuilder private var status: some View {
        if let dev = phone.lastDevice {
            Label("Phone connected (\(dev))", systemImage: "checkmark.circle.fill")
                .font(.title3.weight(.semibold)).foregroundStyle(.green)
            Text("Pick a video on your phone and press ▶ Start.").foregroundStyle(.secondary)
        } else if let stale = phone.staleLinks.max(by: { $0.value < $1.value })?.key {
            Label("Your phone (\(stale)) used an old link — scan this QR again", systemImage: "exclamationmark.triangle.fill")
                .font(.title3.weight(.semibold)).foregroundStyle(.orange)
        } else {
            Text("Scan with your phone's camera").font(.title2.weight(.semibold))
            Text("Same network as this Mac. Then pick a video and press ▶ Start.").foregroundStyle(.secondary)
        }
    }
}

/// Shown while no phone has connected on a network with a web proxy — the usual
/// reason a phone cannot open the Mac's page in hostels, hotels and offices.
struct ProxyHelp: View {
    let proxy: String
    let hasAlternate: Bool
    let useAlternate: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Label("This Wi-Fi sends web traffic through a proxy (\(proxy))", systemImage: "network.badge.shield.half.filled")
                .font(.headline).foregroundStyle(.orange)
            Text("Phones on it often hand the Mac's address to the proxy, which cannot reach your Mac, so the page never opens. Try these in order:")
                .font(.callout).foregroundStyle(.secondary)
            VStack(alignment: .leading, spacing: 8) {
                if hasAlternate {
                    HStack(alignment: .top) {
                        Text("1.").bold()
                        VStack(alignment: .leading, spacing: 4) {
                            Text("Scan the Mac-name QR — proxies usually let .local addresses through.")
                            Button("Show that QR", action: useAlternate).controlSize(.small)
                        }
                    }
                }
                HStack(alignment: .top) {
                    Text(hasAlternate ? "2." : "1.").bold()
                    Text("On the iPhone: Settings › Wi-Fi › ⓘ next to this network › Configure Proxy › Off, then scan again. Turn it back on when you are done if the Wi-Fi needs it for internet.")
                }
                HStack(alignment: .top) {
                    Text(hasAlternate ? "3." : "2.").bold()
                    Text("Most reliable: turn on Personal Hotspot on the iPhone and join it from this Mac (or plug the iPhone in with a cable). The QR updates by itself — no hostel network in between, and recording stays offline.")
                }
            }
            .font(.callout)
        }
        .padding(16)
        .frame(maxWidth: 560, alignment: .leading)
        .background(.orange.opacity(0.08), in: RoundedRectangle(cornerRadius: 12))
        .overlay(RoundedRectangle(cornerRadius: 12).strokeBorder(.orange.opacity(0.35)))
    }
}
