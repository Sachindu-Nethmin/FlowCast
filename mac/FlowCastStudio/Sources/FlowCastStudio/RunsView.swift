import AVKit
import SwiftUI

struct RunsView: View {
    @Environment(Studio.self) private var studio

    var body: some View {
        @Bindable var studio = studio
        Group {
            if studio.jobs.isEmpty {
                ContentUnavailableView {
                    Label("No runs yet", systemImage: "record.circle")
                } description: {
                    Text("Choose Make video on a doc card. FlowCast opens WSO2 Integrator, follows the page, records every action, then narrates it in your cloned voice.")
                }
            } else {
                HSplitView {
                    List(selection: $studio.selectedJobID) {
                        ForEach(studio.jobs.reversed()) { job in
                            JobRow(job: job).tag(job.id)
                                .contextMenu {
                                    if job.status.isActive || job.status.isPending {
                                        Button("Cancel") { studio.cancel(job) }
                                    } else {
                                        Button("Retry from \(job.stage.title)") { studio.retry(job) }
                                        Button("Remove") { studio.remove(job) }
                                    }
                                }
                        }
                    }
                    .frame(minWidth: 240, idealWidth: 280, maxWidth: 360)

                    if let job = studio.jobs.first(where: { $0.id == studio.selectedJobID }) ?? studio.jobs.last {
                        JobDetail(job: job).frame(minWidth: 520)
                    }
                }
            }
        }
        .navigationTitle("Runs")
    }
}

struct JobRow: View {
    let job: Job
    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(job.page.displayTitle).font(.callout.weight(.medium)).lineLimit(1)
            HStack(spacing: 6) {
                statusDot
                Text(job.status == .running ? job.stage.title : job.status.label)
                    .font(.caption).foregroundStyle(.secondary)
            }
            if job.status.isActive {
                ProgressView(value: job.progress).controlSize(.small)
            }
        }
        .padding(.vertical, 4)
    }

    @ViewBuilder private var statusDot: some View {
        switch job.status {
        case .done: Image(systemName: "checkmark.circle.fill").foregroundStyle(.green)
        case .failed: Image(systemName: "xmark.octagon.fill").foregroundStyle(.red)
        case .needsHelp: Image(systemName: "hand.raised.fill").foregroundStyle(.orange)
        case .review: Image(systemName: "text.quote").foregroundStyle(.blue)
        case .cancelled: Image(systemName: "stop.circle").foregroundStyle(.secondary)
        case .queued: Image(systemName: "clock").foregroundStyle(.secondary)
        case .waiting: Image(systemName: "hourglass").foregroundStyle(.secondary)
        case .running: ProgressView().controlSize(.mini)
        }
    }
}

struct JobDetail: View {
    @Environment(Studio.self) private var studio
    let job: Job
    @State private var showLog = false
    @State private var confirmRestart = false

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                HStack(alignment: .top) {
                    VStack(alignment: .leading, spacing: 4) {
                        Text(job.page.displayTitle).font(.title2.weight(.semibold))
                        Text(job.page.url).font(.caption).foregroundStyle(.secondary).textSelection(.enabled)
                    }
                    Spacer()
                    if job.status.isActive || job.status.isPending {
                        if job.stage == .record && job.status.isActive {
                            Button { studio.finishNow(job) } label: { Label("Finish & make video", systemImage: "film") }
                                .help("Stop recording here and make the YouTube video from the steps recorded so far")
                        }
                        Button { confirmRestart = true } label: { Label("Start over", systemImage: "backward.end.fill") }
                            .help("Record this video again from step 1, in a fresh project")
                        Button("Cancel", role: .destructive) { studio.cancel(job) }
                    } else if job.status == .failed || job.status == .cancelled {
                        if job.stage == .record && studio.recordedClips(job) > 0 {
                            Button { studio.makeVideo(fromRecordingOf: job) } label: {
                                Label("Make video from recording", systemImage: "film")
                            }
                            .buttonStyle(.borderedProminent)
                            .help("Script, voice and master the \(studio.recordedClips(job)) clips recorded")
                        }
                        Button { confirmRestart = true } label: { Label("Start over", systemImage: "backward.end.fill") }
                        Button("Retry \(job.stage.title)") { studio.retry(job) }
                            .buttonStyle(.borderedProminent)
                    }
                }

                StagePipeline(job: job)
                    .confirmationDialog("Start “\(job.page.displayTitle)” again from step 1?",
                                        isPresented: $confirmRestart) {
                        Button("Start over", role: .destructive) { studio.restart(job) }
                    } message: {
                        Text("This run stops. The project built so far is moved aside to ~/WSO2Integrator-archive, and recording starts again from step 1.")
                    }

