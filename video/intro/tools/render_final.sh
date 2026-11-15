#!/bin/bash
# Renders the intro as an image sequence, re-renders any glitched frame, then encodes with the mix.
#   tools/render_final.sh <out.mp4> <props-json> <audio.wav>
set -euo pipefail
cd "$(dirname "$0")/.."
OUT=$1; PROPS=$2; AUDIO=$3
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
SEQ=out/seq_render
rm -rf "$SEQ" && mkdir -p "$SEQ"
npx remotion bundle src/index.ts --out-dir=out/bundle >/dev/null
npx remotion render out/bundle MiguelIntro "$SEQ" --sequence --image-format=jpeg --jpeg-quality=96 --props="$PROPS" \
  --chrome-mode=chrome-for-testing --browser-executable="$CHROME" --concurrency=4 2>&1 | grep -E "rror" || true
for pass in 1 2 3; do
  BAD=$(uv run -q --with numpy --with pillow python tools/check_sequence.py "$SEQ")
  [[ -z "$BAD" ]] && break
  echo "pass $pass: re-rendering glitched frames: $BAD"
  for f in $BAD; do
    file=$(ls "$SEQ" | grep -E "[^0-9]0*${f}\.jpeg$" | head -1)
    npx remotion still out/bundle MiguelIntro "$SEQ/$file" --frame="$f" --image-format=jpeg --jpeg-quality=96 --props="$PROPS" \
      --chrome-mode=chrome-for-testing --browser-executable="$CHROME" 2>&1 | grep -E "rror" || true
  done
done
FIRST=$(ls "$SEQ" | head -1)
PATTERN=$(echo "$FIRST" | sed -E 's/[0-9]+\.jpeg$//')
DIGITS=$(echo "$FIRST" | sed -E 's/.*[^0-9]([0-9]+)\.jpeg$/\1/' | tr -d '\n' | wc -c | tr -d ' ')
ffmpeg -loglevel error -y -framerate 60 -i "$SEQ/${PATTERN}%0${DIGITS}d.jpeg" -i "$AUDIO" \
  -c:v libx264 -preset slow -crf 15 -pix_fmt yuv420p -c:a aac -b:a 256k -shortest -movflags +faststart "$OUT"
echo "wrote $OUT"
