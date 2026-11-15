#!/usr/bin/env bash
# Start Miguel: the server (robot link, vision, agent, voice) and the web app (control page, family app).
# Ctrl-C stops both. Someone must be at the robot (the server refuses --robot real otherwise).
#
#   ./start.sh          the real robot over Wi-Fi (laptop and robot on the hotspot)
#   ./start.sh mock     the mock robot on this laptop (nothing real moves)
set -euo pipefail
cd "$(dirname "$0")"
trap 'kill 0' INT TERM EXIT

if [[ "${1:-}" == "mock" ]]; then
  (cd server && uv run python -m mock --armed --quiet) &
  sleep 1
  (cd server && uv run --env-file .env python -m app --robot mock --no-window) &
else
  (cd server && uv run --env-file .env python -m app --robot real --someone-at-robot --no-window) &
fi
(cd web && npm run dev -- -H 0.0.0.0) &
wait
