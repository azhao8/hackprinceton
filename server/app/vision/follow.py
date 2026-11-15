"""Follow controller: turns the target lock's TargetState into speed and turn commands.

Pure logic, no I/O and no clock: time comes in as the `t` argument, so the same code
runs live and on recorded video. The caller sends the result to the robot.

What the camera sees (open question T-14: the phone stays tilted UP, camera ~0.40 m off
the floor): at follow distance (0.7-2 m) the picture shows roughly thighs to head. The
feet are mostly OUT of frame, and close people are cut off at the top and the bottom. So
the bottom of a person's box is NOT where they stand: a box ending at the thighs would read
as ~2.5 m away for a person at 1 m, the robot would drive into them and "too close" would
never fire. Distance therefore comes from cues that survive the tilt:

1. Shoulder gap: the normalized x distance between the two shoulder keypoints, pinhole
   model d = k_shoulder_m / gap.
2. Box width vs a target width (box width ~ 1/distance), the law of follow.swift.
3. Ground plane from the ANKLE keypoints, only if both are confident and well inside the
   frame, and only with `FollowConfig.use_ground_plane` (off while the phone is tilted up).

The controller uses whichever cue says the person is CLOSER (fail-safe: a wrong cue can
only make it stop short, never drive into someone). If the shoulders say the person turned
sideways (one shoulder missing, or the gap collapsed while the box didn't shrink alike),
the shoulder cue is dropped and the robot never drives forward, it only turns (and backs
off if too close). A box cut off at the left/right picture edge can't drive forward either.

Lost target (follow.swift person mode): coast for ~0.3 s (speed decays, turn held), then,
if the person was last seen off-centre, turn toward that side to find them; if they
vanished near the centre (probably behind someone), hold still. After 2 s (`search_for_s`),
stop and WAIT in place ("lost: waiting for you to come back"), for as long as it takes: the
lock keeps looking for the same clothes, and when it re-acquires them the controller starts
fresh from where the person is now (no speed or turn carried over from before they left).
Past the coast it never drives forward or back while the person is lost; only the search turns.
(follow.swift gives up after 2 s; Alex's call, Sat Nov 14: Follow stays on and waits instead.)

Sources (the reference that already works on the real robot):
- firmware/balance/follow/follow.swift on main (a20140d): person mode lines 28 (targetW
  0.45), 43 (TOO_CLOSE_W = max(0.55, targetW + 0.15)), 95-113 (follow + lost behaviour),
  128 (SEARCH_FOR 2 s, SEARCH_W 0.5 rad/s); yellow mode 236-248 (gains tuned on the robot)
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

from app.vision.types import Box, DriveCommand, Person, TargetState, TargetStatus

# ---------------------------------------------------------------------------
# Camera geometry
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

    tilt_deg: the phone is tilted UP (T-14) but the angle hasn't been measured, so this stays
    0 by default. It only matters for the ground-plane cue, which is off by default.
    """

    height_m: float = 0.40  # optical center above the floor (firmware/README.md: "~40 cm off the floor")
    tilt_deg: float = 0.0  # pitch of the optical axis; positive = pitched UP (not measured, see above)
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


# ---------------------------------------------------------------------------
# Distance cues from one detected person
# ---------------------------------------------------------------------------

ANKLES = ("left_ankle", "right_ankle")
SHOULDERS = ("left_shoulder", "right_shoulder")


def _in_frame(x: float, y: float) -> bool:
    return 0.0 <= x <= 1.0 and 0.0 <= y <= 1.0


def feet_point(person: Person, min_conf: float = 0.5, edge_y: float = 0.95) -> float | None:
    """Image row (normalized, y down) of the person's ankles, or None.

    Only ANKLE keypoints count, and only when BOTH are confident (>= min_conf) and well
    inside the frame (0 <= y < edge_y); the lower one is returned (the closer reading). The
    box bottom is never used: with the phone tilted up it is usually the thighs or the frame
    edge, not the floor contact.
    """
    ys = []
    for name in ANKLES:
        kp = person.keypoint(name, min_conf)
        if kp is None or not (0.0 <= kp.x <= 1.0 and 0.0 <= kp.y < edge_y):
            return None
        ys.append(kp.y)
    return max(ys)


