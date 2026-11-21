#!/bin/zsh
cd -- "${0:A:h:h}" || exit 1
mkdir -p captures
./.venv/bin/python -u -m autoblockblast.autoplay 2>captures/preview.log
printf '\nPreview ended. You may close this window.\n'
read -r '?Press Enter to close: '