                if let help = job.help, job.status == .needsHelp {
                    HelpCard(job: job, help: help)
                }
                if job.status == .review {
                    ScriptReview(job: job)
                }
                if let error = job.error, job.status == .failed {
                    Label(error, systemImage: "exclamationmark.octagon.fill")
                        .foregroundStyle(.red)
                        .padding(10)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .background(.red.opacity(0.08), in: RoundedRectangle(cornerRadius: 8))
                }
                if !job.notes.isEmpty {
                    VStack(alignment: .leading, spacing: 6) {
                        Text("Handled without you").font(.headline)
                        ForEach(job.notes) { n in
                            Label(n.text, systemImage: n.symbol).font(.callout)
                        }
                    }
                }
                if job.status == .done, let master = job.masterPath {
                    FinishedCard(path: studio.library.first { $0.folder == job.packagedFolder }?.video ?? master,
                                 folder: job.packagedFolder)
                }
                if !job.steps.isEmpty {
                    StepsProgress(job: job)
                }

                DisclosureGroup(isExpanded: $showLog) {
                    LogView(lines: job.log)
                        .frame(height: 320)
                } label: {
                    Text("Log").font(.headline)
                    Text("\(job.log.count) lines").font(.caption).foregroundStyle(.secondary)
                }
            }
            .padding(20)
        }
    }
}

struct StagePipeline: View {
    let job: Job
    var body: some View {
        HStack(spacing: 0) {
            ForEach(Stage.allCases) { stage in
                let state = state(of: stage)
                VStack(spacing: 6) {
                    ZStack {
                        Circle()
                            .fill(color(state).opacity(state == .pending ? 0.12 : 0.18))
                            .frame(width: 40, height: 40)
                        if state == .current && job.status == .running {
                            ProgressView().controlSize(.small)
                        } else {
                            Image(systemName: state == .done ? "checkmark" : stage.symbol)
                                .foregroundStyle(color(state))
                        }
                    }
                    Text(stage.title).font(.caption)
                        .foregroundStyle(state == .pending ? .secondary : .primary)
                }
                .frame(maxWidth: .infinity)
                if stage != Stage.allCases.last {
                    Rectangle()
                        .fill(state == .done ? Color.green.opacity(0.6) : Color.secondary.opacity(0.2))
                        .frame(height: 2)
                        .frame(maxWidth: 60)
                        .offset(y: -10)
                }
            }
        }
        .padding(.vertical, 6)
    }

    enum S { case done, current, pending, failed }

    private func state(of stage: Stage) -> S {
        if job.status == .done { return .done }
        if stage.rawValue < job.stage.rawValue { return .done }
        if stage == job.stage {
            if job.status == .failed || job.status == .cancelled { return .failed }
            if job.status.isPending { return .pending }
            return .current
        }
        return .pending
    }

    private func color(_ s: S) -> Color {
        switch s {
        case .done: .green
        case .current: job.status == .needsHelp ? .orange : .accentColor
        case .pending: .secondary
        case .failed: .red
        }
    }
}

