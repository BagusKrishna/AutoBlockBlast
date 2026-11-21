import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

from autoblockblast.autoplay import check_stop, read_stable, verify_transition, wait_verified
from autoblockblast.controller import Controller, board_cell_xy
from autoblockblast.phone import require_game
from autoblockblast.solver import Placement, apply_move, has_placement, solve
from autoblockblast.vision import _cell_centers_from_mask, _shape_from_centroids


class VerifiedPlayTests(unittest.TestCase):
    def test_prioritizes_multiple_clear_moves(self):
        board = np.zeros((8, 8), dtype=np.int8)
        board[0, :7] = 1
        board[1, :7] = 1
        one = np.ones((1, 1), dtype=np.int8)
        result = solve(board, [one, one, one])
        self.assertTrue(result.complete)
        self.assertGreaterEqual(result.clear_moves, 2)
        self.assertEqual(len(result.placements), 3)

    def test_separated_diagonal_blocks(self):
        for reverse in (False, True):
            mask = np.zeros((120, 100), dtype=np.uint8)
            cells = [(0, 1), (1, 0)] if reverse else [(0, 0), (1, 1)]
            for row, col in cells:
                mask[30 + row * 20:46 + row * 20, 25 + col * 20:41 + col * 20] = 1
            shape = _shape_from_centroids(_cell_centers_from_mask(mask))
            self.assertEqual(shape.tolist(), [[0, 1], [1, 0]] if reverse else [[1, 0], [0, 1]])

    def setUp(self):
        self.board = np.zeros((8, 8), dtype=np.int8)
        self.single = np.ones((1, 1), dtype=np.int8)
        self.empty = np.zeros((0, 0), dtype=np.int8)
        self.before = SimpleNamespace(board=self.board, pieces=[self.single, self.single, self.empty])
        self.placement = Placement(0, 0, 0)
        self.expected, _ = apply_move(self.board, self.single, 0, 0)

    def test_successful_drag(self):
        after = SimpleNamespace(board=self.expected, pieces=[self.empty, self.single, self.empty])
        verify_transition(self.before, after, self.placement)

    def test_missed_drag_stops(self):
        after = SimpleNamespace(board=self.board, pieces=self.before.pieces)
        with self.assertRaisesRegex(RuntimeError, "differs"):
            verify_transition(self.before, after, self.placement)

    def test_piece_remaining_in_tray_stops(self):
        after = SimpleNamespace(board=self.expected, pieces=self.before.pieces)
        with self.assertRaisesRegex(RuntimeError, "still in"):
            verify_transition(self.before, after, self.placement)

    def test_unrelated_tray_change_stops(self):
        after = SimpleNamespace(board=self.expected, pieces=[self.empty, self.empty, self.empty])
        with self.assertRaisesRegex(RuntimeError, "changed unexpectedly"):
            verify_transition(self.before, after, self.placement)

    def test_last_piece_can_refill_tray(self):
        before = SimpleNamespace(board=self.board, pieces=[self.single, self.empty, self.empty])
        after = SimpleNamespace(board=self.expected, pieces=[self.single] * 3)
        verify_transition(before, after, self.placement)

    def test_game_focus_required(self):
        device = Mock()
        device.shell.return_value = "mCurrentFocus=Window{abc u0 com.block.juggle/Game}"
        require_game(device)
        device.shell.return_value = "mCurrentFocus=Window{abc u0 com.android.settings/Settings}"
        with patch("autoblockblast.phone.time.sleep"), self.assertRaisesRegex(RuntimeError, "not in front"):
            require_game(device)

    def test_stop_request_interrupts_before_next_action(self):
        with patch("autoblockblast.autoplay.STOP_FILE") as stop:
            stop.exists.return_value = True
            with self.assertRaises(KeyboardInterrupt):
                check_stop()

    def test_dead_video_is_rejected(self):
        stream = Mock(alive=False)
        with patch("autoblockblast.autoplay.require_game"), patch("autoblockblast.autoplay.check_stop"):
            with self.assertRaisesRegex(RuntimeError, "stream stopped"):
                read_stable(Mock(), stream)
        stream.snapshot.assert_not_called()

    def test_stale_frames_are_not_analyzed(self):
        stream = Mock(alive=True)
        stream.snapshot.return_value = (np.zeros((800, 360, 3), dtype=np.uint8), 0.0)
        with patch("autoblockblast.autoplay.require_game"), patch("autoblockblast.autoplay.check_stop"), patch("autoblockblast.autoplay.analyze") as analyze:
            with self.assertRaisesRegex(RuntimeError, "fresh, stable"):
                read_stable(Mock(), stream, timeout=0.01)
        analyze.assert_not_called()

    def test_temporary_animation_is_rechecked_without_another_drag(self):
        overlay = self.expected.copy()
        overlay[4, 4] = 1
        transient = SimpleNamespace(board=overlay, pieces=[self.empty, self.single, self.empty])
        settled = SimpleNamespace(board=self.expected, pieces=[self.empty, self.single, self.empty])
        with patch("autoblockblast.autoplay.read_stable", side_effect=[(None, transient), (None, settled)]) as read:
            with patch("autoblockblast.autoplay.save_debug"), patch("autoblockblast.autoplay.time.sleep"):
                _, result = wait_verified(Mock(), Mock(), self.before, self.placement, after=0)
        self.assertIs(result, settled)
        self.assertEqual(read.call_count, 2)

    def test_drag_mapping_matches_measured_phone_geometry(self):
        frame_shape = (2400, 1080, 3)
        cases = [
            (np.array([[1, 0, 0], [1, 1, 1]], dtype=np.int8), (488, 1795, 540, 1818)),
            (np.ones((1, 3), dtype=np.int8), (856, 1819, 855, 1818.5)),
        ]
        for piece, geometry in cases:
            controller = Controller(Mock(), 1080, 2400)
            controller.swipe = Mock()
            placement = Placement(0, 4, 3)
            with patch("autoblockblast.controller.pickup_geometry", return_value=geometry), patch("autoblockblast.controller.time.sleep"):
                controller.drag_piece(0, piece, placement, frame_shape, frame=Mock())
            sx, sy, dx, dy = controller.swipe.call_args.args
            expected_x, expected_y = board_cell_xy(
                frame_shape, placement.row + (piece.shape[0] - 1) / 2,
                placement.col + (piece.shape[1] - 1) / 2,
            )
            # Actual gain/lift measured from the two held-piece screenshots.
            actual_x = geometry[2] + 1.5 * (dx - sx)
            actual_y = geometry[3] + 1.5 * (dy - sy) - 270
            self.assertLess(abs(actual_x - expected_x), 2)
            self.assertLess(abs(actual_y - expected_y), 2)

    def test_two_clears_can_unlock_third_piece(self):
        board = np.array([
            [1, 1, 1, 1, 1, 1, 1, 0],
            [1, 1, 1, 1, 1, 1, 1, 0],
            [0, 0, 0, 1, 1, 1, 1, 1],
            [1, 0, 1, 0, 1, 0, 1, 0],
            [0, 1, 0, 1, 0, 1, 0, 1],
            [1, 0, 1, 0, 1, 0, 1, 0],
            [0, 1, 0, 1, 0, 1, 0, 1],
            [1, 0, 1, 0, 1, 0, 1, 0],
        ], dtype=np.int8)
        square = np.ones((3, 3), dtype=np.int8)
        self.assertFalse(has_placement(board, square))
        result = solve(board, [self.single, self.single, square])
        self.assertIsNotNone(result)
        self.assertEqual(len(result.placements), 3)
        self.assertGreaterEqual(result.lines_cleared, 2)


if __name__ == "__main__":
    unittest.main()
