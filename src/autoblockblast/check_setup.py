"""Check local dependencies and USB connection without sending touch input."""

import importlib
import shutil
import subprocess
import sys

from autoblockblast import config


def main() -> int:
    print(f"Python: {sys.version.split()[0]}")
    missing = False
    for name in ("cv2", "numpy", "adbutils", "av"):
        try:
            module = importlib.import_module(name)
            print(f"OK {name}: {getattr(module, '__version__', 'installed')}")
        except ImportError as exc:
            print(f"MISSING {name}: {exc}")
            missing = True

    if config.SCRCPY_SERVER.is_file():
        print(f"OK scrcpy server: {config.SCRCPY_SERVER} (configured version {config.SCRCPY_VERSION})")
    else:
        print(f"MISSING scrcpy server: {config.SCRCPY_SERVER}")
        missing = True

    adb_path = shutil.which("adb")
    if not adb_path:
        print("MISSING adb: install Android Platform Tools and add adb to PATH.")
        return 1
    print(f"OK adb: {adb_path}")
    try:
        result = subprocess.run(
            [adb_path, "devices"], capture_output=True, text=True, timeout=15, check=True
        )
    except (subprocess.SubprocessError, OSError) as exc:
        print(f"ADB connection failed: {exc}")
        return 1
    devices = [line.split() for line in result.stdout.splitlines()[1:] if line.strip()]
    if not devices:
        print("WAITING: connect your unlocked Android phone and enable USB debugging.")
        return 2 if not missing else 1
    ready = 0
    for fields in devices:
        state = fields[1] if len(fields) > 1 else "unknown"
        print(f"Android connection: {state}")
        if state == "unauthorized":
            print("Unlock the phone and allow USB debugging from this Mac.")
        elif state == "device":
            ready += 1
    if ready > 1:
        print("Connect only the intended phone; the upstream bot selects the first device.")
        return 2
    if missing:
        return 1
    if ready != 1:
        return 2
    print("READY: local dependencies and one authorized Android connection are available.")
    print("Next: open Block Blast, then run .venv/bin/python calibrate.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
