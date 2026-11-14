#!/usr/bin/env python3
"""Hold-to-drive keyboard control for the balancing robot, from a web page.

    python3 drive.py            then open http://localhost:8765 (it opens by itself)

Hold W/A/S/D or the arrow keys to drive; let go to stop. G = start balancing (hold it upright
first; the self stand-up is disabled until it is fixed with the phone on), P = park, X = motors off, Space = stop, Q / E = turn exactly 90 degrees left / right.

The robot is reached over the USB cable for now (the ESP32's COM port). This program sends the team
contract's drive command, {"t":"cmd","v":..,"w":..,"mode":"drive"}, 20 times a second while the page
is open and focused. If the page closes or loses focus, sending stops and the robot holds position by
itself 0.3 s later. Standard library only.
"""
import collections
import glob
import json
import os
import re
import select
import subprocess
import sys
import termios
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HTTP_PORT = 8765
TEL_RE = re.compile(r"^(RUN|off) pitch\s+(-?[\d.]+) \(err\s+(-?[\d.]+)\) rate\s+(-?[\d.]+)\s+v\s+(-?[\d.]+)\s+x\s+(-?[\d.]+)")
ALLOWED_KEYS = {"g", "P", "x", "L", "R", "5"}   # "G" (self stand-up) disabled until it is fixed with the phone on     # one-letter robot commands the page may send


