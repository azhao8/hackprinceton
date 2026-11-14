"""API (open question W-6): how the phone page, the dashboard and later the family app reach the server.

One aiohttp app on the server's asyncio loop, on two ports:
- **HTTPS :8443** for the robot's iPhone. `/` is John's phone page (firmware/balance/phone/); Safari
  only gives a page the camera over HTTPS.
- **HTTP :8080** for this laptop and first-time setup. `/` explains how to trust the certificate
  (`/ca.cer`); `/control` is the control page (localhost only); `/ws` is the dashboard's WebSocket.

The phone page keeps the endpoints it already used with phone_server.py, so it works unchanged:
- `POST /auto {v, w, found, cx, h}`: the page's follow command. It goes to the arbiter as a skill,
  and only while Follow is switched on (control page or WebSocket). Off by default.
- `GET /tel`: `{tel, follow, link, estop, tts}` for the page's status line; `tts` says whether
  `/tts` is set up (Cartesia), so the page knows whether to try it.
- `GET /say?after=N`: lines for the phone to speak. `POST /say {text}` adds one (localhost only).
- `GET /tts?text=...`: the line as Cartesia speech (audio/mpeg). 400 if the text is empty or over
  300 characters, 503 if CARTESIA_API_KEY isn't set, 502 if Cartesia fails; the page then falls
  back to Safari's built-in voice.
- `POST /log`: what the page reports (camera chosen, errors), printed here.

WebSocket `/ws` (dashboard; messages in contract/web/): the server sends the robot's `tel` about
10 times a second; it accepts `{"t":"estop","on":bool}`, `{"t":"joystick","v":..,"w":..}`,
`{"t":"follow","on":bool}`, `{"t":"say","text":..}`, `{"t":"settings", mode?, speed?, distance?, voice?}`,
`{"t":"key","letter":"x|P|5|L|R|F|B"}` and `{"t":"arm"}` (start balancing; this laptop only, decision 0054).
It also sends `{"t":"status", follow, link, estop, settings, lag_ms, skill}` about twice a second.

Follow settings (mode person/yellow, speed cap, stop distance, voice on/off) live here and are set
from the control page (`POST /control/settings`, localhost only) or the WebSocket; the phone page
reads them from `/tel` (decision 0053: the phone is the robot's eye, every control is on the laptop).

The API never sends `g`: starting to balance stays a person's keypress at the robot.

NEW (#54, the voice agent and the guardian channel; additive, for Alex's review as W-6 owner).
Messages in contract/web/README.md ("Agent"). "Agent auth" below = this laptop directly, or
`Authorization: Bearer <GUARDIAN_TOKEN>`; with no GUARDIAN_TOKEN set, only this laptop. A request
that came through a proxy or tunnel (it carries X-Forwarded-For, Forwarded, CF-Connecting-IP or
X-Real-IP) never counts as this laptop, so a tunnel (open question T-17) needs the token.
- NEW `POST /agent/message {text, from?: "guardian"|"operator"}` (agent auth): an Utterance for the
  agent's inbox. `operator` (the control page) only from this laptop; anything else is `guardian`.
  200 `{ok, last}`; 400 empty or over 1000 characters; 401 bad token; 403 no token set and not
  local; 503 the agent is off (no ANTHROPIC_API_KEY).
- NEW `GET /agent/events?after=N` (agent auth): `{events: [AgentEvent...], last}`, the events with
  id > N (the last 200 are kept; after defaults to 0, all of them).
- NEW `GET /agent/photo/{id}.jpg` (agent auth): a camera snapshot the agent attached to a `reply`
  (its `data.photo_url`; the last 20 are kept, 404 after that). `reply` events also carry
  `data.audio_url` = `/tts?text=...` when the voice is set up.
- NEW `POST /control/loaded` (this laptop; the control page's Tray loaded button): the bring
  skill, waiting at the station, goes on. `{ok: false}` if nothing was waiting.
- NEW on `/ws`: the server also sends every agent event as `{"t":"agent", id, kind, text, to, data}`
  (from the moment the socket connects); it accepts `{"t":"agent_message","text":..}` (operator from
  this laptop, guardian with the token on the handshake, ignored otherwise).
- NEW `/mic` (WebSocket, the robot's phone over HTTPS): the hearing module's handler
  (app.speech.mic.make_mic_handler); mounted when the agent is on (without CARTESIA_API_KEY it
  drops the audio). NEW `/mic.js`: the phone page's mic streamer (firmware/balance/phone/mic.js).
"""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote

