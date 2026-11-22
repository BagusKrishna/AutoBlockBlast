"""Regression checks against manually inspected Block Blast screenshots."""
from pathlib import Path
import unittest

import cv2 as cv
import numpy as np

from autoblockblast.vision import analyze, parse_board, parse_piece_slot, parse_pieces, pickup_geometry

FIXTURES = Path(__file__).parent / "fixtures"


class ScreenFixtures(unittest.TestCase):
    def test_gray_board_ignores_hue_noise_but_detects_blocks(self):
        cells = np.resize(np.array([(100, 16, 33), (120, 15, 34), (0, 0, 32)]), (8, 8, 3))
        cells[2, 3] = (120, 15, 100)
        cells[6, 5] = (30, 180, 34)
        hsv = cells.repeat(40, axis=0).repeat(40, axis=1).astype(np.uint8)
        frame = cv.cvtColor(hsv, cv.COLOR_HSV2BGR)
        expected = np.zeros((8, 8), dtype=np.int8)
        expected[2, 3] = expected[6, 5] = 1

        board, _ = parse_board(frame, board_rect=(0, 0, 1, 1))

        np.testing.assert_array_equal(board, expected)

    def test_gray_tray_preserves_shape_and_rejects_near_black_frames(self):
        hsv = np.full((120, 130, 3), (0, 0, 62), dtype=np.uint8)
        hsv[25:97, 49:89] = (100, 20, 66)
        hsv[34:52, 51:87] = (80, 180, 232)
        hsv[52:88, 69:87] = (80, 180, 232)
        slot = cv.cvtColor(hsv, cv.COLOR_HSV2BGR)
        self.assertEqual(parse_piece_slot(slot).tolist(), [[1, 1], [0, 1], [0, 1]])

        dim_slot = np.round(slot * 0.1).astype(np.uint8)
        self.assertFalse(parse_piece_slot(dim_slot).size)

    def test_orange_board_with_colored_edges_keeps_empty_cells(self):
        rows = [
            "###...##", "..##..##", "....####", "..#.####",
            "..##.###", ".#....#.", "####...#", "#.###.##",
        ]
        board = np.array([[cell == "#" for cell in row] for row in rows])
        cells = np.where(board[..., None], (112, 216, 182), (9, 188, 69))
        hsv = cells.repeat(40, axis=0).repeat(40, axis=1).astype(np.uint8)
        hsv[:5] = (11, 180, 69)
        hsv[-5:] = (60, 214, 100)
        hsv[:, :5] = (8, 205, 66)
        hsv[:, -5:] = (112, 216, 182)

        frame = cv.cvtColor(hsv, cv.COLOR_HSV2BGR)
        actual, _ = parse_board(frame, board_rect=(0, 0, 1, 1))

        np.testing.assert_array_equal(actual, board)

    def test_long_bar_does_not_bleed_into_empty_middle_slot(self):
        for x, slot in ((31, 0), (238, 2)):
            with self.subTest(slot=slot):
                frame = np.full((800, 360, 3), (174, 150, 235), dtype=np.uint8)
                for col in range(5):
                    start = x + 18 * col
                    frame[597:615, start:start + 17] = (240, 210, 190)
                pieces, _, _ = parse_pieces(frame)
                expected = [[], [], []]
                expected[slot] = [[1, 1, 1, 1, 1]]
                self.assertEqual([piece.tolist() for piece in pieces], expected)
                pickup_geometry(frame, slot, pieces[slot])

    def test_known_boards_and_pieces(self):
        cases = {
            "pink-five-blocks.png": (
                [".......#", "...##..#", "...###..", ".#.#####", "####....", ".###.###", ".##...#.", "..#....."],
                [[[1] * 5], [[1]] * 5, [[1, 1, 1], [0, 0, 1], [0, 0, 1]]],
            ),
            "blue-start.png": (["........"] * 8, [[[1, 1, 1]], [[1, 0, 0], [1, 1, 1]], [[1, 1, 1]]]),
            "pink-l-shape.png": (
                [".......#", ".......#", "..##..##", "..#.....", "###.....", "..#.....", "###.....", "###....."],
                [[], [], [[0, 0, 1], [0, 0, 1], [1, 1, 1]]],
            ),
            "pink-staggered.png": (
                ["...##...", ".......#", ".#......", "####....", "####....", "........", "....#..#", ".#..#..#"],
                [[], [], [[1, 1, 0], [0, 1, 1]]],
            ),
            "orange-three-blocks.png": (
                ["........", ".....###", "........", "........", "........", "........", "........", "........"],
                [[], [[1, 1, 1, 1, 1]], [[1, 1], [1, 1]]],
            ),
            "orange-red-piece.png": (
                ["........", "........", "........", "##......", "##......", ".#......", ".#......", "#......."],
                [[], [], [[1, 1, 1], [1, 1, 1]]],
            ),
        }
        for name, (rows, pieces) in cases.items():
            with self.subTest(name=name):
                frame = cv.resize(cv.imread(str(FIXTURES / name)), (360, 800))
                result = analyze(frame)
                actual_rows = ["".join("#" if cell else "." for cell in row) for row in result.board]
                self.assertEqual(actual_rows, rows)
                self.assertEqual([piece.tolist() for piece in result.pieces], pieces)


if __name__ == "__main__":
    unittest.main()
