"""Target lock: once engaged, keep following ONE person and never switch to someone else.

The robot's camera sits about 40 cm off the floor, so it mostly sees legs and shoes.
Each frame the lock gets the detector's people (`Detections`) plus the BGR image they
came from, and answers "where is my person now?" as a `TargetState`.

How it works
- Engage: lock onto the person nearest the horizontal center among those whose box is
  tall enough to be close (`LockConfig.engage_min_h`). Nobody suitable -> stay IDLE.
- Keep: an alpha-beta (constant-velocity) filter on the box predicts where the target
  should be. Only people inside a gate around the prediction (the gate grows with time
  since last seen), with a similar box height and a lower-body appearance close enough
  to the stored model, are candidates; the cheapest one by distance + size + appearance
  wins. This is the gate-and-size-ratio idea of the yellow-object lock in
  firmware/balance/follow/follow.swift:167-197, plus a prediction and an appearance check.
- Appearance: a color histogram of the lower body (hips down if the hip keypoints are
  confident, else the lower 60% of the box, inset at the sides), compared with the
  Bhattacharyya distance. Pixels covered by a person standing in front (feet lower in the
  image) are masked out. The model is updated slowly (exponential moving average) only
  on confident matches while no other person overlaps the target, so a passer-by can't
  poison it.
- Lost: no acceptable candidate -> LOST. For a short while (`hold_s`) the person can only
  come back inside the motion gate, and only if the appearance matches strictly; a
  look-alike elsewhere is ignored. After that, anyone who matches the stored appearance
  strictly, for a few frames in a row, is re-acquired (`reacquired=True`). There is no
  fallback to "the biggest person": the lock stays LOST until the target is re-acquired
  or `disengage()` is called.
- Timing comes only from `Detections.frame_t`, so recorded video behaves like live video.

Known weak case (honest note): two people in near-identical lower-body clothing (say,
both in blue jeans and white sneakers) who cross with one fully hidden. Appearance can't
tell them apart, so the lock relies on constant-velocity motion; if they stop, turn back,
or the passer-by ends up where the target was heading, the lock can swap to the passer-by
and nothing later notices. The same applies to re-acquiring after LOST: a look-alike can be
re-acquired.

Sources
- Gate radius 0.22, size ratio 0.45-2.2, 0.7 s hold: firmware/balance/follow/follow.swift:167-197.
- Hue-saturation histogram plus value bins for low-saturation pixels (so black, gray and
  white clothes are told apart; plain H-S can't): Perez, Hue, Vermaak, Gangnet, "Color-Based
  Probabilistic Tracking", ECCV 2002, section 3.
- Bhattacharyya distance: cv2.compareHist with HISTCMP_BHATTACHARYYA
  (https://docs.opencv.org/4.x/d6/dc7/group__imgproc__hist.html).
- Alpha-beta filter: https://en.wikipedia.org/wiki/Alpha_beta_filter.
- Confirming a new track over a few frames before trusting it: the "min hits" idea in
  SORT (Bewley et al., 2016, https://arxiv.org/abs/1602.00763).
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass

import cv2
import numpy as np

from app.vision.types import Box, Detections, Person, TargetState, TargetStatus

__all__ = [
    "LockConfig",
    "TargetLock",
    "appearance_distance",
    "lower_body_histogram",
]


@dataclass(frozen=True)
class LockConfig:
    """Every tunable of the target lock. Distances and sizes are fractions of the frame.

    Values marked "guess" are first picks, not measured; tune them on recorded video.
    """

    # --- Which detections count ---
    min_det_score: float = 0.3  # ignore people the detector is less sure of (guess)

    # --- Engage ---
    # Minimum box height to count as "close enough to follow". At 40 cm camera height a
    # person within ~2 m shows legs taller than ~30% of the frame. (guess)
    engage_min_h: float = 0.3

    # --- Motion model: alpha-beta filter on the box (cx, cy, w, h) ---
    alpha: float = 0.6  # how far the estimate moves toward each measurement (guess)
    beta: float = 0.2  # how fast the velocity estimate adapts (guess)
    max_rate: float = 2.0  # cap on |velocity|, frame units per second (guess)
    max_predict_s: float = 0.5  # extrapolate at most this long, then hold the prediction (guess)

    # --- Gate around the prediction ---
    gate_base: float = 0.22  # radius right after a sighting (follow.swift GATE)
    gate_growth_per_s: float = 0.4  # the radius grows this much per second unseen (guess)
    gate_max: float = 0.45  # radius never grows past this (guess)
    size_ratio_min: float = 0.45  # accepted box-height ratio vs prediction (follow.swift)
    size_ratio_max: float = 2.2  # (follow.swift)

    # --- Choosing among gated candidates: cost = dist/gate + w_size*|ln ratio| + w_app*app ---
    size_weight: float = 1.0  # follow.swift weighs 0.25*|ln ratio| against a 0.22 gate (~1.1)
    appearance_weight: float = 2.0  # appearance matters most for telling people apart (guess)

    # --- Appearance (Bhattacharyya distance: 0 = same colors, 1 = nothing in common) ---
    max_dist_locked: float = 0.6  # while LOCKED, a gated candidate farther than this is rejected (guess)
    max_dist_lost: float = 0.4  # while LOST, re-acquire only at or below this (guess)
    lower_frac: float = 0.6  # without hip keypoints, use this bottom fraction of the box
    hip_min_conf: float = 0.5  # hip keypoints at or above this confidence set the top of the region
    inset_x: float = 0.15  # cut this fraction of the box width from each side (background) (guess)
    min_visible: float = 0.25  # need this fraction of the region unoccluded, else "can't see" (guess)
    front_eps: float = 0.02  # feet this much lower in the image = standing in front (guess)
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

    # --- Lost and re-acquire ---
    # For this long after losing it, the target may only return through the motion gate;
    # re-acquiring anywhere in the frame starts after it. (follow.swift LOCK_HOLD)
    hold_s: float = 0.7
    reacquire_frames: int = 3  # a match away from the gate must hold this many frames in a row (guess)
    reacquire_dist_weight: float = 0.3  # prefer matches near the predicted x (guess)


def lower_body_histogram(
    image: np.ndarray,
    person: Person,
    people: Iterable[Person] = (),
    config: LockConfig = LockConfig(),
) -> np.ndarray | None:
    """Normalized color histogram of a person's lower body, or None if too little is visible.

    `people` are the other people in the frame: those standing in front of `person` (feet
    lower in the image) are masked out. The histogram has h_bins*s_bins hue-saturation bins
    for colorful pixels plus v_bins value bins for gray, black and white pixels, and sums to 1.
    """
    cfg = config
    img_h, img_w = image.shape[:2]
    b = person.box

    top = b.y1 + (1.0 - cfg.lower_frac) * b.h
    hips = [
        kp.y
        for kp in (
            person.keypoint("left_hip", cfg.hip_min_conf),
            person.keypoint("right_hip", cfg.hip_min_conf),
        )
        if kp is not None
    ]
    if hips:
        top = min(max(sum(hips) / len(hips), b.y1), b.y2 - 0.2 * b.h)

    px1, px2 = _px(b.x1 + cfg.inset_x * b.w, img_w), _px(b.x2 - cfg.inset_x * b.w, img_w)
    py1, py2 = _px(top, img_h), _px(b.y2, img_h)
    if px2 - px1 < 2 or py2 - py1 < 2:
        return None

    mask = np.full((py2 - py1, px2 - px1), 255, np.uint8)
    for other in people:
        if other is person or not _in_front(other.box, b, cfg.front_eps):
            continue
        ox1, ox2 = max(_px(other.box.x1, img_w), px1), min(_px(other.box.x2, img_w), px2)
        oy1, oy2 = max(_px(other.box.y1, img_h), py1), min(_px(other.box.y2, img_h), py2)
        if ox2 > ox1 and oy2 > oy1:
            mask[oy1 - py1 : oy2 - py1, ox1 - px1 : ox2 - px1] = 0
    if cv2.countNonZero(mask) < cfg.min_visible * mask.size:
        return None

    hsv = cv2.cvtColor(np.ascontiguousarray(image[py1:py2, px1:px2]), cv2.COLOR_BGR2HSV)
    colorful = (hsv[..., 1] >= cfg.min_sat) & (hsv[..., 2] >= cfg.min_val)
    mask_color = np.where(colorful, mask, 0).astype(np.uint8)
    mask_gray = np.where(colorful, 0, mask).astype(np.uint8)
    hs = cv2.calcHist([hsv], [0, 1], mask_color, [cfg.h_bins, cfg.s_bins], [0, 180, 0, 256])
    v = cv2.calcHist([hsv], [2], mask_gray, [cfg.v_bins], [0, 256])
    hist = np.concatenate([hs.ravel(), v.ravel()]).astype(np.float32)
    total = float(hist.sum())
    return hist / total if total > 0 else None


def appearance_distance(a: np.ndarray, b: np.ndarray) -> float:
    """Bhattacharyya distance between two histograms: 0 = identical, 1 = no overlap."""
    return float(cv2.compareHist(a, b, cv2.HISTCMP_BHATTACHARYYA))


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
    def appearance_model(self) -> np.ndarray | None:
        """A copy of the stored lower-body histogram (for tests and debug views)."""
        return None if self._model is None else self._model.copy()

    def engage(self, detections: Detections, image: np.ndarray) -> TargetState:
        """Lock onto the close person nearest the center of the frame; stay IDLE if there is none."""
        self._reset()
        cfg = self.config
        close = [p for p in self._usable(detections) if p.box.h >= cfg.engage_min_h]
        for person in sorted(close, key=lambda p: abs(p.box.cx - 0.5)):
            hist = lower_body_histogram(image, person, detections.people, cfg)
            if hist is None:  # too occluded to learn what they look like; try the next one
                continue
            self._model = hist
            self._track = _AlphaBeta(person.box, detections.frame_t)
            return self._locked(person, detections.frame_t, reacquired=False)
        return self._state

    def disengage(self) -> None:
        """Forget the target and go IDLE."""
        self._reset()

    def update(self, detections: Detections, image: np.ndarray) -> TargetState:
        """Find the locked person in this frame. Does nothing while IDLE (call engage())."""
        if self._state.status is TargetStatus.IDLE or self._track is None or self._model is None:
            return self._state
        cfg = self.config
        t = detections.frame_t
        candidates = self._usable(detections)
        was_lost = self._state.status is TargetStatus.LOST
        since = max(0.0, t - self._last_seen_t)
        pred = self._track.predict(t, cfg.max_predict_s)

        # 1) Motion continuity: near where the target was heading, similar size, same look.
        if not was_lost or since <= cfg.hold_s:
            max_dist = cfg.max_dist_lost if was_lost else cfg.max_dist_locked
            gate = min(cfg.gate_max, cfg.gate_base + cfg.gate_growth_per_s * since)
            best: tuple[float, Person, np.ndarray, float] | None = None
            for p in candidates:
                d = math.hypot(p.box.cx - pred[0], p.box.cy - pred[1])
                ratio = p.box.h / max(float(pred[3]), 1e-6)
                if d > gate or not cfg.size_ratio_min <= ratio <= cfg.size_ratio_max:
                    continue
                hist = lower_body_histogram(image, p, detections.people, cfg)
                if hist is None:
                    continue
                app = appearance_distance(self._model, hist)
                if app > max_dist:
                    continue
                cost = d / gate + cfg.size_weight * abs(math.log(ratio)) + cfg.appearance_weight * app
                if best is None or cost < best[0]:
                    best = (cost, p, hist, app)
            if best is not None:
                _, p, hist, app = best
                self._track.correct(p.box, t, cfg)
                if not was_lost:
                    self._learn(p, hist, app, detections.people)
                return self._locked(p, t, reacquired=was_lost)

        if not was_lost:
            return self._lost(t)
        if since <= cfg.hold_s:
            # Probably just hidden for a moment: wait for it where it was heading instead of
            # jumping to a look-alike somewhere else.
            self._tentative = None
            return self._lost(t)

        # 2) Re-acquire anywhere by appearance alone, confirmed over a few frames in a row.
        best_r: tuple[float, Person] | None = None
        for p in candidates:
            hist = lower_body_histogram(image, p, detections.people, cfg)
            if hist is None:
                continue
            app = appearance_distance(self._model, hist)
            if app > cfg.max_dist_lost:
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
        self._model: np.ndarray | None = None
        self._track: _AlphaBeta | None = None
        self._last_seen_t = 0.0
        self._last_cx = 0.5
        self._tentative: tuple[float, float, int] | None = None  # (cx, cy, frames matched) while LOST

    def _usable(self, detections: Detections) -> list[Person]:
        return [p for p in detections.people if p.score >= self.config.min_det_score]

    def _learn(self, person: Person, hist: np.ndarray, app: float, people: Iterable[Person]) -> None:
        """Blend this frame into the model, unless the match is shaky or someone overlaps the target."""
        cfg = self.config
        if self._model is None or app > cfg.update_max_dist:
            return
        if any(o is not person and _covered(person.box, o.box) > cfg.freeze_overlap for o in people):
            return
        model = (1.0 - cfg.update_rate) * self._model + cfg.update_rate * hist
        self._model = (model / model.sum()).astype(np.float32)

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


def _in_front(other: Box, me: Box, eps: float) -> bool:
    """Is `other` standing in front of `me`? Feet lower in the image = closer to the camera;
    when both feet rows tie (e.g. both cut off at the bottom), the bigger box is closer. (guess)"""
    dy = other.y2 - me.y2
    if abs(dy) > eps:
        return dy > 0
    return other.h > me.h


def _covered(me: Box, other: Box) -> float:
    """Fraction of `me` that `other` covers."""
    ix = max(0.0, min(me.x2, other.x2) - max(me.x1, other.x1))
    iy = max(0.0, min(me.y2, other.y2) - max(me.y1, other.y1))
    return ix * iy / me.area if me.area > 0 else 0.0
