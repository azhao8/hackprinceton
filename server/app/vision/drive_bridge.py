"""Sends follow commands to the robot's bench bridge (firmware/balance/drive.py, POST /auto).

drive.py (firmware/balance/drive.py:214-218) takes JSON {"v", "w", "found", "cx", "h"}, clamps
v to +-0.45 m/s and w to +-1.2 rad/s, ignores data older than 0.3 s, only drives while Follow
is switched ON on its page, and lets held keys override. So the vision loop must keep sending
every frame (at least ~4 Hz) or the robot stops following and holds position.

This bridge never blocks the vision loop and never raises on network errors: send() drops the
command into a one-slot mailbox (latest command wins) and a background thread POSTs it with a
short timeout, like follow.swift's post() (follow.swift:224-229). dry_run=True, the default,
never touches the network: it only records and logs what it would send.

Standard library only (urllib).
"""

from __future__ import annotations

import json
import logging
import threading
import urllib.request
from collections import deque

from app.vision.types import DriveCommand

log = logging.getLogger(__name__)

DEFAULT_URL = "http://127.0.0.1:8765/auto"


class DriveBridge:
    def __init__(self, url: str = DEFAULT_URL, dry_run: bool = True, timeout_s: float = 0.2) -> None:
        self.url = url
        self.dry_run = dry_run
        self.timeout_s = timeout_s
        self.history: deque[dict] = deque(maxlen=1000)  # payloads handed to send(), newest last
        self.posted = 0  # POSTs that got a response
        self.errors = 0  # POSTs that failed (network error, timeout, bad status)
        self._pending: dict | None = None
        self._cond = threading.Condition()
        self._closed = False
        self._busy = False
        self._thread: threading.Thread | None = None
        # No proxies: the bridge is on this machine, and a system proxy must never see robot commands.
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    @staticmethod
    def payload(cmd: DriveCommand, found: bool, cx: float, h: float) -> dict:
        """Exactly what drive.py's /auto handler reads."""
        return {"v": float(cmd.v), "w": float(cmd.w), "found": bool(found), "cx": float(cx), "h": float(h)}

    def send(self, cmd: DriveCommand, found: bool, cx: float, h: float) -> None:
        """Queue one command. Returns at once; a newer command replaces one not sent yet."""
        body = self.payload(cmd, found, cx, h)
        self.history.append(body)
        if self.dry_run:
            log.debug("dry run, would POST %s %s", self.url, body)
            return
        with self._cond:
            if self._closed:
                return
            self._pending = body
            if self._thread is None:
                self._thread = threading.Thread(target=self._run, name="drive-bridge", daemon=True)
                self._thread.start()
            self._cond.notify()

    def stop(self) -> None:
        """Send a zero command (doesn't wait for it to go out)."""
        self.send(DriveCommand(v=0.0, w=0.0, reason="stop"), found=False, cx=0.5, h=0.0)

    def close(self, timeout_s: float = 0.5) -> None:
        """Send a stop, wait up to timeout_s for it to go out, then end the sender thread."""
        self.stop()
        with self._cond:
            self._cond.wait_for(lambda: self._pending is None and not self._busy, timeout=timeout_s)
            self._closed = True
            self._cond.notify_all()

    def wait_idle(self, timeout_s: float = 1.0) -> bool:
        """Wait until nothing is queued or in flight. True if it got there (for tests and shutdown)."""
        with self._cond:
            return self._cond.wait_for(lambda: self._pending is None and not self._busy, timeout=timeout_s)

    # --- sender thread ---

    def _run(self) -> None:
        while True:
            with self._cond:
                self._cond.wait_for(lambda: self._pending is not None or self._closed)
                if self._pending is None:  # closed and nothing left to send
                    return
                body, self._pending = self._pending, None
                self._busy = True
            try:
                self._post(body)
            finally:
                with self._cond:
                    self._busy = False
                    self._cond.notify_all()

    def _post(self, body: dict) -> None:
        req = urllib.request.Request(
            self.url,
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with self._opener.open(req, timeout=self.timeout_s) as resp:
                resp.read()
            self.posted += 1
        except Exception as e:  # never let a network problem reach the vision loop
            self.errors += 1
            if self.errors == 1 or self.errors % 50 == 0:
                log.warning("drive bridge: POST %s failed (%d so far): %s", self.url, self.errors, e)