def shoulder_count(person: Person, min_conf: float = 0.5) -> int:
    """How many shoulder keypoints are confident and inside the frame (0, 1 or 2)."""
    return sum(
        1 for name in SHOULDERS if (kp := person.keypoint(name, min_conf)) is not None and _in_frame(kp.x, kp.y)
    )


def shoulder_gap(person: Person, min_conf: float = 0.5) -> float | None:
    """Normalized horizontal distance between the two shoulders, or None unless both are
    confident and inside the frame."""
    ls = person.keypoint("left_shoulder", min_conf)
    rs = person.keypoint("right_shoulder", min_conf)
    if ls is None or rs is None or not (_in_frame(ls.x, ls.y) and _in_frame(rs.x, rs.y)):
        return None
    return abs(ls.x - rs.x)


class RangeCue(NamedTuple):
    """One cue's answer to "how far is the person, relative to where we want them"."""

    cue: str  # "shoulders", "box" or "ground"
    ratio: float  # how many times too far: d / d_target - 1 (0 = right distance, < 0 = too close)
    too_close: bool  # inside the back-off distance
    distance_m: float | None  # meters, when the cue measures them (the box cue doesn't)


# ---------------------------------------------------------------------------
# Controller
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FollowConfig:
    """Every tunable of the follow controller. "tuned" = worked on the real robot
    (follow.swift and firmware/README.md); GUESS = not tested yet."""

    camera: CameraGeometry = CameraGeometry()

    # Turn: w = -k_w * (cx - 0.5), zero inside the dead zone, clamped. All tuned (yellow mode,
    # follow.swift:240,245).
    k_w: float = 2.5  # rad/s per unit of horizontal offset (target at the picture edge = 1.25 rad/s)
    dead_x: float = 0.06  # |cx - 0.5| below this: don't turn
    w_max: float = 1.2  # rad/s; drive.py clamps to the same

    # Speed from distance: ratio = d / d_target - 1 ("how many times too far"), v = k_v * ratio.
    # The law of the tuned yellow mode, where patch size ~ 1/distance (follow.swift:241-243).
    d_target_m: float = 1.0  # GUESS: John holds upper-body width 0.45, closer than 0.33 "~1.3 m" (follow.swift:16,28)
    k_v: float = 0.35  # m/s when twice as far as wanted (tuned)
    dead_ratio: float = 0.08  # |ratio| below this: don't move (tuned)
    v_max: float = 0.4  # m/s forward cap (tuned in yellow mode; drive.py clamps at 0.45)
    v_min: float = -0.15  # m/s most-negative speed from the law (tuned)
    d_min_m: float = 0.7  # GUESS: closer than this -> back off (follow.swift TOO_CLOSE_W was "~0.7 m")
    v_back: float = -0.15  # m/s while too close: the tuned reverse limit

    # Cue 1, shoulder gap: d = k_shoulder_m / gap (pinhole). GUESS: a shoulder (keypoint to
    # keypoint) width of ~0.37 m and the 67 deg hfov guess give 0.37 / (2 * tan(33.5 deg))
    # = 0.279 m, i.e. the shoulders span 0.28 of the picture at 1 m. Calibrate: gap * d.
    k_shoulder_m: float = 0.28
    # Turned sideways: the gap shrank below this fraction of its value when the lock was
    # acquired, relative to how much the box shrank (walking away shrinks both alike).
    sideways_ratio: float = 0.6

    # Cue 2, box width vs a target width (box width ~ 1/distance): ratio = target_box_w / box_w - 1.
    target_box_w: float = 0.45  # GUESS: John's upper-body width (follow.swift:28); a YOLO box differs
    too_close_box_w: float | None = None  # None -> max(0.55, target_box_w + 0.15), as follow.swift:43
    side_edge: float = 0.02  # a box within this of the left/right edge is cut off: its width
    # understates closeness, so don't drive forward on it (turning still centers the person)

    # Cue 3, ground plane from the ankles. OFF by default: with the phone tilted up (T-14) the
    # feet are mostly out of frame, the tilt isn't measured, and a wrong tilt turns into a
    # wrong distance. Turn it on only with a measured tilt and the feet in view.
    use_ground_plane: bool = False
    keypoint_min_conf: float = 0.5  # shoulder/ankle keypoints below this confidence are ignored
    feet_edge_y: float = 0.95  # ankles at or below this row are too near the frame edge to trust
    ankle_height_m: float = 0.08  # GUESS: the ankle keypoint sits ~8 cm above the floor

    # Smoothing: out = keep * previous + (1 - keep) * new, at the tuned ~15 Hz detection rate
    # (follow.swift:83 runs every 2nd frame of 30 fps). Scaled by the real frame gap so a
    # different frame rate gives the same time constant (~0.13 s).
    smooth_keep: float = 0.6  # tuned
    smooth_ref_dt_s: float = 1.0 / 15.0

    # Lost target (follow.swift:107-113, 128)
    coast_s: float = 0.3  # first this long: no stop, speed decays and the turn is held
    coast_keep: float = 0.6  # speed kept per 1/15 s while coasting (follow.swift:109)
    search_edge_x: float = 0.15  # last seen further than this from the centre -> search that way
    search_w: float = 0.5  # rad/s toward where the target was last seen (follow.swift:128)
    search_for_s: float = 2.0  # counted from when the target was lost; then stop and wait for them

    # Modes from follow.swift (--turn-only, --camera-back)
    turn_only: bool = False  # safe first test: only turn to face the person, never drive
    camera_back: bool = False  # the camera faces the robot's back: drive backward toward the person

    @property
    def too_close_w(self) -> float:
        """Box width above which the person is too close (follow.swift:43)."""
        if self.too_close_box_w is not None:
            return self.too_close_box_w
        return max(0.55, self.target_box_w + 0.15)


