import AppKit
import QuartzCore
import Vision

final class BlockArtwork: NSView {
    private static let teal = NSColor(srgbRed: 0.44, green: 0.83, blue: 0.76, alpha: 1)
    private static let blue = NSColor(srgbRed: 0.35, green: 0.63, blue: 0.99, alpha: 1)
    private static let peach = NSColor(srgbRed: 1, green: 0.73, blue: 0.57, alpha: 1)
    private static let shapes: [[(Int, Int)]] = [
        [(0, 0), (1, 0), (0, 1), (1, 1)],
        [(0, 0), (0, 1), (1, 1), (2, 1)],
        [(0, 0), (1, 0), (1, 1), (2, 1)],
        [(0, 0), (1, 0), (2, 0), (1, 1)],
        [(0, 0), (1, 0), (1, 1)],
        [(0, 0), (1, 0), (2, 0)]
    ]

    private static let comboColors = [
        peach, teal, blue,
        NSColor(srgbRed: 0.77, green: 0.66, blue: 0.99, alpha: 1),
        NSColor(srgbRed: 0.97, green: 0.59, blue: 0.70, alpha: 1),
        NSColor(srgbRed: 0.91, green: 0.81, blue: 0.43, alpha: 1)
    ]

    private let isLogo: Bool
    private var shapeIndex = Int.random(in: 0..<shapes.count)
    private var colorIndex = Int.random(in: 0..<comboColors.count)
    override var isFlipped: Bool { true }

    init(logo: Bool = false) {
        isLogo = logo
        super.init(frame: .zero)
        setAccessibilityElement(false)
    }

    required init?(coder: NSCoder) { fatalError("Use init(logo:)") }

    func shuffle() {
        shapeIndex = (shapeIndex + Int.random(in: 1..<Self.shapes.count)) % Self.shapes.count
        colorIndex = (colorIndex + Int.random(in: 1..<Self.comboColors.count)) % Self.comboColors.count
        needsDisplay = true
    }

    override func draw(_ dirtyRect: NSRect) {
        if isLogo {
            drawTiles(Self.shapes[4], color: Self.teal, origin: NSPoint(x: 0, y: 0), tile: 5, gap: 1)
            drawTiles(Self.shapes[1], color: Self.blue, origin: NSPoint(x: 15, y: 0), tile: 5, gap: 1)
            drawTiles(Self.shapes[0], color: Self.peach, origin: NSPoint(x: 35, y: 0), tile: 5, gap: 1)
        } else {
            let cells = Self.shapes[shapeIndex]
            let columns = (cells.map { $0.0 }.max() ?? 0) + 1
            let rows = (cells.map { $0.1 }.max() ?? 0) + 1
            let tile: CGFloat = 13
            let gap: CGFloat = 2
            let width = CGFloat(columns) * (tile + gap) - gap
            let height = CGFloat(rows) * (tile + gap) - gap
            let origin = NSPoint(x: 0, y: (bounds.height - height) / 2)
            if width <= bounds.width {
                drawTiles(cells, color: Self.comboColors[colorIndex], origin: origin, tile: tile, gap: gap)
            }
        }
    }

