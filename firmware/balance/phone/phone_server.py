#!/usr/bin/env python3
"""The robot's eye as a web page: the iPhone on the mast opens it in Safari and uses its 0.5x (ultra-wide) back camera.
The page finds the yellow target on the phone itself and sends only speed and turn here; this server passes them on to
drive.py's /auto, the same way the follow program does. Start drive.py first, and press F on the drive page to let it drive.

    python3 phone_server.py         then open the https://... address it prints, in Safari on the iPhone

Safari only gives a page the camera over HTTPS, so this makes a self-signed certificate on first run (cert/, git-ignored).
iPhones refuse self-signed pages, so this makes a small local CA: open http://<this Mac>:8080 on the phone once,
install the profile and turn on full trust for it (Settings > General > About > Certificate Trust Settings).
Standard library only (plus the openssl command that ships with macOS).
"""
import json
import os
import socket
import ssl
import subprocess
import sys
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = 8443
DRIVE = "http://127.0.0.1:8765"
FILES = {"/": ("index.html", "text/html; charset=utf-8"), "/index.html": ("index.html", "text/html; charset=utf-8"),
         "/track.js": ("track.js", "text/javascript; charset=utf-8")}


def lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))          # no packet is sent; this just picks the outgoing interface
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def _openssl(*args):
    subprocess.run(["openssl", *args], check=True, capture_output=True)


def ensure_cert(ip):
    """A tiny local certificate authority, installed on the iPhone once (http://<ip>:8080), plus a certificate for
    this Mac's IP signed by it. The CA only vouches for private-network addresses and localhost, lasts 30 days, and its
    key never leaves this Mac. The server certificate is remade when the IP changes; the CA is kept."""
    d = os.path.join(HERE, "cert")
    os.makedirs(d, exist_ok=True)
    p = lambda n: os.path.join(d, n)
    if not (os.path.exists(p("ca.pem")) and os.path.exists(p("ca.key"))):
        with open(p("ca.cnf"), "w") as f:
            f.write("[req]\ndistinguished_name = dn\nx509_extensions = v3\nprompt = no\n"
                    "[dn]\nCN = Robot Eye local CA (HackPrinceton)\n"
                    "[v3]\nbasicConstraints = critical, CA:TRUE, pathlen:0\nkeyUsage = critical, keyCertSign, cRLSign\n"
                    "subjectKeyIdentifier = hash\n"
                    "nameConstraints = critical, permitted;IP:10.0.0.0/255.0.0.0, permitted;IP:172.16.0.0/255.240.0.0, "
                    "permitted;IP:192.168.0.0/255.255.0.0, permitted;DNS:localhost\n")
        _openssl("req", "-x509", "-newkey", "rsa:2048", "-nodes", "-sha256", "-days", "30",
                 "-keyout", p("ca.key"), "-out", p("ca.pem"), "-config", p("ca.cnf"))
        _openssl("x509", "-in", p("ca.pem"), "-outform", "der", "-out", p("ca.cer"))
        for n in ("cert.pem", "ip.txt"):          # a server certificate from an older CA is useless now
            if os.path.exists(p(n)):
                os.remove(p(n))
    if os.path.exists(p("cert.pem")) and os.path.exists(p("ip.txt")) and open(p("ip.txt")).read().strip() == ip:
        return p("cert.pem"), p("key.pem")
    with open(p("srv.cnf"), "w") as f:
        f.write(f"subjectAltName = IP:{ip},DNS:localhost\nextendedKeyUsage = serverAuth\n"
                "keyUsage = critical, digitalSignature, keyEncipherment\nbasicConstraints = critical, CA:FALSE\n"
                "authorityKeyIdentifier = keyid\n")
    _openssl("req", "-new", "-newkey", "rsa:2048", "-nodes", "-keyout", p("key.pem"), "-out", p("srv.csr"),
             "-subj", "/CN=robot-eye")
    _openssl("x509", "-req", "-in", p("srv.csr"), "-CA", p("ca.pem"), "-CAkey", p("ca.key"), "-CAcreateserial",
             "-sha256", "-days", "30", "-out", p("cert.pem"), "-extfile", p("srv.cnf"))
    with open(p("ip.txt"), "w") as f:
        f.write(ip)
    return p("cert.pem"), p("key.pem")


SAY_LOCK = threading.Lock()
SAY = []                                          # lines typed on the Mac, spoken by the phone page: [{id, text}]


def add_say(text):
    with SAY_LOCK:
        SAY.append({"id": (SAY[-1]["id"] + 1) if SAY else 1, "text": text[:300]})
        del SAY[:-50]


CONTROL_PAGE = """<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width'><title>Miguel says</title>
<body style='font:17px -apple-system,sans-serif;padding:20px;max-width:640px;background:#111;color:#eee'>
<h2>Make Miguel talk</h2><p>Spoken by the phone on the robot (the robot page must be open there, with Start tapped).</p>
<form id=f><input id=t autofocus style='font:inherit;width:70%;padding:10px' placeholder='Type a line, press Enter'>
<button style='font:inherit;padding:10px 14px'>Say</button></form><p id=s></p><div id=p></div>
<script>
const presets=[\"Hi, I'm Miguel!\",'Follow me!','Hello, judges!','Nice to meet you!','Beep boop.','I can see you.','Goodbye!'];
function say(text){fetch('/say',{method:'POST',body:JSON.stringify({text})}).then(r=>{s.textContent=r.ok?'Sent: '+text:'Not sent'})}
f.onsubmit=e=>{e.preventDefault();if(t.value.trim())say(t.value.trim());t.value=''};
for(const x of presets){const b=document.createElement('button');b.textContent=x;b.style.cssText='font:inherit;margin:4px;padding:8px 12px';b.onclick=()=>say(x);p.appendChild(b)}
</script>"""


