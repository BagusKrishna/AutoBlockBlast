from dataclasses import dataclass

import cv2 as cv
import numpy as np

from autoblockblast import config


@dataclass
class VisionResult:
    board: np.ndarray
    pieces: list[np.ndarray]
    board_crop: np.ndarray
    piece_crops: list[np.ndarray]


def _crop_rel(frame: np.ndarray, rect: config.Rect) -> np.ndarray:
    h, w = frame.shape[:2]
    x1, y1, x2, y2 = rect
    return frame[int(h * y1) : int(h * y2), int(w * x1) : int(w * x2)]


def _slot_background(hsv: np.ndarray) -> tuple[float, float, float]:
    h, w = hsv.shape[:2]
    band = max(2, min(h, w) // 8)
    strips = [
        hsv[:band, :].reshape(-1, 3),
        hsv[-band:, :].reshape(-1, 3),
        hsv[:, :band].reshape(-1, 3),
        hsv[:, -band:].reshape(-1, 3),
    ]
    bg = np.vstack(strips)
    return float(np.median(bg[:, 0])), float(np.median(bg[:, 1])), float(np.median(bg[:, 2]))


def _hue_dist(h: np.ndarray, bg_h: float) -> np.ndarray:
    d = np.abs(h.astype(np.int16) - int(bg_h))
    return np.minimum(d, 180 - d)


def piece_mask(hsv: np.ndarray) -> np.ndarray:
    bg_h, bg_s, bg_v = _slot_background(hsv)
    H, S, V = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    dh = _hue_dist(H, bg_h)
    ds = np.abs(S.astype(np.int16) - int(bg_s))
    dv = np.abs(V.astype(np.int16) - int(bg_v))
    block = (dv >= config.PIECE_V_DELTA) | (ds >= config.PIECE_S_DELTA) | ((dh >= config.PIECE_H_DELTA) & (S >= 15))
    mask = block.astype(np.uint8)
    k = config.PIECE_OPEN
    if k > 1:
        mask = cv.morphologyEx(mask, cv.MORPH_OPEN, np.ones((k, k), np.uint8))
    return mask


def _trim_piece(grid: np.ndarray) -> np.ndarray:
    rows = np.any(grid, axis=1)
    cols = np.any(grid, axis=0)
    if not rows.any() or not cols.any():
        return np.zeros((0, 0), dtype=np.int8)
    return grid[rows][:, cols].astype(np.int8)


def _board_sample_points(gh: int, gw: int, n: int) -> list[tuple[int, int]]:
    inset = config.BOARD_INSET
    mx, my = int(gw * inset), int(gh * inset)
    uw, uh = max(1, gw - 2 * mx), max(1, gh - 2 * my)
    return [(int(my + (r + 0.5) * uh / n), int(mx + (c + 0.5) * uw / n)) for r in range(n) for c in range(n)]


def _cluster_1d(values: list[float]) -> list[float]:
    if not values:
        return []
    values = sorted(values)
    clusters: list[list[float]] = [[values[0]]]
    gaps = [values[i + 1] - values[i] for i in range(len(values) - 1)]
    split = max(float(np.median(gaps)) * 0.55 if gaps else 0.0, 5.0)
    for v in values[1:]:
        if v - float(np.mean(clusters[-1])) <= split:
            clusters[-1].append(v)
        else:
            clusters.append([v])
    return [float(np.mean(c)) for c in clusters]


def _largest_component(mask: np.ndarray, core_x: tuple[int, int] | None = None) -> np.ndarray:
    n, labels, stats, centroids = cv.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
    if n <= 1:
        return mask
    candidates = range(1, n)
    if core_x is not None:
        left, right = core_x
        # Padded crops preserve wide pieces, but can also include clipped
        # fragments of the neighboring slot.
        candidates = [i for i in candidates if left <= centroids[i, 0] < right]
    best = max(candidates, key=lambda i: stats[i, cv.CC_STAT_AREA], default=None)
    if best is None:
        return np.zeros_like(mask)
    if stats[best, cv.CC_STAT_AREA] < config.PIECE_MIN_AREA:
        return np.zeros_like(mask)
    # A diagonal piece may consist of two separate blocks. Merge a second
    # similarly sized component only when it is one cell diagonally away.
    bx, by, bw, bh, ba = stats[best]
    selected = labels == best
    for i in candidates:
        if i == best:
            continue
        x, y, w, h, area = stats[i]
        dx = abs((x + w / 2) - (bx + bw / 2))
        dy = abs((y + h / 2) - (by + bh / 2))
        if (0.65 <= area / ba <= 1.5 and 0.7 <= w / bw <= 1.4
                and 0.7 <= h / bh <= 1.4 and 0.8 <= dx / bw <= 1.6
                and 0.8 <= dy / bh <= 1.6):
            selected |= labels == i
    return selected.astype(np.uint8)


def _best_cell_grid(bw: int, bh: int, target: float) -> tuple[int, int]:
    short, long_side = min(bw, bh), max(bw, bh)
    if short >= 1 and long_side / short >= 1.65:
        exact = long_side / short
        # Bevels and shadows make the short side wider than one tray cell.
        # The calibrated cell pitch is more reliable for long straight pieces.
        pitch_count = int(round(long_side / target))
        if 2 <= pitch_count <= 5 and abs(long_side / pitch_count - target) <= target * 0.22:
            return (pitch_count, 1) if bh > bw else (1, pitch_count)
        best_n = max(1, min(5, int(round(exact))))
        best_err = abs(exact - best_n)
        for n in range(1, 6):
            err = abs(exact - n)
            if err < best_err - 1e-6 or (abs(err - best_err) <= 0.12 and n > best_n):
                best_err = err
                best_n = n
        if abs(bw - short) <= abs(bh - short):
            return best_n, 1
        return 1, best_n

    best = (1, 1)
    best_score = 1e9
    for nr in range(1, 6):
        for nc in range(1, 6):
            cw, ch = bw / nc, bh / nr
            if cw < 8 or ch < 8:
                continue
            aspect = abs(cw - ch) / max(cw, ch)
            if aspect > 0.3:
                continue
            size_err = (abs(cw - target) + abs(ch - target)) / max(target, 1.0)
            score = size_err + 4.0 * aspect
            if score < best_score:
                best_score = score
                best = (nr, nc)
    return best


def _maybe_unclip_line(nr: int, nc: int, bw: int, bh: int, x: int, y: int, sw: int, sh: int) -> tuple[int, int]:
    if nr == 1 and nc >= 2:
        exact = bw / max(bh, 1)
        touches_l = x <= 2
        touches_r = x + bw >= sw - 3
        if nc < 5 and exact > nc + 0.2 and (touches_l or touches_r):
            return 1, nc + 1
        if nc < 5 and touches_l and touches_r and exact >= nc - 0.05:
            n = max(nc, min(5, int(round(exact + 0.35))))
            return 1, n
    if nc == 1 and nr >= 2:
        exact = bh / max(bw, 1)
        touches_t = y <= 2
        touches_b = y + bh >= sh - 3
        if nr < 5 and exact > nr + 0.2 and (touches_t or touches_b):
            return nr + 1, 1
        if nr < 5 and touches_t and touches_b and exact >= nr - 0.05:
            n = max(nr, min(5, int(round(exact + 0.35))))
            return n, 1
    return nr, nc


def _cell_centers_from_mask(mask: np.ndarray, core_x: tuple[int, int] | None = None) -> list[tuple[float, float]]:
    if not mask.any():
        return []
    k = max(3, (int(min(mask.shape) * 0.05) | 1))
    closed = cv.morphologyEx(mask.astype(np.uint8), cv.MORPH_CLOSE, np.ones((k, k), np.uint8))
    closed = _largest_component(closed, core_x)
    if not closed.any():
        return []
    x, y, bw, bh = cv.boundingRect(closed)
    if bw < 4 or bh < 4:
        ys, xs = np.where(closed)
        return [(float(ys.mean()), float(xs.mean()))]

    sh, sw = mask.shape[:2]
    # Tray cells on the calibrated 360x800 stream are about 18 px wide.
    target = max(12.0, min(sh, sw) * 0.15)
    nr, nc = _best_cell_grid(bw, bh, target)
    nr, nc = _maybe_unclip_line(nr, nc, bw, bh, x, y, sw, sh)
    pts: list[tuple[float, float]] = []
    for r in range(nr):
        for c in range(nc):
            y1 = int(y + r * bh / nr)
            y2 = int(y + (r + 1) * bh / nr)
            x1 = int(x + c * bw / nc)
            x2 = int(x + (c + 1) * bw / nc)
            cell = closed[y1:y2, x1:x2]
            # Shadows along cell edges can fill >22% of an empty grid cell.
            # Require foreground in its central region as well.
            margin_y, margin_x = cell.shape[0] // 4, cell.shape[1] // 4
            center = cell[margin_y:cell.shape[0]-margin_y, margin_x:cell.shape[1]-margin_x]
            if cell.size and cell.mean() >= 0.22 and center.size and center.mean() >= 0.5:
                pts.append(((y1 + y2) / 2.0, (x1 + x2) / 2.0))
    return pts


def _shape_from_centroids(pts: list[tuple[float, float]]) -> np.ndarray:
    if not pts:
        return np.zeros((0, 0), dtype=np.int8)
    if len(pts) == 1:
        return np.ones((1, 1), dtype=np.int8)
    row_centers = _cluster_1d([p[0] for p in pts])
    col_centers = _cluster_1d([p[1] for p in pts])
    grid = np.zeros((len(row_centers), len(col_centers)), dtype=np.int8)
    for y, x in pts:
        ri = min(range(len(row_centers)), key=lambda i: abs(row_centers[i] - y))
        ci = min(range(len(col_centers)), key=lambda i: abs(col_centers[i] - x))
        grid[ri, ci] = 1
    return _trim_piece(grid)


def parse_board(frame: np.ndarray, board_rect: config.Rect | None = None) -> tuple[np.ndarray, np.ndarray]:
    rect = board_rect or config.BOARD_RECT
    crop = _crop_rel(frame, rect)
    n = config.GRID_SIZE
    gh, gw = crop.shape[:2]
    hsv = cv.cvtColor(crop, cv.COLOR_BGR2HSV)
    pad = max(1, min(gh, gw) // n // 6)
    points = np.asarray(_board_sample_points(gh, gw, n))
    offsets = np.arange(-pad, pad + 1)
    ys = points[:, 0, None, None] + offsets[None, :, None]
    xs = points[:, 1, None, None] + offsets[None, None, :]
    samples = np.median(hsv[ys, xs], axis=(1, 2))
    hue, saturation, value = samples.T
    # Pink empty cells can be brighter than the normal occupancy threshold.
    pink = (hue >= 160) & (hue <= 178) & (value >= 120) & (value <= 175)
    if pink.sum() >= 4:
        bg_h, bg_s, bg_v = np.median(samples[pink], axis=0)
        delta_h = np.abs(hue - bg_h)
        occupied = (np.minimum(delta_h, 180 - delta_h) > 8) | (np.abs(saturation - bg_s) > 25) | (np.abs(value - bg_v) > 25)
    else:
        occupied = (value >= config.CELL_V_MIN) | (
            (value >= config.CELL_V_MIN - 25) & (saturation >= config.CELL_S_MIN)
        )
    board = occupied.reshape(n, n).astype(np.int8)
    return board, crop


def parse_piece_slot(slot_bgr: np.ndarray, *, core_x: tuple[int, int] | None = None) -> np.ndarray:
    mask = piece_mask(cv.cvtColor(slot_bgr, cv.COLOR_BGR2HSV))
    return _shape_from_centroids(_cell_centers_from_mask(mask, core_x))


def _slot_core(tray_width: int, slot_index: int, crop_left: int) -> tuple[int, int]:
    slot_width = max(1, tray_width // 3)
    left = slot_index * slot_width
    right = tray_width if slot_index == 2 else left + slot_width
    return left - crop_left, right - crop_left


def pickup_geometry(frame: np.ndarray, piece_index: int, piece: np.ndarray):
    """Pick the center of an occupied cell rather than a possibly empty slot center."""
    tray = _crop_rel(frame, config.PIECES_RECT)
    x1, x2 = _slot_x_ranges(tray.shape[1])[piece_index]
    slot = tray[:, x1:x2]
    mask = piece_mask(cv.cvtColor(slot, cv.COLOR_BGR2HSV))
    points = _cell_centers_from_mask(mask, _slot_core(tray.shape[1], piece_index, x1))
    if not np.array_equal(_shape_from_centroids(points), piece):
        raise RuntimeError("Piece changed before pickup; no drag sent.")
    y, x = min(points, key=lambda point: (point[0], point[1]))
    ox = int(frame.shape[1] * config.PIECES_RECT[0]) + x1
    oy = int(frame.shape[0] * config.PIECES_RECT[1])
    center_x = (min(p[1] for p in points) + max(p[1] for p in points)) / 2
    center_y = (min(p[0] for p in points) + max(p[0] for p in points)) / 2
    return ox + x, oy + y, ox + center_x, oy + center_y


def _slot_x_ranges(tray_w: int) -> list[tuple[int, int]]:
    slot_w = max(1, tray_w // 3)
    pad = max(8, slot_w // 8)
    ranges = []
    for i in range(3):
        x1 = 0 if i == 0 else i * slot_w - pad
        x2 = tray_w if i == 2 else (i + 1) * slot_w + pad
        ranges.append((max(0, x1), min(tray_w, x2)))
    return ranges


def parse_pieces(
    frame: np.ndarray, pieces_rect: config.Rect | None = None
) -> tuple[list[np.ndarray], np.ndarray, list[np.ndarray]]:
    rect = pieces_rect or config.PIECES_RECT
    crop = _crop_rel(frame, rect)
    h, w = crop.shape[:2]
    pieces = []
    piece_crops = []
    for i, (x1, x2) in enumerate(_slot_x_ranges(w)):
        slot = crop[:, x1:x2]
        piece_crops.append(slot)
        pieces.append(parse_piece_slot(slot, core_x=_slot_core(w, i, x1)))
    return pieces, crop, piece_crops


def analyze(
    frame: np.ndarray,
    board_rect: config.Rect | None = None,
    pieces_rect: config.Rect | None = None,
) -> VisionResult:
    board, board_crop = parse_board(frame, board_rect)
    pieces, _, piece_crops = parse_pieces(frame, pieces_rect)
    return VisionResult(board, pieces, board_crop, piece_crops)


def _draw_rect(frame: np.ndarray, rect: config.Rect, color: tuple[int, int, int]):
    h, w = frame.shape[:2]
    x1, y1, x2, y2 = rect
    cv.rectangle(frame, (int(w * x1), int(h * y1)), (int(w * x2), int(h * y2)), color, 2)


def _draw_board_overlay(frame: np.ndarray, board: np.ndarray, board_rect: config.Rect):
    h, w = frame.shape[:2]
    x1, y1, x2, y2 = board_rect
    bx1, by1, bx2, by2 = int(w * x1), int(h * y1), int(w * x2), int(h * y2)
    n = config.GRID_SIZE
    gh, gw = by2 - by1, bx2 - bx1
    pad = max(2, min(gh, gw) // n // 8)
    for i, (cy, cx) in enumerate(_board_sample_points(gh, gw, n)):
        r, c = divmod(i, n)
        color = (0, 0, 255) if board[r, c] else (0, 255, 0)
        cv.circle(frame, (bx1 + cx, by1 + cy), pad, color, -1)


def _piece_label(piece: np.ndarray) -> str:
    if piece.size == 0:
        return "empty"
    rows = ["".join("#" if piece[r, c] else "." for c in range(piece.shape[1])) for r in range(piece.shape[0])]
    return f"{piece.shape[0]}x{piece.shape[1]} " + "/".join(rows)


def _draw_piece_overlay(frame: np.ndarray, result: VisionResult, pieces_rect: config.Rect):
    h, w = frame.shape[:2]
    x1, y1, x2, y2 = pieces_rect
    bx, by = int(w * x1), int(h * y1)
    tray_w = int(w * x2) - bx
    ranges = _slot_x_ranges(tray_w)
    for i, slot in enumerate(result.piece_crops):
        ox = bx + ranges[i][0]
        sh, sw = slot.shape[:2]
        mask = piece_mask(cv.cvtColor(slot, cv.COLOR_BGR2HSV))
        roi = frame[by : by + sh, ox : ox + min(sw, frame.shape[1] - ox)]
        mw = min(mask.shape[1], roi.shape[1])
        mh = min(mask.shape[0], roi.shape[0])
        roi[:mh, :mw][mask[:mh, :mw] > 0] = (0, 0, 220)
        for cy, cx in _cell_centers_from_mask(mask, _slot_core(tray_w, i, ranges[i][0])):
            cv.circle(frame, (ox + int(round(cx)), by + int(round(cy))), 4, (0, 255, 255), -1)


def render_debug(
    frame: np.ndarray,
    result: VisionResult,
    board_rect: config.Rect | None = None,
    pieces_rect: config.Rect | None = None,
    show_piece_grid: bool = False,
) -> np.ndarray:
    board_rect = board_rect or config.BOARD_RECT
    pieces_rect = pieces_rect or config.PIECES_RECT
    out = frame.copy()
    _draw_rect(out, board_rect, (255, 200, 0))
    _draw_rect(out, pieces_rect, (200, 100, 255))
    _draw_board_overlay(out, result.board, board_rect)
    if show_piece_grid:
        _draw_piece_overlay(out, result, pieces_rect)
    h, w = out.shape[:2]
    x1, y1, x2, y2 = pieces_rect
    tray_w = int(w * (x2 - x1))
    slot_w = tray_w // 3
    bx = int(w * x1)
    py = max(20, int(h * y1) - 8)
    for i, piece in enumerate(result.pieces):
        text = f"P{i + 1}: {_piece_label(piece)}"
        cv.putText(out, text, (bx + i * slot_w + 4, py), cv.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1, cv.LINE_AA)
    return out


def format_state(result: VisionResult) -> str:
    lines = ["Board:"]
    for row in result.board:
        lines.append(" ".join("#" if v else "." for v in row))
    lines.append("Pieces:")
    for i, piece in enumerate(result.pieces):
        lines.append(f"  [{i}] {_piece_label(piece)}")
    return "\n".join(lines)
