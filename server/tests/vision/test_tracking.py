"""Target lock tests on synthetic frames: no model, no camera.

The scene mimics the tilted-up phone camera: each person is painted head (skin), shirt,
trousers split into two legs (the background, or whoever stands behind, shows through the
gap) and shoes, scaled by box width, and cut off by the frame. At the default width the
feet are below the frame, like a person at follow distance. Most tests give everyone the
same shirt, so only the trousers tell people apart (the hard case for a part-based model).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

import numpy as np
import pytest

from app.vision.tracking import (
    BodyParts,
    LockConfig,
    TargetLock,
    appearance_distance,
    body_part_histograms,
    parts_distance,
    shift_for_turn,
)
from app.vision.types import Box, Detections, Keypoint, Person, TargetStatus

LOCKED, LOST, IDLE = TargetStatus.LOCKED, TargetStatus.LOST, TargetStatus.IDLE

W, H = 320, 240
FPS = 30.0
T0 = 5000.0  # arbitrary start time: the lock must take time from Detections.frame_t only
ASPECT = 0.3  # body width / body height, in pixels

BLUE = (180, 90, 20)  # BGR
RED = (40, 30, 190)
GREEN = (50, 160, 40)
BLACK = (25, 25, 25)
WHITE = (225, 225, 225)
GRAY = (140, 140, 140)
SHIRT = (150, 80, 120)
YELLOW = (40, 200, 220)
SKIN = (120, 150, 200)
SHOES = (210, 210, 210)
TABLE = (60, 90, 120)
BACKGROUND = 110

# Rows of the body as fractions of its full height, from the top of the head.
HEAD_END, SHOULDER, HIP, CROTCH, ANKLE = 0.13, 0.18, 0.5, 0.58, 0.94


@dataclass(frozen=True)
class Walker:
    """A person in the synthetic scene. Body height follows from the width (ASPECT)."""

    cx: float
    pants: tuple[int, int, int]
    shirt: tuple[int, int, int] = SHIRT
    w: float = 0.24  # box width; wider = closer
    top: float = 0.02  # top of the head (negative = cut off by the frame)
    patch: tuple[int, int, int] | None = None  # repaints the left half of the shirt and trousers
    keypoints: bool = True  # shoulder and hip keypoints (confident when in view)
    cut: float | None = None  # a table hides everything below this row; the box ends there
    depth: float | None = None  # paint order (larger = farther, painted first); default 1/w

    @property
    def full_h(self) -> float:
        return self.w * W / (ASPECT * H)

    def y(self, frac: float) -> float:
        return self.top + frac * self.full_h

    @property
    def box(self) -> Box:
        bottom = self.y(1.0) if self.cut is None else min(self.y(1.0), self.cut)
        return Box(
            max(self.cx - self.w / 2, 0.0), max(self.top, 0.0), min(self.cx + self.w / 2, 1.0), min(bottom, 1.0)
        )


def _px(v: float, n: int) -> int:
    return int(round(min(max(v, 0.0), 1.0) * n))


def _fill(img, x1, x2, y1, y2, color) -> None:
    img[_px(y1, H) : _px(y2, H), _px(x1, W) : _px(x2, W)] = color


def render(
    index: int, walkers: list[Walker], visible: list[Walker] | None = None
) -> tuple[Detections, np.ndarray]:
    """Paint every walker (far ones first) and detect only `visible` ones (default: all)."""
    img = np.full((H, W, 3), BACKGROUND, np.int16)
    for wk in sorted(walkers, key=lambda w: -(w.depth if w.depth is not None else 1.0 / w.w)):
        x1, x2 = wk.cx - wk.w / 2, wk.cx + wk.w / 2
        mid, gap = wk.cx, 0.1 * wk.w
        _fill(img, wk.cx - 0.2 * wk.w, wk.cx + 0.2 * wk.w, wk.y(0), wk.y(HEAD_END), SKIN)
        _fill(img, x1, x2, wk.y(HEAD_END), wk.y(HIP), wk.shirt)
        _fill(img, x1, x2, wk.y(HIP), wk.y(CROTCH), wk.pants)
        for lx1, lx2 in ((x1, mid - gap), (mid + gap, x2)):  # two legs; the gap stays unpainted
            _fill(img, lx1, lx2, wk.y(CROTCH), wk.y(ANKLE), wk.pants)
            _fill(img, lx1, lx2, wk.y(ANKLE), wk.y(1.0), SHOES)
        if wk.patch is not None:
            _fill(img, x1, mid, wk.y(HEAD_END), wk.y(CROTCH), wk.patch)
            _fill(img, x1, mid - gap, wk.y(CROTCH), wk.y(ANKLE), wk.patch)
        if wk.cut is not None:
            _fill(img, x1 - 0.05, x2 + 0.05, wk.cut, 1.0, TABLE)
    img += np.random.default_rng(index).integers(-6, 7, img.shape, dtype=np.int16)
    image = np.clip(img, 0, 255).astype(np.uint8)

    people = []
    for wk in walkers if visible is None else visible:
        kps = {}
        if wk.keypoints:
            for name, frac in (("shoulder", SHOULDER), ("hip", HIP)):
                y = wk.y(frac)
                seen = 0.0 <= y <= 1.0 and (wk.cut is None or y < wk.cut)
                for side, dx in (("left", -0.3), ("right", 0.3)):
                    kps[f"{side}_{name}"] = Keypoint(wk.cx + dx * wk.w, y, 0.9 if seen else 0.1)
        people.append(Person(box=wk.box, score=0.9, keypoints=kps))
    dets = Detections(frame_t=T0 + index / FPS, frame_index=index, width=W, height=H, people=people)
    return dets, image


def step(lock: TargetLock, index: int, walkers: list[Walker], visible: list[Walker] | None = None, turn_rate=0.0):
    dets, image = render(index, walkers, visible)
    return lock.update(dets, image, turn_rate=turn_rate)


def engage(lock: TargetLock, index: int, walkers: list[Walker], near: Box | None = None):
    dets, image = render(index, walkers)
    return lock.engage(dets, image, near=near)


def parts_of(walker: Walker, others: list[Walker] = (), index: int = 0) -> BodyParts | None:
    dets, image = render(index, [walker, *others])
    return body_part_histograms(image, dets.people[0], dets.people)


def covered(me: Box, other: Box) -> float:
    ix = max(0.0, min(me.x2, other.x2) - max(me.x1, other.x1))
    iy = max(0.0, min(me.y2, other.y2) - max(me.y1, other.y1))
    return ix * iy / me.area


def models_equal(a: BodyParts, b: BodyParts) -> bool:
    def same(x, y):
        return (x is None and y is None) or (x is not None and y is not None and np.array_equal(x, y))

    return same(a.torso, b.torso) and same(a.legs, b.legs)


def test_default_walker_looks_like_the_tilted_up_view():
    box = Walker(0.5, BLUE).box
    assert box.y2 == 1.0  # feet below the frame
    assert Walker(0.5, BLUE, w=0.3, top=-0.1).box.h == 1.0  # close: cut at top and bottom


# --- engage ---


def test_engage_picks_the_widest_person_near_the_center():
    walkers = [
        Walker(0.5, BLUE, w=0.2, top=0.1),  # dead center, but farther away
        Walker(0.68, RED, w=0.27, top=0.0),  # near the center and the closest there: this one
        Walker(0.9, GREEN, w=0.35, top=-0.1),  # closest of all, but off to the side
        Walker(0.42, BLACK, w=0.08, top=0.3),  # near the center, far away (too narrow)
    ]
    for wk in walkers:
        assert wk.box.y2 > 0.98 or wk.w < 0.1  # heights say nothing: the boxes are cut off
    lock = TargetLock()
    st = engage(lock, 0, walkers)
    assert st.status is LOCKED
    assert st.person.box == walkers[1].box
    assert not st.reacquired
    assert lock.state is st


def test_engage_with_nobody_suitable_stays_idle_and_can_be_retried():
    lock = TargetLock()
    assert engage(lock, 0, []).status is IDLE
    far = [Walker(0.5, BLUE, w=0.08, top=0.3)]
    assert engage(lock, 1, far).status is IDLE
    aside = [Walker(0.85, BLUE, w=0.28)]
    assert engage(lock, 2, aside).status is IDLE
    assert step(lock, 3, far).status is IDLE  # update never engages by itself
    near = [Walker(0.4, BLUE)]
    assert step(lock, 4, near).status is IDLE
    assert engage(lock, 5, near).status is LOCKED


def test_engage_near_a_box_picks_that_person_over_a_wider_one_nearer_the_center():
    target = Walker(0.72, RED, w=0.2, top=0.1)  # off center and farther away
    bystander = Walker(0.5, BLUE, w=0.3, top=-0.05)  # dead center and closer: the default pick
    assert engage(TargetLock(), 0, [target, bystander]).person.box == bystander.box

    lock = TargetLock()
    moved = Box(target.box.x1 + 0.02, target.box.y1, target.box.x2 + 0.02, target.box.y2)  # a frame ago
    st = engage(lock, 1, [target, bystander], near=moved)
    assert st.status is LOCKED and st.person.box == target.box
    assert step(lock, 2, [target, bystander]).person.box == target.box  # and keeps them


def test_engage_near_works_off_center_and_for_narrow_boxes():
    edge = Walker(0.88, GREEN, w=0.1, top=0.2)  # outside engage_max_offset and below engage_min_w
    assert engage(TargetLock(), 0, [edge]).status is IDLE
    st = engage(TargetLock(), 0, [edge], near=edge.box)
    assert st.status is LOCKED and st.person.box == edge.box


def test_engage_near_with_no_overlapping_person_stays_idle():
    lock = TargetLock()
    walkers = [Walker(0.3, RED), Walker(0.5, BLUE, w=0.3)]
    assert engage(lock, 0, walkers, near=Box(0.75, 0.1, 0.95, 1.0)).status is IDLE
    # A box that barely overlaps someone (IoU below engage_min_iou) doesn't count either.
    sliver = Box(0.62, 0.0, 0.8, 1.0)
    assert 0 < sliver.iou(walkers[1].box) < LockConfig().engage_min_iou
    assert engage(lock, 1, walkers, near=sliver).status is IDLE
    assert lock.appearance_model is None


def test_disengage_goes_idle_and_stops_tracking():
    lock = TargetLock()
    target = [Walker(0.5, BLUE)]
    engage(lock, 0, target)
    assert step(lock, 1, target).status is LOCKED
    lock.disengage()
    assert lock.state.status is IDLE
    assert lock.appearance_model is None
    assert step(lock, 2, target).status is IDLE


# --- keeping the lock ---


def test_follows_a_moving_target_over_many_frames():
    lock = TargetLock()
    for i in range(90):
        t = i / FPS
        # weaves and approaches: wider, and the head rises out of the frame
        target = Walker(0.5 + 0.3 * math.sin(2.0 * t), BLUE, w=0.2 + 0.03 * t, top=0.06 - 0.05 * t)
        st = engage(lock, i, [target]) if i == 0 else step(lock, i, [target])
        assert st.status is LOCKED, i
        assert st.person.box == target.box


def test_passerby_walking_close_by_does_not_steal_the_lock():
    lock = TargetLock()
    target = Walker(0.4, BLUE)
    engage(lock, 0, [target])
    for i in range(1, 80):
        # walks in from the right, stands shoulder to shoulder with the target, walks away
        x = 0.95 - 0.3 * min(i, 30) / 30 if i < 50 else 0.65 + 0.3 * (i - 50) / 30
        passer = Walker(x, RED, w=0.25, top=0.0)
        st = step(lock, i, [target, passer])
        assert st.status is LOCKED, i
        assert st.person.box == target.box


@pytest.mark.parametrize("target_in_front", [False, True])
def test_two_people_crossing_keeps_the_original_target(target_in_front):
    lock = TargetLock()
    near, far = {"w": 0.25, "top": 0.0}, {"w": 0.21, "top": 0.06}
    overlapped = 0
    for i in range(60):
        t = i / FPS
        a = Walker(0.3 + 0.3 * t, BLUE, **(near if target_in_front else far))  # the target, walking right
        b = Walker(0.9 - 0.3 * t, RED, **(far if target_in_front else near))  # walking left
        front, back = (a, b) if target_in_front else (b, a)
        overlapped += a.box.iou(b.box) > 0
        # the detector misses whoever is more than half hidden
        visible = [a, b] if covered(back.box, front.box) < 0.5 else [front]
        st = engage(lock, i, [a]) if i == 0 else step(lock, i, [a, b], visible)
        if st.status is LOCKED:
            assert st.person.box == a.box, i  # never on the other person
    assert overlapped >= 10  # the boxes really did overlap for a while
    assert st.status is LOCKED
    assert st.person.box == a.box


def test_same_colored_distractor_away_from_target_does_not_steal_the_lock():
    lock = TargetLock()
    for i in range(70):
        target = Walker(0.3 + 0.03 * math.sin(i / 5), BLUE)
        walkers = [target]
        if i >= 10:  # an identical twin walks in from the right and stops 0.25 away (inside the gate)
            walkers.append(Walker(max(0.55, 0.85 - 0.3 * (i - 10) / FPS), BLUE))
        st = engage(lock, i, walkers) if i == 0 else step(lock, i, walkers)
        assert st.status is LOCKED, i
        assert st.person.box == target.box


def test_same_colored_lookalike_is_ignored_while_the_target_is_briefly_hidden():
    lock = TargetLock()
    twin = Walker(0.85, BLUE)
    for i in range(55):
        target = Walker(0.25 + 0.05 * i / FPS, BLUE)
        hidden = 20 <= i < 38  # 0.6 s behind something, shorter than hold_s
        walkers = [twin] if hidden else [target, twin]
        st = engage(lock, i, walkers) if i == 0 else step(lock, i, walkers)
        if hidden:
            assert st.status is LOST, i
        else:
            assert st.status is LOCKED, i
            assert st.person.box == target.box
            assert st.reacquired == (i == 38)


def test_reacquire_needs_a_steady_match():
    lock = TargetLock()
    engage(lock, 0, [Walker(0.5, BLUE)])
    for i in range(1, 40):  # gone for over a second
        assert step(lock, i, []).status is LOST
    # Look-alike glimpses that never hold still for reacquire_frames frames in a row.
    glimpses = [0.2, 0.2, None, 0.8, 0.8, None, 0.2, 0.8, 0.2, 0.8, 0.2, 0.8]
    for k, x in enumerate(glimpses):
        st = step(lock, 40 + k, [] if x is None else [Walker(x, BLUE)])
        assert st.status is LOST, k


def test_short_detector_dropout_relocks_immediately():
    lock = TargetLock()
    for i in range(40):
        target = Walker(0.3 + 0.01 * i, BLUE)
        if i == 0:
            engage(lock, i, [target])
            continue
        missed = i in (20, 21)
        st = step(lock, i, [target], [] if missed else None)
        if missed:
            assert st.status is LOST
            assert st.lost_for_s == pytest.approx((i - 19) / FPS)
        else:
            assert st.status is LOCKED
            assert st.person.box == target.box
            assert st.reacquired == (i == 22)


def test_size_gate_uses_width_not_the_clipped_height():
    lock = TargetLock()
    target = Walker(0.5, BLUE, w=0.2, top=0.06)
    engage(lock, 0, [target])
    for i in range(1, 10):
        assert step(lock, i, [target]).status is LOCKED
    # The target drops out; an identical twin right there but 2.5x wider (much closer). Both
    # boxes are as tall as the frame allows, so height can't tell; width must.
    close_twin = Walker(0.5, BLUE, w=0.5, top=-0.3)
    assert close_twin.box.y2 == 1.0 and target.box.y2 > 0.9
    for i in range(10, 20):
        st = step(lock, i, [close_twin])
        assert st.status is LOST, i


# --- missed detections: the grace period ---


@pytest.mark.parametrize(("missed_frames", "recovers"), [(1, True), (3, True), (7, True), (15, False)])
def test_target_whose_look_drifted_survives_a_short_miss(missed_frames, recovers):
    """Appearance distance in the 0.4-0.6 band: fine while LOCKED, too far for the strict LOST
    rule. A miss shorter than miss_grace_s (0.3 s = 9 frames) must not strand the target."""
    cfg = LockConfig()
    lock = TargetLock(cfg)
    target = Walker(0.5, BLUE)
    engage(lock, 0, [target])
    for i in range(1, 10):
        step(lock, i, [target])
    drifted = replace(target, patch=YELLOW)  # say, a jacket opened on one side
    app = parts_distance(lock.appearance_model, parts_of(drifted), cfg)
    assert cfg.max_dist_lost < app < cfg.max_dist_locked  # the band the old code got stuck in

    for i in range(10, 15):  # still LOCKED with the drifted look (no learning: match too weak)
        st = step(lock, i, [drifted])
        assert st.status is LOCKED and st.person.box == drifted.box
    for i in range(15, 15 + missed_frames):
        st = step(lock, i, [drifted], [])
        assert st.status is LOST
        assert st.lost_for_s == pytest.approx((i - 14) / FPS)
    back = 15 + missed_frames
    st = step(lock, back, [drifted])
    if recovers:
        assert st.status is LOCKED and st.reacquired and st.person.box == drifted.box
    else:
        # Past the grace period the strict rule applies, and it keeps applying.
        for i in range(back, back + 40):
            assert step(lock, i, [drifted]).status is LOST, i


def test_without_the_grace_period_a_single_miss_strands_a_drifted_target():
    """The bug the grace period fixes, reproduced with miss_grace_s = 0."""
    lock = TargetLock(LockConfig(miss_grace_s=0.0))
    target = Walker(0.5, BLUE)
    engage(lock, 0, [target])
    drifted = replace(target, patch=YELLOW)
    for i in range(1, 10):
        step(lock, i, [drifted])
    assert step(lock, 10, [drifted], []).status is LOST
    for i in range(11, 60):
        assert step(lock, i, [drifted]).status is LOST


# --- robot turning (ego-motion) ---


def _bearing(x: float, hfov_deg: float = 67.0) -> float:
    """REP 103 bearing of image column x (left positive), as in follow.py's CameraGeometry."""
    return -math.atan((x - 0.5) * 2.0 * math.tan(math.radians(hfov_deg) / 2.0))


