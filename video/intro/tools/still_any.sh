#!/bin/bash
# tools/still_any.sh <CompositionId> <frame> <out.png> [props-json]
cd "$(dirname "$0")/.."
npx remotion bundle src/index.ts --out-dir=out/bundle >/dev/null 2>&1 || { echo "bundle failed"; exit 1; }
npx remotion still out/bundle "$1" "$3" --frame="$2" ${4:+--props="$4"} --chrome-mode=chrome-for-testing \
  --browser-executable="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" 2>&1 | grep -E "rror|\+ " | head -5