from aiohttp import WSMsgType, web

from app.arbiter import Arbiter, Source
from app.link import RobotLink

log = logging.getLogger("app.api")

PHONE_DIR = Path(__file__).resolve().parents[3] / "firmware" / "balance" / "phone"
PHONE_FILES = {"/": "index.html", "/index.html": "index.html", "/track.js": "track.js",
               "/mic.js": "mic.js"}   # NEW (#54): the phone's mic streamer (hearing)
LOCAL = ("127.0.0.1", "::1")
V_MAX, W_MAX = 0.6, 1.5
KEY_LETTERS = set("xP5LRFB")   # never g here: start balancing has its own message (arm)

# Follow settings, set on the control page and read by the phone page (decision 0053).
# Ranges and defaults are John's from the phone page (MODES in index.html).
FOLLOW_MODES = {"person": {"dmin": 0.25, "dmax": 0.65, "d": 0.45, "s": 0.25},
                "yellow": {"dmin": 0.2, "dmax": 0.6, "d": 0.35, "s": 0.4}}
SPEED_MIN, SPEED_MAX = 0.1, 0.45


def default_settings(mode: str = "person") -> dict:
    m = FOLLOW_MODES[mode]
    return {"mode": mode, "speed": m["s"], "distance": m["d"], "voice": True}


def clean_settings(old: dict, new: dict) -> dict:
    """Merge a partial update into the settings, keeping every value in range."""
    out = dict(old)
    if new.get("mode") in FOLLOW_MODES and new["mode"] != old["mode"]:
        out = default_settings(new["mode"]) | {"voice": old["voice"]}   # a new mode starts from its defaults
    m = FOLLOW_MODES[out["mode"]]
    for key, lo, hi in (("speed", SPEED_MIN, SPEED_MAX), ("distance", m["dmin"], m["dmax"])):
        if key in new:
            try:
                x = float(new[key])
            except (TypeError, ValueError):
                continue
            if x == x:
                out[key] = round(max(lo, min(hi, x)), 3)
    if isinstance(new.get("voice"), bool):
        out["voice"] = new["voice"]
    return out

TTS_MAX_CHARS = 300   # the same cap as a /say line

# NEW (#54) the agent's channel.
AGENT_TEXT_MAX = 1000     # one message to the agent
AGENT_EVENTS_KEPT = 200   # for GET /agent/events
AGENT_PHOTOS_KEPT = 20    # snapshots for reply events, in memory
FORWARDED_HEADERS = ("X-Forwarded-For", "Forwarded", "CF-Connecting-IP", "X-Real-IP")

# The control page's preset buttons.
CONTROL_PRESETS = ["Hi, I'm Miguel!", "Time for your medicine.", "Here is your water.", "Follow me!", "Hello, judges!"]
# What the phone page says by itself: the Start tap and the Voice.event lines in talk(), copied from
# firmware/balance/phone/index.html. Keep them in sync (tests/test_api.py checks they're still there).
PHONE_LINES = [
    "Hi, I'm Miguel.",
    "Hi! I'll follow you.", "Found you!", "Hello there! Lead the way.", "Ooh, something yellow!", "I see yellow!",
    "Whoa, personal space!", "That's a little close.", "Wait for me!", "Not so fast!",
    "Where did you go?", "Hello? I lost you.", "Where did my yellow thing go?",
]
# Made ahead in the background at startup, so these play without waiting for Cartesia.
STOCK_LINES = CONTROL_PRESETS + PHONE_LINES


