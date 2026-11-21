import AppKit
import Vision

final class BlockArtwork: NSView {
    override var isFlipped: Bool { true }
    override func draw(_ dirtyRect: NSRect) {
        let colors = [
            NSColor(calibratedRed: 0.44, green: 0.83, blue: 0.76, alpha: 1),
            NSColor(calibratedRed: 0.48, green: 0.65, blue: 0.98, alpha: 1),
            NSColor(calibratedRed: 0.98, green: 0.70, blue: 0.51, alpha: 1)
        ]
        let tile: CGFloat = 21
        let gap: CGFloat = 4
        let pieces: [(CGFloat, CGFloat, Int, [(Int, Int)])] = [
            (0, 4, 0, [(0,0), (1,0), (1,1)]),
            (60, 12, 1, [(0,0), (0,1), (1,1), (2,1)]),
            (145, 4, 2, [(0,0), (1,0), (0,1), (1,1)])
        ]
        for (originX, originY, color, cells) in pieces {
            for (x, y) in cells {
                let rect = NSRect(x: originX + CGFloat(x) * (tile + gap),
                                  y: originY + CGFloat(y) * (tile + gap),
                                  width: tile, height: tile)
                colors[color].setFill()
                NSBezierPath(roundedRect: rect, xRadius: 5, yRadius: 5).fill()
            }
        }
    }
}

func appMark() -> NSImage {
    let image = NSImage(size: NSSize(width: 128, height: 128))
    image.lockFocus()
    NSColor(calibratedRed: 0.09, green: 0.14, blue: 0.19, alpha: 1).setFill()
    NSBezierPath(roundedRect: NSRect(x: 0, y: 0, width: 128, height: 128), xRadius: 27, yRadius: 27).fill()
    let colors: [NSColor] = [.systemTeal, .systemBlue, .systemOrange]
    for (index, cell) in [(0, 0), (1, 0), (1, 1), (2, 1)].enumerated() {
        colors[min(index / 2, 2)].setFill()
        let rect = NSRect(x: 22 + cell.0 * 29, y: 28 + cell.1 * 29, width: 24, height: 24)
        NSBezierPath(roundedRect: rect, xRadius: 6, yRadius: 6).fill()
    }
    image.unlockFocus()
    return image
}

