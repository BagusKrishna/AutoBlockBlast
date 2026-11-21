#!/bin/bash
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
app="$root/AutoBlockBlast.app"
mkdir -p "$app/Contents/MacOS"
swiftc -module-cache-path "${TMPDIR:-/tmp}/autoblockblast-swift-cache" \
    "$root/desktop/AutoBlockBlast.swift" -framework AppKit -framework Vision -o "$app/Contents/MacOS/AutoBlockBlast-bin"
cat > "$app/Contents/MacOS/AutoBlockBlast" <<'LAUNCH'
#!/bin/bash
root="$(cd "$(dirname "$0")/../../.." && pwd)"
exec "$(dirname "$0")/AutoBlockBlast-bin" "$root"
LAUNCH
chmod +x "$app/Contents/MacOS/AutoBlockBlast"
mkdir -p "$app/Contents/Resources"
iconset="$(mktemp -d ${TMPDIR:-/tmp}/autoblockblast-icon.XXXXXX)/AutoBlockBlast.iconset"
mkdir -p "$iconset"
swift -module-cache-path "${TMPDIR:-/tmp}/autoblockblast-swift-cache" "$root/desktop/make-icon.swift" "$iconset/icon_512x512@2x.png"
for size in 16 32 128 256 512; do
    sips -z "$size" "$size" "$iconset/icon_512x512@2x.png" --out "$iconset/icon_${size}x${size}.png" >/dev/null
    double=$((size * 2))
    sips -z "$double" "$double" "$iconset/icon_512x512@2x.png" --out "$iconset/icon_${size}x${size}@2x.png" >/dev/null
done
/usr/bin/python3 - "$iconset" "$app/Contents/Resources/AutoBlockBlast.icns" <<'PYICON'
import pathlib
import struct
import sys

iconset, target = map(pathlib.Path, sys.argv[1:])
entries = [
    (b"icp4", "icon_16x16.png"),
    (b"icp5", "icon_32x32.png"),
    (b"icp6", "icon_32x32@2x.png"),
    (b"ic07", "icon_128x128.png"),
    (b"ic08", "icon_256x256.png"),
    (b"ic09", "icon_512x512.png"),
    (b"ic10", "icon_512x512@2x.png"),
]
chunks = []
for kind, filename in entries:
    data = (iconset / filename).read_bytes()
    chunks.append(kind + struct.pack(">I", len(data) + 8) + data)
body = b"".join(chunks)
target.write_bytes(b"icns" + struct.pack(">I", len(body) + 8) + body)
PYICON
cat > "$app/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleIconFile</key><string>AutoBlockBlast</string>
<key>CFBundleName</key><string>AutoBlockBlast</string>
<key>CFBundleDisplayName</key><string>AutoBlockBlast</string>
<key>CFBundleIdentifier</key><string>local.autoblockblast.desktop</string>
<key>CFBundleExecutable</key><string>AutoBlockBlast</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>CFBundleVersion</key><string>1</string>
<key>NSDesktopFolderUsageDescription</key><string>AutoBlockBlast needs access to its project folder to run the bot.</string>
<key>NSHighResolutionCapable</key><true/>
</dict></plist>
PLIST
echo "Built $app"
