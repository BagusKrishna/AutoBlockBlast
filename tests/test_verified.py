import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

from autoblockblast.autoplay import StableReadTimeout, check_stop, wait_if_paused, read_stable, run, verify_transition, wait_verified
from autoblockblast.controller import Controller, board_cell_xy
from autoblockblast.phone import require_game
from autoblockblast.solver import Placement, apply_move, has_placement, solve, solve_exact
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

    def test_metrics_wait_until_first_move(self):
        from autoblockblast import autoplay
        frame = np.zeros((800, 360, 3), dtype=np.uint8)
        with patch.object(autoplay, "UI_METRICS", True), patch.object(
            autoplay, "_metrics_ready", False
        ), patch("autoblockblast.autoplay.cv.imencode") as encode:
            autoplay.emit_metrics_frame(frame)
            encode.assert_not_called()

    def test_mid_tray_new_piece_in_empty_slot_stops(self):
        after = SimpleNamespace(board=self.expected, pieces=[self.empty, self.single, self.single])
        with self.assertRaisesRegex(RuntimeError, "changed unexpectedly"):
            verify_transition(self.before, after, self.placement)

    def test_last_piece_partial_refill_waits(self):
        before = SimpleNamespace(board=self.board, pieces=[self.single, self.empty, self.empty])
        after = SimpleNamespace(board=self.expected, pieces=[self.single, self.single, self.empty])
        with self.assertRaisesRegex(RuntimeError, "refill"):
            verify_transition(before, after, self.placement)

    def test_drag_uses_revalidated_frame(self):
        old_frame = np.zeros((800, 360, 3), dtype=np.uint8)
        new_frame = old_frame.copy()
        new_frame[600, 100] = 1
        plan = SimpleNamespace(complete=True, placements=[self.placement])
        with patch.multiple(
            "autoblockblast.autoplay",
            get_device=Mock(), require_game=Mock(), physical_size=Mock(return_value=(1080, 2400)),
            Controller=Mock(), ScrcpyStream=Mock(), check_stop=Mock(), save_debug=Mock(),
            solve_exact=Mock(return_value=plan), format_solution=Mock(), wait_verified=Mock(return_value=(None, SimpleNamespace(board=self.expected), 3)),
            read_stable=Mock(side_effect=[(old_frame, self.before, 1), (new_frame, self.before, 2)]),
        ):
            from autoblockblast import autoplay
            run(execute=True, moves=1)
            drag = autoplay.Controller.return_value.drag_piece
            self.assertTrue(drag.call_args.kwargs["frame"] is new_frame)

    def test_quick_recheck_falls_back_if_new_frame_has_different_board(self):
        from autoblockblast import autoplay
        frame = np.zeros((80, 36, 3), dtype=np.uint8)
        stream = Mock(alive=True)
        stream.snapshot.return_value = (frame, 10.1)
        changed = SimpleNamespace(board=self.expected, pieces=self.before.pieces)
        stable = (frame, self.before, 10.5)
        with patch.multiple(
            "autoblockblast.autoplay", require_game=Mock(), check_stop=Mock(),
            analyze=Mock(return_value=changed), read_stable=Mock(return_value=stable),
        ), patch("autoblockblast.autoplay.time.monotonic", return_value=10.2):
            result, fast = autoplay.recheck_latest(Mock(), stream, self.before, 10.0)
            self.assertIs(result, stable)
            self.assertFalse(fast)
            autoplay.read_stable.assert_called_once_with(unittest.mock.ANY, stream, after=10.0)

    def test_pre_drag_recovers_only_when_planned_board_and_tray_return(self):
        from autoblockblast import autoplay
        frame = np.zeros((80, 36, 3), dtype=np.uint8)
        obscured = SimpleNamespace(board=self.expected, pieces=self.before.pieces)
        observed = (frame, self.before, 10.5)
        with patch.object(autoplay, "read_stable", side_effect=[(frame, obscured, 10.2), observed]) as read:
            actual = autoplay.wait_for_planned_state(Mock(), Mock(), self.before, after=10.0)
        self.assertIs(actual, observed)
        self.assertEqual([call.kwargs["after"] for call in read.call_args_list], [10.0, 10.2])

    def test_pre_drag_stops_if_planned_board_does_not_return(self):
        from autoblockblast import autoplay
        with patch.object(autoplay, "read_stable", side_effect=StableReadTimeout("timeout")):
            with self.assertRaisesRegex(RuntimeError, "board or tray still differs"):
                autoplay.wait_for_planned_state(Mock(), Mock(), self.before, after=10.0)

    def test_replans_from_fresh_state_before_any_swipe(self):
        from autoblockblast import autoplay
        frame = np.zeros((80, 36, 3), dtype=np.uint8)
        changed = SimpleNamespace(board=self.expected, pieces=self.before.pieces)
        old_plan = solve_exact(self.board, self.before.pieces)
        new_plan = solve_exact(changed.board, changed.pieces)
        new_move = new_plan.placements[0]
        placed, _ = apply_move(changed.board, changed.pieces[new_move.piece_index], new_move.row, new_move.col)
        after = SimpleNamespace(board=placed)

        for initial_plan in (old_plan, None):
            with self.subTest(has_initial_plan=initial_plan is not None):
                observations = [(frame, self.before, 1), (frame, changed, 2), (frame, changed, 3)]
                if initial_plan is not None:
                    observations.append((frame, changed, 4))
                with patch.multiple(
                    "autoblockblast.autoplay", get_device=Mock(), require_game=Mock(),
                    physical_size=Mock(return_value=(1080, 2400)), Controller=Mock(),
                    ScrcpyStream=Mock(), check_stop=Mock(), wait_if_paused=Mock(return_value=False),
                    solve_exact=Mock(side_effect=[initial_plan, new_plan]),
                    read_stable=Mock(side_effect=observations),
                    wait_verified=Mock(return_value=(frame, after, 5)),
                ):
                    run(execute=True, moves=1)
                    self.assertIs(autoplay.solve_exact.call_args.args[0], changed.board)
                    drag = autoplay.Controller.return_value.drag_piece
                    drag.assert_called_once()
                    self.assertEqual(drag.call_args.args[2], new_move)
                    autoplay.wait_verified.assert_called_once()

    def test_chain_uses_verified_frame_while_fresh_and_rejects_changed_board(self):
        from autoblockblast import autoplay
        frame = np.zeros((800, 360, 3), dtype=np.uint8)
        changed = frame.copy()
        changed[300:320, 100:120] = 255
        stream = Mock(alive=True)
        verified = (frame, self.before, 10.0)
        with patch("autoblockblast.autoplay.time.monotonic", return_value=10.1):
            stream.snapshot.return_value = (None, 10.0)
            self.assertIs(autoplay.reuse_verified_frame(stream, verified), verified)
            stream.snapshot.return_value = (changed, 10.05)
            changed_state = SimpleNamespace(board=self.expected, pieces=self.before.pieces)
            with patch.object(autoplay, "analyze", return_value=changed_state):
                self.assertIsNone(autoplay.reuse_verified_frame(stream, verified))
            with patch.object(autoplay, "analyze", return_value=self.before):
                self.assertEqual(autoplay.reuse_verified_frame(stream, verified)[2], 10.05)
        with patch("autoblockblast.autoplay.time.monotonic", return_value=10.3):
            self.assertIsNone(autoplay.reuse_verified_frame(stream, verified))

    def test_reuses_remaining_exact_plan_after_successful_verification(self):
        from autoblockblast import autoplay
        frame = np.zeros((80, 36, 3), dtype=np.uint8)
        next_state = SimpleNamespace(board=self.expected, pieces=[self.empty, self.single, self.empty])
        plan = solve_exact(self.board, self.before.pieces)
        first, second = plan.placements
        next_state.board, _ = apply_move(self.board, self.before.pieces[first.piece_index], first.row, first.col)
        next_state.pieces = self.before.pieces.copy()
        next_state.pieces[first.piece_index] = self.empty
        with patch.multiple(
            "autoblockblast.autoplay", get_device=Mock(), require_game=Mock(),
            physical_size=Mock(return_value=(1080, 2400)), Controller=Mock(),
            ScrcpyStream=Mock(), check_stop=Mock(), wait_if_paused=Mock(return_value=False),
            solve_exact=Mock(return_value=plan), wait_verified=Mock(return_value=(frame, next_state, 3)),
            read_stable=Mock(side_effect=[(frame, self.before, 1), (frame, self.before, 2),
                                          (frame, next_state, 4)]),
        ):
            run(execute=True, moves=2, reuse_plan=True)
            autoplay.solve_exact.assert_called_once()
            calls = autoplay.Controller.return_value.drag_piece.call_args_list
            self.assertEqual([call.args[2] for call in calls], [first, second])

    def test_unchanged_board_allows_one_slower_retry_with_fresh_pickup(self):
        from autoblockblast import autoplay
        original_frame = np.zeros((80, 36, 3), dtype=np.uint8)
        retry_frame = original_frame.copy()
        after = SimpleNamespace(board=self.expected, pieces=[self.empty, self.single, self.empty])
        plan = SimpleNamespace(complete=True, placements=[self.placement])
        unchanged = autoplay.SwipeDidNotLand(4.0)
        with patch.multiple(
            "autoblockblast.autoplay", get_device=Mock(), require_game=Mock(),
            physical_size=Mock(return_value=(1080, 2400)), Controller=Mock(),
            ScrcpyStream=Mock(), check_stop=Mock(), wait_if_paused=Mock(return_value=False),
            solve_exact=Mock(return_value=plan), format_solution=Mock(),
            read_stable=Mock(side_effect=[(original_frame, self.before, 1), (original_frame, self.before, 2)]),
            wait_verified=Mock(side_effect=[unchanged, (retry_frame, after, 7)]),
            wait_for_planned_state=Mock(return_value=(retry_frame, self.before, 5)),
        ):
            autoplay.Controller.return_value.drag_piece.side_effect = [3.0, 6.0]
            run(execute=True, moves=1)
            first, retry = autoplay.Controller.return_value.drag_piece.call_args_list
            self.assertIsNone(first.kwargs["duration_ms"])
            self.assertEqual(retry.kwargs["duration_ms"], 250)
            self.assertEqual(retry.args[2], self.placement)
            self.assertIs(retry.kwargs["frame"], retry_frame)
            self.assertEqual(autoplay.wait_for_planned_state.call_args.kwargs["after"], 4.0)
            self.assertEqual(autoplay.wait_verified.call_args.kwargs["after"], 6.0)

    def test_last_piece_can_refill_tray(self):
        before = SimpleNamespace(board=self.board, pieces=[self.single, self.empty, self.empty])
        after = SimpleNamespace(board=self.expected, pieces=[self.single] * 3)
        verify_transition(before, after, self.placement)

    def test_game_focus_required(self):
        device = Mock()
        game = "FocusedDisplayId: 0\n    displayId=0, name='8adb8e0 com.block.juggle/Game'"
        device.shell2.return_value = SimpleNamespace(returncode=0, output=game)
        require_game(device)
        command = device.shell2.call_args.args[0]
        self.assertIn("dumpsys -t 1 input", command)
        self.assertNotIn("dumpsys window", command)
        for denied in (
            game.replace("com.block.juggle", "com.android.settings"),
            game.replace("com.block.juggle", "com.block.juggle.fake"),
            game.replace("FocusedDisplayId: 0", "FocusedDisplayId: 2"),
            "FocusedDisplayId: 0",
        ):
            with self.subTest(output=denied):
                device.shell2.return_value = SimpleNamespace(returncode=0, output=denied)
                with patch("autoblockblast.phone.time.sleep"), self.assertRaisesRegex(RuntimeError, "not in front"):
                    require_game(device)
        device.shell2.return_value = SimpleNamespace(returncode=1, output=game)
        with self.assertRaisesRegex(RuntimeError, "input focus unavailable"):
            require_game(device)

    def test_stop_request_interrupts_before_next_action(self):
        with patch("autoblockblast.autoplay.STOP_FILE") as stop:
            stop.exists.return_value = True
            with self.assertRaises(KeyboardInterrupt):
                check_stop()

    def test_pause_waits_then_resumes(self):
        with patch("autoblockblast.autoplay.PAUSE_FILE") as pause, patch(
            "autoblockblast.autoplay.check_stop"
        ) as stop, patch("autoblockblast.autoplay.time.sleep"):
            pause.exists.side_effect = [True, True, False]
            wait_if_paused()
            stop.assert_called_once()

    def test_stop_interrupts_paused_session(self):
        with patch("autoblockblast.autoplay.PAUSE_FILE") as pause, patch(
            "autoblockblast.autoplay.check_stop", side_effect=KeyboardInterrupt
        ):
            pause.exists.return_value = True
            with self.assertRaises(KeyboardInterrupt):
                wait_if_paused()

    def test_dead_video_is_rejected(self):
        stream = Mock(alive=False)
        with patch("autoblockblast.autoplay.require_game"), patch("autoblockblast.autoplay.check_stop"):
            with self.assertRaisesRegex(RuntimeError, "stream stopped"):
                read_stable(Mock(), stream)
        stream.snapshot.assert_not_called()

    def test_stale_frames_are_not_analyzed(self):
        stream = Mock(alive=True)
        stream.snapshot.return_value = (np.zeros((800, 360, 3), dtype=np.uint8), 0.0)
        with patch("autoblockblast.autoplay.require_game") as focus, patch("autoblockblast.autoplay.check_stop"), patch("autoblockblast.autoplay.analyze") as analyze:
            with self.assertRaisesRegex(RuntimeError, "fresh, stable"):
                read_stable(Mock(), stream, timeout=0.01)
        focus.assert_called_once()
        analyze.assert_not_called()

    def test_invalid_animation_frame_cannot_satisfy_stability(self):
        stream = Mock(alive=True)
        frame = np.zeros((80, 36, 3), dtype=np.uint8)
        invalid = SimpleNamespace(board=self.board, pieces=[np.ones((3, 4))] * 3)
        stream.snapshot.side_effect = [(frame, stamp) for stamp in (10.1, 10.3, 10.4, 10.6)]
        with patch.multiple("autoblockblast.autoplay", require_game=Mock(), check_stop=Mock(),
                            analyze=Mock(side_effect=[self.before, invalid, self.before, self.before])), patch(
            "autoblockblast.autoplay.time.monotonic", return_value=10.8
        ), patch("autoblockblast.autoplay.time.sleep"):
            _, state, stamp = read_stable(Mock(), stream)
        self.assertIs(state, self.before)
        self.assertEqual(stamp, 10.6)

    def test_early_clear_waits_for_matching_post_drag_board_and_tray(self):
        board = self.board.copy()
        board[0, 1:] = 1
        before = SimpleNamespace(board=board, pieces=self.before.pieces)
        expected = SimpleNamespace(board=self.board, pieces=[self.empty, self.single, self.empty])
        frame = np.zeros((80, 36, 3), dtype=np.uint8)
        stream = Mock(alive=True)
        stream.snapshot.side_effect = [(frame, 10.0), (frame, 10.1), (frame, 10.15), (frame, 10.18)]
        with patch.multiple("autoblockblast.autoplay", require_game=Mock(), check_stop=Mock(),
                            analyze=Mock(side_effect=[before, expected, expected])), patch(
            "autoblockblast.autoplay.time.monotonic", return_value=10.2
        ), patch("autoblockblast.autoplay.time.sleep"):
            _, state, stamp = wait_verified(
                Mock(), stream, before, self.placement, after=10.0, early_clear=True
            )
        self.assertIs(state, expected)
        self.assertEqual(stamp, 10.18)

    def test_early_clear_keeps_full_stability_check_for_refill(self):
        board = self.board.copy()
        board[0, 1:] = 1
        before = SimpleNamespace(board=board, pieces=[self.single, self.empty, self.empty])
        after = SimpleNamespace(board=self.board, pieces=[self.single] * 3)
        with patch("autoblockblast.autoplay.read_stable", return_value=(None, after, 11.0)) as read:
            wait_verified(Mock(), Mock(), before, self.placement, after=10.0, early_clear=True)
        self.assertNotIn("expected_key", read.call_args.kwargs)

    def test_temporary_animation_is_rechecked_without_another_drag(self):
        overlay = self.expected.copy()
        overlay[4, 4] = 1
        transient = SimpleNamespace(board=overlay, pieces=[self.empty, self.single, self.empty])
        settled = SimpleNamespace(board=self.expected, pieces=[self.empty, self.single, self.empty])
        with patch("autoblockblast.autoplay.read_stable", side_effect=[(None, transient, 1), (None, settled, 2)]) as read:
            with patch("autoblockblast.autoplay.save_debug"), patch("autoblockblast.autoplay.time.sleep"):
                _, result, _ = wait_verified(Mock(), Mock(), self.before, self.placement, after=0)
        self.assertIs(result, settled)
        self.assertEqual(read.call_count, 2)

    def test_verification_keeps_last_disagreement_when_next_read_times_out(self):
        frame = np.zeros((64, 32, 3), dtype=np.uint8)
        with TemporaryDirectory() as root:
            with patch("autoblockblast.autoplay.ROOT", Path(root)), patch(
                "autoblockblast.autoplay.require_game"
            ), patch(
                "autoblockblast.autoplay.read_stable",
                side_effect=[(frame, self.before, 2), StableReadTimeout("read timeout")],
            ) as read:
                with self.assertRaisesRegex(RuntimeError, "Swipe did not land"):
                    wait_verified(Mock(), Mock(), self.before, self.placement,
                                  after=1, before_frame=frame, before_at=0.5)
            bundle = Path(root) / "captures" / "last-failure"
            report = json.loads((bundle / "transition.json").read_text())
            self.assertEqual(report["observed"]["received_at"], 2)
            self.assertEqual(report["expected_board"], self.expected.tolist())
            self.assertTrue((bundle / "before-raw.png").is_file())
            self.assertTrue((bundle / "after-raw.png").is_file())
            self.assertEqual(read.call_args.kwargs["after"], 2)

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