@dataclass
class ApiState:
    arbiter: Arbiter
    link: RobotLink
    skills: Any = None          # the server's SkillRunner, if any: STOP cancels its skill
    tts: Any = None             # app.speech.tts.CartesiaTTS, or None: the phone uses Safari's voice
    follow: bool = False
    say: list[dict] = field(default_factory=list)
    settings: dict = field(default_factory=default_settings)
    # NEW (#54) the voice agent. All None/empty when the agent is off: the routes then say so.
    agent_inbox: asyncio.Queue | None = None   # the agent's inbox of app.brain.types.Utterance
    guardian_token: str | None = None          # GUARDIAN_TOKEN: remote callers of /agent/* need it
    mic: Any = None                            # aiohttp handler for the phone's /mic WebSocket
    agent_events: list[dict] = field(default_factory=list)
    agent_photos: OrderedDict = field(default_factory=OrderedDict)   # photo id -> JPEG bytes
    _tray: asyncio.Event | None = field(default=None, repr=False)    # set by "Tray loaded"

    # --- NEW (#54) the agent's events and photos ---

    @property
    def last_agent_event(self) -> int:
        return self.agent_events[-1]["id"] if self.agent_events else 0

    def agent_events_after(self, after: int) -> list[dict]:
        return [e for e in self.agent_events if e["id"] > after]

    def save_photo(self, jpeg: bytes) -> str:
        """The ToolBox's save_photo: keep a camera snapshot (the last 20), return its URL for the app."""
        pid = (next(reversed(self.agent_photos)) + 1) if self.agent_photos else 1
        self.agent_photos[pid] = bytes(jpeg)
        while len(self.agent_photos) > AGENT_PHOTOS_KEPT:
            self.agent_photos.popitem(last=False)
        return f"/agent/photo/{pid}.jpg"

    def publish_agent_event(self, ev: Any) -> dict:
        """Keep an AgentEvent (or its dict) for /agent/events and /ws. A `reply` keeps the agent's
        `data.photo_url` (from save_photo) and gets `data.audio_url` when the voice is set up.
        Returns the dict as clients see it."""
        d = ev.to_dict() if hasattr(ev, "to_dict") else dict(ev)
        d["data"] = dict(d.get("data") or {})
        if not isinstance(d.get("id"), int) or d["id"] <= self.last_agent_event:
            d["id"] = self.last_agent_event + 1   # ids must keep increasing: clients poll "after id"
        if d.get("kind") == "reply":
            text = str(d.get("text") or "").strip()
            if self.tts is not None and 0 < len(text) <= TTS_MAX_CHARS:
                d["data"]["audio_url"] = "/tts?text=" + quote(text, safe="")
        self.agent_events.append(d)
        del self.agent_events[:-AGENT_EVENTS_KEPT]
        return d

    # --- NEW (#54) the bring skill's "tray loaded" confirmation ---

    async def wait_loaded(self) -> bool:
        """The bring skill's wait_loaded: returns True once someone presses Tray loaded (after this call)."""
        self._tray = asyncio.Event()
        await self._tray.wait()
        return True

    def mark_loaded(self) -> bool:
        """Tray loaded (control page). False if nothing was waiting for it."""
        if self._tray is None or self._tray.is_set():
            return False
        self._tray.set()
        log.info("tray loaded")
        return True

    def agent_message(self, text: str, source: str, channel: str) -> tuple[int, str]:
        """Put one message in the agent's inbox. Returns (HTTP status, error or "")."""
        text = text.strip()
        if not text or len(text) > AGENT_TEXT_MAX:
            return 400, f"text must be 1 to {AGENT_TEXT_MAX} characters"
        if self.agent_inbox is None:
            return 503, "agent off (ANTHROPIC_API_KEY not set)"
        from app.brain.types import Utterance

        hub = getattr(self.mic, "hub", None)
        try:
            if source == "operator" and hub is not None:
                hub.push_to_talk(text, source="operator")   # push-to-talk: also opens the mic's answer window
            else:
                self.agent_inbox.put_nowait(Utterance(source, text, meta={"channel": channel}))  # type: ignore[arg-type]
        except asyncio.QueueFull:
            return 503, "agent busy"
        log.info("agent: %s says %r (%s)", source, text[:80], channel)
        return 200, ""

    def set_settings(self, new: dict) -> None:
        self.settings = clean_settings(self.settings, new)
        log.info("follow settings: %s", self.settings)

    def add_say(self, text: str) -> None:
        text = text.strip()[:300]
        if text:
            self.say.append({"id": (self.say[-1]["id"] + 1) if self.say else 1, "text": text})
            del self.say[:-50]
            log.info("say: %s", text)

    def set_follow(self, on: bool) -> None:
        """The phone page's follow. Turning it on stops any server skill (for example the server's own
        follow), so two followers never fight over the arbiter's skill slot."""
        if on and self.skills is not None and self.skills.running:
            self.skills.cancel()
        self.follow = on
        if not on:
            self.arbiter.clear(Source.SKILL)
        log.info("phone follow %s", "ON" if on else "off")

    def estop(self, on: bool) -> None:
        self.arbiter.estop(on)
        if on:
            self.set_follow(False)
            if self.skills is not None:
                self.skills.cancel()
        log.info("E-STOP %s", "on" if on else "released")

    def stop_motion(self) -> None:
        """Before park, motors off or start: nothing may keep driving."""
        self.set_follow(False)
        if self.skills is not None:
            self.skills.cancel()
        self.arbiter.clear(Source.JOYSTICK)

    def key(self, letter: str) -> bool:
        """A one-letter robot command from the control page: x, P, 5, L, R, F, B (contract/README.md)."""
        if letter not in KEY_LETTERS:
            return False
        if letter in "xP5":
            self.stop_motion()
        try:
            self.link.send_letter(letter)
        except Exception as e:  # a link without letters (tests) or a closed link
            log.warning("sending %r failed: %s", letter, e)
            return False
        log.info("key %s", letter)
        return True

    def arm(self) -> bool:
        """Start balancing (g): only from this laptop, on a person's press (decision 0054)."""
        arm = getattr(self.link, "arm", None)
        if arm is None:
            return False
        self.stop_motion()
        arm()
        log.info("start balancing (g) sent from the control page")
        return True

    def phone_follow_active(self) -> bool:
        return self.follow and not (self.skills is not None and self.skills.running)

    def status(self) -> dict:
        return {"tel": self.link.telemetry, "follow": self.follow, "link": self.link.health().ok,
                "estop": self.arbiter.estopped, "settings": self.settings,
                "tts": self.tts is not None}