class Robot:
    def __init__(self, path):
        self.fd = os.open(path, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        a = termios.tcgetattr(self.fd)
        a[0] = 0; a[1] = 0; a[2] = termios.CS8 | termios.CREAD | termios.CLOCAL; a[3] = 0
        a[4] = a[5] = termios.B115200
        termios.tcsetattr(self.fd, termios.TCSANOW, a)
        self.lock = threading.Lock()
        self.msgs = collections.deque(maxlen=8)
        self.tel = {}
        threading.Thread(target=self._reader, daemon=True).start()

    def write(self, text):
        with self.lock:
            os.write(self.fd, text.encode())

    def _reader(self):
        buf = b""
        while True:
            r, _, _ = select.select([self.fd], [], [], 0.1)
            if not r:
                continue
            try:
                buf += os.read(self.fd, 4096)
            except BlockingIOError:
                continue
            *lines, buf = buf.split(b"\n")
            for raw in lines:
                line = raw.decode(errors="replace").strip()
                m = TEL_RE.match(line)
                if m:
                    self.tel = {"state": m[1], "pitch": float(m[2]), "err": float(m[3]), "rate": float(m[4]),
                                "v": float(m[5]), "x": float(m[6]), "time": time.time()}
                elif line and line.isprintable():
                    self.msgs.append(line)

    def has_json_firmware(self):
        self.write("V\n")
        end = time.time() + 2.5
        while time.time() < end:
            if any("json-serial" in m for m in self.msgs):
                return True
            time.sleep(0.05)
        return False


state = {"v": 0.0, "w": 0.0, "t": 0.0}                  # keyboard page
auto = {"v": 0.0, "w": 0.0, "t": 0.0, "info": {}}      # follow program
follow = {"on": False}


def sender(robot):
    while True:
        now = time.time()
        manual_fresh = now - state["t"] < 0.3
        manual_active = manual_fresh and (state["v"] != 0 or state["w"] != 0)
        auto_fresh = follow["on"] and now - auto["t"] < 0.3
        if manual_active or (manual_fresh and not auto_fresh):   # keys held override follow
            v, w = state["v"], state["w"]
        elif auto_fresh:
            v, w = auto["v"], auto["w"]
        else:
            v = w = None                                          # nothing fresh: robot's watchdog holds position
        if v is not None:
            robot.write(json.dumps({"t": "cmd", "v": round(v, 3), "w": round(w, 3), "mode": "drive"}) + "\n")
        time.sleep(0.05)


PAGE = r"""<!doctype html><html><head><meta charset="utf-8"><title>Robot drive</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
:root{--bg:#f6f7f9;--fg:#1e2024;--muted:#6b7079;--card:#fff;--line:#d9dce1;--on:#2b6be6;--warn:#d33b2c}
@media (prefers-color-scheme:dark){:root{--bg:#16181b;--fg:#e8eaed;--muted:#9aa0a8;--card:#202327;--line:#353a40;--on:#5b8ff0;--warn:#ff6b5c}}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.4 -apple-system,system-ui,sans-serif}
main{max-width:720px;margin:0 auto;padding:20px 16px}
h1{font-size:20px;margin:0 0 4px}.muted{color:var(--muted)}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px;margin:14px 0}
.pad{display:grid;grid-template-columns:repeat(3,64px);gap:8px;justify-content:center;margin:8px 0}
.k{height:56px;border:1px solid var(--line);border-radius:10px;display:flex;align-items:center;justify-content:center;font-weight:600;user-select:none}
.k.on{background:var(--on);color:#fff;border-color:var(--on)}
.row{display:flex;gap:10px;flex-wrap:wrap}
button{font:inherit;padding:10px 14px;border-radius:10px;border:1px solid var(--line);background:var(--card);color:var(--fg);cursor:pointer}
button.stop{border-color:var(--warn);color:var(--warn)}
.big{font-size:28px;font-weight:700}.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}
label{display:block;margin:8px 0}input[type=range]{width:100%}
#fwarn{color:var(--warn);font-weight:600}
pre{margin:0;white-space:pre-wrap;font-size:13px;color:var(--muted)}
</style></head><body><main>
<h1>Robot drive</h1><div class="muted">Hold W A S D or the arrow keys. Let go to stop. Click this page first so it has the keyboard.</div>
<div id="fwarn"></div>
<div class="card">
 <div class="pad"><div></div><div class="k" id="kU">W</div><div></div>
 <div class="k" id="kL">A</div><div class="k" id="kD">S</div><div class="k" id="kR">D</div></div>
 <div class="grid">
  <div><div class="muted">State</div><div class="big" id="st">-</div></div>
  <div><div class="muted">Tilt</div><div class="big" id="pt">-</div></div>
  <div><div class="muted">Speed</div><div class="big" id="sp">-</div></div>
  <div><div class="muted">Distance</div><div class="big" id="xd">-</div></div>
 </div>
</div>
<div class="card">
 <div class="row">
  <button onclick="key('g')">G · Start (hold it upright first)</button><button onclick="key('P')">P · Park</button>
  <button onclick="key('L')">Q · 90° left</button><button onclick="key('R')">E · 90° right</button>
  <button class="stop" onclick="key('x')">X · Motors off</button>
  <button id="fbtn" onclick="toggleFollow()">F · Follow: off</button>
 </div>
 <label>Top speed <b id="vmaxL"></b> m/s<input id="vmax" type="range" min="0.1" max="0.6" step="0.05" value="0.3"></label>
 <label>Turn rate <b id="wmaxL"></b> rad/s<input id="wmax" type="range" min="0.5" max="1.5" step="0.25" value="1.0"></label>
</div>
<div class="card"><div class="muted">Follow</div><div id="fstat">follow program not running</div></div>
<div class="card"><div class="muted">Robot messages</div><pre id="msgs"></pre></div>
<script>
const held=new Set(), map={w:'U',arrowup:'U',s:'D',arrowdown:'D',a:'L',arrowleft:'L',d:'R',arrowright:'R'};
const vmax=document.getElementById('vmax'), wmax=document.getElementById('wmax');
function labels(){vmaxL.textContent=(+vmax.value).toFixed(2);wmaxL.textContent=(+wmax.value).toFixed(2)}
vmax.oninput=wmax.oninput=labels; labels();
function key(k){fetch('/key',{method:'POST',body:JSON.stringify({k})})}
let followOn=false;
function toggleFollow(){followOn=!followOn;fetch('/follow',{method:'POST',body:JSON.stringify({on:followOn})});fbtn.textContent='F · Follow: '+(followOn?'ON':'off');fbtn.classList.toggle('stop',followOn)}
addEventListener('keydown',e=>{const k=e.key.toLowerCase();
 if(map[k]){held.add(map[k]);e.preventDefault()}
 else if(k===' '){held.clear();e.preventDefault()}
 else if(!e.repeat){if(k==='f')toggleFollow();else if(k==='g')key('g');else if(k==='p')key('P');else if(k==='x'){key('x');if(followOn)toggleFollow();}else if(k==='q')key('L');else if(k==='e')key('R')}});
addEventListener('keyup',e=>{const k=e.key.toLowerCase();if(map[k])held.delete(map[k])});
addEventListener('blur',()=>held.clear());
setInterval(()=>{
 for(const d of ['U','D','L','R'])document.getElementById('k'+d).classList.toggle('on',held.has(d));
 fwarn.textContent=document.hasFocus()?'':'Click the page to drive (keys are ignored while it is not focused).';
 if(!document.hasFocus())return;
 const v=(+vmax.value)*((held.has('U')?1:0)-(held.has('D')?1:0));
 const w=(+wmax.value)*((held.has('L')?1:0)-(held.has('R')?1:0));
 fetch('/state',{method:'POST',body:JSON.stringify({v,w})});
},50);
setInterval(async()=>{try{const r=await (await fetch('/tel')).json(),t=r.tel||{};
 st.textContent=t.state||'-';pt.textContent=t.pitch!==undefined?t.pitch.toFixed(1)+'°':'-';
 sp.textContent=t.v!==undefined?t.v.toFixed(2):'-';xd.textContent=t.x!==undefined?t.x.toFixed(2)+' m':'-';
 msgs.textContent=(r.msgs||[]).join('\n');
 const a=r.auto||{};fstat.textContent=!r.auto_alive?'follow program not running':
   (a.found?('tracking: offset '+(a.cx-0.5).toFixed(2)+', size '+a.h.toFixed(2)):'no person in view')+(r.follow?'  (driving)':'  (follow is off, not driving)');
 }catch(e){}},200);
</script></main></body></html>"""


class Handler(BaseHTTPRequestHandler):
    robot = None

    def log_message(self, *a):
        pass

    def _body(self):
        n = int(self.headers.get("Content-Length", 0))
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            return {}

    def _send(self, code, body, ctype="application/json"):
        data = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/":
            self._send(200, PAGE, "text/html; charset=utf-8")
        elif self.path == "/tel":
            fa = time.time() - auto["t"] < 0.5
            self._send(200, json.dumps({"tel": self.robot.tel, "msgs": list(self.robot.msgs),
                                        "follow": follow["on"], "auto_alive": fa, "auto": auto["info"] if fa else {}}))
        else:
            self._send(404, "{}")

    def do_POST(self):
        b = self._body()
        if self.path == "/state":
            state["v"] = max(-0.6, min(0.6, float(b.get("v", 0))))
            state["w"] = max(-1.5, min(1.5, float(b.get("w", 0))))
            state["t"] = time.time()
            self._send(200, "{}")
        elif self.path == "/auto":                     # from the follow program
            auto["v"] = max(-0.45, min(0.45, float(b.get("v", 0))))
            auto["w"] = max(-1.2, min(1.2, float(b.get("w", 0))))
            auto["info"] = {k: b[k] for k in ("found", "cx", "h") if k in b}
            auto["t"] = time.time()
            self._send(200, "{}")
        elif self.path == "/follow":
            follow["on"] = bool(b.get("on"))
            self._send(200, json.dumps(follow))
        elif self.path == "/key" and b.get("k") in ALLOWED_KEYS:
            self.robot.write(b["k"] + "\n")
            self._send(200, "{}")
        else:
            self._send(400, "{}")


def main():
    ports = sys.argv[1:] or sorted(glob.glob("/dev/cu.usbmodem*")) + sorted(glob.glob("/dev/cu.wchusbserial*"))
    if not ports:
        sys.exit("Robot not found on USB. Plug the cable into the ESP32's COM port.")
    robot = Robot(ports[0])
    if not robot.has_json_firmware():
        sys.exit("The robot's program is too old for this (no 'json-serial'). Upload balance.ino first.")
    Handler.robot = robot
    threading.Thread(target=sender, args=(robot,), daemon=True).start()
    server = ThreadingHTTPServer(("127.0.0.1", HTTP_PORT), Handler)
    url = f"http://localhost:{HTTP_PORT}"
    print(f"Robot on {ports[0]}. Drive page: {url}  (Ctrl+C to quit; motors go off)")
    subprocess.run(["open", url], check=False)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        robot.write("x\n")
        time.sleep(0.2)
        print("Motors off. Bye.")


if __name__ == "__main__":
    main()