def test_shift_for_turn_sign_and_size():
    # Turning LEFT (w > 0) moves still things RIGHT in the image, and the other way round.
    assert shift_for_turn(0.5, 0.1, 67.0) > 0.5
    assert shift_for_turn(0.5, -0.1, 67.0) < 0.5
    for x in (0.1, 0.5, 0.8):
        for yaw in (-0.3, 0.05, 0.4):
            assert _bearing(shift_for_turn(x, yaw, 67.0)) == pytest.approx(_bearing(x) - yaw)
    # Near the center, about yaw / (2 tan(hfov/2)) of the frame per radian.
    assert shift_for_turn(0.5, 0.01, 67.0) - 0.5 == pytest.approx(0.01 / (2 * math.tan(math.radians(33.5))), rel=1e-3)


@pytest.mark.parametrize("direction", [1.0, -1.0])  # +1 = robot turns left
@pytest.mark.parametrize("reported", ["correct", "flipped", "zero"])
def test_turning_robot_keeps_a_still_target(direction, reported):
    """A still target the detector misses while the robot turns: the lock must look for it
    where the turn moved it, not where it was, even with an identical twin standing there."""
    w = 1.5 * direction  # rad/s
    lock = TargetLock()
    engage(lock, 0, [Walker(0.5, BLUE)])
    for i in range(1, 10):
        assert step(lock, i, [Walker(0.5, BLUE)]).status is LOCKED
    passed = {"correct": w, "flipped": -w, "zero": 0.0}[reported]
    yaw = 0.0
    for i in range(10, 17):
        yaw += w / FPS
        target = Walker(shift_for_turn(0.5, yaw, 67.0), BLUE)
        twin = Walker(0.5 - 0.1 * direction, BLUE)  # appears near where the target used to be
        visible = [target, twin] if i == 16 else []  # motion blur: nothing detected until frame 16
        st = step(lock, i, [target, twin] if i == 16 else [target], visible, turn_rate=passed)
    if direction > 0:
        assert target.box.cx > 0.7  # the robot turned left, so the target slid right
    else:
        assert target.box.cx < 0.3
    if reported == "correct":
        assert st.status is LOCKED and st.person.box == target.box
    else:  # the test is sensitive to the sign: a wrong or missing turn rate picks the twin
        assert st.status is LOCKED and st.person.box == twin.box


