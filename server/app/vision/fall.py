"""Possible-fall detection (Alex's redesign, Sat night): fast and free on the laptop, then Claude checks.

Stage 1 (every frame, FallDetector): a person whose body is near horizontal (the shoulders-to-hips
line more than 55 deg from vertical, in pixels; without those keypoints, a box much wider than tall
that isn't cut off by a frame edge), staying like that for HOLD_S. Pose often drops a lying person for
a frame, so only a gap of RESET_S restarts the hold. Stage 2 (FallWatcher): a short clip (CLIP_FRAMES
camera frames CLIP_GAP_S apart) goes to the LLM, Claude or the local model ("is someone on the floor or
in distress?"; several frames tell lying still from bending down); only a yes raises the family app's alert, and the
agent then asks her if she's okay. After a no, it may ask again in RECHECK_S if she's still down.
After an alert: nothing for COOLDOWN_S, and nothing until someone is seen upright for REARM_S, so one
fall gives one alert.

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
WIDE = 1.3              # without torso keypoints: box width / height above this counts as lying
EDGE = 0.02             # a box this close to a frame edge is cut off, so its shape says nothing
HOLD_S = 2.5            # it has to stay like that this long
RESET_S = 0.75          # only a not-lying (or nobody) gap this long restarts the hold
RECHECK_S = 25.0        # after a suspicion that wasn't raised (Claude said no), ask again this soon at most
COOLDOWN_S = 120.0      # after a raised alert, no new one for two minutes
REARM_S = 2.0           # ...and none until someone has been seen upright (nobody lying) this long
CLIP_FRAMES = 3         # the confirmation looks at this many frames...
CLIP_GAP_S = 0.3        # ...this far apart
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
    if min(b.x1, b.y1) <= EDGE or max(b.x2, b.y2) >= 1 - EDGE:
        return False    # cut off by the frame (say, head and shoulders at the bottom): wide means nothing
    w, h = (b.x2 - b.x1) * width, (b.y2 - b.y1) * height
    return h > 0 and w / h > WIDE


class FallDetector:
    """Stage 1. update() each new perception; returns a short description when a fall is suspected.

    A suspicion blocks the next one for RECHECK_S. Call confirmed() once the alert is raised: then
    nothing for COOLDOWN_S, and nothing until someone has been seen upright for REARM_S.
    """

    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self.clock = clock
        self._since: float | None = None        # when someone started lying (the hold)
        self._clear_since: float | None = None  # when the current not-lying / nobody gap started
        self._up_since: float | None = None     # when the current upright streak started
        self._last_up = -math.inf               # last frame with people and nobody lying
        self._next_ok = -math.inf               # no suspicion before this
        self._armed = True                      # False after an alert, until she's seen up again

    def update(self, perception: Any) -> str | None:
        now = self.clock()
        people = list(getattr(getattr(perception, "detections", None), "people", []) or [])
        frame = getattr(perception, "frame", None)
        down = up = False
        if people and frame is not None:
            down = any(lying(p, frame.width, frame.height) for p in people)
            up = not down
        # Re-arm: someone upright and nobody lying for REARM_S (short dropouts don't break the streak).
        if up:
            if self._up_since is None or now - self._last_up >= RESET_S:
                self._up_since = now
            self._last_up = now
            if now - self._up_since >= REARM_S:
                self._armed = True
        elif down:
            self._up_since = None
        # The hold: survives gaps shorter than RESET_S.
        if not down:
            if self._clear_since is None:
                self._clear_since = now
            if now - self._clear_since >= RESET_S:
                self._since = None
            return None
        self._clear_since = None
        if self._since is None:
            self._since = now
        if now - self._since < HOLD_S or now < self._next_ok or not self._armed:
            return None
        self._since, self._next_ok = None, now + RECHECK_S
        return "Someone looks like they are lying down and hasn't gotten up."

    def confirmed(self) -> None:
        """The alert went out: cool down, and wait for her to get up before suspecting again."""
        self._next_ok = max(self._next_ok, self.clock() + COOLDOWN_S)
        self._armed, self._up_since = False, None


class FallWatcher:
    """Stage 2 and the loop: watches vision, asks Claude to confirm, raises the alert."""

    def __init__(self, latest: Callable[[], Any], snapshot: Callable[[], bytes | None],
                 raise_alert: Callable[[str], Any],
                 confirm: Callable[[list[bytes]], Awaitable[str]] | None = None, detector: FallDetector | None = None,
                 period_s: float = 0.2, clip_frames: int = CLIP_FRAMES, clip_gap_s: float = CLIP_GAP_S):
        """confirm: frames (oldest first) -> an answer starting with yes or no (default: describe_scene)."""
        self.latest, self.snapshot, self.raise_alert = latest, snapshot, raise_alert
        self.clip_frames, self.clip_gap_s = clip_frames, clip_gap_s
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
        frames = await self._clip()
        saw = suspect
        if frames:
            try:
                answer = await self._confirm(frames)
            except Exception as e:  # noqa: BLE001 - no network / no key: better a false alarm than a missed fall
                log.warning("fall: couldn't double-check with Claude (%s); raising the alert anyway", e)
                answer = "yes " + suspect
            if not answer.strip().lower().startswith("yes"):
                log.info("fall: Claude says no (%s)", answer[:120])
                return False
            saw = answer.strip()[3:].lstrip(" ,.:-") or suspect
        log.warning("fall: possible fall, raising the alert: %s", saw)
        self.raise_alert(saw)
        self.detector.confirmed()   # only now does the long cooldown start
        return True

    async def _clip(self) -> list[bytes]:
        """CLIP_FRAMES frames CLIP_GAP_S apart, oldest first (an unchanged frame is skipped)."""
        frames: list[bytes] = []
        for i in range(max(1, self.clip_frames)):
            if i:
                await asyncio.sleep(self.clip_gap_s)
            jpeg = self.snapshot()
            if jpeg is not None and (not frames or jpeg != frames[-1]):
                frames.append(jpeg)
        return frames

    async def _confirm(self, frames: list[bytes]) -> str:
        if self.confirm is not None:
            return await self.confirm(frames)
        from app.brain.vision_check import describe_scene

        return await describe_scene(frames, question=CONFIRM_Q)

    async def run(self) -> None:
        log.info("fall detection on (pose on every frame, the LLM confirms on a short clip)")
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
