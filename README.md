# AutoBlockBlast

AutoBlockBlast runs on a Mac and plays **Block Blast on an Android phone connected through ADB over USB or Wi-Fi**. Use it to preview the bot's suggested placements or let it play automatically. It reads the board and tray from a scrcpy video stream, searches the legal placements for the visible pieces, and verifies the result after every ADB drag.

## Preview

| Galaxy A72 gameplay | AutoBlockBlast for Mac |
| --- | --- |
| <img src="docs/media/autoplay.gif" width="280" alt="Five autoplay moves on a Galaxy A72 with the live score visible"> | <img src="docs/media/desktop-preview.png" width="470" alt="Mac app showing the final score, highest combo, and jumping ASCII dino"> |

The recording shows five verified placements and a score increase from **835,965** to **836,142**. The Mac preview shows the final score and highest combo from that run alongside the current solver picker.

## Tested setup

| Component | Tested configuration |
| --- | --- |
| Host | Apple silicon Mac with Python 3.12 |
| Phone | Samsung Galaxy A72 at 1080 × 2400, connected over USB with ADB |
| Video | scrcpy server v3.2, decoded at 360 × 800 |
| Game | Android Block Blast, with blue and pink screenshot fixtures |

Other Android devices may need board, tray and drag calibration. The tested setup covers Android. Support for additional game themes and device layouts depends on validation.

The default solver searches every legal order and position for the pieces it can see. It first favors a complete tray that produces an all-clear. It then favors clearing multiple lines in the same placement by adding the square of each placement's clear count. Total lines, number of clearing placements and space for future pieces break ties. The weighting is a scoring heuristic.

## Setup

