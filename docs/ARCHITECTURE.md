# Architecture

`src/autoblockblast/` contains the Python package:

- `autoplay.py` orchestrates state reads, planning, one move, and result verification.
- `vision.py` converts game frames into board and piece matrices.
- `solver.py` simulates placements and searches the visible tray exactly with a bitboard. Bounded beam variants are available for comparison.
- `controller.py` maps a planned placement into a device drag.
- `phone.py` checks ADB connectivity and foreground game focus.
- `scrcpy_stream.py` starts the scrcpy server and decodes a live H.264 feed.
- `config.py`, `calibrate.py`, and `calibration.py` contain device settings and calibration.
- `main.py` is the legacy interactive OpenCV runner; `check_setup.py` checks prerequisites.

`tests/` contains automated tests and game-only screenshot fixtures. `scripts/` contains macOS launchers. `captures/` and `scrcpy/` are local, ignored runtime directories. Video frames are processed in memory; local debug images and the most recent verification failure are bounded. The current scrcpy server can leave temporary files on the phone; cleanup remains on the roadmap.

The execution loop checks the active game, reads stable fresh frames, validates the input, plans, checks state again, executes one drag, then compares the resulting board and remaining tray against the prediction. If a check fails it stops. These checks reduce errors but do not prove all themes, animations, or shapes are recognized correctly.