def _num(d: dict, key: str, lim: float) -> float:
    try:
        x = float(d.get(key, 0) or 0)
    except (TypeError, ValueError):
        return 0.0
    return max(-lim, min(lim, x)) if x == x else 0.0   # NaN -> 0


def _local(request: web.Request) -> bool:
    return request.remote in LOCAL


# NEW (#54) auth for the agent's routes.
def _direct_local(request: web.Request) -> bool:
    """This laptop, and not a proxy or tunnel on this laptop passing someone else's request along."""
    return _local(request) and not any(h in request.headers for h in FORWARDED_HEADERS)


def _guardian(request: web.Request, state: ApiState) -> bool:
    if not state.guardian_token:
        return False
    scheme, _, given = request.headers.get("Authorization", "").partition(" ")
    return scheme.lower() == "bearer" and hmac.compare_digest(given.strip().encode(), state.guardian_token.encode())


def _agent_auth(request: web.Request, state: ApiState) -> None:
    """This laptop directly, or the guardian's token. Raises 403 (no token set) or 401 (wrong token)."""
    if _direct_local(request):
        return
    if not state.guardian_token:
        raise web.HTTPForbidden(text="GUARDIAN_TOKEN is not set: the agent only takes messages from this laptop")
    if not _guardian(request, state):
        raise web.HTTPUnauthorized(headers={"WWW-Authenticate": "Bearer"})


