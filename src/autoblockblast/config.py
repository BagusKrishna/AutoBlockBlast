import os
from pathlib import Path

SCRCPY_DIR = Path(os.environ.get("SCRCPY_DIR") or Path(__file__).resolve().parents[2] / "scrcpy")
SCRCPY_SERVER = SCRCPY_DIR / "scrcpy-server"
SCRCPY_VERSION = os.environ.get("SCRCPY_VERSION", "3.2")
MAX_SIZE = 800
MAX_FPS = 30
GAME_PACKAGE = "com.block.juggle"

GRID_SIZE = 8

BOARD_RECT = (0.05556, 0.24167, 0.94444, 0.64167)
PIECES_RECT = (0.060, 0.68333, 0.940, 0.83333)
BOARD_INSET = 0.0

CELL_V_MIN = 130
CELL_S_MIN = 35

PIECE_S_DELTA = 26
PIECE_V_DELTA = 36
PIECE_H_DELTA = 17
PIECE_MIN_AREA = 60
PIECE_OPEN = 4

DRAG_MS = 600
SETTLE_S = 0.35
ROUND_PAUSE_S = 0.35
# Measured on this Samsung/game build: block motion = 1.5 * finger motion,
# with a 270 px lift on the 120 px board cells.
DRAG_GAIN_X = 1.5
DRAG_GAIN_Y = 1.5
DRAG_LIFT_CELLS = 2.25
DROP_Y_NUDGE = 0.0
AUTO_INTERVAL_S = 0.25

Rect = tuple[float, float, float, float]
