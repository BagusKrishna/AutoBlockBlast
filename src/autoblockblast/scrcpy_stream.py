import random
import socket
import struct
import threading
import time
from typing import Optional

import av
import numpy as np
from adbutils import AdbDevice, AdbError, Network

from autoblockblast import config
from autoblockblast.phone import require_game


def _scid() -> str:
    return str(random.randint(0, 5)) + "".join(hex(random.randint(1, 15))[-1] for _ in range(7))


class ScrcpyStream:
    def __init__(self, device: AdbDevice, max_size: int = config.MAX_SIZE, max_fps: int = config.MAX_FPS):
        if not config.SCRCPY_SERVER.is_file():
            raise FileNotFoundError(f"scrcpy-server not found at {config.SCRCPY_SERVER}")
        self.device = device
        self.max_size = max_size
        self.max_fps = max_fps
        self.scid = _scid()
        self.alive = False
        self.last_frame: Optional[np.ndarray] = None
        self.last_frame_at = 0.0
        self._frame_lock = threading.Lock()
        self.frame_size = (0, 0)
        self._stream = None
        self._socket: Optional[socket.socket] = None
        self._thread: Optional[threading.Thread] = None
        self._control_socket: Optional[socket.socket] = None
        self._control_stream = None

    def _push_server(self) -> str:
        remote = f"/data/local/tmp/scrcpy-server-{self.scid}"
        self.device.sync.push(str(config.SCRCPY_SERVER), remote)
        return remote

    def _server_cmd(self, remote: str, video: bool, control: bool) -> list[str]:
        args = [
            f"CLASSPATH={remote}",
            "app_process",
            "/",
            "com.genymobile.scrcpy.Server",
            config.SCRCPY_VERSION,
            "log_level=info",
            "tunnel_forward=true",
            "send_frame_meta=false",
            "stay_awake=true",
            f"video={'true' if video else 'false'}",
            f"audio=false",
            f"control={'true' if control else 'false'}",
            f"max_size={self.max_size}",
            f"max_fps={self.max_fps}",
            "video_codec=h264",
            "video_source=display",
            f"scid={self.scid}",
        ]
        if video and not control:
            args += ["audio=false"]
        if control and not video:
            args += ["video=false"]
        return args

    def _recv_exact(self, sock: socket.socket, size: int, timeout: float = 5.0) -> bytes:
        deadline = time.time() + timeout
        buf = b""
        while len(buf) < size:
            if time.time() > deadline:
                raise ConnectionError("scrcpy socket read timeout")
            try:
                chunk = sock.recv(size - len(buf))
                if chunk == b"":
                    raise ConnectionError("scrcpy socket closed")
                buf += chunk
            except BlockingIOError:
                time.sleep(0.01)
        return buf

    def _connect_socket(self, timeout: float = 5.0) -> socket.socket:
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                conn = self.device.create_connection(Network.LOCAL_ABSTRACT, f"scrcpy_{self.scid}")
                conn.setblocking(False)
                if self._recv_exact(conn, 1) != b"\x00":
                    raise ConnectionError("scrcpy dummy byte mismatch")
                self._recv_exact(conn, 64)
                return conn
            except AdbError:
                time.sleep(0.01)
        raise ConnectionError("scrcpy socket timeout")

    def start(self):
        require_game(self.device)
        remote = self._push_server()
        try:
            self._stream = self.device.shell(self._server_cmd(remote, video=True, control=False), stream=True)
            self._socket = self._connect_socket()
            codec = self._recv_exact(self._socket, 4).decode()
            if not codec:
                raise ConnectionError("scrcpy video header missing")
            width, height = struct.unpack(">II", self._recv_exact(self._socket, 8))
            self.frame_size = (width, height)
            self.alive = True
            self._thread = threading.Thread(target=self._decode_loop, args=(codec,), daemon=True)
            self._thread.start()
        except BaseException:
            self.stop()
            raise

    def snapshot(self, *, after: float = 0.0) -> tuple[Optional[np.ndarray], float]:
        with self._frame_lock:
            frame = None
            if self.last_frame is not None and self.last_frame_at > after:
                frame = self.last_frame.copy()
            return frame, self.last_frame_at

    def _decode_loop(self, codec_name: str):
        codec = av.CodecContext.create("h264" if codec_name == "h264" else codec_name, "r")
        while self.alive:
            try:
                raw = self._socket.recv(0x10000)
                if raw == b"":
                    break
                for packet in codec.parse(raw):
                    for frame in codec.decode(packet):
                        decoded = frame.to_ndarray(format="bgr24")
                        with self._frame_lock:
                            self.last_frame = decoded
                            self.last_frame_at = time.monotonic()
            except BlockingIOError:
                time.sleep(0.005)
            except OSError:
                break
            except Exception:
                break
        self.alive = False

    def tap(self, x: int, y: int):
        require_game(self.device)
        self.device.shell(f"input tap {x} {y}")

    def stop(self):
        self.alive = False
        for sock in (self._socket, self._control_socket):
            if sock:
                try:
                    sock.close()
                except OSError:
                    pass
        for stream in (self._stream, self._control_stream):
            if stream:
                try:
                    stream.close()
                except Exception:
                    pass