async def _json(request: web.Request) -> dict:
    try:
        body = await request.json()
    except (ValueError, UnicodeDecodeError):
        return {}
    return body if isinstance(body, dict) else {}


def create_app(state: ApiState, ca_page: str = "") -> web.Application:
    app = web.Application()
    routes = web.RouteTableDef()

    @routes.get("/")
    @routes.get("/index.html")
    @routes.get("/track.js")
    @routes.get("/mic.js")
    async def phone_page(request: web.Request) -> web.StreamResponse:
        if not request.secure and request.path == "/":
            return web.Response(text=ca_page or "Miguel.exe server. Open the HTTPS address on the phone.",
                                content_type="text/html")
        if request.path == "/":
            log.info("phone page opened by %s", request.remote)
        return web.FileResponse(PHONE_DIR / PHONE_FILES[request.path], headers={"Cache-Control": "no-store"})

    @routes.get("/ca.cer")
    async def ca_cert(request: web.Request) -> web.StreamResponse:
        from app.api.certs import CERT_DIR
        log.info("phone downloaded the certificate")
        return web.FileResponse(CERT_DIR / "ca.cer", headers={"Content-Type": "application/x-x509-ca-cert"})

    @routes.post("/auto")
    async def auto(request: web.Request) -> web.Response:
        body = await _json(request)
        if state.phone_follow_active():
            state.arbiter.request(Source.SKILL, _num(body, "v", V_MAX), _num(body, "w", W_MAX))
        return web.json_response({"follow": state.follow})

    @routes.get("/tel")
    async def tel(request: web.Request) -> web.Response:
        return web.json_response(state.status(), headers={"Cache-Control": "no-store"})

    @routes.get("/say")
    async def say_poll(request: web.Request) -> web.Response:
        try:
            after = int(request.query.get("after", "-1"))
        except ValueError:
            after = -1
        last = state.say[-1]["id"] if state.say else 0
        msgs = [m for m in state.say if m["id"] > after] if after >= 0 else []
        return web.json_response({"msgs": msgs, "last": last}, headers={"Cache-Control": "no-store"})

    @routes.post("/say")
    async def say_add(request: web.Request) -> web.Response:
        if not _local(request):
            raise web.HTTPForbidden()
        text = str((await _json(request)).get("text", ""))
        state.add_say(text)
        return web.json_response({"ok": bool(text.strip())}, status=200 if text.strip() else 400)

    @routes.get("/tts")
    async def tts(request: web.Request) -> web.Response:
        text = request.query.get("text", "").strip()
        if not text or len(text) > TTS_MAX_CHARS:
            return web.json_response({"error": f"text must be 1 to {TTS_MAX_CHARS} characters"}, status=400)
        if state.tts is None:
            return web.json_response({"error": "tts not configured"}, status=503)
        try:
            audio = await state.tts.synth(text)
        except Exception as e:   # TTSError (network, key, quota): the page falls back to Safari's voice
            log.warning("tts failed for %r: %s", text[:60], e)
            return web.json_response({"error": "tts failed"}, status=502)
        return web.Response(body=audio, headers={"Content-Type": getattr(state.tts, "MEDIA_TYPE", "audio/mpeg"),
                                                 "Cache-Control": "no-store"})

    @routes.post("/log")
    async def phone_log(request: web.Request) -> web.Response:
        log.info("phone: %s", (await request.text())[:300])
        return web.json_response({})

    @routes.get("/control")
    async def control(request: web.Request) -> web.Response:
        if not _local(request):
            raise web.HTTPForbidden()
        return web.Response(text=CONTROL_PAGE, content_type="text/html")

    @routes.post("/control/{what}")
    async def control_action(request: web.Request) -> web.Response:
        if not _local(request):
            raise web.HTTPForbidden()
        what = request.match_info["what"]
        if what == "follow-on":
            state.set_follow(True)
        elif what == "follow-off":
            state.set_follow(False)
        elif what == "stop":
            state.estop(True)
        elif what == "release":
            state.estop(False)
        elif what == "loaded":   # NEW (#54): the bring skill waits for this at the station
            return web.json_response({"ok": state.mark_loaded()})
        else:
            raise web.HTTPNotFound()
        return web.json_response(state.status())

    @routes.post("/control/settings")
    async def control_settings(request: web.Request) -> web.Response:
        if not _local(request):
            raise web.HTTPForbidden()
        state.set_settings(await _json(request))
        return web.json_response(state.status())

    # --- NEW (#54) the voice agent and the guardian channel ---

    @routes.post("/agent/message")
    async def agent_message(request: web.Request) -> web.Response:
        _agent_auth(request, state)
        body = await _json(request)
        source = "operator" if body.get("from") == "operator" and _direct_local(request) else "guardian"
        status, error = state.agent_message(str(body.get("text", "")), source, "api")
        if status != 200:
            return web.json_response({"ok": False, "error": error}, status=status)
        return web.json_response({"ok": True, "last": state.last_agent_event})

    @routes.get("/agent/events")
    async def agent_events(request: web.Request) -> web.Response:
        _agent_auth(request, state)
        try:
            after = int(request.query.get("after", "0"))
        except ValueError:
            after = 0
        return web.json_response({"events": state.agent_events_after(after), "last": state.last_agent_event},
                                 headers={"Cache-Control": "no-store"})

    @routes.get(r"/agent/photo/{id:\d+}.jpg")
    async def agent_photo(request: web.Request) -> web.Response:
        _agent_auth(request, state)
        jpeg = state.agent_photos.get(int(request.match_info["id"]))
        if jpeg is None:
            raise web.HTTPNotFound()
        return web.Response(body=jpeg, content_type="image/jpeg", headers={"Cache-Control": "private, max-age=3600"})

    @routes.get("/ws")
    async def ws(request: web.Request) -> web.WebSocketResponse:
        sock = web.WebSocketResponse(heartbeat=5)
        await sock.prepare(request)
        log.info("websocket client %s connected", request.remote)

        local = _local(request)
        # NEW (#54): who an agent_message on this socket comes from (None: ignored).
        agent_from = "operator" if _direct_local(request) else "guardian" if _guardian(request, state) else None
        seen = state.last_agent_event   # agent events from now on; GET /agent/events has the history

        async def push() -> None:
            nonlocal seen
            n = 0
            while not sock.closed:
                for ev in state.agent_events_after(seen):   # NEW (#54)
                    await sock.send_json({"t": "agent", **ev})
                    seen = ev["id"]
                if state.link.telemetry:
                    await sock.send_json(state.link.telemetry)
                if n % 5 == 0:                       # about twice a second
                    h = state.link.health()
                    st = state.status()
                    st.pop("tel")
                    await sock.send_json({"t": "status", **st, "lag_ms": h.lag_ms,
                                          "skill": state.skills.running if state.skills is not None else None})
                n += 1
                await asyncio.sleep(0.1)

        pusher = asyncio.create_task(push())
        try:
            async for msg in sock:
                if msg.type != WSMsgType.TEXT:
                    continue
                try:
                    m = json.loads(msg.data)
                except ValueError:
                    continue
                if not isinstance(m, dict):
                    continue
                t = m.get("t")
                if t == "estop":
                    state.estop(bool(m.get("on")))
                elif t == "joystick":
                    state.arbiter.request(Source.JOYSTICK, _num(m, "v", V_MAX), _num(m, "w", W_MAX))
                elif t == "follow":
                    state.set_follow(bool(m.get("on")))
                elif t == "say":
                    state.add_say(str(m.get("text", "")))
                elif t == "settings":
                    state.set_settings(m)
                elif t == "key":
                    state.key(str(m.get("letter", "")))
                elif t == "arm":
                    if local:
                        state.arm()
                    else:
                        log.warning("start balancing refused: not from this laptop (%s)", request.remote)
                elif t == "agent_message":   # NEW (#54)
                    if agent_from is None:
                        log.warning("agent_message refused: not this laptop and no guardian token (%s)", request.remote)
                    else:
                        status, error = state.agent_message(str(m.get("text", "")), agent_from, "ws")
                        if status != 200:
                            log.info("agent_message not taken: %s", error)
        finally:
            pusher.cancel()
        return sock

    app.add_routes(routes)
    if state.mic is not None:   # NEW (#54): the phone's microphone stream, for the agent's hearing
        app.router.add_get("/mic", state.mic)
    return app


