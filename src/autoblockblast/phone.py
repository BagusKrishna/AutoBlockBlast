import sys
import time

from adbutils import adb

from autoblockblast import config


def require_game(device):
    """Refuse capture or input when the requested game is not in front."""
    for attempt in range(3):
        focus = [line for line in device.shell("dumpsys window").splitlines() if "mCurrentFocus=" in line]
        if any(f" {config.GAME_PACKAGE}/" in line for line in focus):
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