def test_turning_while_tracking_keeps_the_lock():
    lock = TargetLock()
    engage(lock, 0, [Walker(0.5, BLUE)])
    yaw = 0.0
    for i in range(1, 40):  # spin left at 2 rad/s for over a second, then stop
        w = 2.0 if i < 20 else 0.0
        yaw += w / FPS
        target = Walker(shift_for_turn(0.5, yaw * 0.3, 67.0), BLUE)  # the person walks along, partly
        st = step(lock, i, [target], turn_rate=w)
        assert st.status is LOCKED, i
        assert st.person.box == target.box


# --- lost and re-acquire ---


@pytest.mark.parametrize("gap_frames", [0, 10])
@pytest.mark.parametrize(
    ("target_look", "stranger_look"),
    [
        ((SHIRT, BLUE), (SHIRT, RED)),
        ((SHIRT, BLACK), (SHIRT, WHITE)),
        ((SHIRT, BLACK), (SHIRT, GRAY)),
        ((SHIRT, GREEN), (SHIRT, BLUE)),
        ((SHIRT, BLUE), (GREEN, BLUE)),  # same trousers, different shirt
    ],
)
def test_stranger_where_the_target_vanished_is_not_reacquired(gap_frames, target_look, stranger_look):
    target = Walker(0.5, target_look[1], shirt=target_look[0])
    stranger = Walker(0.5, stranger_look[1], shirt=stranger_look[0])
    lock = TargetLock()
    engage(lock, 0, [target])
    for i in range(1, 10):
        step(lock, i, [target])
    last_seen = 9
    for i in range(10, 10 + gap_frames):
        st = step(lock, i, [])
        assert st.status is LOST
    for i in range(10 + gap_frames, 80):
        st = step(lock, i, [stranger])
        assert st.status is LOST, i
        assert st.person is None
        assert not st.reacquired
        assert st.last_seen_cx == pytest.approx(0.5)
        assert st.lost_for_s == pytest.approx((i - last_seen) / FPS)


