# Server and web messages

**Family app:** `family.md` (draft v1) and `samples/family/`; types in `web/lib/family/wire.ts`.

**Current list:** the docstring at the top of `server/app/api/__init__.py` and the types in `web/lib/messages.ts` (telemetry is contract v1, angles in degrees). Server to web: `tel`, `status`, `agent`. Web to server: `estop`, `joystick`, `follow`, `say`, `settings`, `key`, `arm`, `trim` (`{"t":"trim","steps":n}`, n x 0.25° on the balance angle; `status.trim_shift` is the total shifted from this server), `agent_message`. The voice agent's endpoints are below ("Agent"). The "First draft" section is kept for history. `status` (and the phone's `GET /tel`) carries `face` with server vision, else null: `{status: idle|locked|lost, target: {cx, cy, w} | null, event: {id, kind: found|lost|waiting|too_close|gave_up} | null}` (`server/app/vision/face_state.py`); the web parser ignores it for now. Follow no longer gives up when the person leaves the picture: after a short search it waits in place (`waiting`, once per wait; status stays `lost`) and follows again when the same person (by their clothes) comes back (`found`). `gave_up` is no longer sent by follow.

## Agent (the family app and the control page; #54, draft for Nick and Alex)

The family's iOS app (decision 0052, open question P-7) talks to Miguel's agent over plain HTTP(S). Paths are relative to the server's address (`http://<laptop>:8080` or `https://<laptop>:8443` on the same Wi-Fi; a tunnel later, T-17).

**Auth.** From the laptop itself: none. From anywhere else, including through a tunnel or proxy (any `X-Forwarded-For`, `Forwarded`, `CF-Connecting-IP` or `X-Real-IP` header): `Authorization: Bearer <GUARDIAN_TOKEN>` on every request below (photos too). Wrong or missing token: 401. No `GUARDIAN_TOKEN` set on the server: 403 (laptop only).

| Request | Body / query | Answer | Sample |
| --- | --- | --- | --- |
| `POST /agent/message` | `{"text": str (1 to 1000 chars), "from": "guardian" \| "operator"}`. `from` is optional (default `guardian`); `operator` only counts from the laptop | 200 `{"ok": true, "last": N}` (`last` = newest event id, poll after it); 400 bad text; 503 agent off (`{"ok": false, "error": str}`) | `samples/agent-message.json` |
| `GET /agent/events?after=N` | `after` = the last id you have (default 0: all kept, the last 200) | `{"events": [event...], "last": N}`, events with `id > after`, oldest first | `samples/agent-events.json` |
| `GET /agent/photo/{id}.jpg` | | A robot camera JPEG (max 960 px wide) the agent attached to a `reply` (use its `data.photo_url`); the last 20 are kept, 404 after that | |
| `GET /tts?text=...` | | Miguel's voice for a line (audio/mpeg); what `data.audio_url` points at. No auth (the robot's phone uses it); 503 if the voice isn't set up | |

**Event** (`id` increases; `to` is `"guardian"`, `"senior"` or `null` = everyone):

| `kind` | `text` | `data` | Sample |
| --- | --- | --- | --- |
| `heard` | What was heard (echo of a message or the mic) | | |
| `say` | What Miguel says out loud at home | | `samples/agent-event-say.json` |
| `reply` | A message for the guardian | `photo_url` + `photo_id` (when the agent attached a photo: asked for one, or proof of a finished task), `audio_url` (when the voice is set up) | `samples/agent-event-reply.json` |
| `task` | The task | `id`, `status`: `started`/`done`/`failed`/`cancelled`, `summary` | `samples/agent-event-task.json` |
| `plan` | | `steps`: [str] | `samples/agent-event-plan.json` |
| `step` | | `index`, `status`: `running`/`done`/`failed`, `detail` | `samples/agent-event-step.json` |
| `error` | Short text | | |

Clients ignore kinds and `data` fields they don't know.

**WebSocket `/ws`:** the server also sends each new event as `{"t": "agent", ...event}` (from the moment you connect; use `GET /agent/events` for history). It accepts `{"t": "agent_message", "text": str}` (`samples/agent-message-ws.json`): from the laptop it's the operator; from elsewhere only with the guardian's `Authorization` header on the WebSocket handshake, otherwise ignored.

**WebSocket `/mic`** (the robot's phone, HTTPS): the phone's microphone stream for speech-to-text; its message format belongs to the hearing module (`server/app/speech/mic.py`). Only there when the agent is on; without `CARTESIA_API_KEY` it accepts the audio and drops it.

## First draft

**Draft.** Nick owns this interface (`docs/01-build-plan.md`). Alex (robot telemetry, arbiter) and Grant (what the robot sees, tasks) need to look before anything depends on it.

The web app (dashboard, later the phone page) talks to the Python server over one WebSocket. Each WebSocket text frame is one JSON object with a `t` field naming its type. Receivers ignore types they don't know, so new types can be added without breaking anything.

Samples, one per message type, are in `samples/`. The web app's tests check that every sample parses.

## Server to web

| `t` | When | Fields | Sample |
| --- | --- | --- | --- |
| `tel` | Every robot telemetry message, about 50 a second | Same as the robot's `tel` message in `contract/` (draft in `docs/03-software.md`): `pitch`, `rate`, `vl`, `vr`, `batt`, `state`, `fault` | `samples/tel.json` |

The server forwards `tel` as-is, so the robot contract stays the only definition of those fields. Units are SI (decision 0046): `pitch` in rad, `rate` in rad/s, `vl`/`vr` in m/s, `batt` in V. The dashboard converts pitch and rate to degrees for display only.

## Web to server

| `t` | When | Fields | Sample |
| --- | --- | --- | --- |
| `estop` | The STOP or Release button | `on`: `true` turns the e-stop on (speed and turn go to zero, the robot keeps balancing, decision 0043); `false` releases it | `samples/estop.json` |

## Not defined yet

- Joystick (`v`, `w` targets, sent by the arbiter's manual source).
- Arbiter state, so the dashboard shows what the server actually did with an e-stop instead of only what it sent.
- What the robot sees (person boxes, gestures), what it's thinking, and tasks, for the companion panel.
- Phone page messages (camera frames, face state).

## Open questions

1. Does the e-stop latch until someone releases it (as drafted), and who can release it: only the dashboard, or a gesture too?
2. Should "motors off" (mode `idle`, decision 0043) also be a dashboard button, and if so, behind a confirm?
