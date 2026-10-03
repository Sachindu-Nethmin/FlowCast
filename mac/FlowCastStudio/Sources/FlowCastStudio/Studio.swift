import AppKit
import Foundation
import Observation
import UserNotifications

enum Stage: Int, CaseIterable, Identifiable {
    case prepare, setup, record, script, voice, master
    var id: Int { rawValue }
    /// Drives the screen (one job at a time); the rest only needs the CPU and
    /// runs alongside the next recording.
    var usesScreen: Bool { self == .prepare || self == .setup || self == .record }
    var title: String {
        switch self {
        case .prepare: "Prepare"
        case .setup: "Prerequisites"
        case .record: "Record"
        case .script: "Script"
        case .voice: "Voice clone"
        case .master: "Master"
        }
    }
    var symbol: String {
        switch self {
        case .prepare: "doc.text.magnifyingglass"
        case .setup: "shippingbox"
        case .record: "record.circle"
        case .script: "text.quote"
        case .voice: "waveform"
        case .master: "film.stack"
        }
    }
}

enum JobStatus: Equatable {
    /// queued: waiting for the screen. waiting: recorded, waiting for its turn
    /// to be turned into a video (script, voice, master).
    case queued, waiting, running, needsHelp, review, done, failed, cancelled
    var label: String {
        switch self {
        case .queued: "Queued"
        case .waiting: "Waiting to process"
        case .running: "Running"
        case .needsHelp: "Needs you"
        case .review: "Review script"
        case .done: "Done"
        case .failed: "Failed"
        case .cancelled: "Cancelled"
        }
    }
    var isActive: Bool { self == .running || self == .needsHelp || self == .review }
    var isPending: Bool { self == .queued || self == .waiting }
}

struct HelpRequest: Equatable {
    let seq: Int
    let step: Int
    let kind: String          // failed | manual
    let label: String
    let reason: String
    let screenshot: String?
    var tried: [String] = []
    var screen: [Int] = []           // logical screen size, for tap-to-click
    // kind "step": a guided run waiting for your next move
    var stepTitle: String = ""
    var actions: [String] = []
    var done: [Int] = []
    var next: Int?
    var canUndo = false
    var isManual: Bool { kind == "manual" }
    var isStep: Bool { kind == "step" }
}

/// What the run did about a problem without you — shown so you can trust it.
struct RecoveryNote: Identifiable, Equatable {
    let id = UUID()
    let text: String
    let symbol: String
}

/// One autopilot run of a page (kb/run_history.json).
struct RunRecord: Decodable {
    let at: String
    let steps: Int
    let recorded: Int?
    let asked_person: Int
    let manual_lines: Int
    let ai_fixes: Int
    let learned_replays: Int
    let hands_free: Bool
}

struct StepProgress: Identifiable, Equatable {
    var id: Int { n }
    let n: Int
    let title: String
    let actions: [String]
    var done: Int = 0
    var failed: Int = 0
    var finished = false
}

@Observable
final class Job: Identifiable {
    let id = UUID()
    let page: DocPage
    var stage: Stage = .prepare
    var status: JobStatus = .queued
    var log: [String] = []
    var steps: [StepProgress] = []
    var currentStep: Int = 0
    var help: HelpRequest?
    var helpCount = 0
    var notes: [RecoveryNote] = []
    /// Step by step from the phone (first run) — or replaying a proven path.
    var guided = false
    var forcedMode: String?          // "guided" | "auto" from the phone
    /// Started over: the half-built project is set aside, whatever Settings say.
    var freshStart = false
    /// Make the video from what is recorded, even if steps are missing.
    var finishEarly = false
    /// Runs once the stopped run's process has exited (see cancel).
    @ObservationIgnored var afterExit: (() -> Void)?

    // What is happening now, and how far along (src/progress.py events).
    var task = ""                     // the "now" line on the Mac and the phone
    var unitDone = 0                  // finished units of this stage (voice lines, render phases)
    var unitTotal = 0
    var unitPart = 0.0                // how far into the unit running now (takes, the encode)
    var lineTotal = 0                 // voice stage: the first lineTotal units are lines
    var lineCount = 0                 // clips recorded = lines to voice (known after recording)
    var stageStartedAt = Date()
    var unitStartedAt = Date()
    var lineTimes: [Double] = []      // seconds a voice line took (cached ones excluded)
    var narrationPath: String?
    var hook: String?
    var masterPath: String?
    var packagedFolder: String?
    var narratedPath: String?
    var error: String?
    var startedAt: Date?
    var finishedAt: Date?
    @ObservationIgnored var process: StudioProcess?

