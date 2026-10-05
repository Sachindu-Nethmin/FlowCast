import AVFoundation
import ApplicationServices
import CoreGraphics
import SwiftUI
import UniformTypeIdentifiers

struct SettingsView: View {
    var body: some View {
        TabView {
            VoiceSettings().tabItem { Label("Voice", systemImage: "waveform") }
            RecordingSettings().tabItem { Label("Recording", systemImage: "record.circle") }
            KeysSettings().tabItem { Label("Keys", systemImage: "key") }
            AISettings().tabItem { Label("Help", systemImage: "sparkles") }
            ServicesSettings().tabItem { Label("Services", systemImage: "shippingbox") }
            PermissionSettings().tabItem { Label("Permissions", systemImage: "lock.shield") }
        }
        .frame(width: 620, height: 480)
    }
}

// ── Voice clone ─────────────────────────────────────────────────────────────

struct VoiceSettings: View {
    @Environment(AppSettings.self) private var settings
    @State private var recorder = VoiceSampleRecorder()
    @State private var testLine = "Hi, this is my voice, narrating a WSO2 Integrator walkthrough."
    @State private var testing = false
    @State private var testResult = ""
    @State private var player: AVAudioPlayer?

    var body: some View {
        @Bindable var settings = settings
        Form {
            Section {
                LabeledContent("Reference sample") {
                    HStack {
                        Text((settings.voiceReference as NSString).lastPathComponent)
                            .foregroundStyle(FileManager.default.fileExists(atPath: settings.voiceReference) ? .primary : Color.red)
                        Button("Choose…") { chooseReference() }
                        Button { play(settings.voiceReference) } label: { Image(systemName: "play.fill") }
                            .disabled(!FileManager.default.fileExists(atPath: settings.voiceReference))
                    }
                }
                LabeledContent("Record a new sample") {
                    HStack {
                        if recorder.isRecording {
                            ProgressView(value: recorder.elapsed, total: VoiceSampleRecorder.seconds)
                                .frame(width: 120)
                            Text("\(Int(VoiceSampleRecorder.seconds - recorder.elapsed))s")
                                .monospacedDigit()
                            Button("Stop") { recorder.stop() }
                        } else {
                            Button {
                                let dir = settings.rootURL.appendingPathComponent("assets/voice")
                                recorder.record(into: dir) { url in settings.voiceReference = url.path }
                            } label: { Label("Record 15 seconds", systemImage: "mic.fill") }
                        }
                    }
                }
                if let err = recorder.error {
                    Text(err).font(.caption).foregroundStyle(.red)
                }
                Text("Read anything in your normal narrating voice — clean room, no music. 10–20 seconds is what the clone needs.")
                    .font(.caption).foregroundStyle(.secondary)
            } header: { Text("Your cloned voice (Chatterbox, runs locally)") }

            Section("Try it") {
                TextField("Line to speak", text: $testLine)
                HStack {
                    Button(testing ? "Synthesizing…" : "Speak in my voice") { test() }
                        .disabled(testing)
                    if testing { ProgressView().controlSize(.small) }
                    Text(testResult).font(.caption).foregroundStyle(.secondary)
                }
            }

            Section("Quality") {
                Stepper("Takes per narration line: \(settings.narrationTakes)", value: $settings.narrationTakes, in: 1...8)
                Stepper("Takes for the title card: \(settings.masterTakes)", value: $settings.masterTakes, in: 1...12)
                Text("More takes keep the take closest to your reference — slower, but short lines stay recognisably you.")
                    .font(.caption).foregroundStyle(.secondary)
            }
        }
        .formStyle(.grouped)
    }

    private func chooseReference() {
        let panel = NSOpenPanel()
        panel.allowedContentTypes = [.wav, .audio]
        panel.directoryURL = settings.rootURL.appendingPathComponent("assets/voice")
        if panel.runModal() == .OK, let url = panel.url { settings.voiceReference = url.path }
    }

    private func play(_ path: String) {
        player = try? AVAudioPlayer(contentsOf: URL(fileURLWithPath: path))
        player?.play()
    }

