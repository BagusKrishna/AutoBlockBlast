import time

import numpy as np
from adbutils import AdbDevice

from autoblockblast import config
from autoblockblast.phone import require_game
from autoblockblast.solver import Placement, SolveResult
from autoblockblast.vision import pickup_geometry


def frame_to_device(x: float, y: float, frame_w: int, frame_h: int, screen_w: int, screen_h: int) -> tuple[int, int]:
    return int(x * screen_w / frame_w), int(y * screen_h / frame_h)


def board_cell_xy(frame_shape, row: float, col: float, board_rect: config.Rect | None = None) -> tuple[float, float]:
    h, w = frame_shape[:2]
    x1, y1, x2, y2 = board_rect or config.BOARD_RECT
    bx1, by1 = w * x1, h * y1
    gw, gh = w * (x2 - x1), h * (y2 - y1)
    inset = config.BOARD_INSET
    mx, my = gw * inset, gh * inset
    uw, uh = max(1.0, gw - 2 * mx), max(1.0, gh - 2 * my)
    n = config.GRID_SIZE
    cx = bx1 + mx + (col + 0.5) * uw / n
    cy = by1 + my + (row + 0.5) * uh / n
    return cx, cy


def piece_slot_center(frame_shape, piece_index: int, pieces_rect: config.Rect | None = None) -> tuple[float, float]:
    h, w = frame_shape[:2]
    x1, y1, x2, y2 = pieces_rect or config.PIECES_RECT
    bx, by = w * x1, h * y1
    tray_w, tray_h = w * (x2 - x1), h * (y2 - y1)
    slot_w = tray_w / 3.0
    cx = bx + (piece_index + 0.5) * slot_w
    cy = by + tray_h * 0.5
    return cx, cy


def placement_center(frame_shape, piece: np.ndarray, place: Placement) -> tuple[float, float]:
    ys, xs = [], []
    ph, pw = piece.shape
    for r in range(ph):
        for c in range(pw):
            if piece[r, c]:
                x, y = board_cell_xy(frame_shape, place.row + r, place.col + c)
                xs.append(x)
                ys.append(y)
    if not xs:
        return board_cell_xy(frame_shape, place.row, place.col)
    return float(np.mean(xs)), float(np.mean(ys))


class Controller:
    def __init__(self, device: AdbDevice, screen_w: int, screen_h: int):
        self.device = device
        self.screen_w = screen_w
        self.screen_h = screen_h
        self.frame_w = 0
        self.frame_h = 0

    def set_frame_size(self, frame_w: int, frame_h: int):
        self.frame_w = frame_w
        self.frame_h = frame_h

    def _to_device(self, fx: float, fy: float) -> tuple[int, int]:
        return frame_to_device(fx, fy, self.frame_w, self.frame_h, self.screen_w, self.screen_h)

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int | None = None):
        require_game(self.device)
        ms = config.DRAG_MS if duration_ms is None else duration_ms
        self.device.shell(f"input swipe {x1} {y1} {x2} {y2} {ms}")

    def drag_piece(self, piece_index: int, piece: np.ndarray, place: Placement, frame_shape, frame=None) -> None:
        self.set_frame_size(frame_shape[1], frame_shape[0])
        sx, sy = piece_slot_center(frame_shape, piece_index)
        center_x, center_y = sx, sy
        ph, pw = piece.shape
        dx, dy = board_cell_xy(frame_shape, place.row + (ph - 1) / 2, place.col + (pw - 1) / 2)
        if frame is not None:
            sx, sy, center_x, center_y = pickup_geometry(frame, piece_index, piece)
        cell_h = (frame_shape[0] * (config.BOARD_RECT[3] - config.BOARD_RECT[1]) * (1 - 2 * config.BOARD_INSET)) / config.GRID_SIZE
        if config.DRAG_GAIN_X <= 0 or config.DRAG_GAIN_Y <= 0:
            raise RuntimeError("Drag gains must be positive.")
        dx = sx + (dx - center_x) / config.DRAG_GAIN_X
        dy = sy + (dy - center_y + (config.DRAG_LIFT_CELLS + config.DROP_Y_NUDGE) * cell_h) / config.DRAG_GAIN_Y
        x1, y1 = self._to_device(sx, sy)
        x2, y2 = self._to_device(dx, dy)
        if not (0 <= x1 < self.screen_w and 0 <= x2 < self.screen_w and 0 <= y1 < self.screen_h and 0 <= y2 < self.screen_h):
            raise RuntimeError("Drag would leave the screen; check the calibration and drop offset.")
        self.swipe(x1, y1, x2, y2)
        time.sleep(config.SETTLE_S)

    def execute(self, pieces: list[np.ndarray], result: SolveResult, frame_shape) -> None:
        for place in result.placements:
            piece = pieces[place.piece_index]
            if piece.size == 0:
                continue
            self.drag_piece(place.piece_index, piece, place, frame_shape)
        time.sleep(config.ROUND_PAUSE_S)
