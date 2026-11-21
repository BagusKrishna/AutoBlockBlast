from dataclasses import dataclass
from itertools import permutations

import numpy as np


@dataclass(frozen=True)
class Placement:
    piece_index: int
    row: int
    col: int


@dataclass
class SolveResult:
    placements: list[Placement]
    score: float
    final_board: np.ndarray
    lines_cleared: int
    clear_moves: int = 0
    complete: bool = True


def _shape(*rows: str) -> np.ndarray:
    return np.array([[1 if ch == "#" else 0 for ch in row] for row in rows], dtype=np.int8)


KEY_SHAPES = [
    _shape("#"),
    _shape("##"),
    _shape("###"),
    _shape("####"),
    _shape("#####"),
    _shape("#", "#"),
    _shape("#", "#", "#"),
    _shape("#", "#", "#", "#"),
    _shape("##", "##"),
    _shape("###", "###"),
    _shape("##", "#."),
    _shape("#.", "##"),
    _shape("###", "#.."),
    _shape("#..", "###"),
]


def place(board: np.ndarray, piece: np.ndarray, row: int, col: int) -> np.ndarray:
    out = board.copy()
    ph, pw = piece.shape
    region = out[row : row + ph, col : col + pw]
    out[row : row + ph, col : col + pw] = np.where(piece, 1, region)
    return out


def clear_lines(board: np.ndarray) -> tuple[np.ndarray, int]:
    full_rows = np.all(board, axis=1)
    full_cols = np.all(board, axis=0)
    cleared = int(full_rows.sum() + full_cols.sum())
    if not cleared:
        return board, 0
    out = board.copy()
    out[full_rows, :] = 0
    out[:, full_cols] = 0
    return out, cleared


def apply_move(board: np.ndarray, piece: np.ndarray, row: int, col: int) -> tuple[np.ndarray, int]:
    return clear_lines(place(board, piece, row, col))


def iter_placements(board: np.ndarray, piece: np.ndarray):
    if piece.size == 0:
        return
    n = board.shape[0]
    ph, pw = piece.shape
    for r in range(n - ph + 1):
        region_rows = board[r : r + ph]
        for c in range(n - pw + 1):
            if not np.any(piece & region_rows[:, c : c + pw]):
                yield r, c


def has_placement(board: np.ndarray, piece: np.ndarray) -> bool:
    for _ in iter_placements(board, piece):
        return True
    return False


def count_placements(board: np.ndarray, piece: np.ndarray, limit: int = 8) -> int:
    n = 0
    for _ in iter_placements(board, piece):
        n += 1
        if n >= limit:
            break
    return n


def _isolated_empties(board: np.ndarray) -> int:
    empty = board == 0
    up = np.ones_like(board, dtype=bool)
    down = np.ones_like(board, dtype=bool)
    left = np.ones_like(board, dtype=bool)
    right = np.ones_like(board, dtype=bool)
    up[1:] = board[:-1] == 1
    down[:-1] = board[1:] == 1
    left[:, 1:] = board[:, :-1] == 1
    right[:, :-1] = board[:, 1:] == 1
    up[0] = True
    down[-1] = True
    left[:, 0] = True
    right[:, -1] = True
    return int(np.sum(empty & up & down & left & right))


def _flexibility(board: np.ndarray) -> float:
    total = 0.0
    distinct = 0
    for shape in KEY_SHAPES:
        n = count_placements(board, shape, 6)
        if n:
            distinct += 1
            total += n
    return total + distinct * 5.0


def _near_full_penalty(board: np.ndarray) -> float:
    penalty = 0.0
    for fills in (board.sum(axis=0), board.sum(axis=1)):
        for filled in fills:
            f = int(filled)
            if 5 <= f <= 7:
                penalty += (8 - f) * 4.0
    return penalty


def _contact(board: np.ndarray, piece: np.ndarray, row: int, col: int) -> int:
    n = board.shape[0]
    ph, pw = piece.shape
    touches = 0
    for r in range(ph):
        for c in range(pw):
            if not piece[r, c]:
                continue
            br, bc = row + r, col + c
            for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                rr, cc = br + dr, bc + dc
                if rr < 0 or cc < 0 or rr >= n or cc >= n or board[rr, cc]:
                    touches += 1
    return touches


