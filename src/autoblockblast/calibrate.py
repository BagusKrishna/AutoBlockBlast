from autoblockblast import config
import cv2 as cv

from autoblockblast.calibration import load_rects, load_tuning, rect_to_trackbar, save_all, trackbar_to_rect
from autoblockblast.phone import get_device, physical_size
from autoblockblast.scrcpy_stream import ScrcpyStream
from autoblockblast.vision import analyze, format_state, render_debug

PREVIEW = "Calibration Preview"
CONTROLS = "Calibration Controls"


def _get_rects():
    return trackbar_to_rect(
        cv.getTrackbarPos("board x1", CONTROLS),
        cv.getTrackbarPos("board y1", CONTROLS),
        cv.getTrackbarPos("board x2", CONTROLS),
        cv.getTrackbarPos("board y2", CONTROLS),
    ), trackbar_to_rect(
        cv.getTrackbarPos("pieces x1", CONTROLS),
        cv.getTrackbarPos("pieces y1", CONTROLS),
        cv.getTrackbarPos("pieces x2", CONTROLS),
        cv.getTrackbarPos("pieces y2", CONTROLS),
    )


def _apply_tuning():
    config.BOARD_INSET = cv.getTrackbarPos("board inset", CONTROLS) / 1000.0
    config.PIECE_S_DELTA = cv.getTrackbarPos("piece S delta", CONTROLS)
    config.PIECE_V_DELTA = cv.getTrackbarPos("piece V delta", CONTROLS)
    config.PIECE_H_DELTA = cv.getTrackbarPos("piece H delta", CONTROLS)
    config.PIECE_MIN_AREA = cv.getTrackbarPos("piece min area", CONTROLS)
    config.PIECE_OPEN = cv.getTrackbarPos("piece open", CONTROLS)
    config.CELL_V_MIN = cv.getTrackbarPos("board V min", CONTROLS)


def _get_tuning():
    return {
        "board_inset": cv.getTrackbarPos("board inset", CONTROLS) / 1000.0,
        "s_delta": cv.getTrackbarPos("piece S delta", CONTROLS),
        "v_delta": cv.getTrackbarPos("piece V delta", CONTROLS),
        "h_delta": cv.getTrackbarPos("piece H delta", CONTROLS),
        "min_area": cv.getTrackbarPos("piece min area", CONTROLS),
        "open_k": cv.getTrackbarPos("piece open", CONTROLS),
        "cell_v": cv.getTrackbarPos("board V min", CONTROLS),
    }


def _set_trackbars(board_rect, pieces_rect, t):
    bx1, by1, bx2, by2 = rect_to_trackbar(board_rect)
    px1, py1, px2, py2 = rect_to_trackbar(pieces_rect)
    for name, val in (
        ("board x1", bx1),
        ("board y1", by1),
        ("board x2", bx2),
        ("board y2", by2),
        ("pieces x1", px1),
        ("pieces y1", py1),
        ("pieces x2", px2),
        ("pieces y2", py2),
        ("board inset", int(t["board_inset"] * 1000)),
        ("piece S delta", t["s_delta"]),
        ("piece V delta", t["v_delta"]),
        ("piece H delta", t["h_delta"]),
        ("piece min area", t["min_area"]),
        ("piece open", t["open_k"]),
        ("board V min", t["cell_v"]),
    ):
        cv.setTrackbarPos(name, CONTROLS, val)


def main():
    device = get_device()
    screen_w, screen_h = physical_size(device)
    board_rect, pieces_rect = load_rects()
    t = load_tuning()
    print(f"Device: {device.serial} ({screen_w}x{screen_h})")
    print("Red mask = color detection. Yellow dots = block centers. Tune until mask hits blocks only.")
    print("S=save P=print R=reset Q=quit")

    cv.namedWindow(PREVIEW)
    cv.namedWindow(CONTROLS)
    cv.resizeWindow(CONTROLS, 520, 0)

    bars = (
        ("board x1", rect_to_trackbar(board_rect)[0], 1000),
        ("board y1", rect_to_trackbar(board_rect)[1], 1000),
        ("board x2", rect_to_trackbar(board_rect)[2], 1000),
        ("board y2", rect_to_trackbar(board_rect)[3], 1000),
        ("pieces x1", rect_to_trackbar(pieces_rect)[0], 1000),
        ("pieces y1", rect_to_trackbar(pieces_rect)[1], 1000),
        ("pieces x2", rect_to_trackbar(pieces_rect)[2], 1000),
        ("pieces y2", rect_to_trackbar(pieces_rect)[3], 1000),
        ("board inset", int(t["board_inset"] * 1000), 120),
        ("piece S delta", t["s_delta"], 80),
        ("piece V delta", t["v_delta"], 80),
        ("piece H delta", t["h_delta"], 40),
        ("piece min area", t["min_area"], 400),
        ("piece open", t["open_k"], 7),
        ("board V min", t["cell_v"], 255),
    )
    for name, val, top in bars:
        cv.createTrackbar(name, CONTROLS, val, top, lambda _v: None)

    saved = (board_rect, pieces_rect, dict(t))
    stream = ScrcpyStream(device, max_size=config.MAX_SIZE, max_fps=30)

    try:
        stream.start()
        while stream.alive or stream.last_frame is not None:
            frame = stream.last_frame
            if frame is None:
                if cv.waitKey(1) & 0xFF == ord("q"):
                    break
                continue

            _apply_tuning()
            board_rect, pieces_rect = _get_rects()
            t = _get_tuning()
            result = analyze(frame, board_rect, pieces_rect)
            debug = render_debug(frame, result, board_rect, pieces_rect, show_piece_grid=True)
            cv.putText(debug, "S=save P=print R=reset Q=quit", (8, 22), cv.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
            cv.putText(
                debug,
                f"dS={t['s_delta']} dV={t['v_delta']} dH={t['h_delta']} area={t['min_area']} open={t['open_k']}",
                (8, 44),
                cv.FONT_HERSHEY_SIMPLEX,
                0.45,
                (0, 255, 255),
                1,
            )
            cv.imshow(PREVIEW, debug)

            key = cv.waitKey(1)
            if key == -1:
                continue
            key &= 0xFF
            if key == ord("q"):
                break
            if key == ord("s"):
                save_all(
                    board_rect,
                    pieces_rect,
                    t["board_inset"],
                    t["s_delta"],
                    t["v_delta"],
                    t["h_delta"],
                    t["min_area"],
                    t["open_k"],
                    t["cell_v"],
                )
                saved = (board_rect, pieces_rect, dict(t))
                print("Saved tuning.")
            elif key == ord("p"):
                print(format_state(result))
                print("-" * 40)
            elif key == ord("r"):
                _set_trackbars(*saved)
    finally:
        stream.stop()
        cv.destroyAllWindows()


if __name__ == "__main__":
    main()
