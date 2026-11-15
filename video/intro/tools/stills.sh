#!/bin/bash
# Usage: tools/stills.sh <frame> [<frame> ...]  — renders review stills into out/frames using the installed Chrome.
cd "$(dirname "$0")/.."
npx remotion bundle src/index.ts --out-dir=out/bundle >/dev/null 2>&1 || { echo "bundle failed"; exit 1; }
mkdir -p out/frames
for f in "$@"; do
  npx remotion still out/bundle MiguelIntro out/frames/f$f.png --frame=$f --chrome-mode=chrome-for-testing \
    --browser-executable="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" 2>&1 | grep -E "rror" | head -3
done
