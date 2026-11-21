"""Verified autoplay for the calibrated Android phone. Ctrl+C stops the session."""

import argparse
import fcntl
import json
from dataclasses import asdict
from pathlib import Path
import time

import cv2 as cv
import numpy as np

from autoblockblast import config
from autoblockblast.controller import Controller
from autoblockblast.phone import get_device, physical_size, require_game
from autoblockblast.scrcpy_stream import ScrcpyStream
from autoblockblast.solver import apply_move, format_solution, solve, solve_exact
from autoblockblast.vision import analyze, format_state, render_debug

ROOT = Path(__file__).resolve().parents[2]
STOP_FILE = ROOT / "captures" / "stop.request"


def check_stop():
    if STOP_FILE.exists():
        raise KeyboardInterrupt


def state_key(state):
    return (state.board.tobytes(), tuple((p.shape, p.tobytes()) for p in state.pieces))


class StableReadTimeout(RuntimeError):
    pass


def read_stable(device, stream, *, after=0.0, timeout=8.0, need_pieces=True):
    deadline = time.monotonic() + timeout
    previous = None
    previous_at = 0.0
    seen_at = after
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
        state = analyze(frame)
        invalid_piece = any(p.size and (max(p.shape) > 5 or p.sum() > 9) for p in state.pieces)
        if invalid_piece or (need_pieces and not any(p.size for p in state.pieces)):
            # Refill and clear animations can temporarily resemble oversized pieces.
            previous = None
            time.sleep(0.04)
            continue
        key = state_key(state)
        if key == previous and received_at > previous_at + 0.1:
            require_game(device)
            return frame, state, received_at
        if key != previous:
            previous, previous_at = key, received_at
        time.sleep(0.04)
    raise StableReadTimeout("No fresh, stable game state. Check that the game is visible and animations have finished.")


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


def wait_verified(device, stream, before, placement, *, after, before_frame=None, before_at=None, debug=False):
    deadline = time.monotonic() + 6.0
    cursor = after
    failure = None
    observed = None
    while time.monotonic() < deadline:
        try:
            observed = read_stable(device, stream, after=cursor, timeout=max(0, deadline - time.monotonic()), need_pieces=False)
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
    failure = failure or RuntimeError("Timed out verifying the drag.")
    if before_frame is not None:
        save_failure(device, before, placement, failure, before_frame=before_frame,
                     before_at=before_at, released_at=after, observed=observed)
    raise failure


def run(*, execute=False, moves=3, drag_ms=None, debug=False, timing=False, solver="exact"):
    device = get_device()
    require_game(device)
    width, height = physical_size(device)
    controller = Controller(device, width, height)
    stream = ScrcpyStream(device)
    played = 0
    verified = None
    all_clear_earned = False
    print("Ctrl+C to stop. Keep Block Blast open, phone unlocked and USB connected.", flush=True)
    try:
        stream.start()
        while moves == 0 or played < moves:
            started = time.monotonic()
            planning_frame, state, state_at = verified if verified is not None else read_stable(device, stream)
            ready = time.monotonic()
            print(format_state(state), flush=True)
            if solver == "exact":
                plan = solve_exact(state.board, state.pieces, all_clear_earned=all_clear_earned)
            else:
                plan = solve(state.board, state.pieces, all_clear_first=solver == "beam-all-clear")
            planned = time.monotonic()
            print(format_solution(plan, state.pieces), flush=True)
            if not execute:
                save_debug(device, planning_frame, state, "before.png")
                print("Preview only. No touch input sent.", flush=True)
                return
            if plan is None or not plan.placements or not plan.complete:
                print("No complete plan for the available pieces. Stopped.", flush=True)
                return
            frame, current, current_at = read_stable(device, stream, after=state_at)
            if state_key(current) != state_key(state):
                raise RuntimeError("Game state changed during planning. Stopped; restart when the board is still.")
            placement = plan.placements[0]
            if debug:
                save_debug(device, frame, current, "before.png")
            check_stop()
            drag_start = time.monotonic()
            released = controller.drag_piece(
                placement.piece_index, current.pieces[placement.piece_index], placement,
                frame.shape, frame=frame, duration_ms=drag_ms, settle=False,
            )
            verified = wait_verified(device, stream, current, placement, after=released,
                                     before_frame=frame, before_at=current_at, debug=debug)
            if sum(bool(piece.size) for piece in current.pieces) == 1:
                all_clear_earned = False
            else:
                all_clear_earned |= not verified[1].board.any()
            finished = time.monotonic()
            played += 1
            print(f"Verified move {played}: piece {placement.piece_index + 1} -> row {placement.row + 1}, column {placement.col + 1}", flush=True)
            if timing:
                print(f"Timing ms | read={(ready-started)*1000:.1f} solve={(planned-ready)*1000:.1f} "
                      f"recheck={(drag_start-planned)*1000:.1f} drag={(released-drag_start)*1000:.1f} "
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
    parser.add_argument("--solver", choices=("exact", "beam", "beam-all-clear"), default="exact")
    args = parser.parse_args()
    if args.drag_ms is not None and (args.drag_ms <= 0 or not args.execute or args.moves <= 0):
        parser.error("--drag-ms needs a positive duration and a bounded --execute run")
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
            run(execute=args.execute, moves=args.moves, drag_ms=args.drag_ms, debug=args.debug, timing=args.timing, solver=args.solver)
    except KeyboardInterrupt:
        print("\nStopped by you.", flush=True)
    except (RuntimeError, ConnectionError, OSError) as exc:
        print(f"\n{exc}", flush=True)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