1. Install Python 3.10+ and Android Platform Tools (`adb`).
2. Enable USB debugging on the Android phone, connect it to the Mac, and authorize the Mac on the phone. Open Block Blast and keep it in the foreground.
3. Download the **scrcpy v3.2 server** and save it as `scrcpy/scrcpy-server` inside the checkout. The configured version must match the download. [scrcpy v3.2 release](https://github.com/Genymobile/scrcpy/releases/tag/v3.2)
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

## Connect over Wi-Fi

Wireless debugging requires Android 11 or newer, a recent Android SDK Platform Tools installation, and the Mac and phone on the same Wi-Fi network. Turn on **Wireless debugging** under Developer options on the phone and allow it on the network.

Select **Pair device with pairing code**. On the Mac, run the following command using the IP address and pairing port shown on that pairing screen, then enter the six-digit code when prompted.

```sh
adb pair PHONE_IP:PAIRING_PORT
```

Check `adb devices`. If the phone does not appear as a connected device, use the **IP address & Port** on the main Wireless debugging screen. This port can differ from the pairing port.

```sh
adb connect PHONE_IP:DEBUGGING_PORT
adb devices
```

Once the Wi-Fi connection is listed as `device`, disconnect the USB cable and use the desktop app or Terminal commands normally. USB remains available by connecting the cable and enabling USB debugging. The bot currently requires exactly one ADB device entry, so when both USB and Wi-Fi entries are present, disconnect one transport before starting. Wi-Fi reconnection or a new debugging port may be needed after changing networks or restarting the phone.

See the [Android wireless debugging guide](https://developer.android.com/tools/adb#connect-to-a-device-over-wi-fi) for pairing and troubleshooting.

## Mac desktop app

While playing, the app shows a jumping ASCII dino and a session timer next to the move count.

Build the app once from the project folder with `desktop/build-app.sh`. This requires Apple's Swift compiler and the Python environment from setup. Double-click `AutoBlockBlast.app` in the project folder to open it.

Connect the phone, open Block Blast and click **Start**. **Pause** finishes the current move and waits, then **Resume** continues after checking the game state. When paused, choose **OneLine** for more clearing placements or **MultiLine** for clears that combine several lines in one placement. An interrupted session can resume with its elapsed time and move count preserved. **Stop** ends the session after the current move. The app reads the current score and tracks the highest combo recognized during the current autoplay session. A lower reading leaves that record in place. Starting a new session resets the displayed combo record. The app also shows verified moves and any stopping reason.

## Run in Terminal

The default swipe duration is 150 ms. Swipes that travel horizontally across at least a third of the display use 250 ms to give the game more time to track the drag. If a swipe leaves the board and tray unchanged, autoplay confirms that state on fresh frames and retries the placement at 250 ms, then at 400 ms if the board and tray are still unchanged. Use `--drag-ms` during a bounded run to test a different duration.

```bash
# Read the board and print a plan without touching the phone
.venv/bin/python -m autoblockblast.autoplay

# Play continuously; press Control+C to stop
.venv/bin/python -m autoblockblast.autoplay --execute --moves 0

# Play at most three moves
.venv/bin/python -m autoblockblast.autoplay --execute --moves 3

# Audit plan consistency and alternate pre-drag checks by tray
.venv/bin/python -m autoblockblast.autoplay --execute --moves 100 --audit --compare-recheck --timing

# Use the faster pre-drag check and reuse the remaining exact plan
.venv/bin/python -m autoblockblast.autoplay --execute --moves 3 --fast-recheck --reuse-plan

# Test a different swipe duration using a bounded run
.venv/bin/python -m autoblockblast.autoplay --execute --moves 3 --drag-ms 500 --timing

# Test reuse of verified frames and pickup coordinates inside a planned tray
.venv/bin/python -m autoblockblast.autoplay --execute --moves 18 --drag-ms 500 --fast-recheck --reuse-plan --chain-tray --timing

# Test earlier verification of clears before the tray refills
.venv/bin/python -m autoblockblast.autoplay --execute --moves 18 --drag-ms 500 --fast-recheck --early-clear --audit --timing
```

On macOS the `scripts/` folder also contains launchers for preview, start and stop. An in-progress drag can finish before stop takes effect. The phone screen must remain unlocked and Block Blast must remain in front.

The most recent failed verification is stored locally in `captures/last-failure/`. Its JSON report records the intended move and the predicted and observed state. Raw game frames are stored when available. Restarting the bot keeps the report until a later verification failure replaces it. Preview saves a board overlay. Pass `--debug` to also save successful before/after frames. The capture directory is gitignored.

Audit results are appended locally to `captures/audit.jsonl`, which is ignored by Git. Each session records move coordinates, timings, and whether the original plan matched later calculations. Audit mode recalculates after every placement for comparison.

The Mac app uses the faster pre-drag check and reuses the remaining exact plan after each verified move. The faster pre-drag check confirms that a fresh video frame matches the previously stabilized board and tray. If the frame differs or fails to arrive promptly, it falls back to the full stable read. The bot verifies every placement against the predicted board and tray before reusing the rest of a plan. Resuming after a pause starts with a fresh board read and calculation. The app uses `--chain-tray` to reuse the recent verified frame for the next move within a tray. If a newer frame is available, the bot checks it immediately and falls back to the regular pre-drag check if the decoded board or tray differs. It reuses pickup coordinates when they match the last state and takes updated coordinates from the existing frame read if the piece shifted. The foreground and post-drag checks still run. In chained play, two fresh frames that match the full predicted board and remaining tray can confirm a clear without a minimum time gap between the frames. The app can continue while an effect is still visible if the board and tray match. Tray refills still use the full stability check. If a pre-drag read differs, the bot waits for the original state or corroborates the changed state with another stable read. It can recalculate once before the next swipe. When the solver finds no complete plan, it checks for a changed board or tray before stopping. Every swipe still requires post-drag verification.

Use `--solver beam` to compare the original beam search or `--solver beam-all-clear` to try width-40 beam search that prioritizes all-clear and individual clearing placements.

## Troubleshooting

- **No fresh, stable game state.** Keep the game visible, dismiss any overlays, and wait for animations to settle. Run preview to check the board and tray before resuming autoplay.
- **Board or tray mismatch.** If two stable reads confirm exactly one alternate legal landing and the expected tray transition, the bot recalculates from that board. For a mismatch that cannot be verified, open `captures/last-failure/transition.json` to inspect the expected and observed states. Keep any accompanying images local.
- **Changes appear missing.** Run the command from the `AutoBlockBlast` checkout that contains this README. The original `blockblast-vision-bot` checkout has a separate entry point.

## Tests

```bash
python -m unittest discover -s tests -v
python -m autoblockblast.solver
```

The tests cover known screen patterns, tray verification and the exact solver. See [architecture](docs/ARCHITECTURE.md), [Android validation results](docs/ANDROID-IMPLEMENTATION-PLAN.md), and [branch workflow](docs/BRANCHING.md).

## Attribution

This project started from [anishrtech/blockblast-vision-bot](https://github.com/anishrtech/blockblast-vision-bot) and has been adapted with device-specific calibration, verification, tests, and planning changes. Check the upstream project's licensing before redistributing its code; no license grant was found in the upstream checkout.
