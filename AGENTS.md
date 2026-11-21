# Guidance for coding agents

Read README.md and docs/ARCHITECTURE.md before modifying this project. Follow docs/ROADMAP.md for priorities, but the user's current instructions take precedence.

Use `development` for ongoing work. `main` is reserved for stable releases. Follow docs/BRANCHING.md; do not merge or push to `main` as part of routine development unless the user explicitly requests a release.

The user prioritizes Android vision correctness first, speed second, and solver strategy third. Do not describe perception or scoring as perfect without representative evidence. Preserve foreground checks, stale-frame checks, per-move verification, stop behavior and device calibration. Never access personal phone files; capture only the foreground game and keep debug artifacts local. Do not transmit screenshots or logs externally.

Run `python -m unittest discover -s tests -v` and `python -m autoblockblast.solver` after relevant changes. Add regression fixtures for confirmed parsing bugs; use screenshots that contain only the game and avoid sensitive data. Hardware tests must be bounded and report what was actually verified. Do not assume the game is in a particular state or initiate a long autoplay session merely to run tests.

Acknowledge upstream attribution and respect repository licenses. Never commit credentials, `.venv`, scrcpy binaries, `captures/`, or user-specific device identifiers.