    private func drawTiles(_ cells: [(Int, Int)], color: NSColor, origin: NSPoint, tile: CGFloat, gap: CGFloat) {
        for (x, y) in cells {
            let rect = NSRect(x: origin.x + CGFloat(x) * (tile + gap),
                              y: origin.y + CGFloat(y) * (tile + gap), width: tile, height: tile)
            let path = NSBezierPath(roundedRect: rect, xRadius: tile * 0.22, yRadius: tile * 0.22)
            NSGradient(starting: color.blended(withFraction: 0.13, of: .white) ?? color,
                       ending: color)?.draw(in: path, angle: 90)
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
    let scoreValue = NSTextField(labelWithString: "—")
    let comboValue = NSTextField(labelWithString: "—")
    let comboArtwork = BlockArtwork()
    let statusIcon = NSImageView()
    let scoreFormatter: NumberFormatter = {
        let formatter = NumberFormatter()
        formatter.numberStyle = .decimal
        return formatter
    }()
    let sessionLine = NSTextField(labelWithString: "")
    var sessionTimer: Timer?
    var sessionStartedAt: TimeInterval?
    var elapsedSessionTime: TimeInterval = 0
    private var playCommentTimer: Timer?
    private var playCommentStartedAt: TimeInterval = 0
    private let playComments = [
        "Ahh, easy one.",
        "Lemme place this one.",
        "Yep, that fits.",
        "That spot will do.",
        "One block at a time.",
        "Nice, room for the next one."
    ]
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
    var highestCombo: Int?
    var metricsBusy = false
    var metricsGeneration = 0
    var captureDirectory: URL { root.appendingPathComponent("captures", isDirectory: true) }
    var pauseFile: URL { captureDirectory.appendingPathComponent("pause.request") }
    var stopFile: URL { captureDirectory.appendingPathComponent("stop.request") }

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 474, height: 296),
                          styleMask: [.titled, .closable, .miniaturizable, .resizable, .fullSizeContentView],
                          backing: .buffered, defer: false)
        window.title = "AutoBlockBlast"
        window.titleVisibility = .hidden
        window.titlebarAppearsTransparent = true
        window.appearance = NSAppearance(named: .darkAqua)
        window.minSize = NSSize(width: 474, height: 296)
        window.isMovableByWindowBackground = true
        window.center()
        NSApp.applicationIconImage = appMark()

        let content = window.contentView!
        content.wantsLayer = true
        content.layer?.backgroundColor = NSColor(srgbRed: 0.116, green: 0.116, blue: 0.124, alpha: 1).cgColor

        let header = NSView()
        header.wantsLayer = true
        header.layer?.backgroundColor = NSColor(srgbRed: 0.163, green: 0.163, blue: 0.176, alpha: 1).cgColor
        let title = NSTextField(labelWithString: "AutoBlockBlast")
        title.font = .systemFont(ofSize: 15, weight: .bold)
        let mark = BlockArtwork(logo: true)
        mark.widthAnchor.constraint(equalToConstant: 46).isActive = true
        mark.heightAnchor.constraint(equalToConstant: 11).isActive = true
        let heading = NSStackView(views: [mark, title])
        heading.spacing = 11
        heading.alignment = .centerY

        let headerRule = NSBox()
        headerRule.boxType = .separator
        let rule = NSBox()
        rule.boxType = .separator

        for value in [scoreValue, comboValue] {
            value.font = .monospacedDigitSystemFont(ofSize: 30, weight: .medium)
        }
        comboArtwork.widthAnchor.constraint(equalToConstant: 43).isActive = true
        comboArtwork.heightAnchor.constraint(equalToConstant: 32).isActive = true
        let comboDisplay = NSStackView(views: [comboValue, comboArtwork])
        comboDisplay.spacing = 9
        comboDisplay.alignment = .centerY

        let comboColumn = metric("Highest combo", value: comboDisplay)
        let metrics = NSStackView(views: [metric("Score", value: scoreValue), comboColumn])
        metrics.distribution = .fillEqually
        metrics.alignment = .top
        metrics.spacing = 16

        status.font = .systemFont(ofSize: 15, weight: .bold)
        detail.font = .systemFont(ofSize: 14)
        detail.textColor = .secondaryLabelColor
        detail.maximumNumberOfLines = 3
        detail.wantsLayer = true
        sessionLine.font = .monospacedDigitSystemFont(ofSize: 11, weight: .regular)
        sessionLine.textColor = .secondaryLabelColor
        sessionLine.isHidden = true
        statusIcon.image = NSImage(systemSymbolName: "exclamationmark.triangle.fill", accessibilityDescription: "Warning")
        statusIcon.contentTintColor = .systemYellow
        statusIcon.widthAnchor.constraint(equalToConstant: 16).isActive = true
        statusIcon.heightAnchor.constraint(equalToConstant: 16).isActive = true
        statusIcon.isHidden = true
        let statusLine = NSStackView(views: [statusIcon, status])
        statusLine.spacing = 8
        sessionLine.alignment = .right
        sessionLine.lineBreakMode = .byTruncatingTail
        statusLine.alignment = .centerY

