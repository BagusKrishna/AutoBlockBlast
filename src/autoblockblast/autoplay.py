"""Verified autoplay for the calibrated Android phone. Ctrl+C stops the session."""

import argparse
import fcntl
from pathlib import Path
import time

import cv2 as cv
import numpy as np

from autoblockblast import config
from autoblockblast.controller import Controller
from autoblockblast.phone import get_device, physical_size, require_game
from autoblockblast.scrcpy_stream import ScrcpyStream
from autoblockblast.solver import apply_move, format_solution, solve
from autoblockblast.vision import analyze, format_state, render_debug

ROOT = Path(__file__).resolve().parents[2]
STOP_FILE = ROOT / "captures" / "stop.request"


def check_stop():
    if STOP_FILE.exists():
        raise KeyboardInterrupt


def state_key(state):
    return (state.board.tobytes(), tuple((p.shape, p.tobytes()) for p in state.pieces))


def read_stable(device, stream, *, after=0.0, timeout=8.0, need_pieces=True):
    deadline = time.monotonic() + timeout
    previous = None
    previous_at = 0.0
    while time.monotonic() < deadline:
        check_stop()
        require_game(device)
        if not stream.alive:
            raise RuntimeError("Phone video stream stopped. Reconnect and restart the bot.")
        frame, received_at = stream.snapshot()
        if frame is None or received_at <= after or time.monotonic() - received_at > 2.0:
            time.sleep(0.1)
            continue
        state = analyze(frame)
        if need_pieces and not any(p.size for p in state.pieces):
            time.sleep(0.1)
            continue
        if any(p.size and (max(p.shape) > 5 or p.sum() > 9) for p in state.pieces):
            raise RuntimeError("Unrecognized piece shape. Recalibrate before playing.")
        key = state_key(state)
        if key == previous and received_at > previous_at + 0.1:
            require_game(device)
            return frame, state
        if key != previous:
            previous, previous_at = key, received_at
        time.sleep(0.12)
    raise RuntimeError("No fresh, stable game state. Check that the game is visible and animations have finished.")


def verify_transition(before, after, placement):
    expected, _ = apply_move(
        before.board, before.pieces[placement.piece_index], placement.row, placement.col
    )
    if not np.array_equal(after.board, expected):
        mismatch = int(np.count_nonzero(after.board != expected))
        raise RuntimeError(f"Stopped: the board differs from the prediction in {mismatch} cells. Check captures/after.png.")
    remaining = [i for i, p in enumerate(before.pieces) if p.size and i != placement.piece_index]
    if remaining:
        if after.pieces[placement.piece_index].size:
            raise RuntimeError("Stopped: the dragged piece is still in its tray slot.")
        if any(not np.array_equal(before.pieces[i], after.pieces[i]) for i in remaining):
            raise RuntimeError("Stopped: another tray piece changed unexpectedly.")


def save_debug(device, frame, state, name):
    require_game(device)
    directory = ROOT / "captures"
    directory.mkdir(exist_ok=True)
    cv.imwrite(str(directory / name), render_debug(frame, state, show_piece_grid=True))


def wait_verified(device, stream, before, placement, *, after):
    deadline = time.monotonic() + 6.0
    failure = None
    while time.monotonic() < deadline:
        frame, state = read_stable(device, stream, after=after, timeout=max(0.1, deadline - time.monotonic()))
        save_debug(device, frame, state, "after.png")
        try:
            verify_transition(before, state, placement)
            return frame, state
        except RuntimeError as exc:
            failure = exc
            time.sleep(0.2)
    raise failure or RuntimeError("Timed out verifying the drag.")


def run(*, execute=False, moves=3):
    device = get_device()
    require_game(device)
    width, height = physical_size(device)
    controller = Controller(device, width, height)
    stream = ScrcpyStream(device)
    played = 0
    print("Ctrl+C to stop. Keep Block Blast open, phone unlocked and USB connected.", flush=True)
    try:
        stream.start()
        while moves == 0 or played < moves:
            frame, state = read_stable(device, stream)
            print(format_state(state), flush=True)
            plan = solve(state.board, state.pieces)
            print(format_solution(plan, state.pieces), flush=True)
            save_debug(device, frame, state, "before.png")
            if not execute:
                print("Preview only. No touch input sent.", flush=True)
                return
            if plan is None or not plan.placements or not plan.complete:
                print("No complete plan for the available pieces. Stopped.", flush=True)
                return
            # Planning can take time; refuse input if the user/game changed the state.
            _, current = read_stable(device, stream)
            if state_key(current) != state_key(state):
                raise RuntimeError("Game state changed during planning. Stopped; restart when the board is still.")
            placement = plan.placements[0]
            check_stop()
            started = time.monotonic()
            controller.drag_piece(placement.piece_index, state.pieces[placement.piece_index], placement, frame.shape, frame=frame)
            if sum(bool(p.size) for p in state.pieces) == 1:
                time.sleep(config.ROUND_PAUSE_S)
            wait_verified(device, stream, state, placement, after=started + config.DRAG_MS / 1000.0)
            played += 1
            print(f"Verified move {played}: piece {placement.piece_index + 1} -> row {placement.row + 1}, column {placement.col + 1}", flush=True)
        print(f"Finished: {played} verified moves.", flush=True)
    finally:
        stream.stop()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="Send drags; otherwise preview only")
    parser.add_argument("--moves", type=int, default=3, help="Maximum moves; 0 runs until stopped")
    args = parser.parse_args()
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
            run(execute=args.execute, moves=args.moves)
    except KeyboardInterrupt:
        print("\nStopped by you.", flush=True)
    except (RuntimeError, ConnectionError, OSError) as exc:
        print(f"\n{exc}", flush=True)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
