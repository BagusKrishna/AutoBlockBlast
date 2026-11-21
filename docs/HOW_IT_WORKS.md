# How AutoBlockBlast works

AutoBlockBlast is an experimental program on a Mac that observes Block Blast on an Android phone and can place pieces automatically. It connects through USB debugging, reads the screen, chooses a placement, sends a drag, and checks the result. It is calibrated for the screen layout in `config.py`; support for other devices and changing game themes must be tested.

## What each part does

1. **Connection and screen stream.** `phone.py` finds the connected Android phone and checks that Block Blast is in front. `scrcpy_stream.py` starts a scrcpy server on the phone and receives a live video stream over ADB. The Mac decodes frames in memory with PyAV.
2. **Vision.** `vision.py` uses OpenCV to turn the board into an 8×8 grid of filled and empty cells and to infer the shape of each available piece. The region coordinates and thresholds are in `config.py`. Game themes, overlays and animations can cause a wrong reading, so the parser should not be assumed perfect.
3. **Planning.** `solver.py` simulates legal placements and clearing complete rows and columns. It searches the available pieces with a bounded beam search. It favors a complete plan, then clearing moves and lines, then a board heuristic for future flexibility. This is an approximation: it does not guarantee the best score, predict unknown future pieces, or model the game's combo score exactly.
4. **Drag.** `controller.py` converts the chosen board position and piece pickup point into screen coordinates, accounting for the calibrated touch gain and lift. It sends one swipe through ADB.
5. **Verification.** `autoplay.py` checks for a stable, fresh state before acting. After each drag it reads the board and tray again and compares them with the predicted result. If they differ, the stream is stale, or the game loses focus, it stops instead of continuing blindly. The next move is planned from the observed state.

## How to use it

Follow the installation and scrcpy setup in the [README](../README.md). Keep one authorized Android phone connected, unlocked, and displaying Block Blast. Run these commands from the project root after activating the virtual environment:

```bash
# Check prerequisites and the phone connection.
python -m autoblockblast.check_setup

# Read the board and show a plan; send no touch input.
python -m autoblockblast.autoplay

# Place up to three pieces, checking each result.
python -m autoblockblast.autoplay --execute --moves 3

# Continue until stopped or a check fails.
python -m autoblockblast.autoplay --execute --moves 0
```

Press **Control+C** in the running Terminal to stop. A drag already underway may finish. The `scripts/` folder also provides macOS preview, start, and stop launchers. Stop leaves the current game state as it is.

For a new device or changed layout, use `python -m autoblockblast.calibrate` to inspect and save board and tray regions and vision thresholds. The drag gain and lift also require device-specific calibration; the visual calibration tool does not determine them automatically. Start with preview and limited moves, checking the result on the phone.

## Data and troubleshooting

The live stream is processed in memory. The runner overwrites local debug images in `captures/`; it does not save every frame to the phone's gallery. The scrcpy server is copied to a temporary phone location for a session, and cleanup of the bot's own temporary files is still planned. `captures/`, the virtual environment and the server binary are ignored by Git.

If the bot reports a mismatch, inspect the latest local debug images and compare the recognized board and pieces with the game. Do not assume a one-cell difference is harmless. If it reports no complete plan, the currently read pieces may not all fit, or vision may be wrong. The current `before.png` and `after.png` are overwritten during later runs, so preserve relevant game-only evidence before restarting if it is needed for debugging.

More detail is in [Architecture](ARCHITECTURE.md) and the planned work is in [Roadmap](ROADMAP.md).