    init(page: DocPage) { self.page = page }

    func append(_ line: String) {
        log.append(line)
        if log.count > 5000 { log.removeFirst(log.count - 5000) }
    }

    var progress: Double {
        if status == .done { return 1 }
        let n = Double(Stage.allCases.count)
        let base = Double(stage.rawValue) / n
        if stage == .record, !steps.isEmpty {
            let total = steps.reduce(0) { $0 + $1.actions.count }
            let done = steps.reduce(0) { $0 + min($1.done, $1.actions.count) }
            return base + (total > 0 ? Double(done) / Double(total) : 0) / n
        }
        guard unitTotal > 0 else { return base }
        return base + min(1, (Double(unitDone) + unitPart) / Double(unitTotal)) / n
    }

    var actionTotal: Int { steps.reduce(0) { $0 + $1.actions.count } }
}

@Observable
final class Studio {
    let settings: AppSettings
    let inputs = InputStore()
    var catalog: Catalog?
    var catalogError: String?
    var refreshing = false
    var refreshLog: [String] = []
    var jobs: [Job] = []
    var library: [LibraryVideo] = []
    var history: [String: [RunRecord]] = [:]
    /// Pages whose guided run completed: slug → when (kb/proven.json).
    var proven: [String: String] = [:]
    var selectedJobID: UUID?
    /// Called when a recording starts — the app starts the phone link here.
    @ObservationIgnored var onRecordingStart: (() -> Void)?
    @ObservationIgnored private var refreshProcess: StudioProcess?

