# AutoBlockBlast

An experimental Android Block Blast player for macOS. It reads an Android screen through scrcpy, detects the board and pieces with OpenCV, searches for placements, and sends drags over ADB. It verifies the board after each move and stops when the observed result differs from its prediction.

## Status

This project is under development. Vision and drag calibration were developed against a Samsung Galaxy A72 at 1080×2400. Game themes, device layouts and animation can change; other devices and themes require calibration and testing. Beam search is approximate, and its clear count is not the game's score or a guarantee of a high score.

## Setup

1. Install Python 3.10+ and Android Platform Tools (`adb`).
2. Enable USB debugging on the Android phone, connect it to the Mac, and authorize the Mac on the phone. Open Block Blast and keep it in the foreground.
3. Download the **scrcpy v3.2 server** from the [official release](https://github.com/Genymobile/scrcpy/releases/tag/v3.2); save the server asset as `scrcpy/scrcpy-server`. The configured server version must match the asset.
4. Set up the project:

```bash
git clone https://github.com/BagusKrishna/AutoBlockBlast.git
cd AutoBlockBlast
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
python -m autoblockblast.check_setup
```

Calibration is device-specific. Run `python -m autoblockblast.calibrate` and inspect the detected board and pieces before enabling autoplay. Drag gain and pickup offsets in `src/autoblockblast/config.py` also need to match the device; the GUI does not calibrate those values.

## Run

```bash
# Read the board and print a plan without touching the phone
python -m autoblockblast.autoplay

# Play continuously; press Control+C to stop
python -m autoblockblast.autoplay --execute --moves 0

# Play at most three moves
python -m autoblockblast.autoplay --execute --moves 3
```

On macOS the `scripts/` folder also contains launchers for preview, start and stop. An in-progress drag can finish before stop takes effect. Debug images are overwritten in the local, gitignored `captures/` directory. The phone screen must remain unlocked and Block Blast must remain in front.

## Tests

```bash
python -m unittest discover -s tests -v
python -m autoblockblast.solver
```

The screen fixtures cover only specific game states and themes, not every possible block or appearance. See [architecture](docs/ARCHITECTURE.md), [roadmap](docs/ROADMAP.md), and [agent guidance](AGENTS.md).

## Attribution

This project started from [anishrtech/blockblast-vision-bot](https://github.com/anishrtech/blockblast-vision-bot) and has been adapted with device-specific calibration, verification, tests, and planning changes. Check the upstream project's licensing before redistributing its code; no license grant was found in the upstream checkout.