    private func test() {
        testing = true
        testResult = "loading the voice model takes ~20s the first time"
        let p = StudioProcess(settings: settings, script: "tools/studio.py",
                              arguments: ["voice-check", "--ref", settings.voiceReference, "--say", testLine])
        p.onEvent = { ev in
            if let preview = ev.string("preview") {
                testResult = "\(ev.data["seconds"] ?? "?")s of speech"
                play(preview)
            } else if ev.bool("chatterbox_ok") == false {
                testResult = "Voice model missing — create .venv-voice (see tools/README-voice-clone.md)"
            } else if ev.name == "error" {
                testResult = ev.string("message") ?? "failed"
            }
        }
        p.onExit = { _ in testing = false }
        try? p.start()
    }
}

@Observable
final class VoiceSampleRecorder: NSObject, AVAudioRecorderDelegate {
    static let seconds: Double = 15
    var isRecording = false
    var elapsed: Double = 0
    var error: String?
    @ObservationIgnored private var recorder: AVAudioRecorder?
    @ObservationIgnored private var timer: Timer?
    @ObservationIgnored private var done: ((URL) -> Void)?

    func record(into dir: URL, completion: @escaping (URL) -> Void) {
        error = nil
        AVCaptureDevice.requestAccess(for: .audio) { granted in
            DispatchQueue.main.async {
                guard granted else {
                    self.error = "Microphone access is off for FlowCast Studio (System Settings › Privacy & Security › Microphone)."
                    return
                }
                self.start(into: dir, completion: completion)
            }
        }
    }

    private func start(into dir: URL, completion: @escaping (URL) -> Void) {
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        let stamp = ISO8601DateFormatter().string(from: Date()).replacingOccurrences(of: ":", with: "")
        let url = dir.appendingPathComponent("reference-\(stamp).wav")
        // 24 kHz mono 16-bit: what tools/voice_clone_server.py expects.
        let fmt: [String: Any] = [AVFormatIDKey: kAudioFormatLinearPCM, AVSampleRateKey: 24000,
                                  AVNumberOfChannelsKey: 1, AVLinearPCMBitDepthKey: 16,
                                  AVLinearPCMIsFloatKey: false, AVLinearPCMIsBigEndianKey: false]
        do {
            let r = try AVAudioRecorder(url: url, settings: fmt)
            r.delegate = self
            r.record(forDuration: Self.seconds)
            recorder = r
            done = completion
            isRecording = true
            elapsed = 0
            timer = Timer.scheduledTimer(withTimeInterval: 0.1, repeats: true) { [weak self] _ in
                guard let self, let r = self.recorder else { return }
                self.elapsed = min(Self.seconds, r.currentTime)
            }
        } catch {
            self.error = error.localizedDescription
        }
    }

    func stop() { recorder?.stop() }

    func audioRecorderDidFinishRecording(_ recorder: AVAudioRecorder, successfully flag: Bool) {
        DispatchQueue.main.async {
            self.timer?.invalidate()
            self.isRecording = false
            if flag { self.done?(recorder.url) } else { self.error = "Recording failed." }
        }
    }
}

// ── Recording ───────────────────────────────────────────────────────────────

struct RecordingSettings: View {
    @Environment(AppSettings.self) private var settings

