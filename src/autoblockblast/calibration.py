import ast

from pathlib import Path



from autoblockblast import config



CONFIG_PATH = Path(__file__).resolve().parent / "config.py"

SCALE = 1000





def _read_line(prefix: str) -> str:

    for line in CONFIG_PATH.read_text().splitlines():

        if line.startswith(prefix):

            return line.split("=", 1)[1].strip()

    raise ValueError(f"{prefix} not found in config.py")





def _read_rect(prefix: str) -> config.Rect:

    return ast.literal_eval(_read_line(prefix))





def load_rects() -> tuple[config.Rect, config.Rect]:

    return _read_rect("BOARD_RECT"), _read_rect("PIECES_RECT")





def load_tuning() -> dict:

    return {

        "board_inset": float(_read_line("BOARD_INSET")),

        "s_delta": int(_read_line("PIECE_S_DELTA")),

        "v_delta": int(_read_line("PIECE_V_DELTA")),

        "h_delta": int(_read_line("PIECE_H_DELTA")),

        "min_area": int(_read_line("PIECE_MIN_AREA")),

        "open_k": int(_read_line("PIECE_OPEN")),

        "cell_v": int(_read_line("CELL_V_MIN")),

    }





def rect_to_trackbar(rect: config.Rect) -> tuple[int, int, int, int]:

    return tuple(int(v * SCALE) for v in rect)





def trackbar_to_rect(x1: int, y1: int, x2: int, y2: int) -> config.Rect:

    vals = [max(0, min(SCALE, v)) / SCALE for v in (x1, y1, x2, y2)]

    x1, y1, x2, y2 = vals

    if x2 <= x1 + 0.02:

        x2 = min(1.0, x1 + 0.02)

    if y2 <= y1 + 0.02:

        y2 = min(1.0, y1 + 0.02)

    return (x1, y1, x2, y2)





def format_rect(rect: config.Rect) -> str:

    return "(" + ", ".join(f"{v:.3f}" for v in rect) + ")"





def _write_config(updates: dict[str, str]):

    lines = CONFIG_PATH.read_text().splitlines()

    out = []

    for line in lines:

        key = line.split("=", 1)[0].strip()

        out.append(f"{key} = {updates[key]}" if key in updates else line)

    CONFIG_PATH.write_text("\n".join(out) + "\n")





def save_all(

    board_rect: config.Rect,

    pieces_rect: config.Rect,

    board_inset: float,

    s_delta: int,

    v_delta: int,

    h_delta: int,

    min_area: int,

    open_k: int,

    cell_v: int,

):

    _write_config(

        {

            "BOARD_RECT": format_rect(board_rect),

            "PIECES_RECT": format_rect(pieces_rect),

            "BOARD_INSET": f"{board_inset:.3f}",

            "PIECE_S_DELTA": str(int(s_delta)),

            "PIECE_V_DELTA": str(int(v_delta)),

            "PIECE_H_DELTA": str(int(h_delta)),

            "PIECE_MIN_AREA": str(int(min_area)),

            "PIECE_OPEN": str(int(open_k)),

            "CELL_V_MIN": str(int(cell_v)),

        }

    )

    config.BOARD_RECT = board_rect

    config.PIECES_RECT = pieces_rect

    config.BOARD_INSET = float(board_inset)

    config.PIECE_S_DELTA = int(s_delta)

    config.PIECE_V_DELTA = int(v_delta)

    config.PIECE_H_DELTA = int(h_delta)

    config.PIECE_MIN_AREA = int(min_area)

    config.PIECE_OPEN = int(open_k)

    config.CELL_V_MIN = int(cell_v)
