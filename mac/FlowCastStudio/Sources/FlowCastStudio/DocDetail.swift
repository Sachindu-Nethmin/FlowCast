import SwiftUI

struct DocDetail: View {
    @Environment(Studio.self) private var studio
    @Environment(AppSettings.self) private var settings
    let page: DocPage
    let openRuns: () -> Void
    var close: () -> Void = {}
    @State private var showWorkflow = false

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                VStack(alignment: .leading, spacing: 8) {
                    HStack {
                        VerdictBadge(verdict: page.kind)
                        Spacer()
                        Button(action: close) { Image(systemName: "xmark.circle.fill") }
                            .buttonStyle(.plain)
                            .foregroundStyle(.secondary)
                            .keyboardShortcut(.cancelAction)
                            .help("Close")
                    }
                    Text(page.displayTitle).font(.title2.weight(.semibold))
                    Text(page.area).font(.callout).foregroundStyle(.secondary)
                    if !page.description.isEmpty {
                        Text(page.description).font(.callout)
                    }
                    if !page.build.isEmpty {
                        Label(page.build, systemImage: "hammer")
                            .font(.callout).foregroundStyle(.secondary)
                    }
                    HStack {
                        Link(destination: URL(string: page.url)!) {
                            Label("Open docs page", systemImage: "safari")
                        }
                        if page.isRecordable {
                            Spacer()
                            let missing = studio.inputs.missing(for: page).count
                            Button {
                                if studio.enqueue([page]) != nil { openRuns() }
                            } label: {
                                Label(missing > 0 ? "Enter \(missing) value\(missing == 1 ? "" : "s") below"
                                      : "Make video", systemImage: missing > 0 ? "key" : "record.circle")
                            }
                            .buttonStyle(.borderedProminent)
                            .tint(page.kind.tint)
                            .disabled(missing > 0)
                            if let rec = studio.unfinishedRecording(page) {
                                Button {
                                    if studio.makeVideo(fromRecordingOf: page) != nil { openRuns() }
                                } label: {
                                    Label("Make video from last recording", systemImage: "film")
                                }
                                .help("\(rec.clips) clips recorded, no finished video yet — starts at \(rec.from.title)")
                            }
                        }
                    }
                    .padding(.top, 4)
                }

                Text(page.kind.explanation)
                    .font(.callout)
                    .foregroundStyle(.secondary)
                    .padding(10)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(page.kind.tint.opacity(0.08), in: RoundedRectangle(cornerRadius: 8))

                if let video = studio.video(for: page) {
                    GroupBox {
                        HStack {
                            Image(systemName: "film").foregroundStyle(.purple)
                            Text(video.title).lineLimit(1)
                            Spacer()
                            Button("Play") { NSWorkspace.shared.open(URL(fileURLWithPath: video.video)) }
                            Button("Reveal") {
                                NSWorkspace.shared.activateFileViewerSelecting([URL(fileURLWithPath: video.video)])
                            }
                        }
                    } label: { Text("Already in your library") }
                }

                if !page.recipes.isEmpty {
                    GroupBox("FlowCast starts these for you") {
                        VStack(alignment: .leading, spacing: 6) {
                            ForEach(page.recipes, id: \.self) { r in
                                Label(recipeLabel(r), systemImage: "shippingbox.fill")
                                    .foregroundStyle(.teal)
                            }
                            Text("Local containers via Docker (colima starts automatically). They keep running between videos — Settings › Services stops them.")
                                .font(.caption).foregroundStyle(.secondary)
                        }
                        .font(.callout)
                        .frame(maxWidth: .infinity, alignment: .leading)
                    }
                }

                if let service = page.service, !page.inputs.isEmpty, !service.contains("locally") {
                    Label("Uses your \(service) account — sign in to it yourself once; FlowCast never signs in for you.",
                          systemImage: "person.badge.key")
                        .font(.callout).foregroundStyle(.secondary)
                }

                if !page.inputs.isEmpty {
                    InputsForm(page: page)
                }

