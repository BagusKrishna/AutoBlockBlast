# Android implementation plan

Audit of the development working tree at 9ac05f5, including the pending vision patch and fourth game fixture. Use the verified autoplay entry point for all milestones. Deliver the phases independently so a speed or strategy experiment can be reversed without losing a perception fix.

## Baseline

The 15 unittest methods and the solver self-check pass. One fixture test checks four labeled screenshots at 360×800. They cover blue and pink, including a staggered piece, L and long bars. The separated-diagonal test uses a synthetic mask. No labeled sequence currently establishes what happened in the reported one-cell incident. Duplicate FFmpeg Objective-C class and pkg_resources warnings appeared at import. Investigate separately if decoder instability is observed.

Offline measurements on this Mac, in milliseconds. For each fixture, resize once to 360×800, warm each function once, then take medians of 30 parse_board calls, 30 parse_pieces calls and five default solve calls. File I/O, decoding, device calls and animation are outside these measurements.

| Fixture | Board | Three slots | Beam solver |
| --- | ---: | ---: | ---: |
| blue-start | 0.88 | 0.60 | 411.16 |
| pink-five-blocks | 0.51 | 0.70 | 19.11 |
| pink-l-shape | 0.52 | 0.47 | 2.32 |
| pink-staggered | 0.51 | 0.45 | 5.78 |

## 1. Establish when a reading is safe to act on

1. Start in autoplay.py and tests/test_verified.py. verify_transition checks the board and previously occupied surviving slots. It can accept a new piece in a previously empty slot mid-tray, and skips slot checks entirely after the last piece. Add failing tests for both, including partial refill, animations and stable full refill. Compare all three predicted slots mid-tray. For the A72, label a real last-piece sequence to confirm the ready condition. Wait for the completed refill or an identified game-end screen before authorizing another move.
2. Fix evidence capture and timing before tuning thresholds. The current after cutoff is estimated from drag start plus configured duration. Record the monotonic time immediately after the swipe command returns, before settle. Require distinct decoded frame IDs after that boundary, allow decoder lag, and require a stable transition. Advance the cursor when retrying. Preserve the last observed discrepancy if a later stable-read timeout occurs. On persistent disagreement, stop after one gesture. Keep a bounded local last-failure bundle with raw before/after game frames, intended target, predicted and observed matrices, frame times, calibration and reason. Keep it across restarts until the next failure. Render overlays from copies. Retain focus, stop and freshness checks.
3. Build session-separated labeled replays. Include fast animations, refill, line and simultaneous row/column clears, top-left and top-middle drops, diagonal pieces, shadows, 1×5 and 5×1, dense and sparse boards, empty slots, and theme transitions. Label board, each slot mask, intended versus actual landing, and whether the frame is actionable. Reserve entire sessions for evaluation. Inspect raw pixels manually before classifying a mismatch as a parser, animation, gesture, or simulation error.
4. In vision.py, distinguish known empty, occupied and uncertain. Board reading currently uses fixed HSV thresholds with a special pink-background branch that requires four qualifying samples. Test low-contrast pieces and boards with few visible empty cells. Compare a calibrated empty-cell reference and multiple interior samples on held-out themes. For tray parsing inspect component selection, assumed cell pitch, overlap between slot crops, and the long-aspect shortcut that assumes a one-cell-wide bar. Add a filled 2×4 versus 1×4 challenge if observed in game. Reject ambiguous fits and capture the reason. Repeated identical misreads can pass the current two-frame check.
5. Use the most recent validated frame for pickup geometry. Currently the pre-drag reread compares board/tray masks but the drag uses the earlier frame. Test a shifted piece that keeps its shape. Capture expected and actual landing for edge misses before changing gain or lift.

**Acceptance.** Report exact whole-board, exact three-slot and full-state accuracy, wrong accepted states, and rejected playable frames by theme/session. Require every labeled stable supported frame to parse exactly or explicitly abstain, zero wrong accepted states in the held-out set, and unchanged or better acceptance on known-good cases. Count abstentions separately to prevent passing by rejecting everything. Replay must send no second drag on mismatch, accept settled valid transitions, and stop on focus loss, stale video and stop requests. Report sample sizes and uncovered themes.