    var body: some View {
        @Bindable var settings = settings
        Form {
            Section("FlowCast project") {
                LabeledContent("Folder") {
                    HStack {
                        Text(settings.projectRoot).lineLimit(1).truncationMode(.middle)
                        Button("Choose…") {
                            let panel = NSOpenPanel()
                            panel.canChooseDirectories = true
                            panel.canChooseFiles = false
                            if panel.runModal() == .OK, let url = panel.url { settings.projectRoot = url.path }
                        }
                    }
                }
                TextField("uv", text: $settings.uvPath)
            }
            Section("Each recording") {
                Toggle("Start from an empty ~/WSO2Integrator", isOn: $settings.freshProjects)
                Text("Moves existing projects to ~/WSO2Integrator-archive so step 1 can create the project without a name clash. Nothing is deleted.")
                    .font(.caption).foregroundStyle(.secondary)
                Toggle("Hide this window while recording", isOn: $settings.hideDuringRecording)
                Toggle("Let me review the narration before it is voiced", isOn: $settings.reviewNarration)
            }
            Section("Video") {
                LabeledContent("Save finished videos to") {
                    HStack {
                        Text((settings.videosFolder as NSString).abbreviatingWithTildeInPath)
                            .lineLimit(1).truncationMode(.middle)
                        Button("Choose…") {
                            let panel = NSOpenPanel()
                            panel.canChooseDirectories = true
                            panel.canChooseFiles = false
                            panel.canCreateDirectories = true
                            if panel.runModal() == .OK, let url = panel.url { settings.videosFolder = url.path }
                        }
                    }
                }
                Picker("Master resolution", selection: $settings.quality) {
                    Text("1080p").tag("1080p")
                    Text("1440p (YouTube keeps text sharper)").tag("1440p")
                    Text("4K").tag("4k")
                }
            }
        }
        .formStyle(.grouped)
    }
}

// ── Permissions ─────────────────────────────────────────────────────────────

struct PermissionSettings: View {
    @State private var screen = CGPreflightScreenCaptureAccess()
    @State private var accessibility = AXIsProcessTrusted()

    var body: some View {
        Form {
            Section {
                row("Screen Recording", ok: screen,
                    detail: "FlowCast films WSO2 Integrator with ffmpeg; macOS grants that to this app.") {
                    _ = CGRequestScreenCaptureAccess()
                    open("Privacy_ScreenCapture")
                }
                row("Accessibility", ok: accessibility,
                    detail: "Moves the mouse and types into WSO2 Integrator.") {
                    let opts = [kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String: true] as CFDictionary
                    _ = AXIsProcessTrustedWithOptions(opts)
                    open("Privacy_Accessibility")
                }
            } footer: {
                Text("After granting, quit and reopen FlowCast Studio — macOS only re-reads these at launch. macOS also asks once to let it control WSO2 Integrator and System Events; allow both.")
            }
            Button("Check again") {
                screen = CGPreflightScreenCaptureAccess()
                accessibility = AXIsProcessTrusted()
            }
        }
        .formStyle(.grouped)
    }

    private func row(_ name: String, ok: Bool, detail: String, request: @escaping () -> Void) -> some View {
        HStack {
            Image(systemName: ok ? "checkmark.circle.fill" : "exclamationmark.circle.fill")
                .foregroundStyle(ok ? .green : .orange)
            VStack(alignment: .leading) {
                Text(name)
                Text(detail).font(.caption).foregroundStyle(.secondary)
            }
            Spacer()
            if !ok { Button("Grant…", action: request) }
        }
    }

    private func open(_ pane: String) {
        NSWorkspace.shared.open(URL(string: "x-apple.systempreferences:com.apple.preference.security?\(pane)")!)
    }
}


// ── Keys ────────────────────────────────────────────────────────────────────

struct KeysSettings: View {
    @Environment(Studio.self) private var studio

    var body: some View {
        Form {
            Section {
                if studio.inputs.saved.isEmpty {
                    Text("Nothing saved yet. Pages that need an API key or a connection value ask for it in their detail panel.")
                        .foregroundStyle(.secondary)
                }
                ForEach(studio.inputs.saved, id: \.name) { item in
                    HStack {
                        Image(systemName: item.secret ? "lock.fill" : "textformat")
                            .foregroundStyle(.secondary).frame(width: 18)
                        Text(item.name).font(.body.monospaced())
                        Spacer()
                        Text(item.secret ? "Keychain" : (studio.inputs.value(item.name, secret: false) ?? ""))
                            .foregroundStyle(.secondary).lineLimit(1).truncationMode(.middle)
                        Button(role: .destructive) { studio.inputs.remove(item.name) } label: {
                            Image(systemName: "trash")
                        }
                        .buttonStyle(.borderless)
                    }
                }
            } header: {
                Text("Values shared by every page that names them")
            } footer: {
                Text("Secrets (keys, tokens, passwords) are stored in your login Keychain under “FlowCast Studio”. They go to a project's Config.toml during a recording and nowhere else.")
            }
        }
        .formStyle(.grouped)
    }
}