def test_target_reappearing_elsewhere_is_reacquired():
    lock = TargetLock()
    stranger = Walker(0.65, RED)
    engage(lock, 0, [Walker(0.65, BLUE)])
    for i in range(1, 10):
        step(lock, i, [Walker(0.65, BLUE)])
    for i in range(10, 55):  # target gone for 1.5 s; a stranger stands where it was
        st = step(lock, i, [stranger])
        assert st.status is LOST
    assert st.last_seen_cx == pytest.approx(0.65)

    back = Walker(0.15, BLUE, w=0.2, top=0.06)  # the target comes back at the other side of the frame
    states = [step(lock, i, [stranger, back]) for i in range(55, 65)]
    first = next(k for k, s in enumerate(states) if s.status is LOCKED)
    assert first < LockConfig().reacquire_frames
    assert all(s.status is LOST for s in states[:first])
    assert states[first].reacquired
    assert states[first].person.box == back.box
    for s in states[first + 1 :]:
        assert s.status is LOCKED and not s.reacquired and s.person.box == back.box


def test_lost_stays_lost_without_a_match():
    lock = TargetLock()
    engage(lock, 0, [Walker(0.5, BLUE)])
    for i in range(1, 300):  # 10 s of strangers and empty frames
        walkers = [Walker(0.2 + 0.002 * i, RED), Walker(0.8, GREEN)] if i % 3 else []
        st = step(lock, i, walkers)
        assert st.status is LOST
    assert st.lost_for_s == pytest.approx(299 / FPS)