## 2. Reduce time per verified placement

1. In autoplay.py, scrcpy_stream.py and controller.py instrument monotonic spans for waiting for a fresh frame, focus checks, board/tray parsing, planning, pre-drag check, ADB swipe, animation/refill, verification, and PNG rendering/writes. Report per-stage and end-to-end median and p95, verified moves/minute, mismatches and dropped/late frames. Separate regular moves, clears and refills. The receiver timestamp records local decode time. Device capture latency needs its own measurement.
2. Start with obvious repeated work. The stream already keeps one latest BGR frame and vision already crops board and tray. Wake on a new frame ID instead of polling every 120 ms and copying the same frame again. Use the verified after-state as the next planning input while keeping a fresh pre-drag check. Generate debug PNGs on failure or explicit debug runs. Keep bounded in-memory evidence until verification completes. Benchmark each change independently.
3. Replace fixed settle (350 ms) and additional refill pause (350 ms) with post-release observation once the replay tests pass. Advance after matching stable board and tray. Keep bounded timeouts. If parsing becomes material, cache geometry by frame size/calibration and batch the 64 medians, reusing HSV statistics on the blue path. Compare every output with the baseline corpus. Reading all 64 cells is cheap here and catches an unexpected change anywhere.
4. Tune swipe duration on the A72 after state timing works. Try 600, 500, then 400 ms as experimental settings. Compare short/long travel, corners, middle, diagonals and refill. Start with three-move bounded live runs, stop at first mismatch, and extend in bounded batches across sessions to cover those cases. Record misses and actual landing errors by distance and target. Keep the fastest duration that passes the same cases, and revert a candidate that introduces a miss.

**Acceptance.** Compare paired offline workloads and comparable live move classes at the same resolution. Adopt a speed change when median and p95 verified-move latency improve without new accepted errors, misdrops or increased false stops on the covered cases. Publish denominators and seconds saved. Three successes are a smoke test only.

## 3. Choose the best move for the visible tray

1. Preserve the current complete-plan execution constraint. Within legal sequences that place every remaining piece, compare in this order: any post-placement all-clear, active combo retained under measured rules, total score gained across the sequence, then future shape flexibility. Count an all-clear even on step one or two. The initial empty board alone earns nothing. Make equal ranks deterministic by slot and coordinates. When no complete path exists, keep the current stop and distinguish proven impossibility from a search timeout.
2. Derive scoring from consecutive game-only observations. Record visible score before and after animations settle, occupied cells placed, cleared rows/columns, combo indicator, moves since clear, and tray boundary. Include ordinary placements, multiple lines in one move, consecutive clears, a gap between clears, all-clear and refill. Hand-label first and validate a candidate scoring rule on a separate session. Carry confirmed combo state across moves and tray boundaries. On mid-game startup with unknown history, expose uncertainty. Until validated, label clear moves and lines as proxies. Do not report heuristic values as game points.
3. Implement exact depth-first search of the one to three visible pieces as an offline challenger in solver.py. Encode occupancy in a 64-bit integer, precompute legal in-bounds translated masks per observed orientation, reject overlap, place with OR, and remove the union of simultaneously completed rows/columns. Enumerate remaining slot choices at each depth and return the original slot index. Include all-clear and combo history in the ranking even when two orders end on the same board. Defer memoization until correctness is established. If added, include all history that affects future rewards or retain nondominated paths. Carry already-earned all-clear and combo state when replanning the tray after a verified move.
4. Check against an independent simple NumPy exhaustive reference on small branching cases. Verify both ranks and legal paths, including crossing lines, identical shapes in distinct slots, an intermediate all-clear, a clear unlocking the next piece, and a delayed high-scoring sequence. Compare exact DFS, existing width-40 beam, and beam with the same new objective on identical boards. This separates gains from changing the objective from gains due to search. Test open boards with three small pieces as the latency stress case. Record nodes, memory, p50/p95/max solve time, complete plans and all-clears missed vs reference, and combo/score when observable. Use identical future tray sequences for simulated survival comparisons and label the draw assumption.
5. Select exact DFS as default if it meets the measured planning budget on the target Mac and matches the reference. Set that budget from phase 2 before comparing candidates. If exact is too slow on open boards, evaluate a time-bounded search seeded with a complete beam plan. Report whether optimality was proven and only execute a complete verified candidate. Keep the existing solver available for comparison and rollback.