struct HelpCard: View {
    @Environment(Studio.self) private var studio
    @Environment(PhoneBridge.self) private var phone
    let job: Job
    let help: HelpRequest
    @State private var command = ""

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            if help.isStep {
                Label("Step by step — step \(help.step): \(help.stepTitle)", systemImage: "iphone")
                    .font(.headline).foregroundStyle(.blue)
                ForEach(Array(help.actions.enumerated()), id: \.offset) { i, a in
                    Button {
                        studio.answer(job, "#action:\(i)")
                    } label: {
                        HStack {
                            Label(a, systemImage: help.done.contains(i) ? "checkmark.circle.fill"
                                  : (i == help.next ? "play.circle.fill" : "circle"))
                                .foregroundStyle(help.done.contains(i) ? Color.secondary : (i == help.next ? Color.accentColor : Color.primary))
                            if help.done.contains(i) {
                                Text("↻ do again").font(.caption).foregroundStyle(.blue)
                            }
                        }
                    }
                    .buttonStyle(.plain)
                    .help(help.done.contains(i) ? "Do this again — the earlier try leaves the video" : "Do this now")
                }
                Text("Usually driven from your phone. Shows ✓ but did not happen? Click it to do it again. When every step works, this path is saved and the next run is automatic.")
                    .font(.caption).foregroundStyle(.secondary)
            } else if help.isManual {
                Label("Your turn — step \(help.step)", systemImage: "hand.raised.fill")
                    .font(.headline).foregroundStyle(.orange)
                Text(help.label)
                    .padding(10)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(.background, in: RoundedRectangle(cornerRadius: 6))
                Text("FlowCast has no action for this line of the docs. Tell it what to do, one command at a time — each is recorded for the video — then press Continue. It is saved and replayed the next time this page is recorded.")
                    .font(.callout).foregroundStyle(.secondary)
                if help.label.range(of: "configurable", options: .caseInsensitive) != nil {
                    Text("Binding fields: type commands with names — e.g. `click Hostname`, `click Configurables`, `click New Configurable`, `type sfHostname into Variable Name`, `click Save`. FlowCast turns the first field you bind into a template and binds every field on every later page itself. (Taps on the screenshot work, but cannot be generalised.)")
                        .font(.caption).foregroundStyle(.indigo)
                }
            } else {
                Label("FlowCast needs you", systemImage: "hand.raised.fill")
                    .font(.headline).foregroundStyle(.orange)
                if !help.label.isEmpty {
                    Text("Step \(help.step): **\(help.label)**")
                }
                Text(help.reason).font(.callout.monospaced()).foregroundStyle(.secondary)
                if job.guided {
                    Text("Step by step, so you are asked straight away. Click the screenshot where it should click, or type a command.")
                        .font(.caption).foregroundStyle(.secondary)
                } else {
                    Text("Already tried: waiting and retrying, the fix you gave last time if there was one, and scrolling.")
                        .font(.caption).foregroundStyle(.secondary)
                }
            }
            if phone.isRunning, let qr = phone.qrImage() {
                HStack(spacing: 12) {
                    Image(nsImage: qr).interpolation(.none).resizable().frame(width: 96, height: 96)
                    VStack(alignment: .leading, spacing: 4) {
                        Text("Answer from your phone").font(.callout.weight(.semibold))
                        Text("Scan to open this help page on your phone — tap the screenshot where FlowCast should click. Leave it open: it chimes the next time a run needs you.")
                            .font(.caption).foregroundStyle(.secondary)
                    }
                }
            }
            if let shot = help.screenshot, let image = NSImage(contentsOfFile: shot) {
                Image(nsImage: image)
                    .resizable()
                    .aspectRatio(contentMode: .fit)
                    .frame(maxHeight: 300)
                    .clipShape(RoundedRectangle(cornerRadius: 6))
                    .overlay(RoundedRectangle(cornerRadius: 6).strokeBorder(.quaternary))
                    .onTapGesture { NSWorkspace.shared.open(URL(fileURLWithPath: shot)) }
                    .help("Open full size")
            }
            HStack {
                TextField("Tell FlowCast what to do — e.g. click Create, at 712,561", text: $command)
                    .textFieldStyle(.roundedBorder)
                    .onSubmit(send)
                Button("Do it", action: send)
                    .buttonStyle(.borderedProminent)
                    .disabled(command.trimmingCharacters(in: .whitespaces).isEmpty)
            }
            HStack {
                if help.isStep {
                    Button { studio.answer(job, "next") } label: {
                        Label(help.next.map { "Do it: \(help.actions[$0])" } ?? "Step done — continue", systemImage: "play.fill")
                    }
                    .buttonStyle(.borderedProminent)
                    Button { studio.answer(job, "skip") } label: { Label("Skip", systemImage: "forward") }
                    Button { studio.answer(job, "ok") } label: { Label("Finish step", systemImage: "checkmark") }
                    if help.canUndo {
                        Button { studio.answer(job, "undo") } label: { Label("Undo last", systemImage: "arrow.uturn.backward") }
                            .help("Take the last action out of the video (⌘Z if it typed) and offer it again")
                        Button { studio.answer(job, "step over") } label: { Label("Step again", systemImage: "arrow.counterclockwise") }
                            .help("Record step \(help.step) again from its first action")
                    }
                    if help.step > 1 {
                        Button { studio.answer(job, "back") } label: { Label("Back to step \(help.step - 1)", systemImage: "chevron.backward") }
                            .help("Record steps \(help.step - 1) and \(help.step) again")
                    }
                } else if help.isManual {
                    Button { studio.answer(job, "next") } label: { Label("Continue", systemImage: "arrow.right.circle.fill") }
                        .buttonStyle(.borderedProminent)
                    Button { studio.answer(job, "skip") } label: { Label("Skip this line", systemImage: "forward") }
                } else {
                    Button { studio.answer(job, "retry") } label: { Label("Retry", systemImage: "arrow.clockwise") }
                    Button { studio.answer(job, "skip") } label: { Label("Skip this action", systemImage: "forward") }
                    Button { studio.answer(job, "ok") } label: { Label("Finish step", systemImage: "checkmark") }
                }
                Spacer()
                Button(role: .destructive) { studio.answer(job, "abort") } label: { Text("Stop recording") }
            }
            Text("Your command runs, then FlowCast tries the step's action again. Whatever fixes it is saved — the next run of this page does it on its own.")
                .font(.caption).foregroundStyle(.secondary)
        }
        .padding(14)
        .background(.orange.opacity(0.08), in: RoundedRectangle(cornerRadius: 10))
        .overlay(RoundedRectangle(cornerRadius: 10).strokeBorder(.orange.opacity(0.4)))
    }

    private func send() {
        let text = command.trimmingCharacters(in: .whitespaces)
        guard !text.isEmpty else { return }
        studio.answer(job, text)
        command = ""
    }
}

