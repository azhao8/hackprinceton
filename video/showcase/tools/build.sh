#!/bin/bash
# The whole showcase from scratch: build the app for filming, capture it, voice (only with --new-voice,
# since it spends Cartesia credits), lip sync, sound, render.
set -euo pipefail
cd "$(dirname "$0")/.."
tools/build-app.sh
node capture/capture.mjs
if [[ " $* " == *" --new-voice "* ]]; then node --env-file=.env tools/voice.mjs; fi
uv run -q --with numpy --with scipy python tools/lipsync.py
npx tsx tools/export_events.ts
uv run -q --with numpy --with scipy python tools/synth_audio.py
tools/render.sh
tools/frames.sh
