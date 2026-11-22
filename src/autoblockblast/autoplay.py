"""Verified autoplay for the calibrated Android phone. Ctrl+C stops the session."""

import argparse
import base64
import fcntl
import json
from dataclasses import asdict, replace
from pathlib import Path
import time

import cv2 as cv
import numpy as np

from autoblockblast import config
from autoblockblast.controller import Controller
from autoblockblast.phone import get_device, physical_size, require_game
from autoblockblast.scrcpy_stream import ScrcpyStream
from autoblockblast.solver import apply_move, format_solution, solve, solve_exact
from autoblockblast.vision import analyze, format_state, render_debug, same_board_and_tray

ROOT = Path(__file__).resolve().parents[2]
STOP_FILE = ROOT / "captures" / "stop.request"
PAUSE_FILE = ROOT / "captures" / "pause.request"
UI_METRICS = False
_last_metrics_at = 0.0
_metrics_ready = False


def check_stop():
    if STOP_FILE.exists():
        raise KeyboardInterrupt


def wait_if_paused():
    if not PAUSE_FILE.exists():
        return False
    print("Paused.", flush=True)
    while PAUSE_FILE.exists():
        check_stop()
        time.sleep(0.1)
    print("Resumed.", flush=True)
    return True


def state_key(state):
    return (state.board.tobytes(), tuple((p.shape, p.tobytes()) for p in state.pieces))


class StableReadTimeout(RuntimeError):
    pass


class SwipeDidNotLand(RuntimeError):
    def __init__(self, received_at):
        super().__init__("Stopped: Swipe did not land. The board and tray stayed the same. See captures/last-failure/.")
        self.received_at = received_at


def emit_metrics_frame(frame):
    global _last_metrics_at
    now = time.monotonic()
    if not UI_METRICS or not _metrics_ready or now - _last_metrics_at < 0.5:
        return
    _last_metrics_at = now
    height = frame.shape[0]
    # Combo text can extend to the sides of the screen.
    crop = frame[int(height * 0.08):int(height * 0.64)]
    ok, encoded = cv.imencode(".jpg", crop, [cv.IMWRITE_JPEG_QUALITY, 85])
    if ok:
        print("UI_FRAME " + base64.b64encode(encoded).decode("ascii"), flush=True)


def read_stable(device, stream, *, after=0.0, timeout=8.0, need_pieces=True, expected_key=None):
    deadline = time.monotonic() + timeout
    previous = None
    previous_at = 0.0
    seen_at = after
    saw_valid_state = False
    while time.monotonic() < deadline:
        check_stop()
        require_game(device)
        if not stream.alive:
            raise RuntimeError("Phone video stream stopped. Reconnect and restart the bot.")
        frame, received_at = stream.snapshot(after=seen_at)
        if frame is None or received_at <= seen_at or time.monotonic() - received_at > 2.0:
            time.sleep(0.04)
            continue
        seen_at = received_at
        emit_metrics_frame(frame)
        state = analyze(frame)
        invalid_piece = any(p.size and (max(p.shape) > 5 or p.sum() > 9) for p in state.pieces)
        if invalid_piece or (need_pieces and not any(p.size for p in state.pieces)):
            # Refill and clear animations can temporarily resemble oversized pieces.
            previous = None
            time.sleep(0.04)
            continue
        saw_valid_state = True
        key = state_key(state)
        # An exact post-clear prediction needs a second fresh match, with no fixed gap.
        stable_interval = 0.0 if expected_key is not None and key == expected_key else 0.1
        if key == previous and received_at > previous_at + stable_interval:
            require_game(device)
            return frame, state, received_at
        if key != previous:
            previous, previous_at = key, received_at
        time.sleep(0.04)
    if seen_at == after:
        reason = "No new video frames arrived from the phone."
    elif not saw_valid_state:
        reason = "Video arrived, but the tray could not be read reliably."
    else:
        reason = "Video arrived, but the board and tray did not stay consistent."
    raise StableReadTimeout(f"No fresh, stable game state. {reason}")


def recheck_latest(device, stream, state, state_at):
    """Confirm the stable planning state on a newer frame or fall back to a stable read."""
    check_stop()
    require_game(device)
    if not stream.alive:
        raise RuntimeError("Phone video stream stopped. Reconnect and restart the bot.")
    expected = state_key(state)
    deadline = time.monotonic() + 0.12
    while time.monotonic() < deadline:
        check_stop()
        frame, received_at = stream.snapshot(after=state_at)
        if frame is not None and state_at < received_at and time.monotonic() - received_at <= 0.25:
            current = analyze(frame)
            if state_key(current) == expected:
                return (frame, current, received_at), True
            break
        time.sleep(0.01)
    return read_stable(device, stream, after=state_at), False


