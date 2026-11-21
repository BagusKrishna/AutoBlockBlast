"""Regression checks against manually inspected Block Blast screenshots."""
from pathlib import Path
import unittest

import cv2 as cv

from autoblockblast.vision import analyze

FIXTURES = Path(__file__).parent / "fixtures"


class ScreenFixtures(unittest.TestCase):
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
