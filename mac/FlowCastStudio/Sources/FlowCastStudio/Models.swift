import Foundation
import SwiftUI

// kb/docs_catalog.json, written by tools/docs_audit.py (src/doc_catalog.py).

struct Catalog: Decodable {
    let source: String
    let site: String
    let commit: String?
    let summary: Summary
    let pages: [DocPage]
}

struct Summary: Decodable {
    let total: Int
    let walkthroughs: Int
    let ready: Int
    let auto: Int?
    let keys: Int?
    let setup: Int
    let partial: Int
    let none: Int
    let verified: Int
    let byArea: [String: [String: Int]]

    enum CodingKeys: String, CodingKey {
        case total, walkthroughs, ready, auto, keys, setup, partial, none, verified
        case byArea = "by_area"
    }
}

struct DocLine: Decodable, Hashable {
    let source: String
    let workflow: [String]
    let actions: Int
    let kind: String          // action | info | mixed | unparsed
    let manual: String?
}

/// A connection field the page binds to a configurable variable.
struct DocBinding: Decodable, Hashable {
    let field: String
    let sub: String?
    let variable: String
    let type: String
    let nested: Bool
    var label: String { sub.map { "\(field).\($0)" } ?? field }
}

/// A configurable the page needs a value for (src/doc_catalog.py `_inputs`).
struct DocInput: Decodable, Hashable, Identifiable {
    var id: String { name }
    let name: String
    let type: String
    let label: String
    let secret: Bool
    let example: String?
    let auto: String?         // value a started prerequisite provides
}

struct DocStep: Decodable, Hashable {
    let n: Int
    let title: String
    let lines: [DocLine]
}

struct DocPage: Decodable, Identifiable, Hashable {
    var id: String { slug }
    let path: String
    let url: String
    let title: String
    let description: String
    let section: String
    let area: String
    let slug: String
    let time: String
    let build: String
    let steps: [DocStep]
    let blockers: [String]
    let notes: [String]
    let verdict: String
    let coverage: Double
    let actionCount: Int
    let unparsed: [String]
    let requires: [String]
    let setupCommands: [String]
    let startsInProject: Bool
    let verified: String?
    let workflowFile: String?
    let recipes: [String]
    let inputs: [DocInput]
    let manualRequires: [String]
    let notesExtra: [String]
    let project: String?
    let bindings: [DocBinding]
    let service: String?

    enum CodingKeys: String, CodingKey {
        case path, url, title, description, section, area, slug, time, build, steps
        case blockers, notes, verdict, coverage, unparsed, requires, verified
        case recipes, inputs, project, bindings, service
        case actionCount = "action_count"
        case setupCommands = "setup_commands"
        case startsInProject = "starts_in_project"
        case workflowFile = "workflow_file"
        case manualRequires = "manual_requires"
        case notesExtra = "notes_extra"
    }

    init(from d: Decoder) throws {
        let c = try d.container(keyedBy: CodingKeys.self)
        path = try c.decode(String.self, forKey: .path)
        url = try c.decode(String.self, forKey: .url)
        title = try c.decode(String.self, forKey: .title)
        description = try c.decode(String.self, forKey: .description)
        section = try c.decode(String.self, forKey: .section)
        area = try c.decode(String.self, forKey: .area)
        slug = try c.decode(String.self, forKey: .slug)
        time = try c.decode(String.self, forKey: .time)
        build = try c.decode(String.self, forKey: .build)
        steps = try c.decode([DocStep].self, forKey: .steps)
        blockers = try c.decode([String].self, forKey: .blockers)
        notes = try c.decode([String].self, forKey: .notes)
        verdict = try c.decode(String.self, forKey: .verdict)
        coverage = try c.decode(Double.self, forKey: .coverage)
        actionCount = try c.decode(Int.self, forKey: .actionCount)
        unparsed = try c.decode([String].self, forKey: .unparsed)
        requires = try c.decode([String].self, forKey: .requires)
        setupCommands = try c.decode([String].self, forKey: .setupCommands)
        startsInProject = try c.decode(Bool.self, forKey: .startsInProject)
        verified = try c.decodeIfPresent(String.self, forKey: .verified)
        workflowFile = try c.decodeIfPresent(String.self, forKey: .workflowFile)
        // Fields added later: an older catalog still loads.
        recipes = try c.decodeIfPresent([String].self, forKey: .recipes) ?? []
        inputs = try c.decodeIfPresent([DocInput].self, forKey: .inputs) ?? []
        manualRequires = try c.decodeIfPresent([String].self, forKey: .manualRequires) ?? []
        notesExtra = try c.decodeIfPresent([String].self, forKey: .notesExtra) ?? []
        project = try c.decodeIfPresent(String.self, forKey: .project)
        bindings = try c.decodeIfPresent([DocBinding].self, forKey: .bindings) ?? []
        service = try c.decodeIfPresent(String.self, forKey: .service)
    }

