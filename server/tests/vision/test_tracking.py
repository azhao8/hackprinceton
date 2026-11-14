"""Target lock tests on synthetic frames: no model, no camera.

Each person is painted as a shirt, pants split into two legs (the background, or whoever
stands behind, shows through the gap) and shoes. Everyone wears the same shirt and shoes,
so only the pants tell people apart, like the low robot camera sees them.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pytest

from app.vision.tracking import LockConfig, TargetLock, appearance_distance, lower_body_histogram
from app.vision.types import Box, Detections, Keypoint, Person, TargetStatus

LOCKED, LOST, IDLE = TargetStatus.LOCKED, TargetStatus.LOST, TargetStatus.IDLE

W, H = 320, 240
FPS = 30.0
T0 = 5000.0  # arbitrary start time: the lock must take time from Detections.frame_t only

BLUE = (180, 90, 20)  # BGR
RED = (40, 30, 190)
GREEN = (50, 160, 40)
BLACK = (25, 25, 25)
WHITE = (225, 225, 225)
GRAY = (140, 140, 140)
SHIRT = (150, 80, 120)
SHOES = (210, 210, 210)
BACKGROUND = 110


@dataclass(frozen=True)
class Walker:
    """A person in the synthetic scene: box from feet (`bottom`) up `h`, width 0.3*h."""

    cx: float
    pants: tuple[int, int, int]
    h: float = 0.6
    bottom: float = 0.95
    hips: bool = False  # add confident hip keypoints at the top of the pants

    @property
    def box(self) -> Box:
        w = 0.3 * self.h
        return Box(self.cx - w / 2, self.bottom - self.h, self.cx + w / 2, self.bottom)


def _px(v: float, n: int) -> int:
    return int(round(min(max(v, 0.0), 1.0) * n))


def render(
    index: int, walkers: list[Walker], visible: list[Walker] | None = None
) -> tuple[Detections, np.ndarray]:
    """Paint every walker (far ones first) and detect only `visible` ones (default: all)."""
    img = np.full((H, W, 3), BACKGROUND, np.int16)
    for wk in sorted(walkers, key=lambda w: w.bottom):
        b = wk.box
        x1, x2, y1, y2 = _px(b.x1, W), _px(b.x2, W), _px(b.y1, H), _px(b.y2, H)
        bh = y2 - y1
        hip, crotch, ankle = y1 + round(0.4 * bh), y1 + round(0.55 * bh), y2 - round(0.1 * bh)
        mid, gap = (x1 + x2) // 2, max(1, round(0.1 * (x2 - x1)))
        img[y1:hip, x1:x2] = SHIRT
        img[hip:crotch, x1:x2] = wk.pants
        for lx1, lx2 in ((x1, mid - gap), (mid + gap, x2)):  # two legs; the gap stays unpainted
            img[crotch:ankle, lx1:lx2] = wk.pants
            img[ankle:y2, lx1:lx2] = SHOES
    img += np.random.default_rng(index).integers(-6, 7, img.shape, dtype=np.int16)
    image = np.clip(img, 0, 255).astype(np.uint8)

    people = []
    for wk in walkers if visible is None else visible:
        kps = {}
        if wk.hips:
            y = wk.box.y1 + 0.4 * wk.h
            kps = {"left_hip": Keypoint(wk.cx - 0.03, y, 0.9), "right_hip": Keypoint(wk.cx + 0.03, y, 0.9)}
        people.append(Person(box=wk.box, score=0.9, keypoints=kps))
    dets = Detections(frame_t=T0 + index / FPS, frame_index=index, width=W, height=H, people=people)
    return dets, image


def step(lock: TargetLock, index: int, walkers: list[Walker], visible: list[Walker] | None = None):
    dets, image = render(index, walkers, visible)
    return lock.update(dets, image)


def engage(lock: TargetLock, index: int, walkers: list[Walker]):
    dets, image = render(index, walkers)
    return lock.engage(dets, image)


def covered(me: Box, other: Box) -> float:
    ix = max(0.0, min(me.x2, other.x2) - max(me.x1, other.x1))
    iy = max(0.0, min(me.y2, other.y2) - max(me.y1, other.y1))
    return ix * iy / me.area


# --- engage ---


def test_engage_picks_the_close_person_nearest_the_center():
    walkers = [
        Walker(0.2, RED),
        Walker(0.62, BLUE),
        Walker(0.88, GREEN),
        Walker(0.5, BLACK, h=0.15, bottom=0.6),  # dead center but far away (too small)
    ]
    lock = TargetLock()
    st = engage(lock, 0, walkers)
    assert st.status is LOCKED
    assert st.person.box == walkers[1].box
    assert not st.reacquired
    assert lock.state is st


def test_engage_with_nobody_suitable_stays_idle_and_can_be_retried():
    lock = TargetLock()
    assert engage(lock, 0, []).status is IDLE
    far = [Walker(0.5, BLUE, h=0.15, bottom=0.6)]
    assert engage(lock, 1, far).status is IDLE
    assert step(lock, 2, far).status is IDLE  # update never engages by itself
    near = [Walker(0.4, BLUE)]
    assert step(lock, 3, near).status is IDLE
    assert engage(lock, 4, near).status is LOCKED


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
        target = Walker(0.5 + 0.3 * math.sin(2.0 * t), BLUE, h=0.5 + 0.1 * t)  # weaves and approaches
        st = engage(lock, i, [target]) if i == 0 else step(lock, i, [target])
        assert st.status is LOCKED, i
        assert st.person.box == target.box


def test_passerby_walking_close_by_does_not_steal_the_lock():
    lock = TargetLock()
    target = Walker(0.45, BLUE)
    engage(lock, 0, [target])
    for i in range(1, 80):
        # walks in from the right, stands shoulder to shoulder with the target, walks away
        x = 0.95 - 0.33 * min(i, 30) / 30 if i < 50 else 0.62 + 0.33 * (i - 50) / 30
        passer = Walker(x, RED, h=0.62, bottom=0.97)
        st = step(lock, i, [target, passer])
        assert st.status is LOCKED, i
        assert st.person.box == target.box


@pytest.mark.parametrize("target_in_front", [False, True])
def test_two_people_crossing_keeps_the_original_target(target_in_front):
    lock = TargetLock()
    near, far = dict(h=0.62, bottom=0.97), dict(h=0.55, bottom=0.9)
    overlapped = 0
    for i in range(60):
        t = i / FPS
        a = Walker(0.2 + 0.3 * t, BLUE, **(near if target_in_front else far))  # the target, walking right
        b = Walker(0.8 - 0.3 * t, RED, **(far if target_in_front else near))  # walking left
        front, back = (a, b) if target_in_front else (b, a)
        overlapped += a.box.iou(b.box) > 0
        # the detector misses whoever is more than half hidden
        visible = [a, b] if covered(back.box, front.box) < 0.5 else [front]
        st = engage(lock, i, [a, b]) if i == 0 else step(lock, i, [a, b], visible)
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
        if i >= 10:  # an identical twin walks in from the right and stops 0.2 away (inside the gate)
            walkers.append(Walker(max(0.5, 0.85 - 0.3 * (i - 10) / FPS), BLUE))
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


# --- lost and re-acquire ---


@pytest.mark.parametrize("gap_frames", [0, 10])
@pytest.mark.parametrize(
    ("target_pants", "stranger_pants"), [(BLUE, RED), (BLACK, WHITE), (BLACK, GRAY), (GREEN, BLUE)]
)
def test_stranger_where_the_target_vanished_is_not_reacquired(gap_frames, target_pants, stranger_pants):
    lock = TargetLock()
    engage(lock, 0, [Walker(0.5, target_pants)])
    for i in range(1, 10):
        step(lock, i, [Walker(0.5, target_pants)])
    last_seen = 9
    for i in range(10, 10 + gap_frames):
        st = step(lock, i, [])
        assert st.status is LOST
    for i in range(10 + gap_frames, 80):
        st = step(lock, i, [Walker(0.5, stranger_pants)])
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

    back = Walker(0.15, BLUE, h=0.5)  # the target comes back at the other side of the frame
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


# --- appearance model ---


@pytest.mark.parametrize("other_in_front", [True, False])
def test_appearance_model_is_frozen_while_another_person_overlaps(other_in_front):
    lock = TargetLock()
    target = Walker(0.5, BLUE)
    other = Walker(0.57, RED, **(dict(h=0.62, bottom=0.98) if other_in_front else dict(h=0.55, bottom=0.9)))
    assert covered(target.box, other.box) > LockConfig().freeze_overlap

    engage(lock, 0, [target])
    previous = lock.appearance_model
    for i in range(1, 10):  # alone: every frame's noise nudges the model a little
        assert step(lock, i, [target]).status is LOCKED
        assert not np.array_equal(lock.appearance_model, previous)
        previous = lock.appearance_model

    frozen = lock.appearance_model
    for i in range(10, 30):  # overlapped: no learning at all
        st = step(lock, i, [target, other])
        assert st.status is LOCKED, i
        assert st.person.box == target.box
        assert np.array_equal(lock.appearance_model, frozen)

    step(lock, 30, [target])  # alone again: learning resumes
    assert not np.array_equal(lock.appearance_model, frozen)


def test_histogram_masks_out_a_person_standing_in_front():
    target, other = Walker(0.5, BLUE), Walker(0.6, RED, h=0.62, bottom=0.98)
    dets, image = render(0, [target, other])
    alone_dets, alone_image = render(0, [target])
    p_target = dets.people[0]
    clean = lower_body_histogram(alone_image, alone_dets.people[0])
    masked = lower_body_histogram(image, p_target, dets.people)
    unmasked = lower_body_histogram(image, p_target)
    assert appearance_distance(clean, masked) < 0.2
    assert appearance_distance(clean, unmasked) > appearance_distance(clean, masked) + 0.2


def test_histogram_starts_at_the_hips_when_they_are_confident():
    # A tall box whose pants start at 40% of its height; hips put the region top right there.
    with_hips = Walker(0.5, BLUE, hips=True)
    dets, image = render(0, [with_hips])
    person = dets.people[0]
    box = person.box
    # Detector box that starts higher (includes more shirt): lower 60% would include shirt.
    tall = Box(box.x1, box.y1 - 0.25, box.x2, box.y2)
    with_kp = Person(box=tall, score=0.9, keypoints=person.keypoints)
    no_kp = Person(box=tall, score=0.9)
    weak_kp = Person(
        box=tall, score=0.9, keypoints={k: Keypoint(v.x, v.y, 0.2) for k, v in person.keypoints.items()}
    )
    reference = lower_body_histogram(image, person)
    assert appearance_distance(reference, lower_body_histogram(image, with_kp)) < 0.1
    assert appearance_distance(reference, lower_body_histogram(image, no_kp)) > 0.3
    assert np.array_equal(lower_body_histogram(image, weak_kp), lower_body_histogram(image, no_kp))


def test_no_histogram_when_the_person_is_hidden():
    target, other = Walker(0.5, BLUE, h=0.5, bottom=0.9), Walker(0.5, RED, h=0.62, bottom=0.97)
    dets, image = render(0, [target, other])
    assert lower_body_histogram(image, dets.people[0], dets.people) is None