# --- appearance model: parts ---


def test_parts_distance_compares_only_parts_visible_in_both():
    full = parts_of(Walker(0.5, BLUE))
    assert full.torso is not None and full.legs is not None
    torso_only = BodyParts(torso=full.torso, torso_px=full.torso_px)
    legs_only = BodyParts(legs=full.legs, legs_px=full.legs_px)
    other = parts_of(Walker(0.5, BLUE), index=1)  # same look, different noise

    assert parts_distance(full, torso_only) == pytest.approx(appearance_distance(full.torso, torso_only.torso))
    assert parts_distance(torso_only, full) == pytest.approx(0.0, abs=1e-6)
    d_t = appearance_distance(full.torso, other.torso)
    d_l = appearance_distance(full.legs, other.legs)
    assert parts_distance(full, BodyParts(torso=other.torso, torso_px=5)) == pytest.approx(d_t)
    assert parts_distance(full, BodyParts(legs=other.legs, legs_px=5)) == pytest.approx(d_l)
    assert parts_distance(torso_only, legs_only) is None  # nothing in common to compare
    # Both parts: weighted by the candidate's visible pixels.
    weighted = (d_t * other.torso_px + d_l * other.legs_px) / (other.torso_px + other.legs_px)
    assert parts_distance(full, other) == pytest.approx(weighted)
    heavy_legs = BodyParts(other.torso, other.legs, torso_px=1, legs_px=1000)
    assert parts_distance(full, heavy_legs) == pytest.approx((d_t + 1000 * d_l) / 1001)


