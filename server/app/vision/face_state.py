"""What the phone's face needs from the server's vision: where the locked person is and what just happened.

The server's status (`GET /tel`, the WebSocket `status`) carries it as `face`, so the phone page can
point Miguel's eyes at the person and react once to each event:

    "face": {
      "status": "idle" | "locked" | "lost",
      "target": {"cx": 0..1, "cy": 0..1, "w": 0..1} | null,      # only while locked
      "event":  {"id": 7, "kind": "found" | "lost" | "waiting" | "too_close" | "gave_up"} | null
    }

`target` is a gaze point in the camera frame exactly as the phone streamed it (normalized, x right,
y down; un-flipped if the server mirrors the phone's frames before vision). It is the head: the mean
of the confident face keypoints (nose, eyes, ears), or, without any, the box's center x and a point
15% of the box height below its top. `w` is the locked person's box width (bigger = closer).

Events, each with a new, increasing `id` (the phone reacts when `id` changes):
- `found`: the status became locked (the first lock, or reacquired after being lost: the same
  person, by their clothes, came back and following resumes);
- `lost`: locked -> lost (also when vision stops delivering while locked);
- `waiting`: the person is still gone after the short search, and Miguel now waits in place for
  them to come back (the follow command's reason became "lost: waiting for you to come back");
  once per time it starts waiting. Follow stays on; `found` follows when they come back;
- `too_close`: the follow command's reason became "too close..."; at most once per 3 s;
- `gave_up`: a command said "lost: gave up" (each such command once). Follow no longer gives up
  (it waits instead, Sat Nov 14), so it doesn't send this any more; kept for the contract.

Pure: no threads, clocks or I/O. The server feeds it the newest vision result and the follow
skill's last command, and reads `snapshot()`.
"""

from __future__ import annotations

import math
from typing import Any

from app.vision.follow import WAITING_REASON
from app.vision.types import Person, TargetStatus

HEAD_KEYPOINTS = ("nose", "left_eye", "right_eye", "left_ear", "right_ear")
HEAD_MIN_CONF = 0.5
HEAD_FROM_TOP = 0.15  # without face keypoints: this far down the box from its top
TOO_CLOSE_EVERY_S = 3.0
STALE_AFTER_S = 1.0  # an older vision result means vision stopped delivering


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def gaze_point(person: Person, mirrored: bool = False) -> dict:
    """{cx, cy, w} for the face to look at, in the phone's own (un-mirrored) frame, rounded to 3 places."""
    box = person.box
    head = [kp for name in HEAD_KEYPOINTS if (kp := person.keypoint(name, HEAD_MIN_CONF)) is not None]
    if head:
        cx = sum(kp.x for kp in head) / len(head)
        cy = sum(kp.y for kp in head) / len(head)
    else:
        cx, cy = box.cx, box.y1 + HEAD_FROM_TOP * box.h
    if mirrored:
        cx = 1.0 - cx
    return {"cx": round(_clamp01(cx), 3), "cy": round(_clamp01(cy), 3), "w": round(_clamp01(box.w), 3)}


class FaceEvents:
    """Turns the vision worker's Perception and the follow skill's last command into the `face` status."""

    def __init__(self, too_close_every_s: float = TOO_CLOSE_EVERY_S, stale_after_s: float = STALE_AFTER_S) -> None:
        self.too_close_every_s = too_close_every_s
        self.stale_after_s = stale_after_s
        self._status = "idle"
        self._target: dict | None = None
        self._event: dict | None = None
        self._last_id = 0
        self._was_too_close = False
        self._was_waiting = False
        self._last_too_close_at = -math.inf
        self._gave_up_cmd: Any = None

    def update(self, perception: Any, following: bool, command: Any, now: float, mirrored: bool = False) -> dict:
        """Feed the newest Perception (or None), whether Follow is running, the follow skill's
        `last_command` (or None) and the time on the Perception's clock (`published_at`). Safe to call
        as often as you like: the same inputs never make a second event."""
        status, target = "idle", None
        if following and perception is not None:
            state = perception.target
            stale = now - perception.published_at > self.stale_after_s
            if stale:
                status = "lost" if self._status != "idle" else "idle"
            elif state.status is TargetStatus.LOCKED and state.person is not None:
                status, target = "locked", gaze_point(state.person, mirrored)
            elif state.status is TargetStatus.LOST:
                status = "lost"

        if status == "locked" and self._status != "locked":
            self._emit("found")
        elif status == "lost" and self._status == "locked":
            self._emit("lost")
        self._status, self._target = status, target

        reason = str(getattr(command, "reason", "") or "")
        too_close = following and reason.startswith("too close")
        if too_close and not self._was_too_close and now - self._last_too_close_at >= self.too_close_every_s:
            self._last_too_close_at = now
            self._emit("too_close")
        self._was_too_close = too_close

        waiting = following and status == "lost" and reason == WAITING_REASON
        if waiting and not self._was_waiting:
            self._emit("waiting")
        self._was_waiting = waiting

        # The skill ends right after giving up, so this is checked whether or not Follow still runs.
        if command is not None and reason.startswith("lost: gave up") and command is not self._gave_up_cmd:
            self._gave_up_cmd = command
            self._emit("gave_up")
        return self.snapshot()

    def snapshot(self) -> dict:
        return {"status": self._status, "target": None if self._target is None else dict(self._target),
                "event": None if self._event is None else dict(self._event)}

    def _emit(self, kind: str) -> None:
        self._last_id += 1
        self._event = {"id": self._last_id, "kind": kind}