    static func == (a: DocPage, b: DocPage) -> Bool { a.slug == b.slug }
    func hash(into h: inout Hasher) { h.combine(slug) }

    var kind: Verdict { Verdict(rawValue: verdict) ?? .none }
    var isRecordable: Bool { kind != .none }
    var areaGroup: String { area.components(separatedBy: " · ").first ?? area }
    /// "Example" and "Setup Guide" pages are titled generically; name the connector.
    var displayTitle: String {
        let generic = ["Example", "Setup Guide", "Overview", "Actions", "Triggers"]
        guard generic.contains(title) else { return title }
        let parts = path.split(separator: "/")
        guard parts.count >= 2 else { return title }
        let name = parts[parts.count - 2]
            .replacingOccurrences(of: ".", with: " ")
            .replacingOccurrences(of: "-", with: " ")
            .capitalized
        return "\(name) — \(title)"
    }
    var stepCount: Int { steps.count }
    var unparsedCount: Int {
        steps.reduce(0) { $0 + $1.lines.filter { $0.kind == "unparsed" || $0.kind == "mixed" }.count }
    }
    /// Inputs no started prerequisite fills — yours to enter.
    var userInputs: [DocInput] { inputs.filter { $0.auto == nil } }
}

enum Verdict: String, CaseIterable, Identifiable {
    case ready, auto, keys, setup, partial, none
    var id: String { rawValue }

    var label: String {
        switch self {
        case .ready: "100% followable"
        case .auto: "Auto setup"
        case .keys: "Needs your keys"
        case .setup: "After setup"
        case .partial: "Needs a person"
        case .none: "Not a walkthrough"
        }
    }

    var explanation: String {
        switch self {
        case .ready:
            "Every instruction becomes an action FlowCast can run, and nothing outside WSO2 Integrator is needed. These record hands-free."
        case .auto:
            "Every instruction parses once FlowCast starts the page's prerequisites itself — a broker or database in a local container — and sends its test event. Hands-free; needs Docker (colima)."
        case .keys:
            "Every instruction parses, but the page's configurables need values only you have — an API key, a tenant URL. Enter them once below; they go to Config.toml, never on camera."
        case .setup:
            "Every instruction parses, but the page needs something FlowCast cannot create or be given — an account to sign up for, a cloud console."
        case .partial:
            "A walkthrough with lines FlowCast has no action for. It records everything else and stops at those lines for you; what you do is learned and replayed on the next run."
        case .none:
            "Concepts, reference and overviews — nothing to click through."
        }
    }

    var symbol: String {
        switch self {
        case .ready: "checkmark.seal.fill"
        case .auto: "shippingbox.fill"
        case .keys: "key.fill"
        case .setup: "wrench.and.screwdriver.fill"
        case .partial: "person.fill.questionmark"
        case .none: "book.closed"
        }
    }

    var tint: Color {
        switch self {
        case .ready: .green
        case .auto: .teal
        case .keys: .indigo
        case .setup: .orange
        case .partial: .blue
        case .none: .secondary
        }
    }
}

/// Human wording for the blocker ids src/doc_catalog.py emits.
func blockerLabel(_ id: String) -> String {
    switch id {
    case "credentials": "API key / token"
    case "account": "External account"
    case "service": "Running service"
    case "terminal": "Terminal command"
    case "code": "Code editing"
    case "external-ui": "Another app"
    case "prerequisite": "Prerequisites"
    case "wso2-sign-in": "WSO2 sign-in"
    default: id
    }
}

/// One finished video in its own folder (src/packager.py writes video.json).
struct LibraryVideo: Identifiable, Hashable {
    var id: String { folder }
    let slug: String
    let video: String          // full paths
    let title: String
    let thumbnail: String?
    let description: String?   // the YouTube description .txt
    let modified: Date
    let bytes: Int64
    let folder: String
    let seconds: Double
    let source: String?

    var duration: String { "\(Int(seconds) / 60):\(String(format: "%02d", Int(seconds) % 60))" }
    var folderName: String { (folder as NSString).lastPathComponent }
    /// <folder>/LinkedIn: the post, its first comment, the post with links (src/linkedin.py).
    var linkedinFolder: String? {
        let m = (folder as NSString).appendingPathComponent("LinkedIn")
        return FileManager.default.fileExists(atPath: m) ? m : nil
    }
    /// <folder>/Medium: the written guide and step GIFs (src/medium.py).
    var mediumFolder: String? {
        let m = (folder as NSString).appendingPathComponent("Medium")
        return FileManager.default.fileExists(atPath: m) ? m : nil
    }
}
