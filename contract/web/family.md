# Family app ↔ server (v1, draft)

What the family app (`web/app/family`, PR #57) needs from the server, so Alex can build the server's side (W-6) and Grant knows which events and skills feed it. Use case: decision 0052 (a caretaker robot in a senior's home, directed by their children).

**Draft for review.** Nick wrote it from the app's side. Alex (API, server core) and Grant (agent, skills, vision) need to agree before anything depends on it. Open points are at the end and in `docs/open-questions.md`.

## Shape

- **One WebSocket per app:** `wss://<server>/family/ws`. Same JSON-per-frame style as the dashboard's `/ws` (`contract/web/README.md`): every frame is one object with a `t` field; receivers ignore types they don't know.
- **Reaching home:** the server's HTTPS port through a tunnel (T-17). On the demo hotspot, `ws://<laptop-ip>:8080/family/ws` also works.
- **State is sent whole, not as diffs.** The server sends `state` (small) whenever anything in it changes, at most 5 times a second, plus the day's `events` once and each new `event` as it happens. The app never has to reconstruct anything.
- **Requests carry `ref`,** a string the app makes up. The server answers each one with `ack` (`ok: true`) or `error` with the same `ref` (standard request/response correlation).
- **Times** are ISO 8601 with the home's UTC offset (`2026-11-14T16:12:00-05:00`). `welcome.tz` gives the home's time zone, so the app shows Mom's local time even when her daughter is three time zones away.
- **Names** are snake_case, like `lag_ms` in the dashboard's `status`.
- **Keepalive:** WebSocket ping every 20 s (aiohttp `heartbeat=20`). The app reconnects with backoff; the server answers every new `hello` with `welcome` and a full snapshot.

## Sign-in

The first frame from the app is `hello` with a token. Anything else first, or a wrong token, gets `error` (`code: "unauthorized"`) and the socket closes. The token goes in the message, never in the URL.

For the weekend: one shared token in the server's `.env` as `FAMILY_TOKEN` (Alex adds the name to `server/.env.example` with the API). Per-person tokens from Manage → Invite come later (T-18).

## Server → app

| `t` | When | Fields | Sample |
| --- | --- | --- | --- |
| `welcome` | Reply to `hello` | `v` (1), `resident {name, short}`, `viewer {id, name}`, `tz` (IANA zone of the home), `now` | `welcome.json` |
| `state` | After `welcome`, then on every change | `mode`, `mode_note`, `since`, `link` (`up`/`down`), `delivery`, `check_in`, `alert` (see below) | `state-with-mom.json`, `state-delivering.json`, `state-check-in.json`, `state-alert.json` |
| `events` | After `welcome`: today so far, oldest first | `day` (date), `items[]` of event | `events.json` |
| `event` | Each new thing in her day | one event | `event.json` |
| `routines` | After `welcome` and when one changes | `items[] {id, kind, title, schedule, detail, on}` | `routines.json` |
| `circle` | After `welcome` and when it changes | `items[] {id, name, relation, access, you?, invited?}` | `circle.json` |
| `pace` | After `welcome`, and once a day | `days[] {date, mps}`, last 7 days, oldest first | `pace.json` |
| `ack` | A request worked | `ref`, `ok: true`, optional `id` (what it created) | `ack.json` |
| `error` | A request didn't | `ref` (if any), `code`, `message` (for people) | `error.json` |
| `rtc` | Check-in video setup, relayed from the robot's phone page | `call`, and `sdp {type, sdp}` or `candidate` | `rtc-answer.json` |
| `frame` | Only in the no-WebRTC fallback, while a check-in is `live` | `call`, `jpeg` (base64) | `frame.json` |

### Inside `state`

**`mode`**, and how the server works it out (first match wins):

| `mode` | When |
| --- | --- |
| `offline` | No robot telemetry for 3 s, or the phone page isn't connected |
| `delivering` | A delivery is in progress |
| `listening` | Miguel's mic is open (he asked her something, or she's talking to him) |
| `night_light` | The night routine is on and she's up (or he's walking with her at night) |
| `with_mom` | Follow is on and has her, or she's within sight and he's parked near her |
| `charging` | On the dock. Needs a battery reading (C-10); until then send `idle` |
| `idle` | Anything else (waiting in her room) |

`mode_note` is one short line for people ("In the living room with her"). `since` is when the mode started.

**`delivery`**: `null`, or `{id, item, label, message?, stage, detail?, photo?}`.
- `item`: `water` | `medication` | `note` | `other`.
- `stage`: `sent` → `loading` (waiting at the station for someone to load the tray) → `on_the_way` → `delivered`, or `failed` with `detail` ("Nothing was put on the tray in 5 minutes", "Couldn't find her").
- `photo`: a media URL (see Media) of her with the item, taken when it's delivered (P-7).
- One delivery at a time: a `send` while one is in progress gets `error` `busy`.

**`check_in`**: `{phase, id?, started_at?}` with `phase` `idle` | `asking` | `live` | `declined`.

