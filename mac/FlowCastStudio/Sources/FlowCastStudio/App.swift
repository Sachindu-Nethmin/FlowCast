import SwiftUI

@main
struct FlowCastStudioApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var delegate
    @State private var settings: AppSettings
    @State private var studio: Studio
    @State private var phone: PhoneBridge

    init() {
        let s = AppSettings()
        let st = Studio(settings: s)
        AppDelegate.studio = st
        _settings = State(initialValue: s)
        _studio = State(initialValue: st)
        let bridge = PhoneBridge(studio: st)
        _phone = State(initialValue: bridge)
        // Help reaches your phone while the Mac's screen is being filmed.
        st.onRecordingStart = { [weak bridge] in
            guard let bridge, s.phoneDuringRuns, !bridge.isRunning else { return }
            bridge.start(port: s.phonePort)
        }
        if s.phoneAtLaunch || UserDefaults.standard.bool(forKey: "FCPhone") {
            bridge.start(port: s.phonePort)
        }
    }

    var body: some Scene {
        WindowGroup("FlowCast Studio") {
            ContentView()
                .environment(settings)
                .environment(studio)
                .environment(phone)
                .frame(minWidth: 980, minHeight: 640)
        }
        .defaultSize(width: 1380, height: 880)
        .windowToolbarStyle(.unified)
        .commands {
            CommandGroup(after: .newItem) {
                Button("Refresh Docs Catalog") { studio.refreshCatalog() }
                    .keyboardShortcut("r", modifiers: [.command, .shift])
            }
        }

        // Each video plays in its own resizable window (full screen works too):
        // a sheet is limited to the size of the main window.
        WindowGroup("Player", id: "player", for: String.self) { $folder in
            if let folder, let video = studio.library.first(where: { $0.folder == folder }) {
                PlayerSheet(video: video)
                    .navigationTitle(video.title)
            } else {
                ContentUnavailableView("Video not found", systemImage: "film")
            }
        }
        .defaultSize(width: 1280, height: 740)

        Settings {
            SettingsView()
                .environment(settings)
                .environment(studio)
                .environment(phone)
        }
    }
}
