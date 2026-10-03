import AVKit
import SwiftUI

/// Finished videos — one folder each (video, thumbnail, YouTube text), in
/// ~/Movies/FlowCast Studio unless Settings says otherwise.
struct LibraryView: View {
    @Environment(Studio.self) private var studio
    @Environment(AppSettings.self) private var settings
    @Environment(\.openWindow) private var openWindow

    var body: some View {
        Group {
            if studio.library.isEmpty {
                ContentUnavailableView {
                    Label("No videos yet", systemImage: "play.rectangle")
                } description: {
                    Text("Finished videos are saved to \(settings.videosFolder) — one folder each, with the video, its thumbnail and the YouTube text.")
                }
            } else {
                ScrollView {
                    LazyVGrid(columns: [GridItem(.adaptive(minimum: 300, maximum: 420), spacing: 18)], spacing: 18) {
                        ForEach(studio.library) { video in
                            VideoTile(video: video, play: { openWindow(id: "player", value: video.folder) })
                        }
                    }
                    .padding(20)
                }
            }
        }
        .navigationTitle("Library")
        .navigationSubtitle("\(studio.library.count) videos · \((settings.videosFolder as NSString).abbreviatingWithTildeInPath)")
        .toolbar {
            Button {
                NSWorkspace.shared.open(URL(fileURLWithPath: settings.videosFolder))
            } label: { Label("Open folder", systemImage: "folder") }
            Button { studio.loadLibrary() } label: { Label("Reload", systemImage: "arrow.clockwise") }
        }
    }
}

struct VideoTile: View {
    let video: LibraryVideo
    let play: () -> Void
    @State private var copied = false

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Button(action: play) {
                ZStack(alignment: .bottomTrailing) {
                    Rectangle().fill(.black.opacity(0.85))
                    if let t = video.thumbnail, let img = NSImage(contentsOfFile: t) {
                        Image(nsImage: img).resizable().aspectRatio(contentMode: .fill)
                    }
                    Image(systemName: "play.circle.fill")
                        .font(.system(size: 48))
                        .foregroundStyle(.white.opacity(0.92))
                        .shadow(radius: 6)
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                    Text(video.duration)
                        .font(.caption.monospacedDigit().weight(.semibold))
                        .padding(.horizontal, 6).padding(.vertical, 2)
                        .background(.black.opacity(0.75), in: RoundedRectangle(cornerRadius: 4))
                        .foregroundStyle(.white)
                        .padding(8)
                }
                .aspectRatio(16 / 9, contentMode: .fit)
                .clipShape(RoundedRectangle(cornerRadius: 10))
            }
            .buttonStyle(.plain)
            .help("Play")

            Text(video.title).font(.headline).lineLimit(2)
            Text("\(video.modified.formatted(date: .abbreviated, time: .omitted)) · "
                 + ByteCountFormatter.string(fromByteCount: video.bytes, countStyle: .file))
                .font(.caption).foregroundStyle(.secondary)
            HStack(spacing: 8) {
                Button(action: play) { Label("Play", systemImage: "play.fill") }
                    .buttonStyle(.borderedProminent)
                Button {
                    NSWorkspace.shared.activateFileViewerSelecting([URL(fileURLWithPath: video.video)])
                } label: { Label("Show in Finder", systemImage: "folder") }
                Button {
                    copyDescription(video)
                    copied = true
                } label: { Label(copied ? "Copied" : "Copy description", systemImage: copied ? "checkmark" : "doc.on.doc") }
                if let m = video.mediumFolder {
                    Button {
                        NSWorkspace.shared.open(URL(fileURLWithPath: m))
                    } label: { Label("Medium", systemImage: "text.document") }
                    .help("The written guide and step GIFs for Medium")
                }
            }
            .controlSize(.small)
        }
        .contextMenu {
            Button("Play", action: play)
            Button("Show in Finder") {
                NSWorkspace.shared.activateFileViewerSelecting([URL(fileURLWithPath: video.video)])
            }
            if let d = video.description {
                Button("Open YouTube text") { NSWorkspace.shared.open(URL(fileURLWithPath: d)) }
            }
            if let m = video.mediumFolder {
                Button("Open Medium folder") { NSWorkspace.shared.open(URL(fileURLWithPath: m)) }
            }
            Button("Copy description") { copyDescription(video) }
        }
    }
}

/// The DESCRIPTION section of the text file — what goes in YouTube's box.
func descriptionText(_ video: LibraryVideo) -> String {
    guard let path = video.description, let txt = try? String(contentsOfFile: path, encoding: .utf8) else {
        return video.title
    }
    guard let start = txt.range(of: "DESCRIPTION\n") else { return txt }
    let rest = txt[start.upperBound...]
    let end = rest.range(of: "\nTAGS\n") ?? rest.range(of: "\nFILE\n")
    return String(end.map { rest[..<$0.lowerBound] } ?? rest).trimmingCharacters(in: .whitespacesAndNewlines)
}

func copyDescription(_ video: LibraryVideo) {
    NSPasteboard.general.clearContents()
    NSPasteboard.general.setString(descriptionText(video), forType: .string)
}

struct PlayerSheet: View {
    let video: LibraryVideo
    @Environment(\.dismiss) private var dismiss
    @State private var player: AVPlayer?
    @State private var copied: String?

    var body: some View {
        HStack(spacing: 0) {
            VStack(spacing: 0) {
                if let player {
                    PlayerView(player: player)
                        .frame(minWidth: 560, minHeight: 315)
                }
                HStack {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(video.title).font(.headline)
                        Text("\(video.duration) · \(video.folderName)").font(.caption).foregroundStyle(.secondary)
                    }
                    Spacer()
                    Button("Show in Finder") {
                        NSWorkspace.shared.activateFileViewerSelecting([URL(fileURLWithPath: video.video)])
                    }
                    Button("Done") { dismiss() }.keyboardShortcut(.cancelAction)
                }
                .padding(12)
            }
            Divider()
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    if let t = video.thumbnail, let img = NSImage(contentsOfFile: t) {
                        Image(nsImage: img).resizable().aspectRatio(16 / 9, contentMode: .fit)
                            .clipShape(RoundedRectangle(cornerRadius: 6))
                    }
                    copyRow("Title", video.title)
                    VStack(alignment: .leading, spacing: 6) {
                        copyRow("Description", descriptionText(video), showText: false)
                        Text(descriptionText(video))
                            .font(.callout).textSelection(.enabled)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                }
                .padding(16)
            }
            .frame(width: 320)
        }
        .onAppear {
            player = AVPlayer(url: URL(fileURLWithPath: video.video))
            player?.play()
        }
        .onDisappear { player?.pause() }
    }

    private func copyRow(_ label: String, _ text: String, showText: Bool = true) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                Text(label.uppercased()).font(.caption.weight(.semibold)).foregroundStyle(.secondary)
                Spacer()
                Button(copied == label ? "Copied" : "Copy") {
                    NSPasteboard.general.clearContents()
                    NSPasteboard.general.setString(text, forType: .string)
                    copied = label
                }
                .controlSize(.small)
            }
            if showText {
                Text(text).font(.callout.weight(.medium)).textSelection(.enabled)
            }
        }
    }
}