async def start(state: ApiState, http_port: int = 8080, https_port: int | None = 8443) -> tuple[web.AppRunner, str]:
    """Start the API. Returns the runner (call `cleanup()` to stop) and the phone page's address."""
    from app.api import certs

    ip = certs.lan_ip()
    phone_url = f"https://{ip}:{https_port}" if https_port else ""
    app = create_app(state, ca_page=_ca_page(ip, phone_url))
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", http_port).start()
    if https_port:
        ctx = await asyncio.to_thread(certs.ssl_context, ip)
        await web.TCPSite(runner, "0.0.0.0", https_port, ssl_context=ctx).start()
    log.info("API up. Phone (once): http://%s:%d to trust this laptop, then %s", ip, http_port, phone_url)
    log.info("Control page: http://localhost:%d/control   Dashboard WebSocket: ws://localhost:%d/ws", http_port, http_port)
    return runner, phone_url


def _ca_page(ip: str, phone_url: str) -> str:
    return ("<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width'>"
            "<body style='font:18px -apple-system,sans-serif;padding:20px;line-height:1.5'>"
            "<h2>Miguel.exe: trust this laptop (once per iPhone)</h2><ol>"
            "<li><a href='/ca.cer'>Download the certificate</a> and tap <b>Allow</b>.</li>"
            "<li>Open <b>Settings</b>, tap <b>Profile Downloaded</b>, then <b>Install</b>.</li>"
            "<li>Settings &rarr; General &rarr; About &rarr; <b>Certificate Trust Settings</b>: turn on "
            "<b>Miguel.exe local CA</b>.</li>"
            f"<li>Open <a href='{phone_url}'>{phone_url}</a> and tap Start.</li></ol>"
            "<p>Remove the profile after the hackathon (Settings &rarr; General &rarr; VPN &amp; Device Management).</p>")


