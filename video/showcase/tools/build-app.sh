#!/bin/bash
# Builds the family app (web/) for filming: the seeded demo day, no server, and demo steps
# shortened to a watchable pace (capture/demo-timing.json). Nothing here changes how the app
# behaves for families.
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$HERE/../../web"
NEXT_PUBLIC_FAMILY_SOURCE=demo \
NEXT_PUBLIC_DEMO_TIMING="$(tr -d '\n ' < "$HERE/capture/demo-timing.json")" \
  npm run build >/dev/null
echo "built web/ for filming"
