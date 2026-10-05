#!/bin/zsh
# Build FlowCast Studio.app from the Swift package next to this script.
#
#   mac/build.sh            → mac/build/FlowCast Studio.app
#   mac/build.sh --install  → also copies it to ~/Applications
#
# Signs with your Apple Development identity when there is one, so the Screen
# Recording / Accessibility grants survive rebuilds (an ad-hoc signature changes
# every build, and macOS then asks again).
set -euo pipefail

HERE=${0:A:h}
ROOT=${HERE:h}
PKG=$HERE/FlowCastStudio
OUT=$HERE/build
BUILT="$OUT/FlowCast Studio.app"
# Assembled and signed outside the project: the Desktop is synced by iCloud,
# which puts Finder attributes back on a bundle as soon as they are cleared,
# and codesign refuses it ("resource fork, Finder information … not allowed").
STAGE=$(mktemp -d "${TMPDIR:-/tmp}/flowcast-build.XXXXXX")
trap 'rm -rf "$STAGE"' EXIT
APP="$STAGE/FlowCast Studio.app"
mkdir -p "$OUT"

echo "▸ compiling"
swift build -c release --package-path "$PKG" 2>&1 | grep -vE "^\[[0-9]+/[0-9]+\]" || true
BIN=$(swift build -c release --package-path "$PKG" --show-bin-path)/FlowCastStudio
[[ -x $BIN ]] || { echo "build failed"; exit 1; }

echo "▸ bundling"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp "$BIN" "$APP/Contents/MacOS/FlowCastStudio"

if [[ ! -f $OUT/AppIcon.icns || $HERE/make_icon.py -nt $OUT/AppIcon.icns ]]; then
  (cd "$ROOT" && uv run python mac/make_icon.py "$OUT/AppIcon.icns" >/dev/null)
fi
cp "$OUT/AppIcon.icns" "$APP/Contents/Resources/AppIcon.icns"

VERSION=$(date +%Y.%m.%d)
cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>FlowCast Studio</string>
  <key>CFBundleDisplayName</key><string>FlowCast Studio</string>
  <key>CFBundleIdentifier</key><string>dev.flowcast.studio</string>
  <key>CFBundleExecutable</key><string>FlowCastStudio</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>$VERSION</string>
  <key>CFBundleVersion</key><string>$(date +%s)</string>
  <key>LSMinimumSystemVersion</key><string>14.0</string>
  <key>LSApplicationCategoryType</key><string>public.app-category.video</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSPrincipalClass</key><string>NSApplication</string>
  <key>FCProjectRoot</key><string>$ROOT</string>
  <key>NSMicrophoneUsageDescription</key>
  <string>FlowCast Studio records a short sample of your voice so narration can be spoken in it.</string>
  <key>NSAppleEventsUsageDescription</key>
  <string>FlowCast Studio brings WSO2 Integrator to the front and makes it full screen while recording.</string>
  <key>NSLocalNetworkUsageDescription</key>
  <string>FlowCast Studio shows the doc cards on your phone over your local Wi-Fi.</string>
</dict>
</plist>
PLIST

# Finder metadata / quarantine attributes make codesign refuse the bundle.
xattr -cr "$APP"

IDENTITY=$(security find-identity -v -p codesigning 2>/dev/null | grep -m1 "Apple Development" | sed -E 's/.*"(.*)"/\1/' || true)
if [[ -n ${IDENTITY:-} ]]; then
  echo "▸ signing as $IDENTITY"
  codesign --force --deep --sign "$IDENTITY" "$APP"
else
  echo "▸ signing ad-hoc (permissions will be asked again after each rebuild)"
  codesign --force --deep --sign - "$APP"
fi

if [[ ${1:-} == --install ]]; then
  # Move, not copy: one FlowCast Studio on the Mac, so Spotlight, Launchpad and
  # the privacy lists never show two. The running copy (if any) is replaced on
  # its next launch — the app quits older copies of itself when it starts.
  DEST=~/Applications/"FlowCast Studio.app"
  LSREG=/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister
  mkdir -p ~/Applications
  codesign --verify --deep "$APP"
  rm -rf "$DEST"
  ditto "$APP" "$DEST"
  rm -rf "$BUILT"
  "$LSREG" -u "$BUILT" 2>/dev/null || true
  "$LSREG" -f "$DEST" 2>/dev/null || true
  echo "✓ installed $DEST (the only copy)"
  exit 0
fi
rm -rf "$BUILT"
ditto "$APP" "$BUILT"
echo "✓ $BUILT"