class CAHandler(BaseHTTPRequestHandler):
    """Plain-HTTP page on port 8080 for installing the local CA on the iPhone (the HTTPS page can't load before that)."""
    ip = ""

    def log_message(self, *args):
        pass

    def _local(self):
        return self.client_address[0] in ("127.0.0.1", "::1")

    def do_POST(self):                                # POST /say from the control page (this Mac only)
        raw = self.rfile.read(int(self.headers.get("Content-Length", 0) or 0))
        if self.path == "/say" and self._local():
            try:
                text = str(json.loads(raw).get("text", "")).strip()
            except ValueError:
                text = ""
            if text:
                add_say(text)
                print("say:", text, flush=True)
            code = 200 if text else 400
        else:
            code = 403
        self.send_response(code)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        if self.path == "/control" and self._local():
            data, ctype = CONTROL_PAGE.encode(), "text/html; charset=utf-8"
        elif self.path == "/ca.cer":
            with open(os.path.join(HERE, "cert", "ca.cer"), "rb") as f:
                data = f.read()
            ctype = "application/x-x509-ca-cert"
            print("phone: downloaded the certificate", flush=True)
        else:
            ip = self.ip
            data = ("<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width'>"
                    "<body style='font:18px -apple-system,sans-serif;padding:20px;line-height:1.5'>"
                    "<h2>Robot eye: trust this Mac (once)</h2><ol>"
                    "<li><a href='/ca.cer'>Download the certificate</a> and tap <b>Allow</b>.</li>"
                    "<li>Open <b>Settings</b>, tap <b>Profile Downloaded</b> at the top, then <b>Install</b>.</li>"
                    "<li>Settings &rarr; General &rarr; About &rarr; <b>Certificate Trust Settings</b>: turn on "
                    "<b>Robot Eye local CA</b>.</li>"
                    f"<li>Open <a href='https://{ip}:8443'>https://{ip}:8443</a>.</li></ol>"
                    "<p>Remove the profile after the hackathon (Settings &rarr; General &rarr; VPN &amp; Device Management).</p>"
                    ).encode()
            ctype = "text/html; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class Server(ThreadingHTTPServer):
    def handle_error(self, request, client_address):
        e = sys.exc_info()[1]
        if isinstance(e, ssl.SSLError):           # one line, not a traceback: says WHY the phone refused
            print(f"TLS refused by {client_address[0]}: {getattr(e, 'reason', None) or e}", flush=True)
            return
        if isinstance(e, ConnectionError):
            return
        super().handle_error(request, client_address)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"                 # keep-alive: the page posts ~15 times a second

    def log_message(self, *args):
        pass

    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            print(f"page opened by {self.client_address[0]}", flush=True)
        if self.path in FILES:
            name, ctype = FILES[self.path]
            with open(os.path.join(HERE, name), "rb") as f:
                self._send(200, f.read(), ctype)
        elif self.path.startswith("/say"):           # the phone polls for lines typed on the Mac
            try:
                after = int(self.path.split("after=", 1)[1]) if "after=" in self.path else -1
            except ValueError:
                after = -1
            with SAY_LOCK:
                last = SAY[-1]["id"] if SAY else 0
                msgs = [m for m in SAY if m["id"] > after] if after >= 0 else []
            self._send(200, json.dumps({"msgs": msgs, "last": last}))
        elif self.path == "/tel":
            try:
                with urllib.request.urlopen(DRIVE + "/tel", timeout=0.5) as r:
                    self._send(200, r.read())
            except OSError:
                self._send(502, '{"error": "drive.py not running"}')
        else:
            self._send(404, "{}")

    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length", 0) or 0))
        if self.path == "/auto":                  # speed and turn from the page -> drive.py (used only while Follow is ON)
            try:
                req = urllib.request.Request(DRIVE + "/auto", data=raw, method="POST",
                                             headers={"Content-Type": "application/json"})
                urllib.request.urlopen(req, timeout=0.25).read()
                self._send(200, "{}")
            except OSError:
                self._send(502, '{"error": "drive.py not running"}')
        elif self.path == "/log":                 # what the page reports (camera chosen, errors)
            try:
                print("phone:", json.dumps(json.loads(raw)), flush=True)
            except ValueError:
                print("phone:", raw[:300], flush=True)
            self._send(200, "{}")
        else:
            self._send(404, "{}")


def main():
    ip = lan_ip()
    crt, key = ensure_cert(ip)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(crt, key)
    server = Server(("0.0.0.0", PORT), Handler)
    server.socket = ctx.wrap_socket(server.socket, server_side=True, do_handshake_on_connect=False)
    CAHandler.ip = ip
    threading.Thread(target=ThreadingHTTPServer(("0.0.0.0", 8080), CAHandler).serve_forever, daemon=True).start()
    print(f"First time on this iPhone: open http://{ip}:8080 in Safari to trust this Mac.", flush=True)
    print(f"Then open https://{ip}:{PORT} in Safari (Ctrl+C to stop).", flush=True)
    print("Make Miguel talk: open http://localhost:8080/control on this Mac.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
