#!/bin/zsh
cd -- "${0:A:h:h}" || exit 1
mkdir -p captures
./.venv/bin/python -u -m autoblockblast.autoplay --execute --moves 0 2>captures/runtime.log
printf '\nSession ended. You may close this window.\n'
read -r '?Press Enter to close: '