CONTROL_PAGE = """<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width'><title>Miguel control</title>
<body style='font:17px -apple-system,sans-serif;padding:20px;max-width:680px;background:#111;color:#eee'>
<h2>Miguel control</h2>
<p><button id=stop style='font:inherit;padding:14px 22px;background:#b91c1c;color:#fff;border:0;border-radius:8px'>STOP</button>
<button id=release style='font:inherit;padding:14px 18px'>Release</button>
<button id=fon style='font:inherit;padding:14px 18px'>Follow ON</button>
<button id=foff style='font:inherit;padding:14px 18px'>Follow off</button>
<button id=loaded style='font:inherit;padding:14px 18px'>Tray loaded</button></p>
<pre id=st style='background:#222;padding:10px;white-space:pre-wrap'>...</pre>
<h3>Follow settings</h3>
<p><select id=mode style='font:inherit;padding:8px'><option value=person>Follow a person</option><option value=yellow>Follow yellow</option></select>
<button id=voice style='font:inherit;padding:8px 12px'>Voice: on</button></p>
<p><label>Speed cap <input id=spd type=range min=0.1 max=0.45 step=0.05> <b id=spdL></b> m/s</label></p>
<p><label>Stop distance <input id=dist type=range step=0.05> <b id=distL></b> (bigger = stops closer)</label></p>
<h3>Make Miguel talk</h3><form id=f><input id=t autofocus style='font:inherit;width:70%;padding:10px' placeholder='Type a line, press Enter'>
<button style='font:inherit;padding:10px 14px'>Say</button></form><div id=p></div>
<h3>Ask Miguel (voice agent)</h3><form id=af><input id=at style='font:inherit;width:70%;padding:10px' placeholder='Ask Miguel to do something'>
<button style='font:inherit;padding:10px 14px'>Send</button></form>
<div id=al style='background:#222;padding:10px;white-space:pre-wrap;max-height:320px;overflow:auto;margin-top:8px'></div>
<p style='color:#999'>The robot only moves after someone at the robot starts it balancing (g). Follow uses the phone page's tracking.</p>
<script>
const $=id=>document.getElementById(id);   // not bare ids: `stop` is the browser's window.stop()
const act=w=>fetch('/control/'+w,{method:'POST'}).then(show);
$('stop').onclick=()=>act('stop');$('release').onclick=()=>act('release');$('fon').onclick=()=>act('follow-on');$('foff').onclick=()=>act('follow-off');
$('loaded').onclick=()=>fetch('/control/loaded',{method:'POST'});
function say(text){fetch('/say',{method:'POST',body:JSON.stringify({text})})}
$('f').onsubmit=e=>{e.preventDefault();const t=$('t');if(t.value.trim())say(t.value.trim());t.value=''};
for(const x of __PRESETS__){const b=document.createElement('button');b.textContent=x;b.style.cssText='font:inherit;margin:4px;padding:8px 12px';b.onclick=()=>say(x);$('p').appendChild(b)}
const RANGES={person:[0.25,0.65],yellow:[0.2,0.6]};let editing=0;
const setS=o=>{editing=Date.now();fetch('/control/settings',{method:'POST',body:JSON.stringify(o)}).then(show)};
$('mode').onchange=()=>setS({mode:$('mode').value});
$('spd').oninput=()=>{$('spdL').textContent=(+$('spd').value).toFixed(2)};$('spd').onchange=()=>setS({speed:+$('spd').value});
$('dist').oninput=()=>{$('distL').textContent=(+$('dist').value).toFixed(2)};$('dist').onchange=()=>setS({distance:+$('dist').value});
$('voice').onclick=()=>setS({voice:$('voice').textContent.endsWith('off')});
function showSettings(s){if(!s||Date.now()-editing<800)return;const r=RANGES[s.mode];
$('mode').value=s.mode;$('dist').min=r[0];$('dist').max=r[1];$('dist').value=s.distance;$('spd').value=s.speed;
$('distL').textContent=(+s.distance).toFixed(2);$('spdL').textContent=(+s.speed).toFixed(2);$('voice').textContent='Voice: '+(s.voice?'on':'off')}
async function show(){const st=$('st');try{const d=await (await fetch('/tel')).json(),t=d.tel||{};
showSettings(d.settings);st.textContent='Link: '+(d.link?'ok':'DOWN')+'   E-stop: '+(d.estop?'ON':'off')+'   Follow: '+(d.follow?'ON':'off')+'\\nRobot: '+(t.state||'?')+'  pitch '+(t.pitch??'?')+'  x '+(t.x??'?')+'  yaw '+(t.yaw??'?')}catch(e){st.textContent='server not answering'}}
setInterval(show,500);show();
// NEW (#54) the voice agent: send as the operator, show its events.
let aLast=0;
function aLine(text,href){const d=document.createElement('div');d.textContent=text;if(href){const a=document.createElement('a');a.href=href;a.target='_blank';a.textContent=' [photo]';a.style.color='#7cf';d.appendChild(a)}$('al').appendChild(d);$('al').scrollTop=1e9}
$('af').onsubmit=async e=>{e.preventDefault();const t=$('at'),text=t.value.trim();t.value='';if(!text)return;
const r=await fetch('/agent/message',{method:'POST',body:JSON.stringify({text,from:'operator'})});if(!r.ok)aLine('(not sent: '+((await r.json()).error||r.status)+')')};
async function aPoll(){try{const d=await (await fetch('/agent/events?after='+aLast)).json();
for(const e of d.events){aLine(e.kind+(e.to?' to '+e.to:'')+': '+e.text,e.data&&e.data.photo_url);aLast=e.id}}catch(e){}}
setInterval(aPoll,1000);aPoll();
</script>""".replace("__PRESETS__", json.dumps(CONTROL_PRESETS))
