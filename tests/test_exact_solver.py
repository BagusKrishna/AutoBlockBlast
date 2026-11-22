import unittest

import numpy as np

from autoblockblast.solver import (
    KEY_SHAPES, Placement, apply_move, count_placements, iter_placements, solve_exact,
)


def oracle(board, pieces, earned=False):
    """Enumerate with NumPy collision and clear routines, without state merging."""
    rank, best = None, None

    def visit(state, slots, path, all_clear, clear_weight, clear_moves, lines):
        nonlocal rank, best
        if not slots:
            counts = [count_placements(state, shape, 6) for shape in KEY_SHAPES]
            flexibility = sum(count + 5 * bool(count) for count in counts)
            candidate = (all_clear, clear_weight, lines, clear_moves, flexibility, -int(state.sum()))
            if rank is None or candidate > rank:
                rank, best = candidate, path
            return
        for slot in slots:
            for row, col in iter_placements(state, pieces[slot]):
                next_board, cleared = apply_move(state, pieces[slot], row, col)
                visit(next_board, [i for i in slots if i != slot],
                      path + [Placement(slot, row, col)], all_clear or not next_board.any(),
                      clear_weight + cleared**2, clear_moves + bool(cleared), lines + cleared)

    visit(board, [i for i, piece in enumerate(pieces) if piece.size], [], earned, 0, 0, 0)
    return rank, best


class ExactSolverTests(unittest.TestCase):
    def test_intermediate_all_clear_and_crossing_lines(self):
        board = np.zeros((8, 8), dtype=np.int8)
        board[2, :] = 1
        board[:, 3] = 1
        board[2, 3] = 0
        single = np.ones((1, 1), dtype=np.int8)
        bar = np.ones((1, 5), dtype=np.int8)
        result = solve_exact(board, [single, bar])
        self.assertEqual(result.placements[0], Placement(0, 2, 3))
        self.assertTrue(result.all_clear)
        self.assertEqual(result.lines_cleared, 2)
        self.assertEqual(result.final_board.sum(), 5)

    def test_empty_board_does_not_count_as_all_clear(self):
        board = np.zeros((8, 8), dtype=np.int8)
        single = np.ones((1, 1), dtype=np.int8)
        self.assertFalse(solve_exact(board, [single] * 3).all_clear)
        self.assertTrue(solve_exact(board, [single], all_clear_earned=True).all_clear)

    def test_concentrates_three_clears_in_one_placement(self):
        board = np.zeros((8, 8), dtype=np.int8)
        board[:3, :] = 1
        board[:3, 3] = 0
        board[7, 7] = 1
        pieces = [np.ones((1, 1), dtype=np.int8)] * 2 + [np.ones((3, 1), dtype=np.int8)]
        plan = solve_exact(board, pieces)
        self.assertFalse(plan.all_clear)
        clears = []
        for move in plan.placements:
            board, count = apply_move(board, pieces[move.piece_index], move.row, move.col)
            clears.append(count)
        self.assertEqual(clears, [0, 0, 3])

    def test_matches_exhaustive_numpy_oracle(self):
        rng = np.random.default_rng(6)
        pieces = [
            np.array([[1, 0], [0, 1]], dtype=np.int8),
            np.ones((1, 2), dtype=np.int8),
            np.ones((1, 2), dtype=np.int8),
        ]
        for case in range(6):
            with self.subTest(case=case):
                board = (rng.random((8, 8)) < 0.76).astype(np.int8)
                # Start from an already settled board.
                for row in np.flatnonzero(np.all(board, axis=1)):
                    board[row, (row + 3) % 8] = 0
                for col in np.flatnonzero(np.all(board, axis=0)):
                    board[(col + 5) % 8, col] = 0
                rank, path = oracle(board, pieces)
                result = solve_exact(board, pieces)
                if rank is None:
                    self.assertIsNone(result)
                else:
                    self.assertEqual(result.placements, path)
                    self.assertEqual(
                        (result.all_clear, result.clear_moves, result.lines_cleared, result.score),
                        (rank[0], rank[3], rank[2], rank[4]),
                    )

    def test_no_complete_sequence(self):
        board = np.indices((8, 8)).sum(axis=0).astype(np.int8) % 2
        self.assertIsNone(solve_exact(board, [np.ones((2, 2), dtype=np.int8)]))
