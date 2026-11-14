"""Debug view: the camera picture with what vision and the robot are doing drawn on top.

`render()` is pure drawing (no window), so it can be tested and saved to a file. `DebugWindow`
shows it with OpenCV; macOS only allows that from the main thread, so the server's asyncio loop
calls `show()` once per tick (imshow + waitKey(1), which doesn't block).

Drawn: every person (gray), the locked target (green, thick), hip/knee/ankle keypoints and leg
lines, the center line; text for fps and detector time, target status (LOST with seconds),
distance, the follow skill's v/w and reason, what the arbiter sends and from whom (e-stop in
red), and the robot link: connected, state, pitch, fault.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np

from app.vision.types import DriveCommand, Person, TargetState, TargetStatus
from app.vision.worker import Perception

# Body points worth drawing from 40 cm up (hips down), and the leg lines between them.
LEG_POINTS = ("left_hip", "right_hip", "left_knee", "right_knee", "left_ankle", "right_ankle")
LEG_LINES = (("left_hip", "left_knee"), ("left_knee", "left_ankle"),
             ("right_hip", "right_knee"), ("right_knee", "right_ankle"))
TORSO_LINES = (("left_shoulder", "right_shoulder"), ("left_shoulder", "left_hip"),
               ("right_shoulder", "right_hip"), ("left_hip", "right_hip"))

GREEN, GRAY, ORANGE, WHITE, RED, YELLOW = (
    (60, 220, 60), (160, 160, 160), (0, 165, 255), (255, 255, 255), (60, 60, 230), (0, 220, 255))

KEYS_HELP = "F follow on/off   Space e-stop   G arm   P park   X motors off   Q quit"
WINDOW_NAME = "Miguel.exe"


@dataclass(frozen=True)
class Hud:
    """Everything outside vision that the overlay shows."""

    robot: str = "mock"  # "mock" or "real"
    sent_v: float = 0.0  # what the arbiter decided this tick
    sent_w: float = 0.0
    source: str = "none"  # arbiter source: estop, joystick, skill, none
    skill: str | None = None  # running skill's name
    follow: DriveCommand | None = None  # the follow skill's last command (v/w + reason, distance)
    connected: bool = False
    telemetry: Any = None  # anything with .state, .pitch_deg, .fault (__main__ adapts the link's telemetry dict)
    vision_status: str = ""  # the worker's status, shown until frames arrive
    note: str = ""  # last event, e.g. "follow: nobody to follow"


def _px(x: float, y: float, w: int, h: int) -> tuple[int, int]:
    return int(x * w), int(y * h)


def draw_person(img: np.ndarray, p: Person, color: tuple[int, int, int], thick: int) -> None:
    h, w = img.shape[:2]
    cv2.rectangle(img, _px(p.box.x1, p.box.y1, w, h), _px(p.box.x2, p.box.y2, w, h), color, thick)
    for a, b in TORSO_LINES + LEG_LINES:
        ka, kb = p.keypoint(a), p.keypoint(b)
        if ka and kb:
            cv2.line(img, _px(ka.x, ka.y, w, h), _px(kb.x, kb.y, w, h), color, 2)
    for name in LEG_POINTS:
        k = p.keypoint(name)
        if k:
            cv2.circle(img, _px(k.x, k.y, w, h), 5, color, -1)


def _text(img: np.ndarray, lines: list[tuple[str, tuple[int, int, int]]], scale: float) -> None:
    step = int(34 * scale / 0.9)
    for i, (text, color) in enumerate(lines):
        y = step + i * step
        cv2.putText(img, text, (14, y), cv2.FONT_HERSHEY_SIMPLEX, scale, (0, 0, 0), 5, cv2.LINE_AA)
        cv2.putText(img, text, (14, y), cv2.FONT_HERSHEY_SIMPLEX, scale, color, 2, cv2.LINE_AA)


def _target_line(state: TargetState | None, engage_pending: bool, follow: DriveCommand | None) -> tuple[str, tuple[int, int, int]]:
    if state is None:
        return "target: -", WHITE
    status = state.status.value.upper()
    if engage_pending:
        status = "ENGAGING (stand 1-2 m in front, centered)"
    elif state.status is TargetStatus.LOST:
        status += f" {state.lost_for_s:.1f}s"
    dist = f"{follow.distance_m:.2f} m" if follow is not None and follow.distance_m is not None else "? m"
    color = {TargetStatus.LOCKED: GREEN, TargetStatus.LOST: ORANGE}.get(state.status, WHITE)
    return f"target: {status}   distance {dist}", color


def _robot_line(hud: Hud) -> tuple[str, tuple[int, int, int]]:
    if not hud.connected:
        return f"robot ({hud.robot}): not connected", RED
    tel = hud.telemetry
    if tel is None:
        return f"robot ({hud.robot}): connected, no telemetry yet", WHITE
    parts = [f"robot ({hud.robot}): {getattr(tel, 'state', '?')}"]
    pitch = getattr(tel, "pitch_deg", None)
    if pitch is not None:
        parts.append(f"pitch {pitch:+.1f} deg")
    fault = getattr(tel, "fault", None)
    if fault:
        parts.append(f"FAULT {fault}")
    return "   ".join(parts), RED if fault else WHITE


def render(perception: Perception | None, hud: Hud, max_width: int = 1280) -> np.ndarray:
    """A new BGR image: the frame (scaled to at most max_width) with the overlay drawn on it."""
    if perception is None:
        img = np.zeros((540, 960, 3), dtype=np.uint8)
    else:
        src = perception.frame.image
        h, w = src.shape[:2]
        if w > max_width:
            img = cv2.resize(src, (max_width, int(h * max_width / w)), interpolation=cv2.INTER_AREA)
        else:
            img = src.copy()
    h, w = img.shape[:2]
    scale = max(0.45, min(0.9, w / 1400))

    lines: list[tuple[str, tuple[int, int, int]]] = []
    if perception is None:
        lines.append((f"vision: {hud.vision_status or 'no frames yet'}", YELLOW))
        lines.append(_target_line(None, False, None))
    else:
        state = perception.target
        target = state.person if state.status is TargetStatus.LOCKED else None
        for p in perception.people:
            if p is not target:
                draw_person(img, p, GRAY, 2)
        if target is not None:
            draw_person(img, target, GREEN, 5)
        cv2.line(img, (w // 2, 0), (w // 2, h), WHITE, 1)  # center line
        lines.append((f"{perception.fps:4.1f} fps   detector {perception.detect_s * 1000:3.0f} ms   "
                      f"latency {perception.latency_s * 1000:3.0f} ms   people {len(perception.people)}", WHITE))
        lines.append(_target_line(state, perception.engage_pending, hud.follow))

    if hud.skill:
        f = hud.follow
        follow_text = f"v {f.v:+.2f}  w {f.w:+.2f}  {f.reason}" if f is not None else "starting"
        lines.append((f"{hud.skill}: {follow_text}", WHITE))
    else:
        lines.append(("follow: off (press F)", GRAY))
    if hud.source == "estop":
        lines.append(("E-STOP ON: sending v 0 w 0 (Space releases)", RED))
    else:
        lines.append((f"sending v {hud.sent_v:+.2f} m/s  w {hud.sent_w:+.2f} rad/s  from {hud.source}", WHITE))
    lines.append(_robot_line(hud))
    if hud.note:
        lines.append((hud.note, YELLOW))
    lines.append((KEYS_HELP, GRAY))
    _text(img, lines, scale)
    return img


class DebugWindow:
    """An OpenCV window. Call show() from the main thread only (macOS)."""

    def __init__(self, name: str = WINDOW_NAME) -> None:
        self.name = name

    def show(self, image: np.ndarray) -> int:
        """Show the image and poll the keyboard without blocking. Returns the key code, or -1."""
        cv2.imshow(self.name, image)
        return cv2.waitKey(1)

    def close(self) -> None:
        cv2.destroyAllWindows()
        cv2.waitKey(1)  # lets macOS actually close the window
