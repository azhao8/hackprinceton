"""API (open question W-6): how the phone page, the dashboard and later the family app reach the server.

One aiohttp app on the server's asyncio loop, on two ports:
- **HTTPS :8443** for the robot's iPhone. `/` is John's phone page (firmware/balance/phone/); Safari
  only gives a page the camera over HTTPS.
- **HTTP :8080** for this laptop and first-time setup. `/` explains how to trust the certificate
  (`/ca.cer`); `/control` is the control page (localhost only); `/ws` is the dashboard's WebSocket.

The phone page keeps the endpoints it already used with phone_server.py, so it works unchanged:
- `POST /auto {v, w, found, cx, h}`: the page's follow command. It goes to the arbiter as a skill,
  and only while Follow is switched on (control page or WebSocket). Off by default.
- `GET /tel`: `{tel, follow, link, estop}` for the page's status line.
- `GET /say?after=N`: lines for the phone to speak. `POST /say {text}` adds one (localhost only).
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
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from aiohttp import WSMsgType, web

from app.arbiter import Arbiter, Source
from app.link import RobotLink

log = logging.getLogger("app.api")

PHONE_DIR = Path(__file__).resolve().parents[3] / "firmware" / "balance" / "phone"
PHONE_FILES = {"/": "index.html", "/index.html": "index.html", "/track.js": "track.js"}
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


@dataclass
class ApiState:
    arbiter: Arbiter
    link: RobotLink
    skills: Any = None          # the server's SkillRunner, if any: STOP cancels its skill
    follow: bool = False
    say: list[dict] = field(default_factory=list)
    settings: dict = field(default_factory=default_settings)

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
                "estop": self.arbiter.estopped, "settings": self.settings}


def _num(d: dict, key: str, lim: float) -> float:
    try:
        x = float(d.get(key, 0) or 0)
    except (TypeError, ValueError):
        return 0.0
    return max(-lim, min(lim, x)) if x == x else 0.0   # NaN -> 0


def _local(request: web.Request) -> bool:
    return request.remote in LOCAL


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
        else:
            raise web.HTTPNotFound()
        return web.json_response(state.status())

    @routes.post("/control/settings")
    async def control_settings(request: web.Request) -> web.Response:
        if not _local(request):
            raise web.HTTPForbidden()
        state.set_settings(await _json(request))
        return web.json_response(state.status())

    @routes.get("/ws")
    async def ws(request: web.Request) -> web.WebSocketResponse:
        sock = web.WebSocketResponse(heartbeat=5)
        await sock.prepare(request)
        log.info("websocket client %s connected", request.remote)

        local = _local(request)

        async def push() -> None:
            n = 0
            while not sock.closed:
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
        finally:
            pusher.cancel()
        return sock

    app.add_routes(routes)
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
<button id=foff style='font:inherit;padding:14px 18px'>Follow off</button></p>
<pre id=st style='background:#222;padding:10px;white-space:pre-wrap'>...</pre>
<h3>Follow settings</h3>
<p><select id=mode style='font:inherit;padding:8px'><option value=person>Follow a person</option><option value=yellow>Follow yellow</option></select>
<button id=voice style='font:inherit;padding:8px 12px'>Voice: on</button></p>
<p><label>Speed cap <input id=spd type=range min=0.1 max=0.45 step=0.05> <b id=spdL></b> m/s</label></p>
<p><label>Stop distance <input id=dist type=range step=0.05> <b id=distL></b> (bigger = stops closer)</label></p>
<h3>Make Miguel talk</h3><form id=f><input id=t autofocus style='font:inherit;width:70%;padding:10px' placeholder='Type a line, press Enter'>
<button style='font:inherit;padding:10px 14px'>Say</button></form><div id=p></div>
<p style='color:#999'>The robot only moves after someone at the robot starts it balancing (g). Follow uses the phone page's tracking.</p>
<script>
const $=id=>document.getElementById(id);   // not bare ids: `stop` is the browser's window.stop()
const act=w=>fetch('/control/'+w,{method:'POST'}).then(show);
$('stop').onclick=()=>act('stop');$('release').onclick=()=>act('release');$('fon').onclick=()=>act('follow-on');$('foff').onclick=()=>act('follow-off');
function say(text){fetch('/say',{method:'POST',body:JSON.stringify({text})})}
$('f').onsubmit=e=>{e.preventDefault();const t=$('t');if(t.value.trim())say(t.value.trim());t.value=''};
for(const x of ["Hi, I'm Miguel!",'Time for your medicine.','Here is your water.','Follow me!','Hello, judges!']){const b=document.createElement('button');b.textContent=x;b.style.cssText='font:inherit;margin:4px;padding:8px 12px';b.onclick=()=>say(x);$('p').appendChild(b)}
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
</script>"""
