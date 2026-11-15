"""Robot link (owner: Alex): the only code that talks to the robot (CLAUDE.md).

It speaks contract v1 (contract/README.md). `RobotLink` is the interface the rest of the server
uses; `UdpLink` speaks it over Wi-Fi (the robot, or the mock robot on this laptop). Grant's USB
serial link implements the same interface.

- `send_cmd(v, w, mode)` sends one `cmd` with the next `seq`. The app calls it about 20 times a
  second; if it stops, the robot's 300 ms watchdog stops the robot.
- `send_letter(c)` sends a one-letter command (`x`, `P`, `5`, `L`, `R`, `F`, `B`). The server
  never sends `g`: starting to balance is a person's keypress while they hold the robot.
- `health()` says whether the link works both ways: telemetry is fresh, and the robot is
  acknowledging the commands we're sending now.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import socket
import time
from collections import OrderedDict
from dataclasses import dataclass
from collections.abc import Callable
from typing import Any, Protocol

log = logging.getLogger("app.link")

PORT = 4210
FRESH_S = 0.5            # telemetry or ack older than this means the link is down
ALLOWED_LETTERS = set("xP5LRFBtyc")   # never "g": a person arms the robot. t/y: trim +/- 0.25 deg; c: recalibrate the gyro
TRIM_STEP_DEG = 0.25


@dataclass(frozen=True)
class Health:
    ok: bool                       # telemetry fresh and our commands acknowledged
    telemetry_age: float | None    # s since the last telemetry, None if never
    ack_age: float | None          # s since a command of ours was last acknowledged
    lag_ms: float | None           # round trip of the last acknowledged command


class RobotLink(Protocol):
    telemetry: dict | None

    async def start(self) -> None: ...
    async def close(self) -> None: ...
    def send_cmd(self, v: float, w: float, mode: str = "drive") -> None: ...
    def send_letter(self, letter: str) -> None: ...
    def health(self) -> Health: ...


class _Proto(asyncio.DatagramProtocol):
    def __init__(self, link: "UdpLink"):
        self.link = link

    def datagram_received(self, data: bytes, addr) -> None:  # type: ignore[override]
        self.link._on_packet(data)

    def error_received(self, exc: Exception) -> None:  # e.g. ICMP port unreachable: nobody listening
        log.debug("udp error: %s", exc)


class ReversedLink:
    """Any link with forward and backward swapped while `flipped()` is true (Alex, Sat 10 pm: the robot
    drove away from people when following, and W drove it backward). The server's "forward" becomes the
    firmware's backward for everything at once: the keyboard, follow, the agent's behaviors and the
    F / B steps. Turning is unchanged (left is still counter-clockwise seen from above). Telemetry is
    shown in the same frame: speeds and distance flip, and the wheels swap sides. Tilt stays in the
    firmware's frame, so the balance angle (trim) keeps its numbers.

    The server makes `flipped` follow the camera (Alex: "whichever way the camera faces is forward"),
    so switching between the phone's back and front camera switches forward too."""

    def __init__(self, link: Any, flipped: Callable[[], bool] = lambda: True):
        self._link = link
        self.flipped = flipped

    def send_cmd(self, v: float, w: float, mode: str = "drive") -> None:
        self._link.send_cmd(-v if self.flipped() else v, w, mode)

    def send_letter(self, letter: str) -> None:
        self._link.send_letter({"F": "B", "B": "F"}.get(letter, letter) if self.flipped() else letter)

    @property
    def telemetry(self) -> dict | None:
        tel = self._link.telemetry
        if not tel or not self.flipped():
            return tel
        out = dict(tel)
        if isinstance(tel.get("vl"), (int, float)) and isinstance(tel.get("vr"), (int, float)):
            out["vl"], out["vr"] = -tel["vr"], -tel["vl"]
        if isinstance(tel.get("x"), (int, float)):
            out["x"] = -tel["x"]
        return out

    def __getattr__(self, name: str) -> Any:   # start, close, health, arm, send_trim, ...
        return getattr(self._link, name)