        for (button, action) in [(startButton, #selector(start)), (pauseButton, #selector(togglePause)), (stopButton, #selector(stop))] {
            button.target = self
            button.action = action
            button.bezelStyle = .rounded
            button.controlSize = .large
            button.font = .systemFont(ofSize: 14, weight: .medium)
            button.widthAnchor.constraint(greaterThanOrEqualToConstant: 74).isActive = true
        }
        let buttons = NSStackView(views: [startButton, pauseButton, stopButton])
        buttons.spacing = 10

        for view in [header, heading, headerRule, metrics, rule, statusLine, sessionLine, detail, buttons] {
            view.translatesAutoresizingMaskIntoConstraints = false
            content.addSubview(view)
        }
        NSLayoutConstraint.activate([
            header.topAnchor.constraint(equalTo: content.topAnchor),
            header.leadingAnchor.constraint(equalTo: content.leadingAnchor),
            header.trailingAnchor.constraint(equalTo: content.trailingAnchor),
            header.heightAnchor.constraint(equalToConstant: 33),
            heading.centerXAnchor.constraint(equalTo: content.centerXAnchor, constant: 16),
            heading.centerYAnchor.constraint(equalTo: header.centerYAnchor),
            headerRule.leadingAnchor.constraint(equalTo: header.leadingAnchor),
            headerRule.trailingAnchor.constraint(equalTo: header.trailingAnchor),
            headerRule.topAnchor.constraint(equalTo: header.bottomAnchor),
            metrics.topAnchor.constraint(equalTo: headerRule.bottomAnchor, constant: 16),
            metrics.leadingAnchor.constraint(equalTo: content.leadingAnchor, constant: 29),
            metrics.trailingAnchor.constraint(equalTo: content.trailingAnchor, constant: -29),
            rule.topAnchor.constraint(equalTo: metrics.bottomAnchor, constant: 18),
            rule.leadingAnchor.constraint(equalTo: content.leadingAnchor, constant: 24),
            rule.trailingAnchor.constraint(equalTo: content.trailingAnchor, constant: -24),
            statusLine.topAnchor.constraint(equalTo: rule.bottomAnchor, constant: 16),
            statusLine.leadingAnchor.constraint(equalTo: metrics.leadingAnchor),
            statusLine.trailingAnchor.constraint(lessThanOrEqualTo: metrics.trailingAnchor),
            sessionLine.leadingAnchor.constraint(equalTo: comboColumn.leadingAnchor),
            sessionLine.trailingAnchor.constraint(equalTo: metrics.trailingAnchor),
            sessionLine.centerYAnchor.constraint(equalTo: statusLine.centerYAnchor),
            detail.topAnchor.constraint(equalTo: statusLine.bottomAnchor, constant: 5),
            detail.leadingAnchor.constraint(equalTo: metrics.leadingAnchor),
            detail.trailingAnchor.constraint(equalTo: metrics.trailingAnchor),
            buttons.leadingAnchor.constraint(equalTo: metrics.leadingAnchor),
            buttons.topAnchor.constraint(greaterThanOrEqualTo: detail.bottomAnchor, constant: 10),
            buttons.bottomAnchor.constraint(equalTo: content.bottomAnchor, constant: -25),
        ])
        sessionTimer = Timer.scheduledTimer(withTimeInterval: 1, repeats: true) { [weak self] _ in
            self?.updateSessionLine()
        }
        updateStats()
        refreshButtons()
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    private func metric(_ name: String, value: NSView) -> NSStackView {
        let label = NSTextField(labelWithString: name)
        label.font = .systemFont(ofSize: 15, weight: .semibold)
        label.textColor = .secondaryLabelColor
        let column = NSStackView(views: [label, value])
        column.orientation = .vertical
        column.alignment = .leading
        column.spacing = 5
        return column
    }

    private var playedSeconds: Int {
        let activeTime = sessionStartedAt.map { ProcessInfo.processInfo.systemUptime - $0 } ?? 0
        return Int(elapsedSessionTime + activeTime)
    }

    private func showPlayComment() {
        if playCommentTimer == nil && !NSWorkspace.shared.accessibilityDisplayShouldReduceMotion {
            let fade = CABasicAnimation(keyPath: "opacity")
            fade.fromValue = 1.0
            fade.toValue = 0.62
            fade.duration = 1.35
            fade.autoreverses = true
            fade.repeatCount = .infinity
            fade.timingFunction = CAMediaTimingFunction(name: .easeInEaseOut)
            detail.layer?.add(fade, forKey: "playCommentFade")
        }
        if playCommentTimer == nil {
            playCommentStartedAt = ProcessInfo.processInfo.systemUptime
            playCommentTimer = Timer.scheduledTimer(withTimeInterval: 0.25, repeats: true) { [weak self] _ in
                self?.updatePlayComment()
            }
        }
        updatePlayComment()
    }

    private func updatePlayComment() {
        let elapsed = ProcessInfo.processInfo.systemUptime - playCommentStartedAt
        let text: String
        if elapsed < 2 {
            text = ". . ."
        } else {
            let commentTime = elapsed - 2
            let comment = playComments[(Int(commentTime) / 15) % playComments.count]
            if NSWorkspace.shared.accessibilityDisplayShouldReduceMotion {
                text = comment
            } else {
                let dots = Int(commentTime.truncatingRemainder(dividingBy: 15) / 0.45) % 4
                text = String(comment.dropLast()) + String(repeating: " .", count: dots)
            }
        }
        if detail.stringValue != text {
            detail.stringValue = text
        }
    }

    private func showDetail(_ text: String) {
        playCommentTimer?.invalidate()
        playCommentTimer = nil
        detail.layer?.removeAnimation(forKey: "playCommentFade")
        detail.stringValue = text
    }

    private func updateSessionLine() {
        sessionLine.isHidden = status.stringValue != "Playing"
        guard !sessionLine.isHidden else { return }
        let seconds = playedSeconds
        let minutesAndSeconds = "\((seconds / 60) % 60)m \(seconds % 60)s"
        let time = seconds >= 3600
            ? "\(seconds / 3600)h \(minutesAndSeconds)"
            : minutesAndSeconds
        sessionLine.stringValue = "Running for \(time) · \(moveCount) \(moveCount == 1 ? "move" : "moves")"
    }

    private func pauseSessionClock() {
        if let startedAt = sessionStartedAt {
            elapsedSessionTime += ProcessInfo.processInfo.systemUptime - startedAt
            sessionStartedAt = nil
        }
        updateSessionLine()
    }

    func refreshButtons() {
        updateSessionLine()
        startButton.isEnabled = process == nil
        startButton.title = needsFolderAccess ? "Allow folder access…" : (hasStarted && process == nil ? "Restart" : "Start")
        startButton.keyEquivalent = startButton.title == "Restart" ? "\r" : ""
        pauseButton.isEnabled = process != nil && !stopping
        stopButton.isEnabled = process != nil && !stopping
        pauseButton.title = paused ? "Resume" : "Pause"
    }

    func explanationForStop(_ message: String) -> String {
        let lower = message.lowercased()
        if lower.contains("no android device") || lower.contains("no device") {
            return "Android not detected. Connect USB or wireless ADB, unlock the phone, and allow debugging."
        }
        if lower.contains("unauthorized") {
            return "USB debugging is not authorized. Unlock the phone and allow debugging for this Mac."
        }
        if lower.contains("more than one adb") {
            return "More than one Android connection detected. Disconnect an extra phone or USB/Wi-Fi connection."
        }
        if lower.contains("not in front") {
            return "Unlock your phone and open Block Blast."
        }
        if lower.contains("stream stopped") || lower.contains("scrcpy socket") || lower.contains("video header missing") {
            return "The phone video stream disconnected. Check USB or wireless ADB, then restart."
        }
        if lower.contains("no new video frames") {
            return "No new video frames arrived. Keep Block Blast open and check USB or wireless ADB."
        }
        if lower.contains("tray could not be read") {
            return "The tray could not be read. Wait for the pieces to appear and dismiss any overlays."
        }
        if lower.contains("did not stay consistent") {
            return "The board and tray kept changing. Wait for animations to finish, then restart."
        }
        if message.hasPrefix("Stopped: ") {
            return String(message.dropFirst("Stopped: ".count))
        }
        if lower.contains("no complete plan") {
            return "No complete plan was found for the current pieces. Check the board in Block Blast."
        }
        return message
    }

    func showError(_ message: String) {
        status.stringValue = "Error"
        statusIcon.isHidden = false
        showDetail(message)
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
            task.arguments = [
                "-u", "-m", "autoblockblast.autoplay", "--execute", "--moves", "0",
                "--ui-metrics", "--fast-recheck", "--reuse-plan", "--chain-tray",
            ]
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
                    self.pauseSessionClock()
                    self.paused = false
                    try? FileManager.default.removeItem(at: self.pauseFile)
                    self.grantedFolder?.stopAccessingSecurityScopedResource()
                    self.grantedFolder = nil
                    self.needsFolderAccess = self.lastMessage.contains("PermissionError:") &&
                        self.lastMessage.contains("Operation not permitted")
                    if self.stopping {
                        self.status.stringValue = "Stopped"
                        self.showDetail("Stopped by you.")
                    } else {
                        let gameHidden = self.lastMessage.lowercased().contains("not in front")
                        self.statusIcon.isHidden = !gameHidden && finished.terminationStatus == 0 && self.lastMessage.isEmpty
                        self.status.stringValue = gameHidden ? "Game not in front" :
                            (finished.terminationStatus == 0 ? "Stopped" : "Stopped with an error")
                        self.showDetail(self.needsFolderAccess
                            ? "macOS blocked access to the project folder. Click Allow folder access and select the AutoBlockBlast folder."
                            : self.lastMessage.isEmpty ? "Bot exited with code \(finished.terminationStatus). Check the game and Android connection." : self.explanationForStop(self.lastMessage))
                    }
                    self.stopping = false
                    self.refreshButtons()
                }
            }
            lastMessage = ""
            pendingOutput = ""
            moveCount = 0
            scoreText = "—"
            highestCombo = nil
            metricsGeneration += 1
            updateStats()
            try task.run()
            hasStarted = true
            process = task
            elapsedSessionTime = 0
            sessionStartedAt = ProcessInfo.processInfo.systemUptime
            updateSessionLine()
            status.stringValue = "Starting…"
            statusIcon.isHidden = true
            showDetail("Checking the phone and game.")
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
        let previousStatus = status.stringValue
        let previousMoveCount = moveCount
        pendingOutput += text
        while let end = pendingOutput.firstIndex(of: "\n") {
            let line = String(pendingOutput[..<end]).trimmingCharacters(in: .whitespacesAndNewlines)
            pendingOutput.removeSubrange(...end)
            guard !line.isEmpty else { continue }
            if line.hasPrefix("UI_STATUS ") {
                if !paused && !stopping {
                    status.stringValue = line == "UI_STATUS Playing…" || moveCount > 0 ? "Playing" : "Starting…"
                    if line == "UI_STATUS Playing…" {
                        showPlayComment()
                    } else {
                        showDetail(String(line.dropFirst("UI_STATUS ".count)))
                    }
                }
            } else if line.hasPrefix("UI_FRAME ") {
                readMetrics(String(line.dropFirst("UI_FRAME ".count)))
            } else if line.hasPrefix("Verified move ") {
                moveCount += 1
                if !stopping {
                    status.stringValue = paused ? "Pausing…" : "Playing"
                    if paused {
                        showDetail("Finishing the current move.")
                    } else {
                        showPlayComment()
                    }
                }
            } else if line == "Paused." {
                pauseSessionClock()
                status.stringValue = "Paused"
                showDetail("Resume when you are ready.")
            } else if line == "Resumed." {
                sessionStartedAt = ProcessInfo.processInfo.systemUptime
                status.stringValue = "Playing"
                showPlayComment()
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
                      line.contains("scrcpy socket") || line.contains("video header missing") ||
                      line.contains("Game state changed") || line.contains("Timed out") ||
                      line.contains("More than one ADB") || line.contains("Waiting for a complete tray") {
                lastMessage = line
            }
        }
        if status.stringValue != previousStatus || moveCount != previousMoveCount {
            updateSessionLine()
        }
    }

    func updateStats() {
        if let score = Int64(scoreText) {
            scoreValue.stringValue = scoreFormatter.string(from: NSNumber(value: score)) ?? scoreText
        } else {
            scoreValue.stringValue = scoreText
        }
        comboArtwork.isHidden = highestCombo == nil
        comboValue.stringValue = highestCombo.map { "\($0) ×" } ?? "—"
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
                if let combo = combo.flatMap(Int.init), combo > (self.highestCombo ?? 0) {
                    self.highestCombo = combo
                    self.comboArtwork.shuffle()
                }
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
                showDetail("Finishing the current move.")
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
            showDetail("Finishing the current move.")
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
