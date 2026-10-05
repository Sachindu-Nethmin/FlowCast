import Foundation
import Observation

/// Persisted preferences. Defaults point at the FlowCast checkout this app was
/// built from (mac/build.sh writes it into Info.plist as FCProjectRoot).
@Observable
final class AppSettings {
    private let d = UserDefaults.standard

    var projectRoot: String { didSet { d.set(projectRoot, forKey: "projectRoot") } }
    var uvPath: String { didSet { d.set(uvPath, forKey: "uvPath") } }
    var voiceReference: String { didSet { d.set(voiceReference, forKey: "voiceReference") } }
    var narrationTakes: Int { didSet { d.set(narrationTakes, forKey: "narrationTakes") } }
    var masterTakes: Int { didSet { d.set(masterTakes, forKey: "masterTakes") } }
    var quality: String { didSet { d.set(quality, forKey: "quality") } }
    var reviewNarration: Bool { didSet { d.set(reviewNarration, forKey: "reviewNarration") } }
    var freshProjects: Bool { didSet { d.set(freshProjects, forKey: "freshProjects") } }
    var hideDuringRecording: Bool { didSet { d.set(hideDuringRecording, forKey: "hideDuringRecording") } }
    var phonePort: Int { didSet { d.set(phonePort, forKey: "phonePort") } }
    var phoneAtLaunch: Bool { didSet { d.set(phoneAtLaunch, forKey: "phoneAtLaunch") } }
    var phoneDuringRuns: Bool { didSet { d.set(phoneDuringRuns, forKey: "phoneDuringRuns") } }
    var aiEnabled: Bool { didSet { d.set(aiEnabled, forKey: "aiEnabled") } }
    var aiModel: String { didSet { d.set(aiModel, forKey: "aiModel") } }
    var videosFolder: String { didSet { d.set(videosFolder, forKey: "videosFolder") } }
    var firstRunGuided: Bool { didSet { d.set(firstRunGuided, forKey: "firstRunGuided") } }

    init() {
        let bundled = Bundle.main.object(forInfoDictionaryKey: "FCProjectRoot") as? String
        let root = d.string(forKey: "projectRoot") ?? bundled
            ?? (NSHomeDirectory() + "/Desktop/Project/Flowcast")
        projectRoot = root
        uvPath = d.string(forKey: "uvPath") ?? AppSettings.findUV()
        voiceReference = d.string(forKey: "voiceReference") ?? root + "/assets/voice/reference.wav"
        narrationTakes = d.object(forKey: "narrationTakes") as? Int ?? 3
        masterTakes = d.object(forKey: "masterTakes") as? Int ?? 8
        quality = d.string(forKey: "quality") ?? "1440p"
        reviewNarration = d.object(forKey: "reviewNarration") as? Bool ?? false
        freshProjects = d.object(forKey: "freshProjects") as? Bool ?? true
        hideDuringRecording = d.object(forKey: "hideDuringRecording") as? Bool ?? true
        phonePort = d.object(forKey: "phonePort") as? Int ?? 8766
        phoneAtLaunch = d.object(forKey: "phoneAtLaunch") as? Bool ?? true
        phoneDuringRuns = d.object(forKey: "phoneDuringRuns") as? Bool ?? true
        aiEnabled = d.object(forKey: "aiEnabled") as? Bool ?? true
        aiModel = d.string(forKey: "aiModel") ?? "ornith:9b"
        videosFolder = d.string(forKey: "videosFolder") ?? (NSHomeDirectory() + "/Movies/FlowCast Studio")
        firstRunGuided = d.object(forKey: "firstRunGuided") as? Bool ?? true
    }

    var rootURL: URL { URL(fileURLWithPath: projectRoot) }
    var catalogURL: URL { rootURL.appendingPathComponent("kb/docs_catalog.json") }

    static func findUV() -> String {
        let candidates = [NSHomeDirectory() + "/.local/bin/uv", "/opt/homebrew/bin/uv",
                          "/usr/local/bin/uv", NSHomeDirectory() + "/.cargo/bin/uv"]
        return candidates.first { FileManager.default.isExecutableFile(atPath: $0) } ?? "uv"
    }

    /// A GUI app does not inherit the shell PATH; ffmpeg and git live here.
    var environment: [String: String] {
        var env = ProcessInfo.processInfo.environment
        let extra = ["/opt/homebrew/bin", "/usr/local/bin", NSHomeDirectory() + "/.local/bin",
                     "/usr/bin", "/bin", "/usr/sbin", "/sbin"]
        env["PATH"] = (extra + [env["PATH"] ?? ""]).joined(separator: ":")
        env["PYTHONUNBUFFERED"] = "1"
        env["FLOWCAST_NO_PROMPT"] = "1"
        env["FLOWCAST_AI"] = aiEnabled ? "on" : "off"
        env["FLOWCAST_AI_MODEL"] = aiModel
        env["FLOWCAST_VIDEOS_DIR"] = videosFolder
        return env
    }
}
