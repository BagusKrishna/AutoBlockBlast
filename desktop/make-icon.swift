import AppKit

let size = 1024
let image = NSImage(size: NSSize(width: size, height: size))
image.lockFocus()
NSColor(calibratedRed: 0.09, green: 0.14, blue: 0.19, alpha: 1).setFill()
NSBezierPath(roundedRect: NSRect(x: 0, y: 0, width: size, height: size), xRadius: 220, yRadius: 220).fill()
let cells: [(Int, Int, NSColor)] = [(0, 0, .systemTeal), (1, 0, .systemTeal), (1, 1, .systemBlue), (2, 1, .systemBlue)]
for (x, y, color) in cells {
    color.setFill()
    NSBezierPath(roundedRect: NSRect(x: 176 + x * 232, y: 224 + y * 232, width: 192, height: 192), xRadius: 48, yRadius: 48).fill()
}
image.unlockFocus()
let bitmap = NSBitmapImageRep(data: image.tiffRepresentation!)!
try bitmap.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: CommandLine.arguments[1]))