def score_board(board: np.ndarray, lines: int, pieces_left: int) -> float:
    filled = int(board.sum())
    empty = board.size - filled
    return (
        -pieces_left * 8000.0
        + _flexibility(board) * 5.0
        + empty * 2.5
        - filled * 1.0
        - _isolated_empties(board) * 40.0
        - _near_full_penalty(board)
        + lines * 15.0
    )


def _partial_score(board: np.ndarray, lines: int, remaining: list[np.ndarray], contact: int) -> float:
    # A later piece may become playable after the next piece clears a line.
    # Only the immediately next piece must fit for this fixed permutation.
    if remaining and not has_placement(board, remaining[0]):
        return -1e9
    filled = int(board.sum())
    return (
        -len(remaining) * 8000.0
        + (board.size - filled) * 3.5
        - filled * 1.5
        - _isolated_empties(board) * 50.0
        - _near_full_penalty(board)
        + lines * 10.0
        + contact * 2.0
    )


def solve(board: np.ndarray, pieces: list[np.ndarray], beam: int = 40) -> SolveResult | None:
    board = board.astype(np.int8)
    active = [(i, p.astype(np.int8)) for i, p in enumerate(pieces) if p.size > 0]
    if not active:
        return None

    best: SolveResult | None = None
    finals: list[tuple[np.ndarray, list[Placement], int, int]] = []

    for order in permutations(active):
        states = [(0.0, board.copy(), [], 0, 0)]
        failed = False
        for step, (pi, piece) in enumerate(order):
            nxt = []
            remaining_after = [p for _, p in order[step + 1 :]]
            for _, state, path, lines_total, clear_moves in states:
                for r, c in iter_placements(state, piece):
                    nb, cleared = apply_move(state, piece, r, c)
                    sc = _partial_score(nb, lines_total + cleared, remaining_after, _contact(state, piece, r, c))
                    if sc <= -1e8:
                        continue
                    nxt.append((sc, nb, path + [Placement(pi, r, c)], lines_total + cleared, clear_moves + int(cleared > 0)))
            if not nxt:
                for _, state, path, lines_total, clear_moves in states:
                    finals.append((state, path, lines_total, clear_moves))
                failed = True
                break
            nxt.sort(key=lambda t: (t[4], t[3], t[0]), reverse=True)
            states = nxt[:beam]
        if not failed:
            for _, state, path, lines_total, clear_moves in states:
                finals.append((state, path, lines_total, clear_moves))

    best_rank = None
    for state, path, lines_total, clear_moves in finals:
        left = len(active) - len(path)
        sc = score_board(state, lines_total, left)
        rank = (len(path), clear_moves, lines_total, sc)
        if best_rank is None or rank > best_rank:
            best_rank = rank
            best = SolveResult(path, sc, state.copy(), lines_total, clear_moves, left == 0)
    return best


def format_solution(result: SolveResult | None, pieces: list[np.ndarray] | None = None) -> str:
    if result is None:
        return "No solution"
    status = "complete" if result.complete else "partial"
    lines = [f"{status} plan: clear moves={result.clear_moves}, lines={result.lines_cleared}, moves={len(result.placements)}, heuristic={result.score:.1f} (beam search, not game score)"]
    for step, p in enumerate(result.placements, 1):
        shape = ""
        if pieces is not None and 0 <= p.piece_index < len(pieces):
            piece = pieces[p.piece_index]
            if piece.size:
                shape = f" {piece.shape[0]}x{piece.shape[1]}"
        lines.append(f"  {step}. P{p.piece_index + 1}{shape} -> r{p.row} c{p.col}")
    return "\n".join(lines)


def _self_check():
    n = 8
    board = np.zeros((n, n), dtype=np.int8)
    board[0, :7] = 1
    empty = np.zeros((0, 0), dtype=np.int8)
    res = solve(board, [np.ones((1, 1), np.int8), empty, empty])
    assert res is not None and res.lines_cleared >= 1
    assert res.placements[0] == Placement(0, 0, 7)

    res = solve(
        np.zeros((n, n), dtype=np.int8),
        [np.ones((4, 1), np.int8), np.ones((1, 4), np.int8), np.ones((2, 2), np.int8)],
    )
    assert res is not None and len(res.placements) == 3

    cramped = np.ones((n, n), dtype=np.int8)
    cramped[0:3, 0:3] = 0
    res = solve(cramped, [np.ones((3, 3), np.int8), empty, empty])
    assert res is not None and len(res.placements) == 1
    print("solver self-check ok")


if __name__ == "__main__":
    _self_check()