class UdpLink:
    def __init__(self, host: str, port: int = PORT, clock=time.monotonic):
        self.host, self.port = host, port
        self.telemetry: dict | None = None
        self._clock = clock
        self._transport: asyncio.DatagramTransport | None = None
        # Start at a random seq: the robot remembers the last seq it saw, and an old ack from an
        # earlier run must not look like one of ours.
        self._seq = random.randint(1_000_000, 2_000_000_000)
        self._sent: OrderedDict[int, float] = OrderedDict()
        self._tel_at: float | None = None
        self._ack_at: float | None = None
        self._lag: float | None = None
        self._best_ack = 0

    async def start(self) -> None:
        """Connect to the robot. If its name doesn't resolve yet (rebooting, or this laptop isn't on the
        hotspot), keep going and retry every 2 s in the background instead of stopping the server."""
        loop = asyncio.get_running_loop()
        try:
            await self._connect(loop)
        except OSError as e:
            log.warning("link: can't find %s yet (%s); retrying every 2 s", self.host, e)
            self._retry = loop.create_task(self._keep_trying(loop))

    async def _connect(self, loop: asyncio.AbstractEventLoop) -> None:
        infos = await loop.getaddrinfo(self.host, self.port, type=socket.SOCK_DGRAM)  # resolves balancebot.local too
        addr = infos[0][4][:2]
        self._transport, _ = await loop.create_datagram_endpoint(lambda: _Proto(self), remote_addr=addr)
        log.info("link: UDP to %s:%d (%s)", self.host, self.port, addr[0])

    async def _keep_trying(self, loop: asyncio.AbstractEventLoop) -> None:
        while self._transport is None:
            await asyncio.sleep(2.0)
            try:
                await self._connect(loop)
            except OSError:
                continue

    async def close(self) -> None:
        retry = getattr(self, "_retry", None)
        if retry is not None:
            retry.cancel()
        if self._transport:
            self._transport.close()
            self._transport = None

    def _send(self, data: bytes) -> None:
        if self._transport:
            self._transport.sendto(data)

    def send_cmd(self, v: float, w: float, mode: str = "drive") -> None:
        self._seq += 1
        now = self._clock()
        self._sent[self._seq] = now
        while len(self._sent) > 200:
            self._sent.popitem(last=False)
        msg = {"t": "cmd", "seq": self._seq, "v": round(v, 3), "w": round(w, 3), "mode": mode}
        self._send(json.dumps(msg, separators=(",", ":")).encode())

    def send_letter(self, letter: str) -> None:
        if letter not in ALLOWED_LETTERS:
            raise ValueError(f"the server may not send {letter!r} (allowed: {''.join(sorted(ALLOWED_LETTERS))})")
        self._send(letter.encode())

    def send_trim(self, steps: int) -> None:
        """Shift the balance angle (trim) by steps x 0.25 deg: t raises it, y lowers it. One packet, so
        a lost packet loses all of them (the control page shows what was sent) rather than some."""
        if steps:
            self._send(('t' if steps > 0 else 'y').encode() * abs(steps))

    def arm(self) -> None:
        """Send g (start balancing). Only for a person's explicit press on this laptop's control page,
        while someone holds the robot upright (decision 0054). Never called by skills or the agent."""
        self._send(b"g")

    def _on_packet(self, data: bytes) -> None:
        try:
            msg = json.loads(data)
        except ValueError:
            return
        if not isinstance(msg, dict) or msg.get("t") != "tel":
            return
        now = self._clock()
        self.telemetry, self._tel_at = msg, now
        ack = msg.get("ack")
        if isinstance(ack, int) and ack in self._sent and ack > self._best_ack:
            self._best_ack, self._ack_at = ack, now
            self._lag = now - self._sent[ack]

    def health(self) -> Health:
        now = self._clock()
        tel_age = None if self._tel_at is None else now - self._tel_at
        ack_age = None if self._ack_at is None else now - self._ack_at
        ok = tel_age is not None and tel_age < FRESH_S and ack_age is not None and ack_age < FRESH_S
        return Health(ok, tel_age, ack_age, None if self._lag is None else self._lag * 1000)
