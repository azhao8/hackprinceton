# Server

One Python process on the laptop: the hub between the phone page, the dashboard and the robot. The architecture diagram is in `docs/03-software.md`.

## Run

```bash
cd server
uv sync
uv run python -m app --robot mock   # the server (today: arbiter only, commands are logged)
uv run pytest                       # tests; CI runs these on every PR
```

Secrets go in `server/.env` (git-ignored); the names are in `.env.example`.

## Layout and owners

Stay in your own folders (CLAUDE.md). A PR that touches someone else's says so and gets their OK.

| Path | Owner | What |
| --- | --- | --- |
| `app/__main__.py` | Alex | Starts everything in one asyncio loop |
| `app/arbiter.py` | Alex | Picks one command: e-stop > joystick > skill |
| `app/link/` | Alex | JSON over UDP to the robot or the mock (next, with the contract) |
| `mock/` | Alex | The mock robot (next, with the contract) |
| `app/api/` | Nick | WebSocket for the phone page and the dashboard |
| `app/vision/` | Grant | Frame source and perception (#3) |
| `app/speech/` | Grant | Speech in and out |
| `app/brain/` | Grant | The agent: Claude picks skills |
| `app/skills/` | Grant | Skill API (draft) and skills |
| `app/memory/` | Grant | World memory |
| `tests/` | Everyone | One test file per module |

## Rules that shape the code

- **One asyncio loop** (open question T-7). Blocking work, such as MediaPipe on every frame, runs in its own thread or process and hands over its latest result.
- **Only the arbiter decides motion.** Skills call `ctx.drive(v, w)`; the API sends e-stop and joystick to the arbiter. Nothing else talks to the link.
- **The LLM picks skills; it never sends speeds** (CLAUDE.md).
- **Units:** SI with ROS REP 103 directions. `v` is m/s (+ forward), `w` is rad/s (+ turning left).
- **Dependencies:** add them with `uv add <package>` in your own PR; the lock file is committed.
