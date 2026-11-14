"""Target lock: once engaged, keep following ONE person and never switch to someone else.

The phone is tilted up (open question T-14: kept tilted up), so at follow distance
(0.7-2 m) the camera sees roughly thighs to head. Close people are cut off at the top and
the bottom of the frame, and feet are mostly out of view, so box heights and box bottoms
both stick at the frame edges; box WIDTH is the size cue that still changes with distance.
Each frame the lock gets the detector's people (`Detections`), the BGR image they came from
and the robot's commanded turn rate, and answers "where is my person now?" as a `TargetState`.

How it works
- Engage: among people near the horizontal center (`LockConfig.engage_max_offset`) and wide
  enough to be close (`engage_min_w`), lock onto the WIDEST one (the closest). Nobody
  suitable -> stay IDLE.
- Keep: an alpha-beta (constant-velocity) filter on the box predicts where the target
  should be. The robot's own turning shifts everything in the image, so the prediction is
  moved by the image motion the commanded turn rate causes (pinhole model, the same one as
  follow.py's `CameraGeometry.bearing_rad`). Only people inside a gate around the prediction
  (the gate grows with time since last seen), with a similar box width and an appearance
  close enough to the stored model, are candidates; the cheapest one by distance + width +
  appearance wins. This is the gate-and-size-ratio idea of the yellow-object lock in
  firmware/balance/follow/follow.swift:167-197, plus a prediction and an appearance check.
- Appearance: two color histograms, TORSO (shoulders to hips from the pose keypoints when
  they are confident, else the upper part of the box below the head) and LEGS (hips to the
  box bottom), compared with the Bhattacharyya distance. Pixels covered by a person standing
  in front are masked out; a part with too little left (or out of frame) is "not visible".
  Only parts visible in both the model and the candidate are compared, weighted by the
  candidate's visible pixels; any one part that is clearly different vetoes the match
  (`max_part_dist`), so a matching shirt can't outvote different pants. The model is
  updated slowly (exponential moving average) only on confident matches while no other
  person overlaps the target, so a passer-by can't poison it; a part missing from the model
  (say, legs hidden at engage) is learned the same way once it shows up.
- Missed detection: for `miss_grace_s` after the last sighting the target is still matched
  with the LOCKED thresholds through the motion gate (the state reports LOST meanwhile,
  since there is no person to report). A single dropped frame therefore can't strand a
  target whose appearance has drifted between the strict and the normal threshold.
- Lost: after the grace period, for the rest of `hold_s` the person can only come back
  inside the motion gate, and only if the appearance matches strictly; a look-alike
  elsewhere is ignored. After that, anyone who matches the stored appearance strictly, for a
  few frames in a row, is re-acquired (`reacquired=True`). There is no fallback to "the
  biggest person": the lock stays LOST until the target is re-acquired or `disengage()` is
  called.
- Timing comes only from `Detections.frame_t`, so recorded video behaves like live video.

Known weak cases (honest notes)
- Two people dressed alike (same shirt and trousers) who cross with one fully hidden.
  Appearance can't tell them apart, so the lock relies on constant-velocity motion; if they
  stop, turn back, or the passer-by ends up where the target was heading, the lock can swap
  to the passer-by and nothing later notices. Re-acquiring after LOST can likewise pick a
  look-alike.
- When only one part is visible (say, legs behind a table), only that part is compared, so
  a stranger in the same shirt is as good as the target.
- Without keypoints the part rows are fixed fractions of the box, which is wrong when the
  box is cut off by the frame; YOLO pose keypoints normally cover this.

Sources
- Gate radius 0.22, size ratio 0.45-2.2, 0.7 s hold: firmware/balance/follow/follow.swift:167-197.
  (follow.swift uses the blob's height; here it's the box width, see above.)
- Hue-saturation histogram plus value bins for low-saturation pixels (so black, gray and
  white clothes are told apart; plain H-S can't): Perez, Hue, Vermaak, Gangnet, "Color-Based
  Probabilistic Tracking", ECCV 2002, section 3.
- Separate histograms per body part (upper/lower body) for person re-identification: the
  part-based color features of e.g. Farenzena et al., "Person Re-Identification by
  Symmetry-Driven Accumulation of Local Features", CVPR 2010.
- Bhattacharyya distance: cv2.compareHist with HISTCMP_BHATTACHARYYA
  (https://docs.opencv.org/4.x/d6/dc7/group__imgproc__hist.html).
- Alpha-beta filter: https://en.wikipedia.org/wiki/Alpha_beta_filter.
- Confirming a new track over a few frames before trusting it: the "min hits" idea in
  SORT (Bewley et al., 2016, https://arxiv.org/abs/1602.00763).
- Turn direction: ROS REP 103 (w > 0 = turn left), as in app/vision/types.py.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass

import cv2
import numpy as np

from app.vision.types import Box, Detections, Person, TargetState, TargetStatus

__all__ = [
    "BodyParts",
    "LockConfig",
    "TargetLock",
    "appearance_distance",
    "body_part_histograms",
    "parts_distance",
    "shift_for_turn",
]


@dataclass(frozen=True)
class LockConfig:
    """Every tunable of the target lock. Distances and sizes are fractions of the frame.

    Values marked "guess" are first picks, not measured; tune them on recorded video.
    """

    # --- Which detections count ---
    min_det_score: float = 0.3  # ignore people the detector is less sure of (guess)

    # --- Camera ---
    # Horizontal field of view, for turning the robot's own rotation into image motion.
    # Same GUESS as follow.py's CameraGeometry.hfov_deg (iPhone 1x camera, 16:9 stream).
    hfov_deg: float = 67.0

    # --- Engage ---
    engage_max_offset: float = 0.25  # only people with |cx - 0.5| <= this count (guess)
    # Minimum box width to count as "close enough to follow". A person ~0.5 m wide (with
    # arms) at 3 m spans about 0.13 of a 67 deg frame. (guess)
    engage_min_w: float = 0.12

    # --- Motion model: alpha-beta filter on the box (cx, cy, w, h) ---
    alpha: float = 0.6  # how far the estimate moves toward each measurement (guess)
    beta: float = 0.2  # how fast the velocity estimate adapts (guess)
    max_rate: float = 2.0  # cap on |velocity|, frame units per second (guess)
    max_predict_s: float = 0.5  # extrapolate at most this long, then hold the prediction (guess)

    # --- Gate around the prediction ---
    gate_base: float = 0.22  # radius right after a sighting (follow.swift GATE)
    gate_growth_per_s: float = 0.4  # the radius grows this much per second unseen (guess)
    gate_max: float = 0.45  # radius never grows past this (guess)
    size_ratio_min: float = 0.45  # accepted box-WIDTH ratio vs prediction (follow.swift, for height)
    size_ratio_max: float = 2.2  # (follow.swift, for height)

    # --- Choosing among gated candidates: cost = dist/gate + w_size*|ln ratio| + w_app*app ---
    size_weight: float = 1.0  # follow.swift weighs 0.25*|ln ratio| against a 0.22 gate (~1.1)
    appearance_weight: float = 2.0  # appearance matters most for telling people apart (guess)

    # --- Appearance (Bhattacharyya distance: 0 = same colors, 1 = nothing in common) ---
    max_dist_locked: float = 0.6  # while LOCKED (and in the miss grace), reject above this (guess)
    max_dist_lost: float = 0.4  # while LOST, re-acquire only at or below this (guess)
    max_part_dist: float = 0.7  # any one shared part farther than this = a different person (guess)
    kp_min_conf: float = 0.5  # shoulder/hip keypoints at or above this confidence set the part rows
    # Part rows without keypoints, as fractions of the box height from its top. For a
    # head-to-feet box: head ~0-0.13, shoulders ~0.18, hips ~0.5. (guess)
    torso_top_frac: float = 0.2
    torso_bottom_frac: float = 0.5
    legs_top_frac: float = 0.55
    min_part_frac: float = 0.1  # a part shorter than this fraction of the box height is not visible (guess)
    inset_x: float = 0.15  # cut this fraction of the box width from each side (background) (guess)
    min_visible: float = 0.25  # need this fraction of a part unoccluded, else "can't see" (guess)
    # Who stands in front (for masking): the wider box is closer. Only when both box bottoms
    # are above `bottom_clip` (feet in view) do feet lower by more than `front_eps` decide.
    bottom_clip: float = 0.98  # (guess)
    front_eps: float = 0.02  # (guess)
    h_bins: int = 10  # hue bins (Perez 2002 uses 10)
    s_bins: int = 10  # saturation bins (Perez 2002)
    v_bins: int = 10  # value bins for low-saturation or dark pixels (Perez 2002)
    min_sat: int = 26  # pixels below this saturation (0..255) go to the value bins (Perez: 0.1)
    min_val: int = 51  # pixels below this value (0..255) go to the value bins (Perez: 0.2)

    # --- Updating the appearance model ---
    update_rate: float = 0.05  # EMA weight of each new frame, ~1 s memory at 20 fps (guess)
    update_max_dist: float = 0.3  # only learn from matches at least this good (guess)
    # Freeze updates while another person's box covers more than this fraction of the
    # target's box (intersection / target area). Stricter than IoU, which stays small when a
    # small box sits inside a big one. (guess)
    freeze_overlap: float = 0.2

    # --- Missed detections, lost and re-acquire ---
    # For this long after the last sighting, keep matching with the LOCKED thresholds through
    # the motion gate, so one dropped detection doesn't switch to the strict LOST rules. (guess)
    miss_grace_s: float = 0.3
    # For this long after losing it, the target may only return through the motion gate;
    # re-acquiring anywhere in the frame starts after it. (follow.swift LOCK_HOLD)
    hold_s: float = 0.7
    reacquire_frames: int = 3  # a match away from the gate must hold this many frames in a row (guess)
    reacquire_dist_weight: float = 0.3  # prefer matches near the predicted x (guess)


@dataclass(frozen=True)
class BodyParts:
    """Normalized color histograms of a person's torso and legs; None = that part not visible.

    `*_px` are the unmasked pixels each histogram was built from (0 when not visible).
    """

    torso: np.ndarray | None = None
    legs: np.ndarray | None = None
    torso_px: int = 0
    legs_px: int = 0

    def copy(self) -> BodyParts:
        return BodyParts(
            None if self.torso is None else self.torso.copy(),
            None if self.legs is None else self.legs.copy(),
            self.torso_px,
            self.legs_px,
        )


def body_part_histograms(
    image: np.ndarray,
    person: Person,
    people: Iterable[Person] = (),
    config: LockConfig = LockConfig(),
) -> BodyParts | None:
    """Torso and legs color histograms of a person, or None if neither part is visible.

    TORSO runs from the shoulders to the hips (keypoints at or above `kp_min_conf`), else
    from `torso_top_frac` to `torso_bottom_frac` of the box. LEGS run from the hips (else
    `legs_top_frac`) to the box bottom. `people` are the other people in the frame: those
    standing in front of `person` (see `_in_front`) are masked out. Each histogram has
    h_bins*s_bins hue-saturation bins for colorful pixels plus v_bins value bins for gray,
    black and white pixels, and sums to 1.
    """
    cfg = config
    b = person.box
    others = [o for o in people if o is not person and _in_front(o.box, b, cfg)]
    shoulders = _mean_y(person, ("left_shoulder", "right_shoulder"), cfg.kp_min_conf)
    hips = _mean_y(person, ("left_hip", "right_hip"), cfg.kp_min_conf)

    torso_top = shoulders if shoulders is not None else b.y1 + cfg.torso_top_frac * b.h
    torso_bottom = hips if hips is not None else b.y1 + cfg.torso_bottom_frac * b.h
    legs_top = hips if hips is not None else b.y1 + cfg.legs_top_frac * b.h

    torso = _region_histogram(image, b, torso_top, torso_bottom, others, cfg)
    legs = _region_histogram(image, b, legs_top, b.y2, others, cfg)
    if torso is None and legs is None:
        return None
    return BodyParts(
        torso=None if torso is None else torso[0],
        legs=None if legs is None else legs[0],
        torso_px=0 if torso is None else torso[1],
        legs_px=0 if legs is None else legs[1],
    )


def appearance_distance(a: np.ndarray, b: np.ndarray) -> float:
    """Bhattacharyya distance between two histograms: 0 = identical, 1 = no overlap."""
    return float(cv2.compareHist(a, b, cv2.HISTCMP_BHATTACHARYYA))


def parts_distance(model: BodyParts, candidate: BodyParts, config: LockConfig = LockConfig()) -> float | None:
    """Appearance distance over the parts visible in both, or None if they share none.

    The mean of the per-part Bhattacharyya distances, weighted by the candidate's visible
    pixels in each part. If any shared part is farther than `max_part_dist`, the largest
    part distance is returned instead (a veto: a matching shirt can't outvote different
    trousers).
    """
    pairs = []
    if model.torso is not None and candidate.torso is not None:
        pairs.append((appearance_distance(model.torso, candidate.torso), max(candidate.torso_px, 1)))
    if model.legs is not None and candidate.legs is not None:
        pairs.append((appearance_distance(model.legs, candidate.legs), max(candidate.legs_px, 1)))
    if not pairs:
        return None
    worst = max(d for d, _ in pairs)
    if worst > config.max_part_dist:
        return worst
    return sum(d * w for d, w in pairs) / sum(w for _, w in pairs)


class TargetLock:
    """Locks onto one person and follows that person only. Not thread-safe."""

    def __init__(self, config: LockConfig = LockConfig()) -> None:
        self.config = config
        self._reset()

    @property
    def state(self) -> TargetState:
        """The result of the last engage() or update()."""
        return self._state

    @property
    def appearance_model(self) -> BodyParts | None:
        """A copy of the stored torso and legs histograms (for tests and debug views)."""
        return None if self._model is None else self._model.copy()

    def engage(self, detections: Detections, image: np.ndarray) -> TargetState:
        """Lock onto the widest (closest) person near the center; stay IDLE if there is none."""
        self._reset()
        cfg = self.config
        near = [
            p
            for p in self._usable(detections)
            if abs(p.box.cx - 0.5) <= cfg.engage_max_offset and p.box.w >= cfg.engage_min_w
        ]
        for person in sorted(near, key=lambda p: -p.box.w):
            parts = body_part_histograms(image, person, detections.people, cfg)
            if parts is None:  # too occluded to learn what they look like; try the next one
                continue
            self._model = parts
            self._track = _AlphaBeta(person.box, detections.frame_t)
            self._last_update_t = detections.frame_t
            return self._locked(person, detections.frame_t, reacquired=False)
        return self._state

    def disengage(self) -> None:
        """Forget the target and go IDLE."""
        self._reset()

    def update(self, detections: Detections, image: np.ndarray, turn_rate: float = 0.0) -> TargetState:
        """Find the locked person in this frame. Does nothing while IDLE (call engage()).

        `turn_rate` is the robot's commanded w in rad/s (REP 103: LEFT positive) over the
        time since the previous update; the prediction is shifted by the image motion it
        causes (turning left moves the scene RIGHT in the image).
        """
        if self._state.status is TargetStatus.IDLE or self._track is None or self._model is None:
            return self._state
        cfg = self.config
        t = detections.frame_t
        dt = max(0.0, t - self._last_update_t)
        self._last_update_t = t
        if turn_rate != 0.0 and dt > 0.0:
            self._track.x[0] = shift_for_turn(float(self._track.x[0]), turn_rate * dt, cfg.hfov_deg)

        candidates = self._usable(detections)
        was_lost = self._state.status is TargetStatus.LOST
        since = max(0.0, t - self._last_seen_t)
        pred = self._track.predict(t, cfg.max_predict_s)

        # 1) Motion continuity: near where the target was heading, similar width, same look.
        #    Right after a miss (grace) the LOCKED threshold still applies; later, the strict one.
        lenient = not was_lost or since <= cfg.miss_grace_s
        if lenient or since <= cfg.hold_s:
            max_dist = cfg.max_dist_locked if lenient else cfg.max_dist_lost
            gate = min(cfg.gate_max, cfg.gate_base + cfg.gate_growth_per_s * since)
            best: tuple[float, Person, BodyParts, float] | None = None
            for p in candidates:
                d = math.hypot(p.box.cx - pred[0], p.box.cy - pred[1])
                ratio = p.box.w / max(float(pred[2]), 1e-6)
                if d > gate or not cfg.size_ratio_min <= ratio <= cfg.size_ratio_max:
                    continue
                parts = body_part_histograms(image, p, detections.people, cfg)
                if parts is None:
                    continue
                app = parts_distance(self._model, parts, cfg)
                if app is None or app > max_dist:
                    continue
                cost = d / gate + cfg.size_weight * abs(math.log(ratio)) + cfg.appearance_weight * app
                if best is None or cost < best[0]:
                    best = (cost, p, parts, app)
            if best is not None:
                _, p, parts, app = best
                self._track.correct(p.box, t, cfg)
                if not was_lost:
                    self._learn(p, parts, app, detections.people)
                return self._locked(p, t, reacquired=was_lost)

        if not was_lost:
            return self._lost(t)  # the first miss never searches the whole frame
        if since <= cfg.hold_s:
            # Probably just hidden for a moment: wait for it where it was heading instead of
            # jumping to a look-alike somewhere else.
            self._tentative = None
            return self._lost(t)

        # 2) Re-acquire anywhere by appearance alone, confirmed over a few frames in a row.
        best_r: tuple[float, Person] | None = None
        for p in candidates:
            parts = body_part_histograms(image, p, detections.people, cfg)
            if parts is None:
                continue
            app = parts_distance(self._model, parts, cfg)
            if app is None or app > cfg.max_dist_lost:
                continue
            cost = app + cfg.reacquire_dist_weight * abs(p.box.cx - pred[0])
            if best_r is None or cost < best_r[0]:
                best_r = (cost, p)
        if best_r is None:
            self._tentative = None
            return self._lost(t)
        p = best_r[1]
        count = 1
        if self._tentative is not None:
            tcx, tcy, n = self._tentative
            if math.hypot(p.box.cx - tcx, p.box.cy - tcy) <= cfg.gate_base:
                count = n + 1
        if count < cfg.reacquire_frames:
            self._tentative = (p.box.cx, p.box.cy, count)
            return self._lost(t)
        self._track = _AlphaBeta(p.box, t)  # fresh motion estimate after a long gap
        return self._locked(p, t, reacquired=True)

    # --- internals ---

    def _reset(self) -> None:
        self._state = TargetState(TargetStatus.IDLE)
        self._model: BodyParts | None = None
        self._track: _AlphaBeta | None = None
        self._last_seen_t = 0.0
        self._last_update_t = 0.0
        self._last_cx = 0.5
        self._tentative: tuple[float, float, int] | None = None  # (cx, cy, frames matched) while LOST

    def _usable(self, detections: Detections) -> list[Person]:
        return [p for p in detections.people if p.score >= self.config.min_det_score]

    def _learn(self, person: Person, parts: BodyParts, app: float, people: Iterable[Person]) -> None:
        """Blend this frame into the model, unless the match is shaky or someone overlaps the target.

        A part the model doesn't have yet is taken from this frame as is.
        """
        cfg = self.config
        model = self._model
        if model is None or app > cfg.update_max_dist:
            return
        if any(o is not person and _covered(person.box, o.box) > cfg.freeze_overlap for o in people):
            return
        self._model = BodyParts(
            torso=_blend(model.torso, parts.torso, cfg.update_rate),
            legs=_blend(model.legs, parts.legs, cfg.update_rate),
            torso_px=parts.torso_px if parts.torso is not None else model.torso_px,
            legs_px=parts.legs_px if parts.legs is not None else model.legs_px,
        )

    def _locked(self, person: Person, t: float, reacquired: bool) -> TargetState:
        self._last_seen_t = t
        self._last_cx = person.box.cx
        self._tentative = None
        self._state = TargetState(
            TargetStatus.LOCKED, person=person, last_seen_cx=person.box.cx, reacquired=reacquired
        )
        return self._state

    def _lost(self, t: float) -> TargetState:
        self._state = TargetState(
            TargetStatus.LOST, lost_for_s=max(0.0, t - self._last_seen_t), last_seen_cx=self._last_cx
        )
        return self._state


def shift_for_turn(cx: float, yaw_rad: float, hfov_deg: float) -> float:
    """Where a still point at image column `cx` lands after the robot yaws by `yaw_rad`.

    REP 103: `yaw_rad` > 0 is a LEFT turn, which moves the scene RIGHT in the image. Pinhole
    model, matching follow.py's CameraGeometry.bearing_rad: bearing = -atan((x - 0.5) * k),
    k = 2 tan(hfov / 2); the point's bearing drops by the yaw. Near the center this is
    about yaw / (2 tan(hfov / 2)) of the frame width per radian.
    """
    k = 2.0 * math.tan(math.radians(hfov_deg) / 2.0)
    bearing = -math.atan((cx - 0.5) * k) - yaw_rad
    bearing = min(max(bearing, -1.4), 1.4)  # stay clear of +-90 deg, where tan blows up
    return 0.5 - math.tan(bearing) / k


class _AlphaBeta:
    """Constant-velocity alpha-beta filter on (cx, cy, w, h)."""

    def __init__(self, box: Box, t: float) -> None:
        self.x = _vec(box)
        self.v = np.zeros(4)
        self.t = t

    def predict(self, t: float, max_dt: float) -> np.ndarray:
        dt = min(max(t - self.t, 0.0), max_dt)
        return self.x + self.v * dt

    def correct(self, box: Box, t: float, cfg: LockConfig) -> None:
        dt = t - self.t
        pred = self.predict(t, cfg.max_predict_s)
        r = _vec(box) - pred
        self.x = pred + cfg.alpha * r
        if dt > 1e-6:
            self.v = np.clip(self.v + cfg.beta * r / dt, -cfg.max_rate, cfg.max_rate)
        self.t = t


def _vec(box: Box) -> np.ndarray:
    return np.array([box.cx, box.cy, box.w, box.h], dtype=float)


def _px(v: float, n: int) -> int:
    return int(round(min(max(v, 0.0), 1.0) * n))


def _mean_y(person: Person, names: tuple[str, ...], min_conf: float) -> float | None:
    ys = [kp.y for kp in (person.keypoint(n, min_conf) for n in names) if kp is not None]
    return sum(ys) / len(ys) if ys else None


def _region_histogram(
    image: np.ndarray, b: Box, top: float, bottom: float, in_front: list[Person], cfg: LockConfig
) -> tuple[np.ndarray, int] | None:
    """Histogram and visible pixel count of rows top..bottom of box `b`, or None if not visible."""
    img_h, img_w = image.shape[:2]
    top, bottom = max(top, b.y1, 0.0), min(bottom, b.y2, 1.0)
    if bottom - top < cfg.min_part_frac * b.h:
        return None
    px1, px2 = _px(b.x1 + cfg.inset_x * b.w, img_w), _px(b.x2 - cfg.inset_x * b.w, img_w)
    py1, py2 = _px(top, img_h), _px(bottom, img_h)
    if px2 - px1 < 2 or py2 - py1 < 2:
        return None

    mask = np.full((py2 - py1, px2 - px1), 255, np.uint8)
    for other in in_front:
        ox1, ox2 = max(_px(other.box.x1, img_w), px1), min(_px(other.box.x2, img_w), px2)
        oy1, oy2 = max(_px(other.box.y1, img_h), py1), min(_px(other.box.y2, img_h), py2)
        if ox2 > ox1 and oy2 > oy1:
            mask[oy1 - py1 : oy2 - py1, ox1 - px1 : ox2 - px1] = 0
    visible = cv2.countNonZero(mask)
    if visible < cfg.min_visible * mask.size:
        return None

    hsv = cv2.cvtColor(np.ascontiguousarray(image[py1:py2, px1:px2]), cv2.COLOR_BGR2HSV)
    colorful = (hsv[..., 1] >= cfg.min_sat) & (hsv[..., 2] >= cfg.min_val)
    mask_color = np.where(colorful, mask, 0).astype(np.uint8)
    mask_gray = np.where(colorful, 0, mask).astype(np.uint8)
    hs = cv2.calcHist([hsv], [0, 1], mask_color, [cfg.h_bins, cfg.s_bins], [0, 180, 0, 256])
    v = cv2.calcHist([hsv], [2], mask_gray, [cfg.v_bins], [0, 256])
    hist = np.concatenate([hs.ravel(), v.ravel()]).astype(np.float32)
    total = float(hist.sum())
    return (hist / total, visible) if total > 0 else None


def _blend(old: np.ndarray | None, new: np.ndarray | None, rate: float) -> np.ndarray | None:
    if new is None:
        return old
    if old is None:
        return new.copy()
    mixed = (1.0 - rate) * old + rate * new
    return (mixed / mixed.sum()).astype(np.float32)


def _in_front(other: Box, me: Box, cfg: LockConfig) -> bool:
    """Is `other` standing in front of `me`?

    With the phone tilted up, box bottoms (and tops) of close people are cut off by the frame,
    so the wider box is the closer one. Only when both feet are in view (both bottoms above
    `bottom_clip`) and differ by more than `front_eps` do feet lower in the image decide. (guess)
    """
    if other.y2 < cfg.bottom_clip and me.y2 < cfg.bottom_clip:
        dy = other.y2 - me.y2
        if abs(dy) > cfg.front_eps:
            return dy > 0
    return other.w > me.w


def _covered(me: Box, other: Box) -> float:
    """Fraction of `me` that `other` covers."""
    ix = max(0.0, min(me.x2, other.x2) - max(me.x1, other.x1))
    iy = max(0.0, min(me.y2, other.y2) - max(me.y1, other.y1))
    return ix * iy / me.area if me.area > 0 else 0.0