                if !page.bindings.isEmpty {
                    GroupBox {
                        VStack(alignment: .leading, spacing: 4) {
                            ForEach(page.bindings, id: \.self) { b in
                                HStack {
                                    Text(b.label).font(.callout.monospaced())
                                    Image(systemName: "arrow.right").font(.caption).foregroundStyle(.secondary)
                                    Text(b.variable).font(.callout.monospaced()).foregroundStyle(.indigo)
                                    if b.nested { Text("nested").font(.caption2).foregroundStyle(.orange) }
                                }
                            }
                            Text(studio.knowsBinding(nested: page.bindings.contains { $0.nested })
                                 ? "FlowCast binds these itself with the pattern it learned."
                                 : "The first time, FlowCast asks you to bind one field — then it does the rest, on every page.")
                                .font(.caption).foregroundStyle(.secondary)
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                    } label: {
                        Label("Connection fields bound to configurables", systemImage: "link")
                    }
                }

                if !page.manualRequires.isEmpty || !page.setupCommands.isEmpty || page.startsInProject
                    || !page.notesExtra.isEmpty {
                    GroupBox("Before FlowCast starts") {
                        VStack(alignment: .leading, spacing: 6) {
                            ForEach(page.manualRequires, id: \.self) { r in
                                Label(r, systemImage: "exclamationmark.triangle")
                                    .foregroundStyle(.orange)
                            }
                            ForEach(page.notesExtra, id: \.self) { n in
                                Label(n, systemImage: "info.circle").foregroundStyle(.secondary)
                            }
                            ForEach(page.setupCommands, id: \.self) { c in
                                Label("FlowCast runs `\(c)` first", systemImage: "terminal")
                            }
                            if page.startsInProject {
                                Label("The page starts inside an integration — FlowCast creates one first, as the docs advise.",
                                      systemImage: "plus.square.on.square")
                            }
                        }
                        .font(.callout)
                        .frame(maxWidth: .infinity, alignment: .leading)
                    }
                }

                if !page.steps.isEmpty {
                    HStack {
                        Text("Line by line").font(.headline)
                        Spacer()
                        Toggle("Show FlowCast actions", isOn: $showWorkflow)
                            .toggleStyle(.switch).controlSize(.mini)
                    }
                    ForEach(page.steps, id: \.n) { step in
                        VStack(alignment: .leading, spacing: 6) {
                            Text("Step \(step.n) · \(step.title)")
                                .font(.subheadline.weight(.semibold))
                            ForEach(Array(step.lines.enumerated()), id: \.offset) { _, line in
                                LineRow(line: line, showWorkflow: showWorkflow)
                            }
                        }
                        .padding(10)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .background(.background.secondary, in: RoundedRectangle(cornerRadius: 8))
                    }
                    HStack(spacing: 14) {
                        legend("checkmark.circle.fill", .green, "FlowCast does it")
                        legend("info.circle", .secondary, "just a check")
                        legend("hand.raised.fill", .orange, "you, once — then replayed")
                    }
                    .font(.caption)
                }

                if let wf = page.workflowFile {
                    Button {
                        NSWorkspace.shared.open(settings.rootURL.appendingPathComponent(wf))
                    } label: {
                        Label("Open generated workflow", systemImage: "doc.plaintext")
                    }
                    .buttonStyle(.link)
                }
            }
            .padding(18)
        }
        .background(.background)
    }

    private func legend(_ symbol: String, _ tint: Color, _ text: String) -> some View {
        Label { Text(text).foregroundStyle(.secondary) } icon: {
            Image(systemName: symbol).foregroundStyle(tint)
        }
    }
}

struct LineRow: View {
    let line: DocLine
    let showWorkflow: Bool

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 8) {
            Image(systemName: symbol).foregroundStyle(tint).font(.caption)
            VStack(alignment: .leading, spacing: 3) {
                Text(markdown(line.source)).font(.callout)
                    .fixedSize(horizontal: false, vertical: true)
                if let manual = line.manual, line.kind == "mixed" {
                    Text("You: " + manual).font(.caption).foregroundStyle(.orange)
                }
                if showWorkflow {
                    ForEach(line.workflow.filter { plain($0) != plain(line.source) }, id: \.self) { w in
                        Text("→ " + w.replacingOccurrences(of: "**", with: ""))
                            .font(.caption.monospaced())
                            .foregroundStyle(.secondary)
                    }
                }
            }
        }
    }

    private func plain(_ s: String) -> String {
        s.replacingOccurrences(of: "**", with: "").replacingOccurrences(of: "`", with: "")
            .trimmingCharacters(in: CharacterSet(charactersIn: ". "))
    }

    private var symbol: String {
        switch line.kind {
        case "action": "checkmark.circle.fill"
        case "info": "info.circle"
        default: "hand.raised.fill"
        }
    }

    private var tint: Color {
        switch line.kind {
        case "action": .green
        case "info": .secondary
        default: .orange
        }
    }
}