# The command's reason while the person is gone and the robot waits in place for them. The face
# (app/vision/face_state.py) turns it into the `waiting` event; the debug view shows it as is.
WAITING_REASON = "lost: waiting for you to come back"


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def ground_distance(person: Person, config: FollowConfig) -> float | None:
    """Ground-plane distance (m) from the ankle keypoints, or None (cue off, ankles not both
    confident and in frame, or the geometry gives no sane answer)."""
    if not config.use_ground_plane:
        return None
    y = feet_point(person, config.keypoint_min_conf, config.feet_edge_y)
    if y is None:
        return None
    return config.camera.ground_distance(y, config.ankle_height_m)


class FollowController:
    """TargetState in, DriveCommand out, once per frame."""

    def __init__(self, config: FollowConfig = FollowConfig()) -> None:
        self.config = config
        self.reset()

    def reset(self) -> None:
        """Forget the smoothing state and the shoulder reference (e.g. when Follow is switched
        on, or a new video starts)."""
        self._v = 0.0
        self._w = 0.0
        self._last_t: float | None = None
        self._ref: tuple[float, float] | None = None  # (shoulder gap, box width) when the lock was acquired
        self._lost_for = 0.0  # how long the target had been lost at the last update (0 while locked)

    def update(self, state: TargetState, t: float) -> DriveCommand:
        dt = self._frame_gap(t)
        if state.status == TargetStatus.LOCKED and state.person is not None:
            if state.reacquired:  # the person came back: their pose may have changed
                self._ref = None
                if self._lost_for >= self.config.coast_s:
                    # Back after the robot had stopped (searching or waiting): start fresh from
                    # where they are now, nothing carried over from before they left.
                    self._v = 0.0
                    self._w = 0.0
            self._lost_for = 0.0
            return self._follow(state.person, dt)
        if state.status == TargetStatus.IDLE:
            self._ref = None
            self._lost_for = 0.0
            return self._stop("idle")
        # LOST (or LOCKED without a person, which shouldn't happen: treat as just lost)
        lost_for = state.lost_for_s if state.status == TargetStatus.LOST else 0.0
        self._lost_for = lost_for
        return self._lost(lost_for, state.last_seen_cx, dt)

    def range_cues(self, person: Person) -> tuple[list[RangeCue], bool]:
        """The usable distance cues for `person`, and whether they look turned sideways.

        Updates the shoulder reference (set on the first frame after the lock was acquired
        that shows both shoulders)."""
        cfg = self.config
        box = person.box
        cues = [
            RangeCue("box", cfg.target_box_w / max(box.w, 1e-3) - 1.0, box.w > cfg.too_close_w, None)
        ]

        sideways = False
        gap = shoulder_gap(person, cfg.keypoint_min_conf)
        if gap is not None:
            if self._ref is None:
                self._ref = (gap, max(box.w, 1e-3))
            ref_gap, ref_box_w = self._ref
            gap_ratio = gap / max(ref_gap, 1e-3)
            box_ratio = max(box.w, 1e-3) / ref_box_w
            sideways = gap_ratio < cfg.sideways_ratio * box_ratio
            if not sideways:
                d = cfg.k_shoulder_m / max(gap, 1e-3)
                cues.append(RangeCue("shoulders", d / cfg.d_target_m - 1.0, d < cfg.d_min_m, d))
        elif shoulder_count(person, cfg.keypoint_min_conf) == 1:
            sideways = True  # one shoulder hidden: side view (or half occluded)

        d = ground_distance(person, cfg)
        if d is not None:
            cues.append(RangeCue("ground", d / cfg.d_target_m - 1.0, d < cfg.d_min_m, d))
        return cues, sideways

    # --- internals ---

    def _frame_gap(self, t: float) -> float:
        prev, self._last_t = self._last_t, t
        if prev is None or t < prev:  # first frame, or time went backward (new video)
            return self.config.smooth_ref_dt_s
        return t - prev

    def _keep(self, keep_per_ref_frame: float, dt: float) -> float:
        return keep_per_ref_frame ** (dt / self.config.smooth_ref_dt_s)

    def _smooth(self, v_cmd: float, w_cmd: float, dt: float) -> tuple[float, float]:
        keep = self._keep(self.config.smooth_keep, dt)
        self._v = keep * self._v + (1.0 - keep) * v_cmd
        self._w = keep * self._w + (1.0 - keep) * w_cmd
        return self._v, self._w

    def _stop(self, reason: str) -> DriveCommand:
        # Stops are immediate, not smoothed.
        self._v = 0.0
        self._w = 0.0
        return DriveCommand(v=0.0, w=0.0, reason=reason)

    def _lost(self, lost_for: float, last_seen_cx: float, dt: float) -> DriveCommand:
        cfg = self.config
        if lost_for >= cfg.search_for_s:  # searched long enough: stay put until they come back
            return self._stop(WAITING_REASON)
        if lost_for < cfg.coast_s:  # a brief dropout: no hard stop, let the speed die out, keep turning
            self._v *= self._keep(cfg.coast_keep, dt)
            return DriveCommand(v=self._v, w=self._w, reason="lost: coasting")
        off = last_seen_cx - 0.5
        if abs(off) <= cfg.search_edge_x:  # vanished near the centre: probably behind someone, don't spin away
            return self._stop("lost: holding")
        left = off < 0  # last seen on the left of the picture -> turn left (w > 0)
        keep = self._keep(cfg.smooth_keep, dt)
        self._v = 0.0
        self._w = keep * self._w + (1.0 - keep) * (cfg.search_w if left else -cfg.search_w)
        return DriveCommand(v=0.0, w=self._w, reason=f"lost: searching {'left' if left else 'right'}")

    def _follow(self, person: Person, dt: float) -> DriveCommand:
        cfg = self.config
        box: Box = person.box

        ex = box.cx - 0.5
        w_cmd = 0.0 if abs(ex) < cfg.dead_x else -cfg.k_w * ex  # target on the right -> turn right (w < 0)
        w_cmd = _clamp(w_cmd, -cfg.w_max, cfg.w_max)

        cues, sideways = self.range_cues(person)
        nearest = min(cues, key=lambda c: c.ratio)  # fail-safe: trust whichever cue says closer
        too_close = any(c.too_close for c in cues)
        cut_at_side = box.x1 < cfg.side_edge or box.x2 > 1.0 - cfg.side_edge

        v_cmd = 0.0 if abs(nearest.ratio) < cfg.dead_ratio else cfg.k_v * nearest.ratio
        v_cmd = _clamp(v_cmd, cfg.v_min, cfg.v_max)
        if sideways or cut_at_side:  # distance not trustworthy: never drive forward
            v_cmd = min(v_cmd, 0.0)
        if too_close:
            v_cmd = cfg.v_back
        if cfg.turn_only:
            v_cmd = 0.0
        if cfg.camera_back:  # image left/right still map to the same turn direction; only v flips
            v_cmd = -v_cmd

        v, w = self._smooth(v_cmd, w_cmd, dt)
        if too_close and not cfg.turn_only:
            reason = "too close: backing off"
        elif sideways and not cfg.turn_only:
            reason = "following: sideways, turn only"
        else:
            reason = "following"
        return DriveCommand(v=v, w=w, reason=reason, distance_m=nearest.distance_m)
