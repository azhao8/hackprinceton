#!/bin/bash
# One-command build of the Miguel intro.
#   tools/build.sh             → deliverables/miguel-intro.mp4 (Corey's saved take if present, otherwise no dialogue)
#   tools/build.sh --new-voice → asks Cartesia for a fresh take of Corey's lines first
#   tools/build.sh --preview   → also deliverables/miguel-intro_PLACEHOLDER-VOICE.mp4 (macOS voice, timing review only)
# The video is rendered as an image sequence, glitched frames are re-rendered, then it is encoded with the mix
# (tools/render_final.sh).
set -euo pipefail
cd "$(dirname "$0")/.."
PY=(uv run -q --with numpy --with scipy python)
mkdir -p deliverables

npx tsx tools/export_motion.ts

if [[ " $* " == *" --new-voice "* ]] || [[ ! -f public/audio/voice/line1.wav ]]; then node tools/voice.mjs || true; fi
if [[ -f public/audio/voice/line1.wav ]]; then
  "${PY[@]}" tools/voice_env.py public/audio/voice public/audio/voice-env.json
  "${PY[@]}" tools/synth_audio.py --voice-dir public/audio/voice --out mix
  PROPS='{"audio":null,"voiceEnvelope":"audio/voice-env.json"}'
else
  echo "No Corey voice: rendering music + sound effects only."
  "${PY[@]}" tools/synth_audio.py --voice-dir public/audio/voice --out mix
  PROPS='{"audio":null,"voiceEnvelope":null}'
fi
tools/render_final.sh deliverables/miguel-intro.mp4 "$PROPS" public/audio/mix.wav

if [[ " $* " == *" --preview "* ]]; then
  node tools/voice.mjs --placeholder
  "${PY[@]}" tools/voice_env.py public/audio/voice-placeholder public/audio/voice-env-placeholder.json
  "${PY[@]}" tools/synth_audio.py --voice-dir public/audio/voice-placeholder --out mix_placeholder_voice
  tools/render_final.sh deliverables/miguel-intro_PLACEHOLDER-VOICE.mp4 \
    '{"audio":null,"voiceEnvelope":"audio/voice-env-placeholder.json"}' public/audio/mix_placeholder_voice.wav
fi