def test_one_clearly_different_part_vetoes_the_match():
    cfg = LockConfig()
    model = parts_of(Walker(0.5, BLUE))
    same_shirt = parts_of(Walker(0.5, RED))  # same shirt, different trousers
    d_legs = appearance_distance(model.legs, same_shirt.legs)
    assert appearance_distance(model.torso, same_shirt.torso) < 0.2
    assert d_legs > cfg.max_part_dist
    assert parts_distance(model, same_shirt, cfg) == pytest.approx(d_legs)  # not the diluted mean


def test_torso_alone_keeps_the_lock_when_the_legs_are_hidden():
    lock = TargetLock()
    target = Walker(0.35, BLUE)
    stranger = Walker(0.62, RED, shirt=GREEN)  # inside the gate, different shirt
    engage(lock, 0, [target])
    for i in range(1, 10):
        assert step(lock, i, [target, stranger]).status is LOCKED
    hips = target.y(HIP)
    behind = replace(target, cut=hips + 0.03)  # walks behind a table: the box ends at the hips
    stranger_behind = replace(stranger, cut=hips + 0.03)
    assert parts_of(behind).legs is None and parts_of(behind).torso is not None
    assert behind.box.h < 0.6 * target.box.h  # height halves; width doesn't
    for i in range(10, 40):
        st = step(lock, i, [behind, stranger_behind])
        assert st.status is LOCKED, i
        assert st.person.box == behind.box
    # The stranger alone, legs hidden too, where the target was: never taken.
    for i in range(40, 80):
        st = step(lock, i, [replace(stranger_behind, cx=0.35)])
        assert st.status is LOST, i


