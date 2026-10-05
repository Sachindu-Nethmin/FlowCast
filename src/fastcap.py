"""Fast screen reads for the recording loop (Quartz, in-process).

pyautogui.screenshot() on macOS runs `screencapture` into a PNG and reads it
back: 0.45 s a frame on a Retina display. runner waits for the UI to change
and settle by comparing screenshots in a loop, so that cost was paid several
times per action. Quartz returns the same pixels (same size, RGBA) in about
0.1 s.

front_app() answers "is WSO2 Integrator already in front?" in a few
milliseconds, so runner does not run AppleScript and sleep 0.3 s before every
screenshot when it already is.

Both return None on any failure; callers fall back to the slow path.
"""
from __future__ import annotations

from PIL import Image

try:
    import Quartz
except Exception:                     # pyobjc missing: slow path only
    Quartz = None


def screenshot() -> Image.Image | None:
    """The main display, in pixels, as pyautogui.screenshot() returns it."""
    if Quartz is None:
        return None
    try:
        bounds = Quartz.CGDisplayBounds(Quartz.CGMainDisplayID())
        img = Quartz.CGWindowListCreateImage(bounds, Quartz.kCGWindowListOptionOnScreenOnly,
                                             Quartz.kCGNullWindowID, Quartz.kCGWindowImageDefault)
        if img is None:
            return None
        w, h = Quartz.CGImageGetWidth(img), Quartz.CGImageGetHeight(img)
        data = Quartz.CGDataProviderCopyData(Quartz.CGImageGetDataProvider(img))
        return Image.frombuffer("RGBA", (w, h), bytes(data), "raw", "BGRA",
                                Quartz.CGImageGetBytesPerRow(img), 1)
    except Exception:
        return None


def front_app() -> str | None:
    """Owner of the frontmost normal window on the current Space."""
    if Quartz is None:
        return None
    try:
        wins = Quartz.CGWindowListCopyWindowInfo(
            Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements,
            Quartz.kCGNullWindowID)
        for w in wins or []:
            if w.get("kCGWindowLayer") == 0:
                return str(w.get("kCGWindowOwnerName") or "")
    except Exception:
        pass
    return None
