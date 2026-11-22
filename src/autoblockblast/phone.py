import re
import sys
import time

from adbutils import AdbError, adb

from autoblockblast import config


# Drain the whole input dump on Android and forward only default-display focus.
_INPUT_FOCUS_COMMAND = """set -o pipefail; dumpsys -t 1 input | awk '
    /^[[:space:]]*FocusedDisplayId:/ { print }
    /^[[:space:]]*FocusedWindows:[[:space:]]*$/ { focused = 1; next }
    focused && /^[[:space:]]*displayId=/ {
        if ($0 ~ /^[[:space:]]*displayId=0,/) print
        next
    }
    focused && NF { focused = 0 }
    /DUMP TIMEOUT|Permission Denial/ { failed = 1 }
    END { if (failed) exit 1 }
'"""
_FOCUSED_WINDOW = re.compile(r"displayId=0, name='(?:[0-9a-fA-F]+ )?([\w.]+)/[^']+'")


def require_game(device):
    """Refuse capture or input when the requested game is not in front."""
    for attempt in range(3):
        try:
            result = device.shell2(_INPUT_FOCUS_COMMAND, timeout=3)
        except (AdbError, OSError) as exc:
            raise RuntimeError("Android input focus unavailable. Check the ADB connection.") from exc
        lines = [line.strip() for line in result.output.splitlines() if line.strip()]
        if result.returncode or not lines:
            raise RuntimeError("Android input focus unavailable. Check the ADB connection.")
        if len(lines) == 2 and lines[0] == "FocusedDisplayId: 0":
            match = _FOCUSED_WINDOW.fullmatch(lines[1])
            if match and match.group(1) == config.GAME_PACKAGE:
                return
        if attempt < 2:
            time.sleep(0.15)
    raise RuntimeError("Block Blast is not in front. Open the game and unlock the phone, then restart the bot.")


def get_device():
    devices = adb.device_list()
    if not devices:
        print("No Android device found. Connect via USB or wireless debugging and check ADB authorization.")
        sys.exit(1)
    if len(devices) != 1:
        raise RuntimeError("More than one ADB connection found. Disconnect extra phones or one USB/Wi-Fi connection and restart.")
    device = devices[0]
    state = device.get_state()
    if state != "device":
        print(f"Device {device.serial} is '{state}'.")
        if state == "unauthorized":
            print("Unlock your phone and tap 'Allow USB debugging' on the prompt, then run this again.")
        sys.exit(1)
    return device


def physical_size(device):
    for line in device.shell("wm size").splitlines():
        if "Physical size" in line or "Override size" in line:
            w, h = line.split(":")[1].strip().split("x")
            return int(w), int(h)
    raise RuntimeError("Could not read device screen size")