**`alert`**: `null`, or `{id, kind: "possible_fall", at, place?, saw, heard?, did[], status, handled_by?, photo?}`.
- `saw`: what vision noticed, in words. `heard`: what she said when Miguel asked if she was okay (speech to text), if anything.
- `did`: what Miguel did, in order ("Asked if she was okay", "Told David", "Staying beside her").
- `status`: `active` | `handled`. `handled_by` names who answered it; every app sees the same alert change.
- Raised by the agent when the fall detector fires (Grant). The control page can raise it too, for testing.

### Events

`{id, at, kind, title, note?, quote?, quote_by?, photo?}`. `kind` is one of: `wake`, `walk`, `water`, `medication`, `meal`, `rest`, `message`, `check_in`, `company`, `night_light`, `delivery`, `alert`. Titles and notes are written for people, by the server ("Morning pills", "Miguel asked; she said she took them").

Where they come from:

| Source | Events |
| --- | --- |
| Vision (Grant) | `wake` (first time up), `walk` (walked with Miguel; `note` has distance), `rest` |
| Skills (Grant) | `water`, `medication`, `delivery` (delivered), `night_light` |
| Agent (Grant) | `medication` (her answer when reminded), `message` (a note or voice note played) |
| Server (Alex) | `check_in` (with length), `alert` (raised, then handled) |

**Walking pace** (`pace`): Miguel's wheel speed while he follows her steadily on a walk, averaged per day (telemetry `vl`/`vr`, contract v1).

## App → server

| `t` | Fields | What the server does | Sample |
| --- | --- | --- | --- |
| `hello` | `v`, `token`, `viewer` (member id) | Signs in; sends `welcome` and snapshots | `hello.json` |
| `send` | `ref`, `item`, `label`, `message?`, `voice_note?` (media id) | Starts the deliver skill (below); `ack` with the delivery `id` | `send.json` |
| `check_in` | `ref`, `action`: `request` \| `end` | `request`: Miguel asks her, `state.check_in` goes `asking`, then `live` or `declined`. `end`: stops the call | `check-in-request.json` |
| `rtc` | `call`, `sdp` or `candidate` | Relays to the robot's phone page, **only while `check_in` is `live`**; otherwise `error` `no_consent` | `rtc-offer.json` |
| `talk` | `ref`, `media` (id) | The robot's phone page plays the clip out loud | `talk.json` |
| `alert` | `ref`, `id`, `action`: `handled` | Marks the alert handled by this person, tells everyone | `alert-handled.json` |
| `routine` | `ref`, `id`, `on` | Turns a routine on or off; sends `routines` | `routine.json` |
| `invite` | `ref`, `name`, `relation` | Adds them to the circle as invited (no real invite yet); sends `circle` | `invite.json` |

## Media (HTTP)

- **Voice clips:** `POST /family/media` with the recording as the body (`audio/mp4` from iPhone Safari, or `audio/webm`), header `Authorization: Bearer <token>`, at most 60 s and 2 MB. Answers `{"id": "...", "seconds": 4.2}`; the app then sends that `id` in `send.voice_note` or `talk.media`.
- **Photos** (delivery proof, alert snapshot): the server stores them and puts a URL in the message: `/family/media/<id>`. Ids are random 128-bit values, so the URL itself is the permission (an `<img>` tag can't send a header); they expire after 24 h. No names or other personal details in any URL.

## What each request makes the robot do

**`send` → the deliver skill** (Grant; P-5 station):
1. Tell whoever stocks the station what's needed (control page or a line on the robot's speaker), and drive to the station marker. `stage: sent`.
2. Wait until it's loaded: a thumbs-up to the camera, or the "Loaded" button on the control page. `stage: loading`. Give up after 5 minutes (`failed`).
3. Find her (turn in place, look for the person), drive over, stop at follow distance. `stage: on_the_way`. Give up after 2 minutes of not finding her (`failed`).
4. Say the message (Cartesia `/tts`) or play the voice note; ask her to take the item; take the photo. `stage: delivered`, plus an `event`.

**`check_in: request` → ask first** (Grant for the asking, Nick for the phone page, Alex for the relay):
1. Miguel says: "<Name>, <viewer> would like to say hi. Is now a good time?" and listens for up to 15 s (phone mic → speech to text → yes or no; a thumbs-up counts as yes).
2. Yes: `phase: live`. The phone page switches to the **front camera** (follow pauses; Safari opens one camera at a time) and shows the viewer's video instead of the face. Video and audio go app ↔ phone page over **WebRTC**, with `rtc` messages relayed through this socket. No or silence: `phase: declined`.
3. `end`, either side hanging up, or 10 minutes: back to `idle`, follow resumes, an `event` with the length.
4. The server never relays `rtc` unless the call is `live`, and the face shows a camera-on dot for the whole call.

Simpler fallback if WebRTC isn't ready (T-19): the phone page sends JPEG frames (T-10) that the server forwards as `{"t":"frame","call":..,"jpeg":"<base64>"}` at about 5 fps, and talking uses `talk` clips.

## Not in v1

- Notifications while the app is closed (T-20). For the demo the app is open, and `state.alert` takes over the screen.
- Several homes or residents per account.
- Editing routine times from the app (on/off only).
