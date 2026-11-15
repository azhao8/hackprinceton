"""Possible-fall detection (Alex's redesign, Sat night): fast and free on the laptop, then Claude checks.

Stage 1 (every frame, FallDetector): a person whose body is near horizontal (the shoulders-to-hips
line more than 55 deg from vertical, in pixels) or whose box is much wider than tall, staying like
that for HOLD_S. Stage 2 (FallWatcher): one camera frame goes to Claude ("is someone on the floor or
in distress?"); only a yes raises the family app's alert, and the agent then asks her if she's okay.

Known limit: the camera sits low and tilts up, so a person lying on the floor may be partly out of
view. The control page's "Test fall alert" button runs the same path for the demo.
"""

from __future__ import annotations

import asyncio
import logging
import math
import os
import time
from collections.abc import Awaitable, Callable
from typing import Any

log = logging.getLogger("app.vision.fall")

TILT_DEG = 55.0         # torso this far from vertical counts as lying
WIDE = 1.3              # box width / height above this counts as lying
HOLD_S = 2.5            # it has to stay like that this long
COOLDOWN_S = 120.0      # one alert per two minutes at most
CONFIRM_Q = ("Is a person lying on the floor, fallen, or in distress in this picture? Start your answer "
             "with yes or no, then say in one short sentence what you see.")


def torso_tilt_deg(person: Any, width: int, height: int) -> float | None:
    """Angle of the shoulders-to-hips line from vertical, in degrees (0 = upright), or None."""
    pts = {n: person.keypoint(n, 0.4) for n in ("left_shoulder", "right_shoulder", "left_hip", "right_hip")}
    if any(v is None for v in pts.values()):
        return None
    sx = (pts["left_shoulder"].x + pts["right_shoulder"].x) / 2 * width
    sy = (pts["left_shoulder"].y + pts["right_shoulder"].y) / 2 * height
    hx = (pts["left_hip"].x + pts["right_hip"].x) / 2 * width
    hy = (pts["left_hip"].y + pts["right_hip"].y) / 2 * height
    if abs(hx - sx) < 1e-6 and abs(hy - sy) < 1e-6:
        return None
    return math.degrees(math.atan2(abs(hx - sx), abs(hy - sy)))


def lying(person: Any, width: int, height: int) -> bool:
    tilt = torso_tilt_deg(person, width, height)
    if tilt is not None:
        return tilt > TILT_DEG
    b = person.box
    w, h = (b.x2 - b.x1) * width, (b.y2 - b.y1) * height
    return h > 0 and w / h > WIDE


class FallDetector:
    """Stage 1. update() each new perception; returns a short description when a fall is suspected."""

    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self.clock = clock
        self._since: float | None = None
        self._last_alert = -math.inf

    def update(self, perception: Any) -> str | None:
        now = self.clock()
        people = list(getattr(getattr(perception, "detections", None), "people", []) or [])
        frame = getattr(perception, "frame", None)
        if not people or frame is None:
            self._since = None
            return None
        w, h = frame.width, frame.height
        down = [p for p in people if lying(p, w, h)]
        if not down:
            self._since = None
            return None
        if self._since is None:
            self._since = now
        if now - self._since < HOLD_S or now - self._last_alert < COOLDOWN_S:
            return None
        self._last_alert, self._since = now, None
        return "Someone looks like they are lying down and hasn't gotten up."


class FallWatcher:
    """Stage 2 and the loop: watches vision, asks Claude to confirm, raises the alert."""

    def __init__(self, latest: Callable[[], Any], snapshot: Callable[[], bytes | None],
                 raise_alert: Callable[[str], Any],
                 confirm: Callable[[bytes], Awaitable[str]] | None = None, detector: FallDetector | None = None,
                 period_s: float = 0.2):
        self.latest, self.snapshot, self.raise_alert = latest, snapshot, raise_alert
        self.confirm = confirm
        self.detector = detector or FallDetector()
        self.period_s = period_s
        self._seen: Any = None

    async def check_once(self) -> bool:
        p = self.latest()
        if p is None or p is self._seen:
            return False
        self._seen = p
        suspect = self.detector.update(p)
        if suspect is None:
            return False
        jpeg = self.snapshot()
        saw = suspect
        if jpeg is not None:
            try:
                answer = await self._confirm(jpeg)
            except Exception as e:  # noqa: BLE001 - no network / no key: better a false alarm than a missed fall
                log.warning("fall: couldn't double-check with Claude (%s); raising the alert anyway", e)
                answer = "yes " + suspect
            if not answer.strip().lower().startswith("yes"):
                log.info("fall: Claude says no (%s)", answer[:120])
                return False
            saw = answer.strip()[3:].lstrip(" ,.:-") or suspect
        log.warning("fall: possible fall, raising the alert: %s", saw)
        self.raise_alert(saw)
        return True

    async def _confirm(self, jpeg: bytes) -> str:
        if self.confirm is not None:
            return await self.confirm(jpeg)
        from app.brain.vision_check import describe_scene

        return await describe_scene(jpeg, question=CONFIRM_Q)

    async def run(self) -> None:
        log.info("fall detection on (pose on every frame, Claude confirms)")
        while True:
            try:
                await self.check_once()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - never kill the server
                log.exception("fall check failed")
            await asyncio.sleep(self.period_s)


def enabled() -> bool:
    return os.environ.get("FALL_DETECT", "1").strip().lower() not in ("0", "false", "no", "off")