def test_a_part_missing_at_engage_is_learned_later():
    lock = TargetLock()
    target = Walker(0.5, BLUE)
    behind = replace(target, cut=target.y(HIP) + 0.03)
    engage(lock, 0, [behind])
    assert lock.appearance_model.legs is None and lock.appearance_model.torso is not None
    st = step(lock, 1, [target])  # steps out from behind the table
    assert st.status is LOCKED
    legs = lock.appearance_model.legs
    assert legs is not None
    assert appearance_distance(legs, parts_of(target).legs) < 0.2
    # From now on trousers count: a same-shirt stranger in red trousers is rejected.
    for i in range(2, 5):
        step(lock, i, [target])
    assert step(lock, 5, [Walker(0.5, RED)], []).status is LOST  # target missed this frame
    for i in range(6, 40):
        assert step(lock, i, [Walker(0.5, RED)]).status is LOST, i


@pytest.mark.parametrize("other_in_front", [True, False])
def test_appearance_model_is_frozen_while_another_person_overlaps(other_in_front):
    lock = TargetLock()
    target = Walker(0.5, BLUE)
    other = Walker(0.68, RED, w=0.27, top=0.0) if other_in_front else Walker(0.62, RED, w=0.2, top=0.08)
    assert covered(target.box, other.box) > LockConfig().freeze_overlap

    engage(lock, 0, [target])
    previous = lock.appearance_model
    for i in range(1, 10):  # alone: every frame's noise nudges the model a little
        assert step(lock, i, [target]).status is LOCKED
        assert not models_equal(lock.appearance_model, previous)
        previous = lock.appearance_model

    frozen = lock.appearance_model
    for i in range(10, 30):  # overlapped: no learning at all
        st = step(lock, i, [target, other])
        assert st.status is LOCKED, i
        assert st.person.box == target.box
        assert models_equal(lock.appearance_model, frozen)

    step(lock, 30, [target])  # alone again: learning resumes
    assert not models_equal(lock.appearance_model, frozen)


