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
from typing import Protocol

log = logging.getLogger("app.link")

PORT = 4210
FRESH_S = 0.5            # telemetry or ack older than this means the link is down
ALLOWED_LETTERS = set("xP5LRFB")   # never "g": a person arms the robot


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
        loop = asyncio.get_running_loop()
        infos = await loop.getaddrinfo(self.host, self.port, type=socket.SOCK_DGRAM)  # resolves balancebot.local too
        addr = infos[0][4][:2]
        self._transport, _ = await loop.create_datagram_endpoint(lambda: _Proto(self), remote_addr=addr)
        log.info("link: UDP to %s:%d (%s)", self.host, self.port, addr[0])

    async def close(self) -> None:
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