def wait_for_planned_state(device, stream, state, *, after, changed_key=None):
    """Wait for the planned state or corroborate a changed pre-drag reading."""
    deadline = time.monotonic() + 2.0
    expected = state_key(state)
    while time.monotonic() < deadline:
        try:
            observed = read_stable(device, stream, after=after,
                                   timeout=max(0.0, deadline - time.monotonic()))
        except StableReadTimeout:
            break
        key = state_key(observed[1])
        if key == expected or key == changed_key:
            return observed
        if changed_key is not None:
            changed_key = key
        after = observed[2]
    raise RuntimeError(
        "Game state changed during planning. The board or tray still differs after waiting. "
        "Check Block Blast before restarting."
    )


def reuse_verified_frame(stream, verified):
    """Use the most recent verified state without waiting for another frame."""
    frame, state, received_at = verified
    if not stream.alive or time.monotonic() - received_at > 0.25:
        return None
    latest, latest_at = stream.snapshot(after=received_at)
    if latest is None:
        return verified
    if time.monotonic() - latest_at > 0.25:
        return None
    if same_board_and_tray(frame, latest):
        return latest, state, latest_at
    current = analyze(latest)
    if state_key(current) == state_key(state):
        return latest, current, latest_at
    return None


def verify_transition(before, after, placement):
    expected, _ = apply_move(
        before.board, before.pieces[placement.piece_index], placement.row, placement.col
    )
    if not np.array_equal(after.board, expected):
        changed = np.argwhere(after.board != expected)
        locations = ", ".join(f"({int(r)+1},{int(c)+1})" for r, c in changed[:8])
        raise RuntimeError(f"Stopped: the board differs from the prediction in {len(changed)} cells at row,column {locations}. See captures/last-failure/.")
    remaining = [i for i, p in enumerate(before.pieces) if p.size and i != placement.piece_index]
    if remaining:
        if after.pieces[placement.piece_index].size:
            raise RuntimeError("Stopped: the dragged piece is still in its tray slot.")
        if any(not np.array_equal(before.pieces[i], after.pieces[i]) for i in range(len(before.pieces)) if i != placement.piece_index):
            raise RuntimeError("Stopped: another tray piece changed unexpectedly.")

    elif not all(piece.size for piece in after.pieces):
        raise RuntimeError("Waiting for a complete tray refill after the last piece.")


def save_debug(device, frame, state, name):
    require_game(device)
    directory = ROOT / "captures"
    directory.mkdir(exist_ok=True)
    cv.imwrite(str(directory / name), render_debug(frame, state, show_piece_grid=True))
    cv.imwrite(str(directory / name.replace('.png', '-raw.png')), frame)


def save_failure(device, before, placement, failure, *, before_frame, before_at, released_at, observed):
    require_game(device)
    directory = ROOT / "captures" / "last-failure"
    directory.mkdir(parents=True, exist_ok=True)
    cv.imwrite(str(directory / "before-raw.png"), before_frame)
    after_path = directory / "after-raw.png"
    actual = None
    if observed is not None:
        frame, state, received_at = observed
        cv.imwrite(str(after_path), frame)
        actual = {"board": state.board.tolist(), "tray": [p.tolist() for p in state.pieces], "received_at": received_at}
    else:
        after_path.unlink(missing_ok=True)
    expected, _ = apply_move(before.board, before.pieces[placement.piece_index], placement.row, placement.col)
    (directory / "transition.json").write_text(json.dumps({
        "reason": str(failure),
        "target_zero_based": asdict(placement),
        "before": {"board": before.board.tolist(), "tray": [p.tolist() for p in before.pieces], "received_at": before_at},
        "expected_board": expected.tolist(),
        "observed": actual,
        "released_at": released_at,
        "board_rect": config.BOARD_RECT,
        "tray_rect": config.PIECES_RECT,
    }, indent=2) + "\n")