    init(settings: AppSettings) {
        self.settings = settings
        loadCatalog()
        loadLibrary()
        loadHistory()
        if UserDefaults.standard.bool(forKey: "FCDemoHelp") { addDemoHelp() }
        if UserDefaults.standard.bool(forKey: "FCDemoStep") { addDemoStep() }
        UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound]) { _, _ in }
    }

    // ── catalog ──────────────────────────────────────────────────────────────

    func loadCatalog() {
        do {
            let data = try Data(contentsOf: settings.catalogURL)
            catalog = try JSONDecoder().decode(Catalog.self, from: data)
            catalogError = nil
        } catch {
            catalog = nil
            catalogError = "No docs catalog at \(settings.catalogURL.path). Use Refresh docs to build it."
        }
    }

    /// Re-read the WSO2 docs (git pull of wso2/docs-integrator) and re-audit.
    func refreshCatalog() {
        guard !refreshing else { return }
        refreshing = true
        refreshLog = []
        let p = StudioProcess(settings: settings, script: "tools/studio.py",
                              arguments: ["catalog", "--refresh"])
        p.onLine = { [weak self] in self?.refreshLog.append($0) }
        p.onExit = { [weak self] _ in
            self?.refreshing = false
            self?.loadCatalog()
        }
        refreshProcess = p
        do { try p.start() } catch {
            refreshing = false
            refreshLog.append("could not start uv: \(error.localizedDescription)")
        }
    }

    func pages(for verdict: Verdict?) -> [DocPage] {
        guard let all = catalog?.pages else { return [] }
        guard let verdict else { return all.filter { $0.isRecordable } }
        return all.filter { $0.kind == verdict }
    }

    func job(for page: DocPage) -> Job? {
        jobs.last { $0.page.slug == page.slug }
    }

    /// `-FCDemoHelp YES`: a stuck job built from a real help screenshot, for
    /// checking the help screens on the Mac and the phone. Nothing runs.
    private func addDemoHelp() {
        guard let page = catalog?.pages.first(where: { $0.slug == "build-file-driven-integration" }) else { return }
        let job = Job(page: page)
        job.stage = .record
        job.status = .needsHelp
        job.steps = [StepProgress(n: 4, title: "Add file tracking logic",
                                  actions: ["Select onModify", "Select +", "Search printInfo"], done: 2)]
        job.notes = [RecoveryNote(text: "Replayed your fix “click Local Files” — opens the artifact designer", symbol: "sparkles")]
        job.help = HelpRequest(seq: 1, step: 4, kind: "failed", label: "Search printInfo",
                               reason: "✗ cannot find 'Search' — demo, nothing is running",
                               screenshot: settings.rootURL.appendingPathComponent(
                                   "output/recordings/build-file-driven-integration/help-001.png").path,
                               tried: ["click Local Files"], screen: [1512, 982])
        jobs.append(job)
        selectedJobID = job.id
    }

    /// `-FCDemoStep YES`: a guided run waiting on step 3 (real screenshot). Nothing runs.
    private func addDemoStep() {
        guard let page = catalog?.pages.first(where: { $0.slug == "build-automation" }) else { return }
        let job = Job(page: page)
        job.stage = .record
        job.status = .needsHelp
        job.guided = true
        var h = HelpRequest(seq: 1, step: 3, kind: "step", label: "Select Initialize Array", reason: "",
                            screenshot: settings.rootURL.appendingPathComponent(
                                "output/recordings/build-automation/help-001.png").path, screen: [1512, 982])
        h.stepTitle = "Add logic"
        h.actions = ["Select +", "Select Call Function", "Select Print under io", "Select Initialize Array",
                     "Set Values to \"Hello World\"", "Select Save"]
        h.done = [0, 1, 2]
        h.next = 3
        h.canUndo = true
        job.help = h
        jobs.append(job)
        selectedJobID = job.id
    }

    // ── run history: evidence, not prediction ────────────────────────────────

    func loadHistory() {
        if let data = try? Data(contentsOf: settings.rootURL.appendingPathComponent("kb/proven.json")),
           let obj = try? JSONSerialization.jsonObject(with: data) as? [String: [String: Any]] {
            proven = obj.mapValues { $0["proven_at"] as? String ?? "" }
        }
        let url = settings.rootURL.appendingPathComponent("kb/run_history.json")
        guard let data = try? Data(contentsOf: url),
              let h = try? JSONDecoder().decode([String: [RunRecord]].self, from: data) else { return }
        history = h
    }

    func lastRun(_ page: DocPage) -> RunRecord? { history[page.slug]?.last }

    enum RunMode { case firstRun, learned, handsFree }

    /// Step by step from the phone until a guided run completes; from then on
    /// its path is replayed automatically ("learned"), and once an automatic
    /// run has finished without you it is "hands-free".
    func mode(_ page: DocPage) -> RunMode {
        let runs = history[page.slug] ?? []
        if runs.contains(where: { $0.hands_free }) { return .handsFree }
        if proven[page.slug] != nil { return .learned }
        if runs.contains(where: { ($0.recorded ?? 0) >= $0.steps && $0.steps > 0 }) { return .learned }
        return .firstRun
    }

    /// Whether a run of this page should be guided from the phone.
    func runsGuided(_ page: DocPage, forced: String? = nil) -> Bool {
        if let forced { return forced == "guided" }
        return settings.firstRunGuided && proven[page.slug] == nil
    }

    /// Whether autopilot has a learned binding template (kb/macros.json).
    func knowsBinding(nested: Bool) -> Bool {
        let url = settings.rootURL.appendingPathComponent("kb/macros.json")
        guard let data = try? Data(contentsOf: url),
              let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return false }
        return obj["bind"] != nil && (!nested || obj["bind_nested"] != nil)
    }

    // ── library ──────────────────────────────────────────────────────────────

    /// Finished videos: one folder each in Settings › Recording › Videos folder.
    func loadLibrary() {
        let root = URL(fileURLWithPath: settings.videosFolder)
        let fm = FileManager.default
        let dirs = (try? fm.contentsOfDirectory(at: root, includingPropertiesForKeys: nil)) ?? []
        var out: [LibraryVideo] = []
        for dir in dirs {
            guard let data = try? Data(contentsOf: dir.appendingPathComponent("video.json")),
                  let m = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  let file = m["video"] as? String else { continue }
            let video = dir.appendingPathComponent(file)
            guard fm.fileExists(atPath: video.path) else { continue }
            let thumb = (m["thumbnail"] as? String).map { dir.appendingPathComponent($0).path }
            let text = (m["text"] as? String).map { dir.appendingPathComponent($0).path }
            let size = (try? video.resourceValues(forKeys: [.fileSizeKey]).fileSize) ?? 0
            let made = (m["made"] as? String).flatMap { ISO8601DateFormatter.flexible.date(from: $0) } ?? modDate(video)
            out.append(LibraryVideo(slug: m["slug"] as? String ?? "", video: video.path,
                                    title: m["title"] as? String ?? dir.lastPathComponent,
                                    thumbnail: thumb, description: text, modified: made,
                                    bytes: Int64(size), folder: dir.path,
                                    seconds: (m["seconds"] as? NSNumber)?.doubleValue ?? 0,
                                    source: m["source"] as? String))
        }
        library = out.sorted { $0.modified > $1.modified }
    }

    private func modDate(_ u: URL) -> Date {
        (try? u.resourceValues(forKeys: [.contentModificationDateKey]).contentModificationDate) ?? .distantPast
    }

    func video(for page: DocPage) -> LibraryVideo? {
        library.first { $0.slug == page.slug || $0.slug == page.verified }
    }

    // ── jobs ─────────────────────────────────────────────────────────────────

    @discardableResult
    func enqueue(_ pages: [DocPage], mode: String? = nil) -> Job? {
        var first: Job?
        for page in pages where page.isRecordable && inputs.missing(for: page).isEmpty {
            if let existing = jobs.first(where: { $0.page.slug == page.slug && ($0.status.isPending || $0.status.isActive) }) {
                first = first ?? existing
                continue
            }
            let job = Job(page: page)
            job.forcedMode = mode
            jobs.append(job)
            first = first ?? job
        }
        if let first { selectedJobID = first.id }
        startNextIfIdle()
        return first
    }

    /// The job using the screen: preparing, installing or recording.
    var activeJob: Job? { jobs.first { $0.status.isActive && $0.stage.usesScreen } }
    /// The job being turned into a video (script, voice, master) — alongside.
    var processingJob: Job? { jobs.first { $0.process != nil && !$0.stage.usesScreen } }
    /// Anything still running a process (quitting would stop it).
    var busy: Bool { jobs.contains { $0.process != nil } || !stopping.isEmpty }

    /// Two lanes. Recording: one job at a time, it drives the mouse. Processing:
    /// script → voice → master for one recorded video at a time (the voice model
    /// fills the GPU), at background priority while something is recording.
    /// So a finished recording never holds up the next one.
    func startNextIfIdle() {
        // A stopped run is still writing its log and letting go of the app for
        // a moment; the next one starts when it has exited.
        if activeJob == nil, stopping.isEmpty,
           !jobs.contains(where: { $0.process != nil && $0.stage.usesScreen }),
           let next = jobs.first(where: { $0.status == .queued }) {
            next.status = .running
            next.startedAt = next.startedAt ?? Date()
            run(next, stage: next.stage)
        }
        if processingJob == nil, let next = jobs.first(where: { $0.status == .waiting }) {
            next.status = .running
            run(next, stage: next.stage)
        }
        applyPriorities()
    }

    /// Processing yields to a recording: background QoS (efficiency cores,
    /// throttled I/O) while one runs, full speed otherwise.
    private func applyPriorities() {
        let recording = jobs.contains { $0.stage == .record && $0.process != nil }
        for job in jobs where !job.stage.usesScreen {
            job.process?.setBackground(recording)
        }
    }

    func cancel(_ job: Job, show: Bool = true) {
        job.status = .cancelled
        job.finishedAt = Date()
        job.help = nil
        if let p = job.process {
            job.afterExit = { [weak self] in self?.startNextIfIdle() }
            p.terminate()
        } else {
            startNextIfIdle()
        }
        if show { showApp() }
    }

    /// Stop this video and record it again from step 1, in a fresh project.
    func restart(_ job: Job) {
        let again = Job(page: job.page)
        again.forcedMode = job.guided ? "guided" : job.forcedMode
        again.freshStart = true
        if let i = jobs.firstIndex(where: { $0.id == job.id }) {
            jobs[i] = again              // takes the stopped run's place in the list
        } else {
            jobs.insert(again, at: 0)
        }
        selectedJobID = again.id
        if job.status.isActive || job.status.isPending {
            cancel(job, show: false)
            // The old run is out of the list but its process still ends cleanly.
            if job.process != nil { stopping.append(job) }
        } else {
            startNextIfIdle()
        }
    }

    /// Stop recording here and make the video from the steps recorded so far.
    func finishNow(_ job: Job) {
        guard job.stage == .record, job.status.isActive else { return }
        job.finishEarly = true
        job.append("› you: finish the video here")
        if job.status == .needsHelp {
            job.help = nil
            job.status = .running
            job.process?.send("abort")
        }
        // Mid-action: told at its next prompt (see handle "help").
    }

    /// A stopped or failed recording with clips in it: script, voice and master it.
    func makeVideo(fromRecordingOf job: Job) {
        guard !job.status.isActive, !job.status.isPending, job.stage == .record,
              recordedClips(job) > 0 else { return }
        job.finishEarly = true
        job.stage = .script
        job.status = .waiting
        job.error = nil
        job.finishedAt = nil
        startNextIfIdle()
    }

    /// The page's last recording when it has clips and no finished video was
    /// made after it — e.g. after the app was restarted mid-voicing. Picks up
    /// at Voice when its script is already written (lines voiced so far are
    /// cached), else at Script.
    func unfinishedRecording(_ page: DocPage) -> (clips: Int, from: Stage)? {
        let rec = settings.rootURL.appendingPathComponent("output/recordings/\(page.slug)")
        let log = rec.appendingPathComponent("actions.json")
        guard FileManager.default.fileExists(atPath: log.path),
              let data = try? Data(contentsOf: log),
              let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let clips = (obj["clips"] as? [Any])?.count, clips > 0 else { return nil }
        let recorded = modDate(log)
        if let v = video(for: page), v.modified >= recorded { return nil }
        let script = rec.appendingPathComponent("narration-script.txt")
        let scripted = FileManager.default.fileExists(atPath: script.path) && modDate(script) >= recorded
        return (clips, scripted ? .voice : .script)
    }

    /// Make the video from the page's last recording (see unfinishedRecording).
    @discardableResult
    func makeVideo(fromRecordingOf page: DocPage) -> Job? {
        guard !jobs.contains(where: { $0.page.slug == page.slug && ($0.status.isActive || $0.status.isPending) }),
              let rec = unfinishedRecording(page) else { return nil }
        let job = Job(page: page)
        job.finishEarly = true
        job.stage = rec.from
        job.status = .waiting
        job.append("── making the video from the recording of \(rec.clips) clips ──")
        jobs.append(job)
        selectedJobID = job.id
        startNextIfIdle()
        return job
    }

    /// Clips the last recording of this page logged (output/recordings/<slug>/actions.json).
    func recordedClips(_ job: Job) -> Int {
        let url = settings.rootURL.appendingPathComponent("output/recordings/\(job.page.slug)/actions.json")
        guard let data = try? Data(contentsOf: url),
              let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let clips = obj["clips"] as? [Any] else { return 0 }
        return clips.count
    }

    // ── time left ────────────────────────────────────────────────────────────

    /// How long things take on this Mac, learned from finished stages (seconds;
    /// voiceTake is one take of one line, action one recorded action).
    private(set) var timing: [String: Double] = {
        var t: [String: Double] = ["prepare": 15, "setup": 20, "script": 8, "voiceTake": 50,
                                   "master": 420, "action": 14]
        for (k, v) in (UserDefaults.standard.dictionary(forKey: "stageTiming") as? [String: Double]) ?? [:] {
            t[k] = v
        }
        return t
    }()

    private func learn(_ key: String, _ seconds: Double) {
        guard seconds.isFinite, seconds > 0 else { return }
        timing[key] = (timing[key] ?? seconds) * 0.5 + seconds * 0.5
        UserDefaults.standard.set(timing, forKey: "stageTiming")
    }

    /// (left in the stage running now — nil while that depends on you, left in
    /// the stages after it).
    func estimate(_ job: Job) -> (now: Double?, after: Double) {
        let takes = Double(max(1, settings.narrationTakes))
        let perLine = (timing["voiceTake"] ?? 50) * takes
        let lines = Double(job.lineCount > 0 ? job.lineCount : job.actionTotal)
        let elapsed = Date().timeIntervalSince(job.stageStartedAt)
        var now: Double?
        if job.status.isPending {
            now = 0                                   // not started: all of it is "after"
        } else {
            switch job.stage {
            case .prepare: now = max(3, (timing["prepare"] ?? 15) - elapsed)
            case .setup: now = max(3, (timing["setup"] ?? 20) - elapsed)
            case .script: now = max(3, (timing["script"] ?? 8) - elapsed)
            case .record:
                let left = Double(max(0, job.actionTotal - job.steps.reduce(0) { $0 + min($1.done, $1.actions.count) }))
                now = job.guided || job.status == .needsHelp ? nil : left * (timing["action"] ?? 14)
            case .voice:
                let measured = job.lineTimes.isEmpty ? perLine : job.lineTimes.reduce(0, +) / Double(job.lineTimes.count)
                let total = job.lineTotal > 0 ? job.lineTotal : Int(lines)
                let inLine = job.unitDone < total ? job.unitPart : 0
                let linesLeft = max(0, Double(total - min(job.unitDone, total)) - inLine)
                let stepsLeft = Double(max(0, job.unitTotal - max(job.unitDone, total)))
                now = linesLeft * measured + stepsLeft * 8
            case .master:
                var left = max(10, (timing["master"] ?? 420) - elapsed)
                if job.unitDone == 2, job.unitPart > 0.05 {     // the render reports its fraction
                    let r = Date().timeIntervalSince(job.unitStartedAt)
                    left = r / job.unitPart * (1 - job.unitPart) + 45
                }
                now = left
            }
        }
        var after = 0.0
        let from = job.status.isPending ? job.stage.rawValue - 1 : job.stage.rawValue
        for s in Stage.allCases where s.rawValue > from {
            switch s {
            case .prepare: after += timing["prepare"] ?? 15
            case .setup: after += timing["setup"] ?? 20
            case .record: after += Double(job.actionTotal) * (timing["action"] ?? 14)
            case .script: after += timing["script"] ?? 8
            case .voice: after += lines * perLine
            case .master: after += timing["master"] ?? 420
            }
        }
        return (now, after)
    }

    /// "about 14 min left · ready ~21:05" — or what still depends on you.
    func etaText(_ job: Job) -> String {
        guard job.status.isActive || job.status.isPending else { return "" }
        let (now, after) = estimate(job)
        guard let now else {
            return after > 30 ? "then about \(Self.duration(after)) to make the video" : ""
        }
        let total = now + after
        if total < 45 { return "less than a minute left" }
        let ready = Date().addingTimeInterval(total).formatted(date: .omitted, time: .shortened)
        return "about \(Self.duration(total)) left · ready ~\(ready)"
    }

    static func duration(_ s: Double) -> String {
        let m = Int((s / 60).rounded())
        if m < 1 { return "under a minute" }
        return m < 60 ? "\(m) min" : "\(m / 60) h \(m % 60) min"
    }

    /// Runs that were replaced by a restart and have not exited yet.
    private var stopping: [Job] = []

    func remove(_ job: Job) {
        guard !job.status.isActive else { return }
        jobs.removeAll { $0.id == job.id }
    }

    func retry(_ job: Job) {
        guard !job.status.isActive else { return }
        // Back into its lane; it starts when that lane is free.
        job.status = job.stage.usesScreen ? .queued : .waiting
        job.error = nil
        job.finishedAt = nil
        startNextIfIdle()
    }

    /// Answer the autopilot's "help" event.
    func answer(_ job: Job, _ text: String) {
        guard job.status == .needsHelp else { return }
        let wasStep = job.help?.isStep == true
        job.append("› you: \(text)")
        job.help = nil
        job.status = .running
        if settings.hideDuringRecording && !wasStep { NSApp.hide(nil) }
        job.process?.send(text)
    }

    /// Continue after reviewing the narration script.
    func approveScript(_ job: Job) {
        guard job.status == .review else { return }
        job.stage = .voice
        job.status = .waiting
        startNextIfIdle()
    }

    private func run(_ job: Job, stage: Stage) {
        job.stage = stage
        job.stageStartedAt = Date()
        job.unitStartedAt = Date()
        job.unitDone = 0
        job.unitTotal = 0
        job.unitPart = 0
        job.lineTotal = 0
        job.lineTimes = []
        job.task = switch stage {
        case .prepare: "Preparing the workspace"
        case .setup: "Starting the prerequisites"
        case .record: job.guided || runsGuided(job.page, forced: job.forcedMode) ? "Recording step by step" : "Recording"
        case .script: "Writing the narration"
        case .voice: "Voicing the narration"
        case .master: "Making the YouTube video"
        }
        if stage.rawValue > Stage.record.rawValue, job.lineCount == 0 { job.lineCount = recordedClips(job) }
        let slug = job.page.slug
        let ref = settings.voiceReference
        var script = "tools/studio.py"
        var args: [String]
        var env: [String: String] = [:]
        switch stage {
        case .prepare:
            args = ["prepare", slug] + (settings.freshProjects || job.freshStart ? ["--fresh-projects"] : [])
        case .setup:
            args = ["setup", slug]
        case .record:
            script = "tools/autopilot.py"
            args = ["workflows/\(slug).md"]
            job.guided = runsGuided(job.page, forced: job.forcedMode)
            if job.guided { args.append("--guided") }
            // Your values, for tools/write_config.py — via the environment only.
            env = inputs.environment(for: job.page)
            job.steps = []
            job.notes = []
            onRecordingStart?()
            if settings.hideDuringRecording { NSApp.hide(nil) }
        case .script:
            args = ["narration", slug, "--force"]
        case .voice:
            args = ["voice", slug, "--ref", ref, "--takes", String(settings.narrationTakes)]
        case .master:
            args = ["master", slug, "--ref", ref, "--takes", String(settings.masterTakes),
                    "--quality", settings.quality]
        }
        job.append("── \(stage.title) ──")
        let p = StudioProcess(settings: settings, script: script, arguments: args, extraEnv: env)
        p.onLine = { [weak job] line in job?.append(line) }
        p.onEvent = { [weak self, weak job] ev in
            guard let self, let job else { return }
            self.handle(ev, job: job)
        }
        p.onExit = { [weak self, weak job] code in
            guard let self, let job else { return }
            self.finished(job, stage: stage, code: code)
        }
        job.process = p
        do { try p.start() } catch {
            fail(job, "Could not start \(settings.uvPath): \(error.localizedDescription)")
        }
        applyPriorities()
    }

    private func handle(_ ev: StudioEvent, job: Job) {
        switch ev.name {
        case "start":
            if let steps = ev.data["steps"] as? [[String: Any]] {
                job.steps = steps.map {
                    StepProgress(n: ($0["n"] as? NSNumber)?.intValue ?? 0,
                                 title: $0["title"] as? String ?? "",
                                 actions: $0["actions"] as? [String] ?? [])
                }
            }
        case "progress":
            let done = ev.int("done") ?? 0
            let lines = ev.int("lines") ?? 0
            if done > job.unitDone {
                let took = Date().timeIntervalSince(job.unitStartedAt) / Double(done - job.unitDone)
                // Lines from the cache take no time; they would make it look fast.
                if job.stage == .voice, job.unitDone < lines, took > 1.5 { job.lineTimes.append(took) }
            }
            job.unitDone = done
            job.unitTotal = ev.int("total") ?? job.unitTotal
            job.lineTotal = lines
            job.unitPart = 0
            job.unitStartedAt = Date()
            if let t = ev.string("task") { job.task = t }
        case "part":
            job.unitPart = (ev.data["fraction"] as? NSNumber)?.doubleValue ?? job.unitPart
        case "step":
            // A step starting — for the first time, or again after Back — and
            // every step after it are still to do.
            let n = ev.int("n") ?? 0
            job.currentStep = n
            job.task = "Recording step \(n) of \(job.steps.count): \(ev.string("title") ?? "")"
            for i in job.steps.indices where job.steps[i].n >= n {
                job.steps[i].finished = false
                job.steps[i].done = 0
                job.steps[i].failed = 0
            }
        case "action":
            if let n = ev.int("step"), let i = job.steps.firstIndex(where: { $0.n == n }) {
                if ev.bool("ok") == true { job.steps[i].done += 1 } else { job.steps[i].failed += 1 }
            }
        case "step_done":
            if let n = ev.int("n"), let i = job.steps.firstIndex(where: { $0.n == n }),
               ev.string("status") == "recorded" {
                job.steps[i].finished = true
            }
        case "help" where job.finishEarly:
            // You chose to finish here: end the recording at this prompt.
            job.process?.send("abort")
        case "help" where ev.string("kind") == "step":
            // Your move in a guided run: shown on the phone, no alarm.
            let info = ev.data["step_info"] as? [String: Any] ?? [:]
            var h = HelpRequest(seq: ev.int("seq") ?? 0, step: ev.int("step") ?? 0, kind: "step",
                                label: ev.string("label") ?? "", reason: "",
                                screenshot: ev.string("screenshot"),
                                screen: (ev.data["screen"] as? [NSNumber])?.map(\.intValue) ?? [])
            h.stepTitle = info["title"] as? String ?? ""
            h.actions = info["actions"] as? [String] ?? []
            h.done = (info["done"] as? [NSNumber])?.map(\.intValue) ?? []
            h.next = (info["next"] as? NSNumber)?.intValue
            h.canUndo = (info["can_undo"] as? Bool) ?? false
            if let i = job.steps.firstIndex(where: { $0.n == h.step }) {
                job.steps[i].done = h.done.count     // undo / redo change it
            }
            job.task = h.next.map { "Your move — step \(h.step): \(h.actions[$0])" }
                ?? "Your move — step \(h.step) is done, continue"
            job.help = h
            job.status = .needsHelp
        case "proven":
            loadHistory()
            job.notes.append(RecoveryNote(text: "Every step worked — this path is saved. The next run of this video is automatic.",
                                          symbol: "checkmark.seal.fill"))
        case "help":
            job.help = HelpRequest(seq: ev.int("seq") ?? 0, step: ev.int("step") ?? 0,
                                   kind: ev.string("kind") ?? "failed",
                                   label: ev.string("label") ?? "",
                                   reason: ev.string("reason") ?? "An action failed.",
                                   screenshot: ev.string("screenshot"),
                                   tried: ev.strings("tried"),
                                   screen: (ev.data["screen"] as? [NSNumber])?.map(\.intValue) ?? [])
            job.helpCount += 1
            job.status = .needsHelp
            job.task = (ev.string("kind") == "manual" ? "Your turn — " : "Waiting for you — ")
                + (ev.string("label") ?? "an action failed")
            showApp()
            notify(ev.string("kind") == "manual" ? "Your turn" : "FlowCast needs you",
                   "\(job.page.displayTitle): \(ev.string("label") ?? "an action failed")")
            NSSound(named: "Glass")?.play()
        case "narration":
            job.narrationPath = ev.string("path")
            job.hook = ev.string("hook")
        case "voiced":
            job.narratedPath = ev.string("path")
        case "master":
            job.masterPath = ev.string("path")
        case "ai":
            if let cmd = ev.string("command") {
                job.notes.append(RecoveryNote(text: "\(ev.string("model") ?? "Local AI") chose “\(cmd)” — \(ev.string("reason") ?? "")",
                                              symbol: "sparkles"))
            } else {
                job.notes.append(RecoveryNote(text: "\(ev.string("model") ?? "Local AI") had no answer: \(ev.string("reason") ?? "")",
                                              symbol: "sparkles"))
            }
        case "recovering":
            job.notes.append(RecoveryNote(text: "Replaying a fix learned earlier: \(ev.strings("commands").joined(separator: " → "))",
                                          symbol: "arrow.triangle.2.circlepath"))
        case "recovered":
            let by = ev.string("by") ?? ""
            let who = ["ai": "the local AI", "you": "you", "learned": "a learned fix",
                       "scroll": "scrolling", "wait": "waiting and retrying"][by] ?? by
            job.notes.append(RecoveryNote(text: "Unstuck by \(who)" + (["ai", "you"].contains(by) ? " — learned for next time" : ""),
                                          symbol: by == "you" ? "person.fill.checkmark" : "checkmark.circle"))
        case "history":
            loadHistory()
        case "packaged":
            job.packagedFolder = ev.string("folder")
            loadLibrary()
        case "setup_progress":
            job.append("starting \(ev.string("label") ?? "a prerequisite")…")
        case "error":
            job.error = ev.string("message")
        default:
            break
        }
    }

    private func finished(_ job: Job, stage: Stage, code: Int32) {
        job.process = nil
        if code == 0, job.status != .cancelled {
            let took = Date().timeIntervalSince(job.stageStartedAt)
            switch stage {
            case .prepare: learn("prepare", took)
            case .setup: learn("setup", took)
            case .script: learn("script", took)
            case .master: learn("master", took)
            case .voice:
                if !job.lineTimes.isEmpty {
                    learn("voiceTake", job.lineTimes.reduce(0, +) / Double(job.lineTimes.count)
                          / Double(max(1, settings.narrationTakes)))
                }
            case .record:
                if !job.guided, job.actionTotal > 0 { learn("action", took / Double(job.actionTotal)) }
            }
        }
        stopping.removeAll { $0.id == job.id }
        guard job.status != .cancelled else {
            let then = job.afterExit
            job.afterExit = nil
            then?()
            return
        }
        if stage == .record { showApp() }
        if code != 0 {
            fail(job, job.error ?? "\(stage.title) exited with code \(code). See the log.")
            return
        }
        switch stage {
        case .prepare: run(job, stage: .setup)
        case .setup: run(job, stage: .record)
        case .record:
            let recorded = job.steps.filter(\.finished).count
            if recorded < job.steps.count && !(job.finishEarly && recordedClips(job) > 0) {
                // A video with a step missing teaches the wrong thing; record again.
                fail(job, "Recorded \(recorded) of \(job.steps.count) steps. Retry records the page again.")
                return
            }
            // Into the processing lane; the screen is free for the next video.
            job.stage = .script
            job.status = .waiting
            startNextIfIdle()
        case .script:
            if settings.reviewNarration {
                job.status = .review
                notify("Narration ready", "Review the script for \(job.page.displayTitle).")
                startNextIfIdle()
            } else {
                run(job, stage: .voice)
            }
        case .voice: run(job, stage: .master)
        case .master:
            job.status = .done
            job.finishedAt = Date()
            loadLibrary()
            notify("Video ready", job.page.displayTitle)
            startNextIfIdle()
        }
    }

    private func fail(_ job: Job, _ message: String) {
        job.error = message
        job.status = .failed
        job.finishedAt = Date()
        job.append("✗ \(message)")
        showApp()
        notify("FlowCast stopped", "\(job.page.displayTitle): \(message)")
        startNextIfIdle()
    }

    private func showApp() {
        NSApp.unhide(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    private func notify(_ title: String, _ body: String) {
        let c = UNMutableNotificationContent()
        c.title = title
        c.body = body
        UNUserNotificationCenter.current().add(
            UNNotificationRequest(identifier: UUID().uuidString, content: c, trigger: nil))
    }
}


extension ISO8601DateFormatter {
    /// video.json writes local time without a zone ("2026-10-03T16:12:00").
    static let flexible: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withFullDate, .withTime, .withColonSeparatorInTime, .withDashSeparatorInDate]
        f.timeZone = .current
        return f
    }()
}
