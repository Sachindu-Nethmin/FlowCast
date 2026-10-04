import SwiftUI

struct DocsBrowser: View {
    @Environment(Studio.self) private var studio
    let verdict: Verdict?
    @Binding var inspected: DocPage?
    let openRuns: () -> Void

    @State private var query = ""
    @State private var area = "All areas"
    @State private var selecting = false
    @State private var picked: Set<String> = []

    private var pages: [DocPage] {
        let base = studio.pages(for: verdict)
        let q = query.trimmingCharacters(in: .whitespaces).lowercased()
        return base.filter { p in
            (area == "All areas" || p.areaGroup == area) &&
            (q.isEmpty || p.title.lowercased().contains(q) || p.path.lowercased().contains(q)
             || p.description.lowercased().contains(q))
        }
        .sorted { a, b in
            if (a.verified != nil) != (b.verified != nil) { return a.verified != nil }
            if a.coverage != b.coverage { return a.coverage > b.coverage }
            return a.actionCount > b.actionCount
        }
    }

    private var areas: [String] {
        let all = Set(studio.pages(for: verdict).map(\.areaGroup))
        return ["All areas"] + all.sorted()
    }

    var body: some View {
        Group {
            if let error = studio.catalogError, studio.catalog == nil {
                ContentUnavailableView {
                    Label("No docs catalog yet", systemImage: "doc.text.magnifyingglass")
                } description: {
                    Text(error)
                } actions: {
                    Button("Build catalog") { studio.refreshCatalog() }
                        .buttonStyle(.borderedProminent)
                        .disabled(studio.refreshing)
                }
            } else {
                ScrollView {
                    VStack(alignment: .leading, spacing: 18) {
                        header
                        if pages.isEmpty {
                            ContentUnavailableView.search(text: query)
                                .frame(maxWidth: .infinity, minHeight: 240)
                        } else {
                            LazyVGrid(columns: [GridItem(.adaptive(minimum: 290, maximum: 420), spacing: 14)],
                                      spacing: 14) {
                                ForEach(pages) { page in
                                    DocCard(page: page,
                                            selecting: selecting,
                                            picked: picked.contains(page.slug),
                                            inspected: inspected?.slug == page.slug,
                                            make: { make([page]) })
                                    .onTapGesture {
                                        if selecting {
                                            toggle(page)
                                        } else {
                                            inspected = page
                                        }
                                    }
                                }
                            }
                        }
                    }
                    .padding(20)
                }
            }
        }
        .navigationTitle(verdict?.label ?? "All walkthroughs")
        .navigationSubtitle(subtitle)
        .searchable(text: $query, placement: .toolbar, prompt: "Search docs")
        .overlay(alignment: .bottom) {
            if studio.refreshing {
                RefreshBanner(lines: studio.refreshLog)
                    .padding()
            }
        }
    }

    private var subtitle: String {
        guard let s = studio.catalog?.summary else { return "" }
        return "\(pages.count) shown · \(s.total) pages · \(s.walkthroughs) walkthroughs"
    }

    @ViewBuilder private var header: some View {
        if let s = studio.catalog?.summary {
            VStack(alignment: .leading, spacing: 14) {
                // Wraps into rows when the detail panel narrows the page.
                LazyVGrid(columns: [GridItem(.adaptive(minimum: 170), spacing: 12)], spacing: 12) {
                    StatTile(value: s.total, label: "docs pages", symbol: "doc.on.doc", tint: .secondary)
                    StatTile(value: s.walkthroughs, label: "walkthroughs", symbol: "list.number", tint: .blue)
                    StatTile(value: s.ready + (s.auto ?? 0), label: "run hands-free",
                             symbol: Verdict.ready.symbol, tint: .green)
                    StatTile(value: s.verified, label: "already recorded", symbol: "film", tint: .purple)
                }
                if let v = verdict {
                    Label {
                        Text(v.explanation).foregroundStyle(.secondary)
                    } icon: {
                        Image(systemName: v.symbol).foregroundStyle(v.tint)
                    }
                    .font(.callout)
                }
                controls
                if verdict == .ready || verdict == .auto, !pages.isEmpty, !selecting {
                    HStack {
                        Button {
                            make(pages)
                        } label: {
                            Label(pages.count == 1 ? "Make this video" : "Make videos of all \(pages.count)",
                                  systemImage: "film.stack")
                        }
                        .buttonStyle(.borderedProminent)
                        .controlSize(.large)
                        Text("Records each one hands-free, then narrates it in your cloned voice.")
                            .font(.callout).foregroundStyle(.secondary)
                    }
                }
            }
        }
    }