final class BotApp: NSObject, NSApplicationDelegate {
    let root = URL(fileURLWithPath: CommandLine.arguments[1], isDirectory: true)
    var window: NSWindow!
    let status = NSTextField(labelWithString: "Ready")
    let detail = NSTextField(wrappingLabelWithString: "Connect Android, unlock it, and open Block Blast.")
    let stats = NSTextField(labelWithString: "Score  —     Combo  —")
    let startButton = NSButton(title: "Start", target: nil, action: nil)
    let pauseButton = NSButton(title: "Pause", target: nil, action: nil)
    let stopButton = NSButton(title: "Stop", target: nil, action: nil)
    var process: Process?
    var stopping = false
    var hasStarted = false
    var paused = false
    var lastMessage = ""
    var pendingOutput = ""
    var moveCount = 0
    var needsFolderAccess = false
    var grantedFolder: URL?
    var scoreText = "—"
    var comboText = "—"
    var metricsBusy = false
    var metricsGeneration = 0
    var captureDirectory: URL { root.appendingPathComponent("captures", isDirectory: true) }
    var pauseFile: URL { captureDirectory.appendingPathComponent("pause.request") }
    var stopFile: URL { captureDirectory.appendingPathComponent("stop.request") }

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 480, height: 375),
                          styleMask: [.titled, .closable, .miniaturizable], backing: .buffered, defer: false)
        window.title = "AutoBlockBlast"
        window.center()
        NSApp.applicationIconImage = appMark()
        let title = NSTextField(labelWithString: "AutoBlockBlast")
        title.font = .systemFont(ofSize: 25, weight: .bold)
        status.font = .systemFont(ofSize: 16, weight: .semibold)
        detail.font = .systemFont(ofSize: 13)
        detail.textColor = .secondaryLabelColor
        stats.font = .monospacedDigitSystemFont(ofSize: 15, weight: .medium)
        let explanation = NSTextField(wrappingLabelWithString: "Score and last visible combo are read from the game screen.")
        explanation.textColor = .secondaryLabelColor
        explanation.font = .systemFont(ofSize: 12)
        for (button, action) in [(startButton, #selector(start)), (pauseButton, #selector(togglePause)), (stopButton, #selector(stop))] {
            button.target = self
            button.action = action
            button.bezelStyle = .rounded
        }
        startButton.keyEquivalent = "\r"
        let buttons = NSStackView(views: [startButton, pauseButton, stopButton])
        buttons.orientation = .horizontal
        buttons.spacing = 12
        let artwork = BlockArtwork(frame: NSRect(x: 0, y: 0, width: 200, height: 65))
        artwork.widthAnchor.constraint(equalToConstant: 200).isActive = true
        artwork.heightAnchor.constraint(equalToConstant: 65).isActive = true
        let stack = NSStackView(views: [title, artwork, status, detail, stats, explanation, buttons])
        stack.orientation = .vertical
        stack.alignment = .leading
        stack.spacing = 14
        stack.translatesAutoresizingMaskIntoConstraints = false
        window.contentView!.addSubview(stack)
        NSLayoutConstraint.activate([
            stack.leadingAnchor.constraint(equalTo: window.contentView!.leadingAnchor, constant: 28),
            stack.trailingAnchor.constraint(equalTo: window.contentView!.trailingAnchor, constant: -28),
            stack.topAnchor.constraint(equalTo: window.contentView!.topAnchor, constant: 25)
        ])
        refreshButtons()
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    func refreshButtons() {
        startButton.isEnabled = process == nil
        startButton.title = needsFolderAccess ? "Allow folder access…" : (hasStarted && process == nil ? "Restart" : "Start")
        pauseButton.isEnabled = process != nil && !stopping
        stopButton.isEnabled = process != nil && !stopping
        pauseButton.title = paused ? "Resume" : "Pause"
    }

    func showError(_ message: String) {
        status.stringValue = "Error"
        detail.stringValue = message
    }

    @objc func start() {
        guard process == nil else { return }
        if needsFolderAccess {
            let panel = NSOpenPanel()
            panel.message = "Select the AutoBlockBlast project folder to allow the app to read the bot and its environment."
            panel.canChooseDirectories = true
            panel.canChooseFiles = false
            panel.allowsMultipleSelection = false
            panel.directoryURL = root.deletingLastPathComponent()
            guard panel.runModal() == .OK, let selected = panel.url else { return }
            guard selected.standardizedFileURL.resolvingSymlinksInPath() == root.standardizedFileURL.resolvingSymlinksInPath() else {
                showError("Select the AutoBlockBlast folder containing .venv and src.")
                return
            }
            grantedFolder = selected
            _ = selected.startAccessingSecurityScopedResource()
            needsFolderAccess = false
        }
        do {
            try FileManager.default.createDirectory(at: captureDirectory, withIntermediateDirectories: true)
            try? FileManager.default.removeItem(at: pauseFile)
            let task = Process()
            task.executableURL = root.appendingPathComponent(".venv/bin/python")
            task.currentDirectoryURL = root
            var environment = ProcessInfo.processInfo.environment
            let paths = ["/opt/homebrew/bin", "/usr/local/bin",
                         NSHomeDirectory() + "/Library/Android/sdk/platform-tools"]
            environment["PATH"] = (paths + [environment["PATH"] ?? "/usr/bin:/bin"]).joined(separator: ":")
            task.environment = environment
            task.arguments = ["-u", "-m", "autoblockblast.autoplay", "--execute", "--moves", "0", "--ui-metrics"]
            let pipe = Pipe()
            task.standardOutput = pipe
            task.standardError = pipe
            pipe.fileHandleForReading.readabilityHandler = { [weak self] handle in
                let data = handle.availableData
                guard !data.isEmpty, let text = String(data: data, encoding: .utf8) else { return }
                DispatchQueue.main.async { self?.consume(text) }
            }
            task.terminationHandler = { [weak self] finished in
                DispatchQueue.main.async {
                    guard let self = self else { return }
                    pipe.fileHandleForReading.readabilityHandler = nil
                    self.process = nil
                    self.paused = false
                    try? FileManager.default.removeItem(at: self.pauseFile)
                    self.grantedFolder?.stopAccessingSecurityScopedResource()
                    self.grantedFolder = nil
                    self.needsFolderAccess = self.lastMessage.contains("PermissionError:") &&
                        self.lastMessage.contains("Operation not permitted")
                    if self.stopping {
                        self.status.stringValue = "Stopped"
                        self.detail.stringValue = "Stopped by you."
                    } else {
                        self.status.stringValue = finished.terminationStatus == 0 ? "Stopped" : "Stopped with an error"
                        self.detail.stringValue = self.needsFolderAccess
                            ? "macOS blocked access to the project folder. Click Allow folder access and select the AutoBlockBlast folder."
                            : self.lastMessage.isEmpty ? "Bot exited with code \(finished.terminationStatus). Check the game and USB connection." : self.lastMessage
                    }
                    self.stopping = false
                    self.refreshButtons()
                }
            }
            lastMessage = ""
            pendingOutput = ""
            moveCount = 0
            scoreText = "—"
            comboText = "—"
            metricsGeneration += 1
            updateStats()
            try task.run()
            hasStarted = true
            process = task
            status.stringValue = "Starting…"
            detail.stringValue = "Checking the phone and game."
            refreshButtons()
        } catch {
            grantedFolder?.stopAccessingSecurityScopedResource()
            grantedFolder = nil
            if (error as NSError).code == NSFileReadNoPermissionError {
                needsFolderAccess = true
                refreshButtons()
            }
            showError("Could not start the bot: \(error.localizedDescription)")
        }
    }

    func consume(_ text: String) {
        pendingOutput += text
        while let end = pendingOutput.firstIndex(of: "\n") {
            let line = String(pendingOutput[..<end]).trimmingCharacters(in: .whitespacesAndNewlines)
            pendingOutput.removeSubrange(...end)
            guard !line.isEmpty else { continue }
            if line.hasPrefix("UI_FRAME ") {
                readMetrics(String(line.dropFirst("UI_FRAME ".count)))
            } else if line.hasPrefix("Verified move ") {
                moveCount += 1
                status.stringValue = paused ? "Pausing…" : "Playing"
                detail.stringValue = "\(moveCount) verified moves"
            } else if line == "Paused." {
                status.stringValue = "Paused"
                detail.stringValue = "Resume when you are ready."
            } else if line == "Resumed." {
                status.stringValue = "Playing"
                detail.stringValue = "\(moveCount) verified moves"
            } else if line.hasPrefix("RuntimeError:") || line.hasPrefix("FileNotFoundError:") ||
                      line.hasPrefix("ConnectionError:") || line.hasPrefix("OSError:") ||
                      line.hasPrefix("PermissionError:") || line.hasPrefix("ModuleNotFoundError:") ||
                      line.hasPrefix("adbutils.errors.") {
                lastMessage = line
            } else if line.contains("Stopped") || line.contains("No complete plan") ||
                      line.contains("No fresh") || line.contains("not in front") ||
                      line.contains("not found") || line.contains("No Android device") ||
                      line.contains("unauthorized") || line.contains("already running") ||
                      line.contains("No adb exe") || line.contains("No Android device found") ||
                      line.contains("Unrecognized") || line.contains("stream stopped") ||
                      line.contains("Game state changed") || line.contains("Timed out") {
                lastMessage = line
            }
        }
    }

    func updateStats() {
        stats.stringValue = "Score  \(scoreText)     Last combo  \(comboText)"
    }

    func readMetrics(_ encoded: String) {
        guard !metricsBusy, let data = Data(base64Encoded: encoded),
              let source = CGImageSourceCreateWithData(data as CFData, nil),
              let image = CGImageSourceCreateImageAtIndex(source, 0, nil) else { return }
        metricsBusy = true
        let generation = metricsGeneration
        DispatchQueue.global(qos: .utility).async {
            let request = VNRecognizeTextRequest()
            request.recognitionLevel = .accurate
            request.usesLanguageCorrection = false
            request.recognitionLanguages = ["en-US"]
            let handler = VNImageRequestHandler(cgImage: image)
            try? handler.perform([request])
            let results = request.results ?? []
            var score: String?
            var combo: String?
            var comboBox: CGRect?
            var numericObservations: [(String, CGRect)] = []
            for observation in results {
                guard let candidate = observation.topCandidates(1).first, candidate.confidence >= 0.6 else { continue }
                let text = candidate.string.trimmingCharacters(in: .whitespacesAndNewlines)
                let box = observation.boundingBox
                let digits = text.filter { $0.isNumber }
                // The live score sits in the top centre of the captured area.
                if box.midY > 0.75 && box.midX > 0.25 && box.midX < 0.75 &&
                    !digits.isEmpty && text.allSatisfy({ $0.isNumber || $0 == "," }) {
                    score = digits
                }
                if !digits.isEmpty && text.allSatisfy({ $0.isNumber }) {
                    numericObservations.append((digits, box))
                }
                if text.lowercased().contains("combo") {
                    comboBox = box
                    if !digits.isEmpty { combo = digits }
                }
            }
            if combo == nil, let label = comboBox {
                combo = numericObservations.first(where: { _, box in
                    box.midX > label.midX && abs(box.midY - label.midY) < 0.08
                })?.0
            }
            DispatchQueue.main.async {
                self.metricsBusy = false
                guard generation == self.metricsGeneration else { return }
                if let score = score { self.scoreText = score }
                if let combo = combo { self.comboText = combo }
                self.updateStats()
            }
        }
    }

    @objc func togglePause() {
        guard process != nil, !stopping else { return }
        do {
            if paused {
                try FileManager.default.removeItem(at: pauseFile)
                paused = false
                status.stringValue = "Resuming…"
            } else {
                try Data().write(to: pauseFile)
                paused = true
                status.stringValue = "Pausing…"
                detail.stringValue = "Finishing the current move."
            }
            refreshButtons()
        } catch {
            showError("Could not update pause state. Stop the session and try again.")
        }
    }

    @objc func stop() {
        guard process != nil, !stopping else { return }
        do {
            try Data().write(to: stopFile)
            stopping = true
            status.stringValue = "Stopping…"
            detail.stringValue = "Finishing the current move."
            refreshButtons()
        } catch {
            showError("Could not send the stop request.")
        }
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        guard process != nil else { return .terminateNow }
        stop()
        process?.terminationHandler = { _ in
            DispatchQueue.main.async { NSApp.reply(toApplicationShouldTerminate: true) }
        }
        return .terminateLater
    }
}

let app = NSApplication.shared
let delegate = BotApp()
app.delegate = delegate
app.run()
