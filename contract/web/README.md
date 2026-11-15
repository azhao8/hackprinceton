# Server and web messages

**Family app:** `family.md` (draft v1) and `samples/family/`; types in `web/lib/family/wire.ts`.

**Current list:** the docstring at the top of `server/app/api/__init__.py` and the types in `web/lib/messages.ts` (telemetry is contract v1, angles in degrees). Server to web: `tel`, `status`. Web to server: `estop`, `joystick`, `follow`, `say`, `settings`, `key`, `arm`. `status` (and the phone's `GET /tel`) carries `face` with server vision, else null: `{status: idle|locked|lost, target: {cx, cy, w} | null, event: {id, kind: found|lost|too_close|gave_up} | null}` (`server/app/vision/face_state.py`); the web parser ignores it for now. The text below is the first draft, kept for history.

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
