#!/bin/bash
# Renders the showcase and one clip per feature into deliverables/, with sound.
#   tools/render.sh                  → everything
#   tools/render.sh FamilyShowcase   → just that composition
# Frames are rendered as an image sequence; any frame a GPU hiccup glitched (the narrator bubble is
# WebGL) is re-rendered (tools/check_sequence.py); then it's encoded with its mix.
# Uses the installed Google Chrome: the headless shell Remotion downloads doesn't start on this Mac.
set -euo pipefail
cd "$(dirname "$0")/.."
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PY=(uv run -q --with numpy --with pillow python)
mkdir -p deliverables/clips out
npx remotion bundle src/index.ts --out-dir=out/bundle >/dev/null
render() {
  local id=$1 out=$2 audio=$3 seq=out/seq/$1
  rm -rf "$seq" && mkdir -p "$seq"
  npx remotion render out/bundle "$id" "$seq" --sequence --image-format=jpeg --jpeg-quality=95 --props='{"audio":null}' \
    --chrome-mode=chrome-for-testing --browser-executable="$CHROME" --concurrency=6 2>&1 | grep -E "rror" || true
  for pass in 1 2 3; do
    BAD=$("${PY[@]}" tools/check_sequence.py "$seq")
    [[ -z "$BAD" ]] && break
    echo "$id pass $pass: re-rendering glitched frames: $BAD"
    for f in $BAD; do
      file=$(printf '%s\n' "$seq"/*.jpeg | grep -E "[^0-9]0*${f}\.jpeg$" | sed -n 1p | xargs basename)
      npx remotion still out/bundle "$id" "$seq/$file" --frame="$f" --image-format=jpeg --jpeg-quality=95 --props='{"audio":null}' \
        --chrome-mode=chrome-for-testing --browser-executable="$CHROME" 2>&1 | grep -E "rror" || true
    done
  done
  local frames first pattern digits
  frames=("$seq"/*.jpeg)   # a glob, not ls | head: with thousands of files that pipe dies of SIGPIPE under pipefail
  first=$(basename "${frames[0]}")
  pattern=$(echo "$first" | sed -E 's/[0-9]+\.jpeg$//')
  digits=$(echo "$first" | sed -E 's/.*[^0-9]([0-9]+)\.jpeg$/\1/' | tr -d '\n' | wc -c | tr -d ' ')
  ffmpeg -nostdin -loglevel error -y -framerate 60 -i "$seq/${pattern}%0${digits}d.jpeg" -i "$audio" \
    -c:v libx264 -preset slow -crf 16 -pix_fmt yuv420p -c:a aac -b:a 256k -shortest -movflags +faststart "$out"
  echo "wrote $out"
}
ALL=(FamilyShowcase Feature1-KnowHowTheyreDoing Feature2-SendSomething Feature3-CheckIn Feature4-TheBiggerPicture)
MIX=(mix mix-day mix-send mix-checkin mix-summary)
for i in "${!ALL[@]}"; do
  id=${ALL[$i]}
  if [[ $# -gt 0 && " $* " != *" $id "* ]]; then continue; fi
  if [[ $id == FamilyShowcase ]]; then render "$id" deliverables/miguel-family-showcase.mp4 "public/audio/${MIX[$i]}.wav"
  else render "$id" "deliverables/clips/$(echo "$id" | sed -E 's/^Feature/feature-/').mp4" "public/audio/${MIX[$i]}.wav"; fi
done
