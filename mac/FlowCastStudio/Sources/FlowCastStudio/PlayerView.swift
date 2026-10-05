import AVKit
import SwiftUI

/// AppKit's AVPlayerView — QuickTime's player — inside SwiftUI.
///
/// SwiftUI's own `VideoPlayer` aborts the app on this Mac: built with the
/// macOS 26 SDK and run on macOS 27, its `_AVKit_SwiftUI` bridge fails to set
/// up its class metadata (getSuperclassMetadata → abort; crash reports of
/// 3 Oct 16:07 and 16:14). Wrapping AVPlayerView directly never touches that
/// type, so nothing in this app may use `VideoPlayer`.
struct PlayerView: NSViewRepresentable {
    let player: AVPlayer

    func makeNSView(context: Context) -> AVPlayerView {
        let view = AVPlayerView()
        view.player = player
        view.controlsStyle = .floating
        view.showsFullScreenToggleButton = true
        view.allowsPictureInPicturePlayback = true
        return view
    }

    func updateNSView(_ view: AVPlayerView, context: Context) {
        if view.player !== player { view.player = player }
    }

    static func dismantleNSView(_ view: AVPlayerView, coordinator: ()) {
        view.player?.pause()
        view.player = nil
    }
}
