import time

import cv2 as cv

from autoblockblast import config
from autoblockblast.autoplay import check_stop, read_stable, state_key, wait_verified
from autoblockblast.controller import Controller, board_cell_xy
from autoblockblast.phone import get_device, physical_size, require_game
from autoblockblast.scrcpy_stream import ScrcpyStream
from autoblockblast.solver import format_solution, solve
from autoblockblast.vision import analyze, format_state, render_debug

WINDOW = "Block Blast Bot"
CONTROLS = "Bot Controls"


def draw_solution(frame, pieces, result):
    out = frame.copy()
    if result is None:
        return out
    colors = [(0, 255, 255), (255, 128, 0), (255, 0, 255)]
    for step, place in enumerate(result.placements):
        piece = pieces[place.piece_index]
        if piece.size == 0:
            continue
        color = colors[step % len(colors)]
        ph, pw = piece.shape
        for r in range(ph):
            for c in range(pw):
                if not piece[r, c]:
                    continue
                cx, cy = board_cell_xy(out.shape, place.row + r, place.col + c)
                cv.circle(out, (int(cx), int(cy)), 10, color, 2)
                if r == 0 and c == 0:
                    cv.putText(
                        out,
                        f"{step + 1}:P{place.piece_index + 1}",
                        (int(cx) - 18, int(cy) - 12),
                        cv.FONT_HERSHEY_SIMPLEX,
                        0.4,
                        color,
                        1,
                        cv.LINE_AA,
                    )
    return out


def _setup_controls():
    cv.namedWindow(CONTROLS)
    cv.resizeWindow(CONTROLS, 420, 120)
    nudge0 = int(round((config.DROP_Y_NUDGE + 2.0) * 100))
    cv.createTrackbar("drop Y nudge", CONTROLS, max(0, min(800, nudge0)), 800, lambda _v: None)
    cv.createTrackbar("drag ms", CONTROLS, max(50, min(1200, config.DRAG_MS)), 1200, lambda _v: None)
    cv.createTrackbar("settle ms", CONTROLS, max(0, min(2000, int(config.SETTLE_S * 1000))), 2000, lambda _v: None)


def _apply_controls():
    config.DROP_Y_NUDGE = cv.getTrackbarPos("drop Y nudge", CONTROLS) / 100.0 - 2.0
    config.DRAG_MS = max(50, cv.getTrackbarPos("drag ms", CONTROLS))
    config.SETTLE_S = cv.getTrackbarPos("settle ms", CONTROLS) / 1000.0


def main():
    device = get_device()
    screen_w, screen_h = physical_size(device)
    ctrl = Controller(device, screen_w, screen_h)
    print(f"Device: {device.serial} ({screen_w}x{screen_h})")
    print("S=solve+play once  A=auto toggle  P=print only  Q=quit")
    print("Sliders: drop Y nudge (-2..+6), drag ms, settle ms")

    stream = ScrcpyStream(device, max_size=config.MAX_SIZE, max_fps=30)
    cv.namedWindow(WINDOW)
    _setup_controls()
    auto = False
    busy = False
    last_plan = None
    last_auto = 0.0

    try:
        stream.start()
        while stream.alive:
            try:
                require_game(device)
            except RuntimeError as exc:
                print(exc)
                break
            _apply_controls()
            frame = stream.last_frame
            if frame is None:
                if cv.waitKey(1) & 0xFF == ord("q"):
                    break
                continue

            vision = analyze(frame)
            debug = render_debug(frame, vision, show_piece_grid=True)
            if last_plan is not None:
                debug = draw_solution(debug, vision.pieces, last_plan)
            mode = "AUTO" if auto else "MANUAL"
            status = "BUSY" if busy else mode
            cv.putText(
                debug,
                f"{status}  S=play  A=auto  P=print  Q=quit",
                (10, 24),
                cv.FONT_HERSHEY_SIMPLEX,
                0.5,
                (0, 255, 0) if not busy else (0, 165, 255),
                2,
            )
            cv.putText(
                debug,
                f"nudge={config.DROP_Y_NUDGE:.2f} drag={config.DRAG_MS}ms settle={config.SETTLE_S:.2f}s",
                (10, 48),
                cv.FONT_HERSHEY_SIMPLEX,
                0.45,
                (0, 255, 255),
                1,
            )
            cv.imshow(WINDOW, debug)

            key = cv.waitKey(1) & 0xFF
            if key == ord("q"):
                break
            if key == ord("a"):
                auto = not auto
                print(f"Auto: {'ON' if auto else 'OFF'}")
            if key == ord("p") and not busy:
                print(format_state(vision))
                last_plan = solve(vision.board, vision.pieces)
                print(format_solution(last_plan, vision.pieces))
                print("-" * 40)

            should_play = False
            if key == ord("s") and not busy:
                should_play = True
            elif auto and not busy and time.time() - last_auto >= config.AUTO_INTERVAL_S:
                should_play = True

            if should_play:
                busy = True
                try:
                    frame, vision = read_stable(device, stream)
                    print(format_state(vision))
                    plan = solve(vision.board, vision.pieces)
                    last_plan = plan
                    print(format_solution(plan, vision.pieces))
                    if plan is None or not plan.placements:
                        print("No moves.")
                    else:
                        print("Executing...")
                        for placement in plan.placements:
                            check_stop()
                            _, current = read_stable(device, stream)
                            if state_key(current) != state_key(vision):
                                raise RuntimeError("Game changed during planning; stopped.")
                            started = time.monotonic()
                            ctrl.drag_piece(placement.piece_index, vision.pieces[placement.piece_index], placement, frame.shape, frame=frame)
                            if sum(bool(p.size) for p in vision.pieces) == 1:
                                time.sleep(config.ROUND_PAUSE_S)
                            frame, vision = wait_verified(device, stream, vision, placement, after=started + config.DRAG_MS / 1000.0)
                        print("Done.")
                    print("-" * 40)
                except (RuntimeError, ConnectionError, OSError) as exc:
                    auto = False
                    last_plan = None
                    print(f"Stopped autoplay: {exc}")
                finally:
                    busy = False
                    last_auto = time.time()
    finally:
        stream.stop()
        cv.destroyAllWindows()


if __name__ == "__main__":
    main()
