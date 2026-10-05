import AppKit

/// One FlowCast Studio at a time — the newest launch wins.
///
/// Two copies would mean two recorders fighting over one mouse. A new launch
/// asks every older copy to quit; one that is mid-recording asks you first, and
/// if you keep it, the new launch steps aside and brings that one forward.
final class AppDelegate: NSObject, NSApplicationDelegate {
    static weak var studio: Studio?
    private var steppingAside = false

    func applicationDidFinishLaunching(_ notification: Notification) {
        guard let id = Bundle.main.bundleIdentifier else { return }
        let me = NSRunningApplication.current
        let others = NSRunningApplication.runningApplications(withBundleIdentifier: id)
            .filter { $0.processIdentifier != me.processIdentifier }
        guard !others.isEmpty else { return }
        others.forEach { $0.terminate() }
        DispatchQueue.main.asyncAfter(deadline: .now() + 4) {
            if let kept = others.first(where: { !$0.isTerminated }) {
                // The older copy is busy (it asked you, or you kept it): step
                // aside quietly — this one has nothing to lose yet.
                kept.activate()
                self.steppingAside = true
                NSApp.terminate(nil)
            }
        }
    }

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        guard !steppingAside, let studio = Self.studio, studio.busy,
              let job = studio.activeJob ?? studio.processingJob ?? studio.jobs.first(where: { $0.process != nil })
        else { return .terminateNow }
        NSApp.unhide(nil)
        NSApp.activate(ignoringOtherApps: true)
        let alert = NSAlert()
        alert.messageText = job.stage.usesScreen ? "A recording is in progress" : "A video is being made"
        alert.informativeText = "“\(job.page.displayTitle)” is at \(job.stage.title). Quitting stops it; you can retry it later."
        alert.addButton(withTitle: "Keep recording")
        alert.addButton(withTitle: "Quit")
        return alert.runModal() == .alertSecondButtonReturn ? .terminateNow : .terminateCancel
    }

    func applicationWillTerminate(_ notification: Notification) {
        // Never leave a recorder driving the mouse after the app is gone.
        Self.studio?.jobs.forEach { $0.process?.terminate() }
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        !(Self.studio?.busy ?? false)
    }
}
