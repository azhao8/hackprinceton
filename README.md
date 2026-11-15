# Miguel.exe

A two-wheeled self-balancing robot with an iPhone for a head, built at HackPrinceton (Fall 2026). Miguel lives with an older person at home: he follows them, fetches water or pills from a station on his tray, talks with them, notices a possible fall, and keeps the family in touch through an app. The design and decisions are in `docs/` (start with `docs/00-overview.md`).

```
Mom (voice) ──► robot's iPhone: face, camera, mic, speaker ─┐
Sarah ────────► family app (web/app/family) ─────────────────┤
You ──────────► control page (web, localhost:3000) ──────────┤
                                                             ▼
                Python server on the laptop (server/): vision (YOLO), the agent (Claude),
                behaviors (follow, find, go to, bring), memory (SQLite), the arbiter
                (STOP > keyboard > behaviors) and the link ──► ESP32 robot (firmware/)
```

| Path | What |
| --- | --- |
| `server/` | The brain: robot link, vision, voice (Cartesia), agent (Claude), family layer, memory |
| `web/` | The control page (`/`) and the family app (`/family`), Next.js |
| `firmware/` | The ESP32 balance firmware and the robot's phone page (`firmware/balance/phone/`) |
| `contract/` | The messages between the laptop, the robot and the apps |
| `docs/` | Overview, decisions, open questions |

## 1. Install (once)

