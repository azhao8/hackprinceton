# Server

One Python process on the laptop: the hub between the phone page, the dashboard and the robot. The architecture diagram is in `docs/03-software.md`.

## Run

```bash
cd server
uv sync
uv run pytest                       # tests; CI runs these on every PR
```

**See the server drive the mock robot** (two terminals):

```bash
uv run python -m mock --armed                     # mock robot, already balancing
uv run python -m app --robot mock --test-drive    # forward 2 s, turn left 2 s, through the arbiter
```

Every second the server logs what it sent, what the robot reports, and the link health (`ok` plus the round-trip lag, or `DOWN`).

**The robot's phone page** (John's page, served by the server):

1. Start the server (`python -m app ...`); it prints the phone's address.
2. First time on an iPhone: open `http://<laptop IP>:8080` in Safari and trust the certificate.
3. Open `https://<laptop IP>:8443` on the robot's iPhone and tap Start.
4. On the laptop, open `http://localhost:8080/control`: **STOP**/Release, **Follow ON**/off, and lines for Miguel to say. The phone page only drives the robot while Follow is ON.

The dashboard connects to `ws://localhost:8080/ws` (set `NEXT_PUBLIC_SERVER_WS_URL` in `web/`).

**The real robot over Wi-Fi** (someone at the robot, both on our hotspot):

```bash
uv run python -m app --robot real --test-drive    # finds balancebot.local; --host IP to override
```

The server never starts balancing by itself: the person at the robot holds it upright and presses `g` (for example in `firmware/balance/teleop.py`). Until then the commands do nothing.

Secrets go in `server/.env` (git-ignored); the names are in `.env.example`.

## Layout and owners

Stay in your own folders (CLAUDE.md). A PR that touches someone else's says so and gets their OK.

| Path | Owner | What |
| --- | --- | --- |
| `app/__main__.py` | Alex | Starts everything in one asyncio loop |
| `app/arbiter.py` | Alex | Picks one command: e-stop > joystick > skill |
| `app/link/` | Alex | The link interface, and UDP to the robot or the mock (contract v1); Grant's serial link goes here too |
| `mock/` | Alex | The mock robot: behaves like the firmware over UDP (contract v1) |
| `app/api/` | Alex (W-6) | Hosts the phone page (HTTPS), its endpoints, the control page, and the dashboard WebSocket |
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