struct ScriptReview: View {
    @Environment(Studio.self) private var studio
    let job: Job
    @State private var text = ""
    @State private var loaded = false

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Label("Review the narration", systemImage: "text.quote").font(.headline)
            Text("One line per recorded action, spoken in your cloned voice. Edit the wording; keep the number of lines in each step.")
                .font(.callout).foregroundStyle(.secondary)
            TextEditor(text: $text)
                .font(.body.monospaced())
                .frame(minHeight: 260)
                .scrollContentBackground(.hidden)
                .padding(6)
                .background(.background, in: RoundedRectangle(cornerRadius: 6))
                .overlay(RoundedRectangle(cornerRadius: 6).strokeBorder(.quaternary))
            HStack {
                Spacer()
                Button {
                    if let p = job.narrationPath { try? text.write(toFile: p, atomically: true, encoding: .utf8) }
                    studio.approveScript(job)
                } label: {
                    Label("Save and voice it", systemImage: "waveform")
                }
                .buttonStyle(.borderedProminent)
            }
        }
        .padding(14)
        .background(.blue.opacity(0.06), in: RoundedRectangle(cornerRadius: 10))
        .onAppear {
            guard !loaded, let p = job.narrationPath else { return }
            text = (try? String(contentsOfFile: p, encoding: .utf8)) ?? ""
            loaded = true
        }
    }
}

struct FinishedCard: View {
    let path: String
    var folder: String? = nil
    @State private var player: AVPlayer?

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Label("Video ready", systemImage: "checkmark.seal.fill")
                .font(.headline).foregroundStyle(.green)
            if let player {
                PlayerView(player: player)
                    .aspectRatio(16 / 9, contentMode: .fit)
                    .clipShape(RoundedRectangle(cornerRadius: 8))
            }
            HStack {
                Button("Show in Finder") {
                    NSWorkspace.shared.activateFileViewerSelecting([URL(fileURLWithPath: path)])
                }
                if let folder {
                    Button("Open YouTube text") {
                        let txt = (try? FileManager.default.contentsOfDirectory(atPath: folder))?
                            .first { $0.hasSuffix("YouTube description.txt") }
                        if let txt { NSWorkspace.shared.open(URL(fileURLWithPath: folder).appendingPathComponent(txt)) }
                    }
                }
                Spacer()
                Text(folder.map { "Saved in \(($0 as NSString).lastPathComponent)" } ?? (path as NSString).lastPathComponent)
                    .font(.caption).foregroundStyle(.secondary)
            }
        }
        .onAppear { player = AVPlayer(url: URL(fileURLWithPath: path)) }
    }
}

struct StepsProgress: View {
    let job: Job
    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Recording").font(.headline)
            ForEach(job.steps) { step in
                HStack(alignment: .top, spacing: 10) {
                    Image(systemName: step.finished ? "checkmark.circle.fill"
                          : (job.currentStep == step.n && job.stage == .record ? "record.circle" : "circle"))
                        .foregroundStyle(step.finished ? .green : (job.currentStep == step.n ? .red : .secondary))
                    VStack(alignment: .leading, spacing: 2) {
                        Text("Step \(step.n): \(step.title)").font(.callout.weight(.medium))
                        Text("\(min(step.done, step.actions.count)) of \(step.actions.count) actions"
                             + (step.failed > 0 ? " · \(step.failed) retried" : ""))
                            .font(.caption).foregroundStyle(.secondary)
                    }
                }
            }
        }
    }
}

struct LogView: View {
    let lines: [String]
    var body: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 1) {
                    ForEach(Array(lines.enumerated()), id: \.offset) { i, line in
                        Text(line)
                            .font(.caption.monospaced())
                            .foregroundStyle(line.contains("✗") ? .red : (line.hasPrefix("──") ? .primary : .secondary))
                            .textSelection(.enabled)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .id(i)
                    }
                }
                .padding(8)
            }
            .background(.background.secondary, in: RoundedRectangle(cornerRadius: 6))
            .onChange(of: lines.count) { _, n in
                proxy.scrollTo(n - 1, anchor: .bottom)
            }
        }
    }
}