def wait_verified(device, stream, before, placement, *, after, before_frame=None, before_at=None,
                  debug=False, early_clear=False):
    read_options = {}
    if early_clear and sum(bool(piece.size) for piece in before.pieces) > 1:
        board, cleared = apply_move(
            before.board, before.pieces[placement.piece_index], placement.row, placement.col
        )
        if cleared:
            tray = list(before.pieces)
            tray[placement.piece_index] = np.empty((0, 0), dtype=np.int8)
            read_options["expected_key"] = (
                board.tobytes(), tuple((piece.shape, piece.tobytes()) for piece in tray)
            )
    deadline = time.monotonic() + 6.0
    cursor = after
    failure = None
    observed = None
    while time.monotonic() < deadline:
        try:
            observed = read_stable(device, stream, after=cursor, timeout=max(0, deadline - time.monotonic()), need_pieces=False,
                                   **read_options)
        except StableReadTimeout as exc:
            if failure is None:
                failure = exc
            break
        frame, state, cursor = observed
        try:
            verify_transition(before, state, placement)
        except RuntimeError as exc:
            failure = exc
            continue
        if debug:
            save_debug(device, frame, state, "after.png")
        return observed
    if observed is not None and state_key(observed[1]) == state_key(before):
        failure = SwipeDidNotLand(observed[2])
    failure = failure or RuntimeError("Timed out verifying the drag.")
    if before_frame is not None:
        save_failure(device, before, placement, failure, before_frame=before_frame,
                     before_at=before_at, released_at=after, observed=observed)
    raise failure