// ── Services ────────────────────────────────────────────────────────────────

struct ServicesSettings: View {
    @Environment(AppSettings.self) private var settings
    @State private var engine: Bool?
    @State private var running: [String] = []
    @State private var busy = false

    var body: some View {
        Form {
            Section {
                LabeledContent("Docker") {
                    if let engine {
                        Label(engine ? "running" : "stopped — starts automatically when a page needs it",
                              systemImage: engine ? "checkmark.circle.fill" : "pause.circle")
                            .foregroundStyle(engine ? .green : .secondary)
                    } else {
                        ProgressView().controlSize(.small)
                    }
                }
                if running.isEmpty {
                    Text("No FlowCast containers running.").foregroundStyle(.secondary)
                } else {
                    ForEach(running, id: \.self) { r in
                        Label(recipeLabel(r), systemImage: "shippingbox.fill").foregroundStyle(.teal)
                    }
                }
                HStack {
                    Button("Refresh") { refresh() }
                    Button("Stop all", role: .destructive) { run(["services", "--stop"]) }
                        .disabled(running.isEmpty)
                    if busy { ProgressView().controlSize(.small) }
                }
            } header: {
                Text("Prerequisites FlowCast starts for you")
            } footer: {
                Text("Brokers and databases for event and connector pages run as containers named flowcast-*. They are kept between videos so the next recording does not wait for them; Stop all removes them.")
            }
        }
        .formStyle(.grouped)
        .onAppear(perform: refresh)
    }

    private func refresh() { run(["services"]) }

    private func run(_ args: [String]) {
        busy = true
        let p = StudioProcess(settings: settings, script: "tools/studio.py", arguments: args)
        p.onEvent = { ev in
            guard ev.name == "services" else { return }
            running = ev.strings("running")
            if let e = ev.bool("engine") { engine = e }
        }
        p.onExit = { _ in
            busy = false
            if args.contains("--stop") { refresh() }
        }
        try? p.start()
    }
}


// ── Local model (YouTube text) + phone help ─────────────────────────────────

struct AISettings: View {
    @Environment(AppSettings.self) private var settings
    @State private var models: [String] = []
    @State private var ollama: Bool?

    var body: some View {
        @Bindable var settings = settings
        Form {
            Section {
                Toggle("Write the YouTube title, description and thumbnail text with a local model", isOn: $settings.aiEnabled)
                Picker("Model", selection: $settings.aiModel) {
                    ForEach(Array(Set(models + [settings.aiModel])).sorted(), id: \.self) { Text($0).tag($0) }
                }
                .disabled(!settings.aiEnabled)
                LabeledContent("Ollama") {
                    if let ollama {
                        Label(ollama ? "running on this Mac" : "not running — open Ollama",
                              systemImage: ollama ? "checkmark.circle.fill" : "xmark.circle")
                            .foregroundStyle(ollama ? .green : .orange)
                    } else { ProgressView().controlSize(.small) }
                }
            } header: {
                Text("Local model")
            } footer: {
                Text("Used only while the Master stage writes the title, description, thumbnail headline and intro line — then released, so the voice model has the memory (on 16 GB, a model left loaded pushed the voice into swap). Never used while recording: a stuck action asks you on your phone. Narration lines come from FlowCast's rules. Nothing leaves this Mac.")
            }
            Section {
                Toggle("Start the phone link with every recording", isOn: $settings.phoneDuringRuns)
                Toggle("First run of a video: step by step on my phone", isOn: $settings.firstRunGuided)
            } footer: {
                Text("Keep the phone page open: it chimes and vibrates when a run needs you, and you can tap the screenshot where FlowCast should click. Fixes you give are learned, so each one is asked once.")
            }
        }
        .formStyle(.grouped)
        .task { await load() }
    }

    private func load() async {
        guard let url = URL(string: "http://127.0.0.1:11434/api/tags"),
              let (data, _) = try? await URLSession.shared.data(from: url),
              let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let list = obj["models"] as? [[String: Any]] else {
            ollama = false
            return
        }
        ollama = true
        models = list.compactMap { $0["name"] as? String }
    }
}