# --- appearance model: masking and part rows ---


def _masking_gain(target: Walker, other: Walker) -> tuple[float, float]:
    """(distance clean->masked, distance clean->unmasked) of the target's trousers."""
    dets, image = render(0, [target, other])
    alone_dets, alone_image = render(0, [target])
    clean = body_part_histograms(alone_image, alone_dets.people[0])
    masked = body_part_histograms(image, dets.people[0], dets.people)
    unmasked = body_part_histograms(image, dets.people[0])
    return appearance_distance(clean.legs, masked.legs), appearance_distance(clean.legs, unmasked.legs)


def test_histogram_masks_out_a_wider_person_in_front_when_feet_are_cut_off():
    target, other = Walker(0.5, BLUE), Walker(0.62, RED, w=0.27, top=0.0)
    assert target.box.y2 == other.box.y2 == 1.0  # feet can't tell who's in front
    masked, unmasked = _masking_gain(target, other)
    assert masked < 0.2
    assert unmasked > masked + 0.2
    # The narrower person behind is not masked out of the wider one in front.
    dets, image = render(0, [other, target])
    assert body_part_histograms(image, dets.people[0], dets.people).legs_px == (
        body_part_histograms(image, dets.people[0]).legs_px
    )


def test_feet_decide_who_is_in_front_when_both_are_in_view():
    # A narrower person (a child, say) whose feet are lower in the image stands in front.
    target = Walker(0.5, BLUE, w=0.18, top=0.12)
    other = Walker(0.6, RED, w=0.16, top=0.25, depth=1.0)  # painted in front
    assert target.box.y2 < 0.98 and other.box.y2 < 0.98
    assert other.box.y2 > target.box.y2 + LockConfig().front_eps and other.w < target.w
    masked, unmasked = _masking_gain(target, other)
    assert masked < 0.2
    assert unmasked > masked + 0.2


def test_part_rows_come_from_shoulder_and_hip_keypoints_when_confident():
    walker = Walker(0.5, BLUE, w=0.15, top=0.3)
    dets, image = render(0, [walker])
    person = dets.people[0]
    box = person.box
    # A detector box that starts much higher (background and head would fall into the
    # fixed-fraction torso rows).
    tall = Box(box.x1, 0.0, box.x2, box.y2)
    with_kp = Person(box=tall, score=0.9, keypoints=person.keypoints)
    no_kp = Person(box=tall, score=0.9)
    weak_kp = Person(
        box=tall, score=0.9, keypoints={k: Keypoint(v.x, v.y, 0.2) for k, v in person.keypoints.items()}
    )
    reference = body_part_histograms(image, person)
    kp = body_part_histograms(image, with_kp)
    assert appearance_distance(reference.torso, kp.torso) < 0.1
    assert appearance_distance(reference.legs, kp.legs) < 0.1
    fixed = body_part_histograms(image, no_kp)
    assert appearance_distance(reference.torso, fixed.torso) > 0.3
    weak = body_part_histograms(image, weak_kp)
    assert np.array_equal(weak.torso, fixed.torso) and np.array_equal(weak.legs, fixed.legs)


def test_no_histogram_when_the_person_is_hidden():
    target, other = Walker(0.5, BLUE, w=0.2, top=0.06), Walker(0.5, RED, w=0.27, top=0.0)
    dets, image = render(0, [target, other])
    assert body_part_histograms(image, dets.people[0], dets.people) is None


def test_legs_out_of_frame_are_not_visible():
    very_close = Walker(0.5, BLUE, w=0.5, top=-0.14)  # hips just above the bottom edge
    assert 0.95 < very_close.y(HIP) < 1.0
    parts = parts_of(very_close)
    assert parts is not None and parts.torso is not None and parts.legs is None
