"""Shared data types for vision and follow-me.

Every module in app/vision builds on these. Nothing outside the detector adapter
imports a model library (Ultralytics, MediaPipe, ...): detectors convert their
output into these types, so a detector can be swapped without touching the rest.

Conventions
- Image coordinates are NORMALIZED to 0..1: x to the right, y DOWN, origin at the
  top-left of the frame. Multiply by Frame.width/height for pixels.
- Times are time.monotonic() seconds.
- Robot commands follow ROS REP 103 and SI units: v in m/s (forward positive),
  w in rad/s (LEFT positive). A target right of center needs w < 0.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

import numpy as np

# COCO keypoint order, as YOLO pose models output it.
KEYPOINT_NAMES: tuple[str, ...] = (
    "nose", "left_eye", "right_eye", "left_ear", "right_ear",
    "left_shoulder", "right_shoulder", "left_elbow", "right_elbow",
    "left_wrist", "right_wrist", "left_hip", "right_hip",
    "left_knee", "right_knee", "left_ankle", "right_ankle",
)


@dataclass(frozen=True)
class Frame:
    """One camera or video frame."""

    t: float  # capture time: time.monotonic() seconds, or index / fps for offline video playback
    index: int  # frame counter from the source, starting at 0
    image: np.ndarray  # BGR, uint8, shape (height, width, 3)

    @property
    def width(self) -> int:
        return int(self.image.shape[1])

    @property
    def height(self) -> int:
        return int(self.image.shape[0])


@dataclass(frozen=True)
class Box:
    """Axis-aligned box in normalized image coordinates."""

    x1: float
    y1: float
    x2: float
    y2: float

    @property
    def cx(self) -> float:
        return (self.x1 + self.x2) / 2

    @property
    def cy(self) -> float:
        return (self.y1 + self.y2) / 2

    @property
    def w(self) -> float:
        return self.x2 - self.x1

    @property
    def h(self) -> float:
        return self.y2 - self.y1

    @property
    def area(self) -> float:
        return max(0.0, self.w) * max(0.0, self.h)

    def iou(self, other: Box) -> float:
        ix = max(0.0, min(self.x2, other.x2) - max(self.x1, other.x1))
        iy = max(0.0, min(self.y2, other.y2) - max(self.y1, other.y1))
        inter = ix * iy
        union = self.area + other.area - inter
        return inter / union if union > 0 else 0.0


@dataclass(frozen=True)
class Keypoint:
    x: float  # normalized
    y: float  # normalized
    conf: float  # 0..1 visibility/confidence from the model


@dataclass(frozen=True)
class Person:
    """One detected person in one frame."""

    box: Box
    score: float  # detector confidence 0..1
    keypoints: dict[str, Keypoint] = field(default_factory=dict)  # names from KEYPOINT_NAMES; may be empty

    def keypoint(self, name: str, min_conf: float = 0.5) -> Keypoint | None:
        """The named keypoint if it's confident enough, else None."""
        kp = self.keypoints.get(name)
        return kp if kp is not None and kp.conf >= min_conf else None


@dataclass(frozen=True)
class Detections:
    """Everything the detector found in one frame."""

    frame_t: float  # Frame.t of the frame these came from
    frame_index: int
    width: int  # pixels of the frame the detector saw
    height: int
    people: list[Person]
    latency_s: float = 0.0  # time the detector took


class TargetStatus(str, Enum):
    IDLE = "idle"  # not following anyone (Follow is off, or never locked)
    LOCKED = "locked"  # following the locked person; `person` is set
    LOST = "lost"  # had a target, can't see it right now; keeps trying to re-acquire it


@dataclass(frozen=True)
class TargetState:
    """What the target lock knows after one frame."""

    status: TargetStatus
    person: Person | None = None  # the locked person in THIS frame (only when LOCKED)
    lost_for_s: float = 0.0  # seconds since last seen (when LOST)
    last_seen_cx: float = 0.5  # normalized x where the target was last seen (for searching)
    reacquired: bool = False  # True on the frame the lock came back after being LOST


@dataclass(frozen=True)
class DriveCommand:
    """Speed and turn targets for the robot (REP 103, SI)."""

    v: float  # m/s, forward positive
    w: float  # rad/s, left positive
    reason: str = ""  # short human-readable note, e.g. "following", "lost: searching left"
    distance_m: float | None = None  # estimated distance to the target, if known
