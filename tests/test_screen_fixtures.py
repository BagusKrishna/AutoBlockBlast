"""Regression checks against manually inspected Block Blast screenshots."""
from pathlib import Path
import unittest

import cv2 as cv
import numpy as np

from autoblockblast.vision import analyze, parse_pieces, pickup_geometry

FIXTURES = Path(__file__).parent / "fixtures"


class ScreenFixtures(unittest.TestCase):
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
