"""Follow controller: turns the target lock's TargetState into speed and turn commands.

Pure logic, no I/O and no clock: time comes in as the `t` argument, so the same code
runs live and on recorded video. DriveBridge (drive_bridge.py) sends the result.

Sources (the reference that already works on the real robot):
- firmware/balance/follow/follow.swift:38-44, 95-105 (person mode), 199-213 (yellow mode,
  whose gains were tuned on the robot)
- firmware/README.md, "Follow gains that worked on the robot"
- firmware/balance/drive.py:214-218 (the receiving end clamps v to +-0.45, w to +-1.2)

Conventions are those of types.py: normalized image coords with y DOWN; commands in
REP 103 + SI (v m/s forward positive, w rad/s LEFT positive: a target right of center
needs w < 0).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import NamedTuple

from app.vision.types import DriveCommand, Person, TargetState, TargetStatus

# ---------------------------------------------------------------------------
# Camera geometry: distance from where the feet touch the floor
# ---------------------------------------------------------------------------

# Sanity limits for ground-plane distance estimates.
MIN_GROUND_ANGLE_DEG = 2.0  # closer to the horizon than this and tiny pixel errors become meters
MIN_GROUND_DISTANCE_M = 0.2
MAX_GROUND_DISTANCE_M = 8.0


@dataclass(frozen=True)
class CameraGeometry:
    """Where the camera sits and what it sees.

    The FOV defaults are GUESSES for an iPhone main (1x, 26 mm-equivalent) camera streaming
    16:9 landscape over Continuity Camera: ~79.5 deg diagonal on a 4:3 sensor gives ~67 deg
    horizontal, and a 16:9 crop of the same width gives ~41 deg vertical. Calibrate them
    (tape a known distance on the floor and check where it lands in the picture).
    """

    height_m: float = 0.40  # optical center above the floor (firmware/README.md: "~40 cm off the floor")
    tilt_deg: float = 0.0  # pitch of the optical axis; positive = pitched UP
    vfov_deg: float = 41.0  # GUESS, see above
    hfov_deg: float = 67.0  # GUESS, see above

    def ground_distance(self, y: float, point_height_m: float = 0.0) -> float | None:
        """Horizontal distance (m) to a point at image row `y` (normalized, y down) that sits
        `point_height_m` above the floor, assuming flat ground. None when the point is at or
        above the horizon, too close to it to trust, or the result is outside a sane range."""
        below_axis = math.atan((y - 0.5) * 2.0 * math.tan(math.radians(self.vfov_deg) / 2.0))
        below_horizon = below_axis - math.radians(self.tilt_deg)
        if below_horizon < math.radians(MIN_GROUND_ANGLE_DEG):
            return None
        drop = self.height_m - point_height_m
        if drop <= 0:
            return None
        d = drop / math.tan(below_horizon)
        if not (MIN_GROUND_DISTANCE_M <= d <= MAX_GROUND_DISTANCE_M):
            return None
        return d

    def bearing_rad(self, x: float) -> float:
        """Horizontal angle to image column `x` (normalized), REP 103: LEFT positive."""
        return -math.atan((x - 0.5) * 2.0 * math.tan(math.radians(self.hfov_deg) / 2.0))


class FeetPoint(NamedTuple):
    y: float  # normalized image row where the feet are
    from_ankle: bool  # True: an ankle keypoint (sits above the floor); False: the box bottom


ANKLES = ("left_ankle", "right_ankle")


def feet_point(person: Person, min_conf: float = 0.5, edge_y: float = 0.98) -> FeetPoint | None:
    """Where the person's feet are in the image.

    The lowest confident ankle keypoint that is inside the frame; else the box bottom if the
    frame edge doesn't cut it off (y2 < edge_y); else None (feet not visible).
    """
    ys = [kp.y for name in ANKLES if (kp := person.keypoint(name, min_conf)) is not None and 0.0 <= kp.y <= 1.0]
    if ys:
        return FeetPoint(max(ys), True)
    if person.box.y2 < edge_y:
        return FeetPoint(person.box.y2, False)
    return None


# ---------------------------------------------------------------------------
# Controller
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FollowConfig:
    """Every tunable of the follow controller. "tuned" = worked on the real robot
    (yellow mode, follow.swift:205-212 and firmware/README.md); GUESS = not tested yet."""

    camera: CameraGeometry = CameraGeometry()

    # Turn: w = -k_w * (cx - 0.5), zero inside the dead zone, clamped. All tuned (follow.swift:205,210).
    k_w: float = 2.5  # rad/s per unit of horizontal offset (target at the picture edge = 1.25 rad/s)
    dead_x: float = 0.06  # |cx - 0.5| below this: don't turn
    w_max: float = 1.2  # rad/s; drive.py clamps to the same

    # Speed from distance: ratio = d / d_target - 1 ("how many times too far"), v = k_v * ratio.
    # Same law as the tuned yellow mode, where patch size ~ 1/distance (follow.swift:206-208).
    d_target_m: float = 1.5  # GUESS: follow.swift person mode's default width 0.28 is "~1.5 m" (follow.swift:16)
    k_v: float = 0.35  # m/s when twice as far as wanted (tuned)
    dead_ratio: float = 0.08  # |ratio| below this: don't move (tuned)
    v_max: float = 0.4  # m/s forward cap (tuned; drive.py clamps at 0.45)
    v_min: float = -0.15  # m/s most-negative speed from the law (tuned)
    d_min_m: float = 0.7  # GUESS: closer than this -> back off (follow.swift:43 TOO_CLOSE_W is "~0.7 m")
    v_back: float = -0.15  # m/s while too close: the tuned reverse limit (follow.swift:210)

    # Fallback when the feet aren't visible (distance unknown): box width vs a target width,
    # with the same ratio law (box width ~ 1/distance): ratio = target_box_w / box_w - 1.
    target_box_w: float = 0.28  # GUESS: follow.swift:28 default, but that was an UPPER-BODY box at ~1.5 m
    too_close_box_w: float = 0.55  # box wider than this -> back off (follow.swift:43, "~0.7 m")
    side_edge: float = 0.02  # a box within this of the left/right edge is cut off: its width
    # understates closeness, so don't drive forward on it (turning still centers the person)

    # Feet detection
    keypoint_min_conf: float = 0.5  # ankle keypoints below this confidence are ignored
    feet_edge_y: float = 0.98  # a box bottom at or below this is cut off by the frame edge
    ankle_height_m: float = 0.08  # GUESS: the ankle keypoint sits ~8 cm above the floor; without
    # this the distance comes out ~25% too far for a 0.40 m camera (0.40 / 0.32)

    # Smoothing: out = keep * previous + (1 - keep) * new, at the tuned ~15 Hz detection rate
    # (follow.swift:80 runs every 2nd frame of 30 fps). Scaled by the real frame gap so a
    # different frame rate gives the same time constant (~0.13 s).
    smooth_keep: float = 0.6  # tuned
    smooth_ref_dt_s: float = 1.0 / 15.0

    # Lost target
    lost_hold_s: float = 0.5  # stop and hold this long before searching (tuned: "stop after 0.5 s")
    search_w: float = 0.5  # rad/s, GUESS: slow turn toward where the target was last seen
    search_for_s: float = 5.0  # GUESS: search this long (after the hold), then give up and stop

    # Modes from follow.swift (--turn-only, --camera-back)
    turn_only: bool = False  # safe first test: only turn to face the person, never drive
    camera_back: bool = False  # the camera faces the robot's back: drive backward toward the person


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


class FollowController:
    """TargetState in, DriveCommand out, once per frame."""

    def __init__(self, config: FollowConfig = FollowConfig()) -> None:
        self.config = config
        self.reset()

    def reset(self) -> None:
        """Forget the smoothing state (e.g. when Follow is switched on, or a new video starts)."""
        self._v = 0.0
        self._w = 0.0
        self._last_t: float | None = None

    def update(self, state: TargetState, t: float) -> DriveCommand:
        dt = self._frame_gap(t)
        if state.status == TargetStatus.LOCKED and state.person is not None:
            return self._follow(state.person, dt)
        if state.status == TargetStatus.IDLE:
            return self._stop("idle")
        # LOST (or LOCKED without a person, which shouldn't happen: treat as just lost)
        lost_for = state.lost_for_s if state.status == TargetStatus.LOST else 0.0
        cfg = self.config
        if lost_for < cfg.lost_hold_s:
            return self._stop("lost: holding")
        if lost_for < cfg.lost_hold_s + cfg.search_for_s:
            left = state.last_seen_cx < 0.5  # last seen on the left of the picture -> turn left (w > 0)
            v, w = self._smooth(0.0, cfg.search_w if left else -cfg.search_w, dt)
            return DriveCommand(v=v, w=w, reason=f"lost: searching {'left' if left else 'right'}")
        return self._stop("lost: gave up")

    # --- internals ---

    def _frame_gap(self, t: float) -> float:
        prev, self._last_t = self._last_t, t
        if prev is None or t < prev:  # first frame, or time went backward (new video)
            return self.config.smooth_ref_dt_s
        return t - prev

    def _smooth(self, v_cmd: float, w_cmd: float, dt: float) -> tuple[float, float]:
        keep = self.config.smooth_keep ** (dt / self.config.smooth_ref_dt_s)
        self._v = keep * self._v + (1.0 - keep) * v_cmd
        self._w = keep * self._w + (1.0 - keep) * w_cmd
        return self._v, self._w

    def _stop(self, reason: str) -> DriveCommand:
        # Stops are immediate, not smoothed.
        self._v = 0.0
        self._w = 0.0
        return DriveCommand(v=0.0, w=0.0, reason=reason)

    def _follow(self, person: Person, dt: float) -> DriveCommand:
        cfg = self.config
        box = person.box

        ex = box.cx - 0.5
        w_cmd = 0.0 if abs(ex) < cfg.dead_x else -cfg.k_w * ex  # target on the right -> turn right (w < 0)
        w_cmd = _clamp(w_cmd, -cfg.w_max, cfg.w_max)

        distance = self.distance_to(person)
        if distance is not None:
            ratio = distance / cfg.d_target_m - 1.0
            too_close = distance < cfg.d_min_m
            cut_at_side = False
        else:  # feet not visible: judge distance by box width
            ratio = cfg.target_box_w / max(box.w, 1e-3) - 1.0
            too_close = box.w > cfg.too_close_box_w
            cut_at_side = box.x1 < cfg.side_edge or box.x2 > 1.0 - cfg.side_edge

        v_cmd = 0.0 if abs(ratio) < cfg.dead_ratio else cfg.k_v * ratio
        v_cmd = _clamp(v_cmd, cfg.v_min, cfg.v_max)
        if cut_at_side:
            v_cmd = min(v_cmd, 0.0)
        if too_close:
            v_cmd = cfg.v_back
        if cfg.turn_only:
            v_cmd = 0.0
        if cfg.camera_back:  # image left/right still map to the same turn direction; only v flips
            v_cmd = -v_cmd

        v, w = self._smooth(v_cmd, w_cmd, dt)
        reason = "too close: backing off" if too_close and not cfg.turn_only else "following"
        return DriveCommand(v=v, w=w, reason=reason, distance_m=distance)

    def distance_to(self, person: Person) -> float | None:
        """Ground-plane distance to the person's feet, or None when they aren't visible."""
        cfg = self.config
        fp = feet_point(person, cfg.keypoint_min_conf, cfg.feet_edge_y)
        if fp is None:
            return None
        return cfg.camera.ground_distance(fp.y, cfg.ankle_height_m if fp.from_ankle else 0.0)