func markdown(_ s: String) -> AttributedString {
    let cleaned = s.hasPrefix("  - ") ? "• " + s.dropFirst(4) : s
    return (try? AttributedString(markdown: String(cleaned),
                                  options: .init(interpretedSyntax: .inlineOnlyPreservingWhitespace)))
        ?? AttributedString(cleaned)
}


func recipeLabel(_ id: String) -> String {
    ["rabbitmq": "RabbitMQ", "kafka": "Kafka", "mqtt": "MQTT broker (Mosquitto)", "mysql": "MySQL",
     "postgres": "PostgreSQL", "mssql": "Microsoft SQL Server", "redis": "Redis", "mongodb": "MongoDB",
     "activemq": "ActiveMQ", "solace": "Solace PubSub+", "sftp": "SFTP server",
     "smtp": "Mail server (Mailpit)"][id] ?? id
}

/// The page's configurables: yours to fill (secrets go to Keychain), or
/// already answered by a prerequisite FlowCast starts.
struct InputsForm: View {
    @Environment(Studio.self) private var studio
    let page: DocPage
    @State private var drafts: [String: String] = [:]
    @State private var saved: Set<String> = []

    var body: some View {
        GroupBox {
            VStack(alignment: .leading, spacing: 10) {
                ForEach(page.inputs) { input in
                    VStack(alignment: .leading, spacing: 3) {
                        HStack {
                            Text(input.name).font(.callout.monospaced().weight(.medium))
                            if input.secret {
                                Image(systemName: "lock.fill").font(.caption2).foregroundStyle(.secondary)
                            }
                            Spacer()
                            if let auto = input.auto, !studio.inputs.has(input) {
                                Text(input.secret ? "from the local container" : "auto: \(auto)")
                                    .font(.caption).foregroundStyle(.teal)
                            } else if studio.inputs.has(input) {
                                Label(input.secret ? "in Keychain" : "saved", systemImage: "checkmark.circle.fill")
                                    .font(.caption).foregroundStyle(.green)
                            }
                        }
                        Group {
                            if input.secret {
                                SecureField(placeholder(input), text: binding(input))
                            } else {
                                TextField(placeholder(input), text: binding(input))
                            }
                        }
                        .textFieldStyle(.roundedBorder)
                        .onSubmit { commit(input) }
                        Text(input.label).font(.caption).foregroundStyle(.secondary).lineLimit(2)
                    }
                }
                HStack {
                    Button("Save values") { page.inputs.forEach(commit) }
                        .buttonStyle(.borderedProminent)
                    Spacer()
                    Text("Written to the project's Config.toml when the run reaches that step — never typed on screen, never in the video or logs.")
                        .font(.caption).foregroundStyle(.secondary)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        } label: {
            Label("Your keys and values", systemImage: "key.fill")
        }
        .onAppear(perform: load)
        .onChange(of: page.slug) { _, _ in load() }
    }

    private func placeholder(_ i: DocInput) -> String {
        if let a = i.auto { return i.secret ? "leave empty to use the local container's" : a }
        if let e = i.example { return "e.g. \(e)" }
        return i.secret ? "paste it here" : i.type
    }

    private func binding(_ i: DocInput) -> Binding<String> {
        Binding(get: { drafts[i.name] ?? "" }, set: { drafts[i.name] = $0 })
    }

    private func load() {
        drafts = [:]
        for i in page.inputs where !i.secret {
            drafts[i.name] = studio.inputs.value(i.name, secret: false) ?? ""
        }
        // Secrets are not read back into the view; an empty field keeps the
        // stored value, typing replaces it.
    }

    private func commit(_ i: DocInput) {
        let v = drafts[i.name] ?? ""
        if i.secret && v.isEmpty { return }
        studio.inputs.set(i.name, v, secret: i.secret)
        if i.secret { drafts[i.name] = "" }
    }
}