- **macOS** laptop (tested), **Python 3.12+** with [uv](https://docs.astral.sh/uv/), **Node.js 20+**.
- For the firmware: [arduino-cli](https://arduino.github.io/arduino-cli/) with the ESP32 core 3.3.12 (`arduino-cli core install esp32:esp32@3.3.12`).

```bash
cd server && uv sync && uv run python -m app.vision.fetch_models   # Python deps + the YOLO pose weights
cd ../web && npm install
```

## 2. Keys and settings

Copy the examples and fill them in. Both files are git-ignored; never commit keys.

```bash
cp server/.env.example server/.env
cp web/.env.example web/.env.local
```

**`server/.env`** (the names are explained in `server/.env.example`):

| Name | Needed for |
| --- | --- |
| `ANTHROPIC_API_KEY` | The agent (Claude). Without it Miguel can't think: no voice commands, no family app requests |
| `CARTESIA_API_KEY` | Hearing (speech to text) and Miguel's voice. Without it he can't hear, and speaks with Safari's voice |
| `FAMILY_TOKEN` | Any password-like string. Phones need it to use the family app; without it only this laptop can |
| `ROBOT_HOST` | The robot's address (default `balancebot.local`) |
| `ROBOT_REVERSE_DRIVE` | `0` (default): the phone's back camera faces the battery side. Forward always follows the camera in use |
| `CARTESIA_MAX_CONCURRENT` | Voice requests at once (default 1; Cartesia's plan limits it) |
| Others | Voice timing, fall detection, the resident's name; see `.env.example` |

**`web/.env.local`**: `NEXT_PUBLIC_FAMILY_TOKEN` = the same value as `FAMILY_TOKEN`.

## 3. The network

Everything talks over one iPhone hotspot (ours is `miguel.exe2`):

1. Turn on **Maximize Compatibility** (the ESP32 only does 2.4 GHz).
2. Join it from the laptop. On the Mac, turn off **Auto-Join** for other Wi-Fi networks (System Settings → Wi-Fi → ⓘ), or it hops off the hotspot.
3. The terminal app you start the server from needs **Local Network** permission (System Settings → Privacy & Security → Local Network), or it can't reach the robot.

Usual addresses: hotspot 172.20.10.1, laptop 172.20.10.11, robot 172.20.10.12.

## 4. Flash the firmware (when it changes)

Put the hotspot's name and password in `firmware/balance/secrets.h` (copy `secrets.example.h`). Then, robot stopped and plugged in over USB:

```bash
cd firmware/balance && arduino-cli compile --upload --fqbn esp32:esp32:esp32s3 -p /dev/cu.usbmodem* .
```

Keep the robot **still for 3 s** after it restarts (it calibrates its tilt sensor). Details, gains and bench tools: `firmware/README.md`.

## 5. Start everything

```bash
./start.sh          # the real robot (someone must be at it)
./start.sh mock     # the mock robot on this laptop; nothing real moves
```

This starts the server and the web app; Ctrl-C stops both. The server waits for the robot if it isn't on the network yet.

Then open:

| What | Where |
| --- | --- |
| Control page (this laptop) | http://localhost:3000 |
| The robot's iPhone (Safari) | https://172.20.10.11:8443 (first time: open http://172.20.10.11:8080 and install the certificate it offers) |
| Family app (any phone on the hotspot) | http://172.20.10.11:3000/family (add `?demo` for demo data) |

On the robot's iPhone, allow the camera and the microphone.

## 6. First run with the robot

1. Lay the robot down so it can't move. If the status bar says **Tilt sensor drifting** (Miguel also says so, and Start is blocked), click **Recalibrate tilt sensor**, on the control page or on the phone (the "⋯" button).
2. Click **Start** (or Start on the phone), then hold it upright and steady: it starts balancing by itself after about a second. Let go once it holds itself.
3. **STOP** (Space) stops all driving; the robot keeps balancing. To end a run, hold the robot and click **Cut motor power** (Details). **Don't use Park**: it leans onto the kickstand, which was removed.
4. Teach him: "Miguel, this is Mom" (one person in front of him) and "Miguel, learn this station" (a station card with its marker in view).
5. Try: "Miguel, follow me", the family app's Send and Check in, the control page's **Test fall alert**.

Top speed is uncapped (up to the step generator's 3.2 m/s); raise the sliders slowly, with someone ready to catch it.

## 6b. Run the AI on this laptop (optional, no internet)

Brain, hearing and voice can each run locally on an Apple Silicon Mac instead of Claude and Cartesia. Cloud stays the default; set any of these in `server/.env` and restart. (The brain can also run on Google Gemini: `MIGUEL_LLM=gemini` with `GEMINI_API_KEY`; model `MIGUEL_GEMINI_MODEL`, default `gemini-4-hydrogen`. Like the local model, it answers the picture questions and the fall check too.)

| Switch | Local model | Speed here (M5 Pro, 48 GB) |
| --- | --- | --- |
| `MIGUEL_LLM=local` | Qwen3.8 27B through [Ollama](https://ollama.com) (`ollama pull qwen3.8:27b`); it also answers the picture questions and the fall check | first spoken sentence about 2.8 s; first start loads the model for about 30 s |
| `MIGUEL_STT=local` | Parakeet TDT 0.6B v3 with Silero VAD | a final transcript 65–90 ms after the speaker's pause |
| `MIGUEL_TTS=local` | Kokoro-82M (`MIGUEL_KOKORO_VOICE`, default `af_heart`) | 0.07 s for a short line |
| `MIGUEL_TTS=clone` | Miguel's Cartesia voice, copied by Qwen3-TTS 0.6B from `server/models/miguel-voice/full.wav` and its transcript (`MIGUEL_CLONE_REF`; make them once with `uv run --env-file .env python -m app.speech.make_voice_ref`); falls back to Kokoro | 0.24 s for "On it!", 0.5 s for a short sentence, 1.3 s for two; 3.5 s to load |

Once: `cd server && uv sync --group local` (a plain `uv sync` removes these packages again), then start once online so the models download. At the venue set `HF_HUB_OFFLINE=1`. With `MIGUEL_LLM=local` no Anthropic key is needed. Details and tuning names: `server/.env.example`.

## 7. Troubleshooting

| Symptom | Likely cause and fix |
| --- | --- |
| Control page: "Robot not connected" | The laptop isn't on the hotspot, or the robot is off. Check `ipconfig getifaddr en0` shows 172.20.10.x |
| Tilt reads nonsense / drifting warning | The tilt sensor calibrated while moving: lay it still, **Recalibrate tilt sensor** |
| One wheel oscillating | That wheel's motor is disconnected from its stepper driver: reseat the motor cable |
| Follow drives away from you | Forward follows the camera: check the camera setting on the control page and `ROBOT_REVERSE_DRIVE` |
| Miguel can't hear, or speaks with a robotic voice | Cartesia: out of credit (HTTP 402) or busy (429); check the server log |
| Family app says "offline" on a phone | `FAMILY_TOKEN` and `NEXT_PUBLIC_FAMILY_TOKEN` missing or different; restart both and reload |
| iPhone mic fails ("AudioSession…") | Reload the phone page (it switches the audio session to play-and-record) |
| Server: "Couldn't start the robot link" in an old build | Pull: the server now waits for the robot instead |

## 8. Develop and test

```bash
cd server && uv run pytest -q                           # server
cd web && npm test && npm run lint && npx tsc --noEmit  # web
node --test firmware/balance/phone/face.test.js         # the phone's face
```

Team workflow, lanes and decision rules: `CLAUDE.md`.

## Credits

- [Ultralytics YOLO](https://github.com/ultralytics/ultralytics) (AGPL-3.0): the pose model; see decision 0056.
- [PyTorch](https://pytorch.org), [OpenCV](https://opencv.org), [NumPy](https://numpy.org), [aiohttp](https://github.com/aio-libs/aiohttp), [pyserial](https://github.com/pyserial/pyserial).
- [Anthropic Claude](https://www.anthropic.com) (API): the agent and the picture checks.
- [Google Gemini](https://ai.google.dev) (API, optional, #99): the same brain on Gemini through its OpenAI-compatible endpoint.
- [Cartesia](https://cartesia.ai) (API): speech to text (Ink) and Miguel's voice (Sonic).
- [Next.js](https://nextjs.org), [React](https://react.dev), [Tailwind CSS](https://tailwindcss.com), [three.js](https://threejs.org): the web apps.
- Arduino core for ESP32 (Espressif): the firmware.
- Local AI (optional, #81): [Ollama](https://github.com/ollama/ollama) (MIT) running [Qwen3.8](https://github.com/QwenLM) (Apache-2.0); [parakeet-mlx](https://github.com/senstella/parakeet-mlx) (Apache-2.0) with NVIDIA's [Parakeet TDT 0.6B v3](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3) (CC-BY-4.0); [Silero VAD](https://github.com/snakers4/silero-vad) (MIT); [mlx-audio](https://github.com/Blaizzy/mlx-audio) (MIT) with [Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M) (Apache-2.0) and [Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS) 0.6B Base (Apache-2.0), [misaki](https://github.com/hexgrad/misaki) (Apache-2.0), [spaCy](https://spacy.io) `en_core_web_sm` (MIT) and [espeak-ng](https://github.com/espeak-ng/espeak-ng) (GPL-3.0); [Apple MLX](https://github.com/ml-explore/mlx) (MIT).
- John's balance firmware and follow gains; Grant's agent, face and behaviors; Nick's family app.