    /// Filters live in the page, not the toolbar: a crowded toolbar beside the
    /// inspector overflows back and forth and AppKit gives up on the layout.
    private var controls: some View {
        HStack(spacing: 10) {
            Menu {
                ForEach(areas, id: \.self) { a in
                    Button { area = a } label: {
                        if a == area { Label(a, systemImage: "checkmark") } else { Text(a) }
                    }
                }
            } label: {
                Label(area, systemImage: "line.3.horizontal.decrease.circle")
            }
            .menuStyle(.borderlessButton)
            .fixedSize()
            Divider().frame(height: 16)
            Toggle(isOn: $selecting.animation()) {
                Label(selecting ? "Done selecting" : "Select several", systemImage: "checklist")
            }
            .toggleStyle(.button)
            if selecting {
                Button {
                    make(pages.filter { picked.contains($0.slug) })
                    picked = []
                    selecting = false
                } label: {
                    Label("Make \(picked.count) video\(picked.count == 1 ? "" : "s")", systemImage: "film.stack")
                }
                .buttonStyle(.borderedProminent)
                .disabled(picked.isEmpty)
                Button("All shown") { picked = Set(pages.filter(\.isRecordable).map(\.slug)) }
                    .buttonStyle(.link)
            }
            Spacer()
        }
        .font(.callout)
    }

    private func toggle(_ page: DocPage) {
        guard page.isRecordable else { return }
        if picked.contains(page.slug) { picked.remove(page.slug) } else { picked.insert(page.slug) }
    }

    private func make(_ pages: [DocPage]) {
        // Pages missing your keys are recorded with placeholders.
        if studio.enqueue(pages) != nil { openRuns() }
    }
}

struct StatTile: View {
    let value: Int
    let label: String
    let symbol: String
    let tint: Color

    var body: some View {
        HStack(spacing: 10) {
            Image(systemName: symbol)
                .font(.title2)
                .foregroundStyle(tint)
                .frame(width: 28)
            VStack(alignment: .leading, spacing: 0) {
                Text("\(value)").font(.title2.weight(.semibold).monospacedDigit())
                    .lineLimit(1).fixedSize()
                Text(label).font(.caption).foregroundStyle(.secondary).lineLimit(1)
            }
            Spacer(minLength: 0)
        }
        .padding(12)
        .frame(maxWidth: .infinity)
        .background(.background.secondary, in: RoundedRectangle(cornerRadius: 10))
    }
}

