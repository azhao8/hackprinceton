"""HTTPS for the phone page. Safari only gives a page the camera over HTTPS, and iPhones refuse
self-signed pages, so this keeps a tiny local certificate authority that the iPhone trusts once.

Adapted from John's firmware/balance/phone/phone_server.py (same CA, same limits):
- The CA only vouches for private-network addresses and localhost, lasts 30 days, and its key
  never leaves this laptop (server/cert/, git-ignored).
- The server certificate is remade when the laptop's IP changes; the CA is kept.
"""

from __future__ import annotations

import socket
import ssl
import subprocess
from pathlib import Path

CERT_DIR = Path(__file__).resolve().parents[2] / "cert"


def lan_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))   # no packet is sent; this picks the outgoing interface
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def _openssl(*args: str) -> None:
    subprocess.run(["openssl", *args], check=True, capture_output=True)


def ensure_cert(ip: str, d: Path = CERT_DIR) -> tuple[Path, Path]:
    d.mkdir(parents=True, exist_ok=True)
    p = lambda n: d / n  # noqa: E731
    if not (p("ca.pem").exists() and p("ca.key").exists()):
        p("ca.cnf").write_text(
            "[req]\ndistinguished_name = dn\nx509_extensions = v3\nprompt = no\n"
            "[dn]\nCN = Miguel.exe local CA (HackPrinceton)\n"
            "[v3]\nbasicConstraints = critical, CA:TRUE, pathlen:0\nkeyUsage = critical, keyCertSign, cRLSign\n"
            "subjectKeyIdentifier = hash\n"
            "nameConstraints = critical, permitted;IP:10.0.0.0/255.0.0.0, permitted;IP:172.16.0.0/255.240.0.0, "
            "permitted;IP:192.168.0.0/255.255.0.0, permitted;DNS:localhost\n")
        _openssl("req", "-x509", "-newkey", "rsa:2048", "-nodes", "-sha256", "-days", "30",
                 "-keyout", str(p("ca.key")), "-out", str(p("ca.pem")), "-config", str(p("ca.cnf")))
        _openssl("x509", "-in", str(p("ca.pem")), "-outform", "der", "-out", str(p("ca.cer")))
        for n in ("cert.pem", "ip.txt"):
            p(n).unlink(missing_ok=True)
    if p("cert.pem").exists() and p("ip.txt").exists() and p("ip.txt").read_text().strip() == ip:
        return p("cert.pem"), p("key.pem")
    p("srv.cnf").write_text(
        f"subjectAltName = IP:{ip},DNS:localhost\nextendedKeyUsage = serverAuth\n"
        "keyUsage = critical, digitalSignature, keyEncipherment\nbasicConstraints = critical, CA:FALSE\n"
        "authorityKeyIdentifier = keyid\n")
    _openssl("req", "-new", "-newkey", "rsa:2048", "-nodes", "-keyout", str(p("key.pem")), "-out", str(p("srv.csr")),
             "-subj", "/CN=miguel-server")
    _openssl("x509", "-req", "-in", str(p("srv.csr")), "-CA", str(p("ca.pem")), "-CAkey", str(p("ca.key")),
             "-CAcreateserial", "-sha256", "-days", "30", "-out", str(p("cert.pem")), "-extfile", str(p("srv.cnf")))
    p("ip.txt").write_text(ip)
    return p("cert.pem"), p("key.pem")


def ssl_context(ip: str) -> ssl.SSLContext:
    crt, key = ensure_cert(ip)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(crt, key)
    return ctx
