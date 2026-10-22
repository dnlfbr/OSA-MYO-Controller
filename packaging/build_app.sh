#!/bin/sh
# Build "dist/OSA MYO Controller.app" (native arm64) and its disk image. From the repository root:
#   sh packaging/build_app.sh
# Optional: CODESIGN_IDENTITY="Developer ID Application: ..." sh packaging/build_app.sh
set -e
cd "$(dirname "$0")/.."
APP="dist/OSA MYO Controller.app"
DMG="dist/OSA-MYO-Controller.dmg"
uv pip install -e ".[gui,dongle,build]"
rm -rf build dist
uv run pyinstaller --noconfirm --clean packaging/osa-myo-controller.spec
# ad-hoc signature so Gatekeeper/TCC accept the bundle locally (replace with a real identity to distribute)
if [ -z "$CODESIGN_IDENTITY" ]; then
  codesign --force --deep --sign - "$APP"
fi
echo "built $APP"
plutil -p "$APP/Contents/Info.plist" | grep -i bluetooth

# disk image: drag the app onto the Applications link
STAGE=build/dmg
rm -rf "$STAGE" "$DMG"
mkdir -p "$STAGE"
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
cp config.example.toml "$STAGE/"
hdiutil create -volname "OSA MYO Controller" -srcfolder "$STAGE" -ov -format UDZO "$DMG" >/dev/null
echo "built $DMG"