struct DocCard: View {
    @Environment(Studio.self) private var studio
    let page: DocPage
    let selecting: Bool
    let picked: Bool
    let inspected: Bool
    let make: () -> Void
    @State private var hover = false

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 6) {
                VerdictBadge(verdict: page.kind)
                if let run = studio.lastRun(page) {
                    let mode = studio.mode(page)
                    Label(mode == .handsFree ? "Hands-free ✓" : mode == .learned ? "Path proven · auto"
                          : "Needed you \(run.asked_person + run.manual_lines)×",
                          systemImage: mode == .handsFree ? "checkmark.seal" : "person.fill.questionmark")
                        .font(.caption.weight(.medium))
                        .padding(.horizontal, 7).padding(.vertical, 3)
                        .background((run.hands_free ? Color.green : Color.orange).opacity(0.14), in: Capsule())
                        .foregroundStyle(run.hands_free ? .green : .orange)
                        .help("Last run \(run.at): \(run.recorded ?? 0)/\(run.steps) steps, "
                              + "\(run.ai_fixes) fixed by the local AI, \(run.learned_replays) by learned fixes")
                } else if page.verified != nil || studio.video(for: page) != nil {
                    Label("Recorded", systemImage: "film")
                        .font(.caption.weight(.medium))
                        .padding(.horizontal, 7).padding(.vertical, 3)
                        .background(.purple.opacity(0.14), in: Capsule())
                        .foregroundStyle(.purple)
                }
                Spacer()
                if selecting {
                    Image(systemName: picked ? "checkmark.circle.fill" : "circle")
                        .font(.title3)
                        .foregroundStyle(picked ? Color.accentColor : .secondary)
                        .opacity(page.isRecordable ? 1 : 0.3)
                }
            }
            Text(page.area)
                .font(.caption)
                .foregroundStyle(.secondary)
            Text(page.displayTitle)
                .font(.headline)
                .lineLimit(2)
                .fixedSize(horizontal: false, vertical: true)
            if !page.description.isEmpty {
                Text(page.description)
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                    .lineLimit(3)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Spacer(minLength: 0)
            if !page.blockers.isEmpty || !page.notes.isEmpty || (page.service != nil && !page.inputs.isEmpty) {
                FlowChips(items: (page.blockers + page.notes).map(blockerLabel)
                          + (page.service.map { s in page.inputs.isEmpty || s.contains("locally") ? [] : ["Your \(s) account"] } ?? []))
            }
            Divider()
            HStack(spacing: 10) {
                Label("\(page.stepCount)", systemImage: "list.number")
                    .help("\(page.stepCount) steps")
                Label("\(page.actionCount)", systemImage: "cursorarrow.click")
                    .help("\(page.actionCount) actions FlowCast performs")
                Label("\(Int((page.coverage * 100).rounded()))%", systemImage: "checkmark.circle")
                    .help("Share of instructions FlowCast can execute")
                Spacer()
                if let job = studio.job(for: page), job.status.isActive || job.status.isPending {
                    Text(job.status.label).font(.caption).foregroundStyle(.orange)
                } else if page.isRecordable && !selecting {
                    let missing = !studio.inputs.missing(for: page).isEmpty
                    Button(action: make) {
                        Label(missing ? "Make video · placeholders" : "Make video", systemImage: "record.circle")
                    }
                    .buttonStyle(.borderedProminent)
                    .tint(page.kind.tint)
                    .controlSize(.small)
                }
            }
            .font(.caption)
            .foregroundStyle(.secondary)
            .labelStyle(.titleAndIcon)
        }
        .padding(14)
        .frame(maxWidth: .infinity, minHeight: 200, alignment: .topLeading)
        .background(.background, in: RoundedRectangle(cornerRadius: 12))
        .overlay(
            RoundedRectangle(cornerRadius: 12)
                .strokeBorder(borderColor, lineWidth: picked || inspected ? 2 : 1)
        )
        .shadow(color: .black.opacity(hover ? 0.12 : 0.04), radius: hover ? 8 : 3, y: 2)
        .contentShape(RoundedRectangle(cornerRadius: 12))
        .onHover { hover = $0 }
        .animation(.easeOut(duration: 0.15), value: hover)
        .opacity(selecting && !page.isRecordable ? 0.5 : 1)
    }

    private var borderColor: Color {
        if picked || inspected { return .accentColor }
        return Color.primary.opacity(0.08)
    }
}

struct VerdictBadge: View {
    let verdict: Verdict
    var body: some View {
        Label(verdict.label, systemImage: verdict.symbol)
            .font(.caption.weight(.semibold))
            .padding(.horizontal, 8).padding(.vertical, 3)
            .background(verdict.tint.opacity(0.15), in: Capsule())
            .foregroundStyle(verdict.tint)
    }
}

struct FlowChips: View {
    let items: [String]
    var body: some View {
        HStack(spacing: 5) {
            ForEach(Array(Set(items)).sorted().prefix(4), id: \.self) { item in
                Text(item)
                    .font(.caption2.weight(.medium))
                    .padding(.horizontal, 6).padding(.vertical, 2)
                    .background(Color.orange.opacity(0.12), in: Capsule())
                    .foregroundStyle(.orange)
                    .lineLimit(1)
            }
        }
    }
}

struct RefreshBanner: View {
    let lines: [String]
    var body: some View {
        HStack(spacing: 10) {
            ProgressView().controlSize(.small)
            VStack(alignment: .leading, spacing: 2) {
                Text("Reading the WSO2 Integrator docs…").font(.callout.weight(.medium))
                Text(lines.last ?? "starting")
                    .font(.caption.monospaced())
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }
        }
        .padding(12)
        .frame(maxWidth: 520)
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 10))
    }
}
