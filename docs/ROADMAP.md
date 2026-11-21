# Roadmap

1. **Vision reliability:** validate board occupancy and every piece shape against labeled real-game screenshots, including disconnected diagonals, five-cell pieces, changing colors/themes and animations. Stop when uncertain. Add regression fixtures before claiming support.
2. **Speed:** measure capture, parsing, planning, drag and settle times independently. Reduce delays only after reliability testing; retain stale-frame, foreground and post-drag checks. Keep screenshots local and bounded; clean up only the bot's own temporary files.
3. **Planning:** compare current bounded beam search against exact three-piece DFS/bitboards and measure runtime, survival and clear counts on the same replay data. Prioritize complete placements, clearing moves, lines and future flexibility. Game combo and score rules need measurement; three-piece lookahead cannot guarantee a best game outcome.
4. **macOS UI:** local start, stop, preview, calibration, status and plan explanation without requiring Terminal.
5. **iPhone exploration:** investigate iPhone Mirroring and XCUITest/WebDriverAgent as separate backends after Android is reliable; account for distinct capture, input, privacy and calibration requirements.