**Acceptance.** Every exact result matches the oracle ranking on the reference suite and never misses an achievable all-clear among complete plans. Report score claims only for validated game rules. Future draws are unknown, so optimality applies to the visible tray and specified ranking.

## Execution order and handoff

First deliver the transition regressions and replay diagnostics, then perception fixes driven by labeled failures. Deliver timings before changing the drag profile. Implement the solver comparison after the verified-move pipeline is stable. For each phase run the commands below, document baseline versus candidate and the remaining gaps, and preserve unrelated development changes. Use preview for inspection and bounded hardware runs for live verification.

```sh
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m autoblockblast.solver
```

## Implementation results

Three regression tests reproduced the gaps in empty-slot verification, partial refill and pickup frame selection. Verification now waits for valid settled shapes, checks the entire expected tray after each drag and preserves the latest discrepancy when the next read times out. The same raw frame used to verify the pre-drag state supplies pickup geometry. The last-failure bundle survives a restart.

Updated offline medians on the same four resized screenshots, using the baseline sample counts.

| Fixture | Board read (ms) | Original beam (ms) | Beam with new objective (ms) | Exact DFS (ms) |
| --- | ---: | ---: | ---: | ---: |
| blue-start | 0.21 | 447.56 | 439.75 | 217.13 |
| pink-five-blocks | 0.28 | 19.78 | 20.05 | 0.20 |
| pink-l-shape | 0.22 | 2.40 | 2.43 | 0.07 |
| pink-staggered | 0.23 | 5.94 | 6.13 | 0.14 |
| Empty board, three singles | | 607.16 | 605.40 | 0.13 |

Exact DFS is the autoplay default based on these offline comparisons and its agreement with the independent exhaustive NumPy reference on seeded cases. The all-clear ranking is lexicographic. Clear moves and lines serve as provisional combo and score proxies.

On the A72, the first attempt stopped during refill on an oversized vision result. After changing that case to wait for a valid fresh frame, three bounded batches completed.

| Configured swipe | Verified | Median drag stage | Median verified move | Batch content |
| --- | ---: | ---: | ---: | --- |
| 600 ms | 3/3 | 796 ms | 2.56 s | Diagonal to upper-left, clear and refill |
| 500 ms | 3/3 | 721 ms | 1.82 s | Two five-cell pieces and refill |
| 400 ms | 3/3 | 666 ms | 2.63 s | Two top-row drops, three clear moves and refill |

The batches used successive trays. Startup cost is included in the first move of each batch. The 600 ms default is retained pending comparable repeated trials. Use `--timing` to report move stages and `--drag-ms` for bounded experiments.

The four labeled screenshots cover two themes. Additional independent sessions are needed for held-out accuracy, near-threshold themes, game-over screens and the original one-cell mismatch. Capture score and combo before and after each settled placement, the cleared rows and columns, and the tray boundary before fitting a score rule. The live batches verify transitions and do not establish score or combo behavior.

### Tray overlap regression

A five-cell bar in the left slot extended into the padded crop for the empty middle slot. The parser interpreted the clipped fragment as a vertical two-cell piece, even after the selected middle piece had landed on the correct board cells. The vision code now checks component ownership against the unpadded slot before interpreting a shape. Synthetic tests cover overlap from either side. The original game capture remains local. A follow-up Galaxy A72 run resumed from the affected board and verified three placements, including two clears and a refill.