def run(*, execute=False, moves=3, drag_ms=None, debug=False, timing=False, solver="exact", audit=False, compare_recheck=False, fast_recheck=False, reuse_plan=False, early_clear=False, chain_tray=False):
    global _metrics_ready
    _metrics_ready = False
    startup = time.monotonic()
    audit_session = time.time_ns()
    def stage(message):
        if UI_METRICS:
            print("UI_STATUS " + message, flush=True)
    def record(event):
        if audit:
            with (ROOT / "captures" / "audit.jsonl").open("a") as out:
                out.write(json.dumps({"session": audit_session, **event}) + "\n")

    stage("Looking for the Android phone…")
    device = get_device()
    device_ready = time.monotonic()
    stage("Checking that Block Blast is open…")
    require_game(device)
    width, height = physical_size(device)
    controller = Controller(device, width, height)
    stream = ScrcpyStream(device)
    played = 0
    verified = None
    remaining_plan = None
    tray_pickups = {}
    all_clear_earned = False
    initial_plan = None
    initial_boards = []
    initial_step = 0
    tray_index = -1
    replanned = False
    print("Ctrl+C to stop. Keep Block Blast open, phone unlocked and ADB connected.", flush=True)
    try:
        stage("Connecting phone video…")
        stream_started = time.monotonic()
        stream.start()
        stream_ready = time.monotonic()
        stage("Reading the board…")
        while moves == 0 or played < moves:
            check_stop()
            if wait_if_paused():
                verified = None
                remaining_plan = None
                initial_plan = None
            started = time.monotonic()
            planning_frame, state, state_at = verified if verified is not None else read_stable(device, stream)
            ready = time.monotonic()
            if played == 0:
                stage("Calculating the first move…")
            print(format_state(state), flush=True)
            solve_started = time.monotonic()
            if remaining_plan is not None:
                plan = remaining_plan
            elif solver == "exact":
                plan = solve_exact(state.board, state.pieces, all_clear_earned=all_clear_earned)
            else:
                plan = solve(state.board, state.pieces, all_clear_first=solver == "beam-all-clear")
            planned = time.monotonic()
            print(format_solution(plan, state.pieces), flush=True)
            if played == 0:
                record({"event": "startup", "device_ms": (device_ready-startup)*1000,
                        "stream_ms": (stream_ready-stream_started)*1000,
                        "first_read_ms": (ready-stream_ready)*1000,
                        "first_solve_ms": (planned-solve_started)*1000})
            if audit and plan and plan.complete:
                if initial_plan is None:
                    tray_index += 1
                    initial_plan = list(plan.placements)
                    initial_boards = []
                    predicted = state.board.copy()
                    for step in initial_plan:
                        predicted, _ = apply_move(predicted, state.pieces[step.piece_index], step.row, step.col)
                        initial_boards.append(predicted.copy())
                    initial_step = 0
                else:
                    record({"event": "plan_comparison", "step": initial_step,
                            "remaining_matches": plan.placements == initial_plan[initial_step:],
                            "original": [asdict(p) for p in initial_plan[initial_step:]],
                            "replanned": [asdict(p) for p in plan.placements]})
            if not execute:
                save_debug(device, planning_frame, state, "before.png")
                print("Preview only. No touch input sent.", flush=True)
                return
            if plan is None or not plan.placements or not plan.complete:
                if not replanned:
                    stage("Checking the board and tray again…")
                    latest = read_stable(device, stream, after=state_at, timeout=2.0)
                    if state_key(latest[1]) != state_key(state):
                        verified = latest
                        remaining_plan = initial_plan = None
                        all_clear_earned = False
                        replanned = True
                        continue
                print("No complete plan for the available pieces. Stopped.", flush=True)
                return
            quick_trial = fast_recheck or (compare_recheck and tray_index % 2 == 1)
            used_quick_frame = False
            recheck_started = time.monotonic()
            chained = reuse_verified_frame(stream, verified) if chain_tray and remaining_plan is not None else None
            if chained is not None:
                frame, current, current_at = chained
            elif quick_trial:
                (frame, current, current_at), used_quick_frame = recheck_latest(device, stream, state, state_at)
            else:
                frame, current, current_at = read_stable(device, stream, after=state_at)
            planned_key = state_key(state)
            current_key = state_key(current)
            if current_key != planned_key:
                stage("Waiting for the board to settle…")
                frame, current, current_at = wait_for_planned_state(
                    device, stream, state, after=current_at,
                    changed_key=None if replanned else current_key,
                )
                if state_key(current) != planned_key:
                    stage("Board or tray changed. Recalculating the move…")
                    verified = (frame, current, current_at)
                    remaining_plan = initial_plan = None
                    all_clear_earned = False
                    replanned = True
                    continue
            rechecked = time.monotonic()
            placement = plan.placements[0]
            pickup = None
            cached_pickup_used = False
            if chain_tray:
                if remaining_plan is None:
                    tray_pickups = current.pickups
                pickup = current.pickups.get(placement.piece_index)
                cached = tray_pickups.get(placement.piece_index)
                if cached is not None and pickup == cached:
                    pickup = cached
                    cached_pickup_used = remaining_plan is not None
            stage("Playing…")
            if debug:
                save_debug(device, frame, current, "before.png")
            check_stop()
            if PAUSE_FILE.exists():
                # Re-read the board after resuming because the game may have changed.
                verified = None
                remaining_plan = None
                initial_plan = None
                continue
            drag_start = time.monotonic()
            released = controller.drag_piece(
                placement.piece_index, current.pieces[placement.piece_index], placement,
                frame.shape, frame=frame, duration_ms=drag_ms, settle=False, pickup=pickup,
            )
            retried = False
            try:
                verified = wait_verified(device, stream, current, placement, after=released,
                                         before_frame=frame, before_at=current_at, debug=debug,
                                         early_clear=early_clear or chain_tray)
            except SwipeDidNotLand as exc:
                retry_ms = 250
                if drag_ms is not None or config.DRAG_MS >= retry_ms:
                    raise
                stage("Swipe did not land. Checking the board before retrying…")
                retry_frame, retry_state, retry_at = wait_for_planned_state(
                    device, stream, current, after=exc.received_at
                )
                if wait_if_paused():
                    verified = None
                    remaining_plan = None
                    initial_plan = None
                    continue
                check_stop()
                stage(f"Retrying the swipe at {retry_ms} ms…")
                retry_release = controller.drag_piece(
                    placement.piece_index, retry_state.pieces[placement.piece_index], placement,
                    retry_frame.shape, frame=retry_frame, duration_ms=retry_ms, settle=False,
                )
                retried = True
                verified = wait_verified(device, stream, retry_state, placement, after=retry_release,
                                         before_frame=retry_frame, before_at=retry_at, debug=debug)
            if sum(bool(piece.size) for piece in current.pieces) == 1:
                all_clear_earned = False
            else:
                all_clear_earned |= not verified[1].board.any()
            finished = time.monotonic()
            remaining_plan = None
            if reuse_plan or audit:
                _, cleared = apply_move(
                    current.board, current.pieces[placement.piece_index], placement.row, placement.col
                )
            if reuse_plan and len(plan.placements) > 1:
                # wait_verified has already matched the predicted board and remaining tray.
                remaining_plan = replace(
                    plan, placements=plan.placements[1:],
                    lines_cleared=plan.lines_cleared - cleared,
                    clear_moves=plan.clear_moves - int(cleared > 0),
                )
            if audit and initial_plan is not None:
                board_matches = np.array_equal(verified[1].board, initial_boards[initial_step])
                record({"event": "move", "step": initial_step + 1,
                        "tray": tray_index, "recheck_mode": "quick" if quick_trial else "stable",
                        "quick_frame_used": used_quick_frame, "lines_cleared": cleared,
                        "early_clear_enabled": early_clear, "configured_drag_ms": drag_ms or config.DRAG_MS,
                        "tray_refilled": initial_step + 1 == len(initial_plan), "retried": retried,
                        "placement": asdict(placement), "board_matches_original": bool(board_matches),
                        "solver_ms": (planned-solve_started)*1000, "recheck_ms": (rechecked-recheck_started)*1000,
                        "drag_ms": (released-drag_start)*1000, "verify_ms": (finished-released)*1000,
                        "total_ms": (finished-started)*1000})
                initial_step += 1
                if not board_matches or initial_step == len(initial_plan):
                    initial_plan = None
            played += 1
            replanned = False
            _metrics_ready = True
            print(f"Verified move {played}: piece {placement.piece_index + 1} -> row {placement.row + 1}, column {placement.col + 1}", flush=True)
            if timing:
                if retried:
                    print("Swipe recovery | retried at 250 ms", flush=True)
                if chain_tray:
                    print(f"Tray timing | reused_frame={chained is not None} reused_pickup={cached_pickup_used}", flush=True)
                print(f"Timing ms | read={(ready-started)*1000:.1f} solve={(planned-solve_started)*1000:.1f} "
                      f"recheck={(rechecked-recheck_started)*1000:.1f} drag={(released-drag_start)*1000:.1f} "
                      f"verify={(finished-released)*1000:.1f} total={(finished-started)*1000:.1f}", flush=True)
        print(f"Finished: {played} verified moves.", flush=True)
    finally:
        stream.stop()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="Send drags; otherwise preview only")
    parser.add_argument("--moves", type=int, default=3, help="Maximum moves; 0 runs until stopped")
    parser.add_argument("--drag-ms", type=int, help="Override the calibrated swipe duration for a bounded run")
    parser.add_argument("--debug", action="store_true", help="Save successful before/after game frames too")
    parser.add_argument("--timing", action="store_true", help="Print per-move stage timings")
    parser.add_argument("--early-clear", action="store_true",
                        help="Use a shorter stability window for matching clears in a bounded run")
    parser.add_argument("--fast-recheck", action="store_true", help="Confirm a newer matching frame before each drag")
    parser.add_argument("--chain-tray", action="store_true", help="Reuse verified frames and unchanged pickup geometry between tray moves")
    parser.add_argument("--reuse-plan", action="store_true", help="Use the remaining exact plan after verifying each move")
    parser.add_argument("--compare-recheck", action="store_true", help="Alternate stable and quick rechecks by tray in a bounded audit")
    parser.add_argument("--audit", action="store_true", help="Append local timing and plan comparisons to captures/audit.jsonl")
    parser.add_argument("--ui-metrics", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--solver", choices=("exact", "beam", "beam-all-clear"), default="exact")
    args = parser.parse_args()
    global UI_METRICS
    UI_METRICS = args.ui_metrics
    if args.drag_ms is not None and (args.drag_ms <= 0 or not args.execute or args.moves <= 0):
        parser.error("--drag-ms needs a positive duration and a bounded --execute run")
    if args.early_clear and (not args.execute or args.moves <= 0):
        parser.error("--early-clear requires --execute and a positive --moves")
    if args.chain_tray and (not args.reuse_plan or not args.execute):
        parser.error("--chain-tray requires --reuse-plan and --execute")
    if args.reuse_plan and (args.audit or args.solver != "exact"):
        parser.error("--reuse-plan requires the exact solver and cannot be combined with --audit")
    if args.compare_recheck and (args.fast_recheck or not args.audit or not args.execute or args.moves <= 0):
        parser.error("--compare-recheck requires --audit, --execute and a positive --moves, without --fast-recheck")
    if args.moves < 0:
        parser.error("--moves must be zero or positive")
    try:
        (ROOT / "captures").mkdir(exist_ok=True)
        with (ROOT / "captures" / "session.lock").open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RuntimeError("Another bot session is already running. Stop it before starting a new session.")
            STOP_FILE.unlink(missing_ok=True)
            run(execute=args.execute, moves=args.moves, drag_ms=args.drag_ms, debug=args.debug, timing=args.timing, solver=args.solver, audit=args.audit, compare_recheck=args.compare_recheck,
                fast_recheck=args.fast_recheck, reuse_plan=args.reuse_plan, early_clear=args.early_clear, chain_tray=args.chain_tray)
    except KeyboardInterrupt:
        print("\nStopped by you.", flush=True)
    except (RuntimeError, ConnectionError, OSError) as exc:
        print(f"\n{exc}", flush=True)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
