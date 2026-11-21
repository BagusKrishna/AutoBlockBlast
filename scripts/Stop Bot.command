#!/bin/zsh
cd -- "${0:A:h:h}" || exit 1
mkdir -p captures
touch captures/stop.request
printf 'Stop requested. An in-progress drag may finish.\n'
