#!/bin/bash
# tools/stills_multi.sh <out-prefix> <frame> [<frame> ...] — renders MiguelIntro stills (one bundle) with installed Chrome
cd "$(dirname "$0")/.."
npx remotion bundle src/index.ts --out-dir=out/bundle >/dev/null 2>&1 || { echo "bundle failed"; exit 1; }
p=$1; shift
for f in "$@"; do
  npx remotion still out/bundle MiguelIntro "${p}${f}.png" --frame=$f --chrome-mode=chrome-for-testing \
    --browser-executable="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" 2>&1 | grep -E "rror" | head -3
done
