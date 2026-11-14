# Server

One Python process on the laptop: the hub between the phone page, the dashboard and the robot. The architecture diagram is in `docs/03-software.md`.

## Run

```bash
cd server
uv sync
uv run python -m app.vision.fetch_models      # once: the YOLO pose weights into server/models/
uv run pytest -q                              # tests; CI runs these on every PR
```

**Mock robot, camera and debug window** (two terminals; nothing real moves):

```bash
uv run python -m mock                         # terminal 1: the mock robot on 127.0.0.1:4210 (--armed: already balancing)
uv run python -m app --source 0               # terminal 2: the server, camera 0, debug window
uv run python -m app --source clip.mov        # the same on a recorded clip
```

**See the server drive the mock robot** without a camera:

```bash
uv run python -m mock --armed                                 # mock robot, already balancing
uv run python -m app --robot mock --test-drive --no-vision    # forward 2 s, turn left 2 s, through the arbiter
```

Every second the server logs what it sent, what the robot reports, and the link health (`ok` plus the round-trip lag, or `DOWN`). The debug window shows the same.

**The real robot over USB** (someone at the robot, ready to catch it; first test only turns to face you):

```bash
uv run python -m app --robot real --link serial --someone-at-robot --turn-only    # --port to pick the port
```

**The real robot over Wi-Fi** (someone at the robot, both on our hotspot):

```bash
uv run python -m app --robot real --someone-at-robot --test-drive --no-vision    # finds balancebot.local; --host IP to override
```

`python -m app` runs one asyncio loop at 20 Hz: the arbiter picks a command (e-stop > joystick > skill) and the robot link sends it. `--link udp` (the default) talks to the mock on 127.0.0.1, or to the real robot at `$ROBOT_HOST` / `balancebot.local`; `--link serial` talks to the robot over its USB cable. `--robot real` **refuses to start without `--someone-at-robot`**. Start the server yourself in Terminal: macOS only gives the camera to programs a person starts. Other flags: `--rotate left|right|180`, `--camera-back`, `--height-m`, `--tilt-deg`, `--turn-only`, `--follow` (start following at once), `--no-window`, `--no-vision`, `--test-drive`; `--help` lists them.

Keys in the debug window:

| Key | Does |
| --- | --- |
| F | Start or stop the follow skill (locks onto the close person nearest the center) |
| Space | E-stop on or off (on: sends `5` once, then speed and turn 0; the robot keeps balancing; the skill ends) |
| G | Over USB: arm the robot (`g`). Someone holds it upright and lets go once it balances. Ends any running skill first. Over Wi-Fi the server never sends `g`: the person at the robot arms it (`firmware/balance/teleop.py`), or start the mock with `--armed` |
| P | Park on the kickstand (`P`); ends the skill |
| X | Motors off (`x`); ends the skill |
| Q / Esc | Quit |

The server never starts balancing by itself. Quitting, Ctrl+C, SIGTERM or a crash cancels the skill, sends `x` (motors off), closes the link, stops vision and closes the window.

**Camera trouble:**

- *The camera won't open, or another program has it:* a server or `follow` run from earlier may still hold it. Find it with `ps aux | grep -i "python -m app"` and stop it.
- *The window shows solid black frames from the phone (Continuity Camera):* on Nov 14 the Mac's peer-to-peer Wi-Fi link was off (`ifconfig awdl0` showed no `UP`). `sudo ifconfig awdl0 up` fixed it at once. See `firmware/README.md`. Also check the phone is locked, not paused, and nobody is touching it.

Secrets go in `server/.env` (git-ignored); the names are in `.env.example`.

## The phone page, control page and dashboard (the API)

**Vision runs on the server** (decision 0055). By default (`--source phone`) the robot's phone page streams its camera to `POST /frame`; YOLO pose finds people, Follow on the control page runs the server's follow skill, and the control page shows the server's view (`/video.mjpg`). First time: `uv run python -m app.vision.fetch_models` (downloads `yolo26n-pose.pt`, git-ignored). For desk testing without the phone use `--source 0` (laptop camera) or a video file; `--no-vision` turns it off.

`python -m app` also starts the API (`--no-api` turns it off):

1. First time on an iPhone: open `http://<laptop IP>:8080` in Safari and trust the certificate.
2. On the robot's iPhone, open `https://<laptop IP>:8443` (John's phone page) and tap Start.
3. On the laptop, open `http://localhost:8080/control`: **STOP**/Release, phone **Follow ON**/off, and lines for Miguel to say.

The phone page only drives the robot while its Follow is ON. Turning it on stops any server skill (such as the server's own follow, F), and STOP ends both. The dashboard connects to `ws://localhost:8080/ws`.

## Miguel's voice (Cartesia)

Without a key, the phone page speaks with Safari's built-in voice. With one, it speaks in a Cartesia voice (`sonic-3.6`):

1. Copy `.env.example` to `.env` and type your key after `CARTESIA_API_KEY=` yourself. Never commit it or paste it into a chat. Optionally set `CARTESIA_VOICE_ID` (pick a voice in Cartesia's voice library), `CARTESIA_MODEL` and `CARTESIA_SPEED`.
2. Start the server with the file loaded: `uv run --env-file .env python -m app ...`. The log says which voice is in use.
3. On the phone page, tap Start once (iOS only plays audio after a tap).

The server makes each line with Cartesia (`GET /tts?text=...`, an mp3), caches it, and makes the stock lines at startup. If Cartesia or the network fails, the phone falls back to Safari's voice for that line.

## Layout and owners

Stay in your own folders (CLAUDE.md). A PR that touches someone else's says so and gets their OK.

| Path | Owner | What |
| --- | --- | --- |
| `app/__main__.py` | Alex | Starts everything in one asyncio loop: link, arbiter, vision worker, skills, debug window, keys |
| `app/arbiter.py` | Alex | Picks one command: e-stop > joystick > skill |
| `app/link/` | Alex | The link interface, and UDP to the robot or the mock (contract v1); Grant's serial link goes here too |
| `mock/` | Alex | The mock robot: behaves like the firmware over UDP (contract v1) |
| `app/api/` | Alex (W-6) | Hosts the phone page (HTTPS), its endpoints, the control page, and the dashboard WebSocket |
| `app/vision/` | Grant | Perception (#3): frame source, YOLO pose detector, target lock, follow controller; `worker.py` runs them on a thread and publishes the newest `Perception`; `debug_view.py` draws the window |
| `app/speech/` | Grant | Speech in and out |
| `app/brain/` | Grant | The agent: Claude picks skills |
| `app/skills/` | Grant | Skill API (draft: `ctx.drive`, `ctx.stop`, `ctx.perception`, `ctx.vision`) and skills: `follow.py` |
| `app/memory/` | Grant | World memory |
| `tests/` | Everyone | One test file per module |

## Rules that shape the code

- **One asyncio loop** (open question T-7). Blocking work, such as YOLO on every frame, runs in its own thread or process and hands over its latest result (`app/vision/worker.py`).
- **Only the arbiter decides motion.** Skills call `ctx.drive(v, w)`; the API sends e-stop and joystick to the arbiter. Nothing else talks to the link.
- **The LLM picks skills; it never sends speeds** (CLAUDE.md).
- **Units:** SI with ROS REP 103 directions. `v` is m/s (+ forward), `w` is rad/s (+ turning left).
- **Dependencies:** add them with `uv add <package>` in your own PR; the lock file is committed.

## Credits

- [Ultralytics YOLO](https://github.com/ultralytics/ultralytics) (AGPL-3.0): the pose model and its runtime (open question T-15 is about the license).
- [PyTorch](https://pytorch.org) (BSD-3-Clause): runs the model.
- [OpenCV](https://opencv.org) (Apache-2.0): camera capture, image handling, the debug window.
- [NumPy](https://numpy.org) (BSD-3-Clause).
- [pyserial](https://github.com/pyserial/pyserial) (BSD-3-Clause): the USB link to the robot.
- [Cartesia](https://cartesia.ai) (paid API, `sonic-3.6`): Miguel's voice.
- The follow gains come from John's `firmware/balance/follow/follow.swift`, tuned on the real robot.
