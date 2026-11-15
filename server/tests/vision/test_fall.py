"""Possible-fall detection: pose on every frame, Claude confirms, then the alert."""

import asyncio
import types

import numpy as np

from app.vision.fall import (COOLDOWN_S, HOLD_S, RECHECK_S, REARM_S, RESET_S, FallDetector, FallWatcher, lying,
                             torso_tilt_deg)
from app.vision.types import Box, Keypoint, Person


def person(upright: bool) -> Person:
    if upright:
        kps = {"left_shoulder": (0.45, 0.3), "right_shoulder": (0.55, 0.3), "left_hip": (0.46, 0.6), "right_hip": (0.54, 0.6)}
        box = Box(0.4, 0.2, 0.6, 0.95)
    else:
        kps = {"left_shoulder": (0.3, 0.80), "right_shoulder": (0.3, 0.86), "left_hip": (0.6, 0.82), "right_hip": (0.6, 0.88)}
        box = Box(0.2, 0.75, 0.8, 0.95)
    return Person(box, 0.9, {n: Keypoint(x, y, 0.9) for n, (x, y) in kps.items()})


def perception(*people: Person):
    frame = types.SimpleNamespace(width=640, height=360, image=np.zeros((360, 640, 3), np.uint8))
    return types.SimpleNamespace(frame=frame, detections=types.SimpleNamespace(people=list(people)))


def test_tilt():
    assert torso_tilt_deg(person(True), 640, 360) < 20
    assert torso_tilt_deg(person(False), 640, 360) > 80


def test_detector_needs_it_to_last_and_then_cools_down():
    t = [0.0]
    d = FallDetector(clock=lambda: t[0])
    assert d.update(perception(person(True))) is None
    assert d.update(perception(person(False))) is None          # just went down
    t[0] = HOLD_S + 0.1
    assert d.update(perception(person(False))) is not None      # still down: suspected
    t[0] += 5
    d.update(perception(person(False)))
    t[0] += HOLD_S + 0.1
    assert d.update(perception(person(False))) is None          # cooling down: no second alert


def test_watcher_raises_only_when_claude_agrees():
    raised = []
    answers = iter(["no, she is sitting on the floor playing with the cat", "yes, a woman is lying on the floor"])

    async def confirm(jpeg):
        return next(answers)

    class Always(FallDetector):
        def update(self, p):
            return "lying down"

    w = FallWatcher(lambda: perception(person(False)), lambda: b"jpeg", raised.append, confirm=confirm, detector=Always())
    assert asyncio.run(w.check_once()) is False and raised == []
    assert asyncio.run(w.check_once()) is True and raised == ["a woman is lying on the floor"]


def test_watcher_raises_when_claude_is_unreachable():
    raised = []

    async def broken(jpeg):
        raise ConnectionError("offline")

    class Always(FallDetector):
        def update(self, p):
            return "lying down"

    w = FallWatcher(lambda: perception(person(False)), lambda: b"jpeg", raised.append, confirm=broken, detector=Always())
    assert asyncio.run(w.check_once()) is True and raised == ["lying down"]


# --- review fixes: recheck after a no, dropouts, cropped boxes, one alert per fall ---------------------

def fake_clock():
    t = [0.0]
    return t, FallDetector(clock=lambda: t[0])


def hold_down(d, t, seconds, step=0.2):
    """She stays down for `seconds`; returns the first suspicion (or None)."""
    end, out = t[0] + seconds, None
    while t[0] < end - 1e-9:
        t[0] += step
        out = out or d.update(perception(person(False)))
    return out


def stand_up(d, t, seconds, step=0.2):
    end = t[0] + seconds
    while t[0] < end - 1e-9:
        t[0] += step
        assert d.update(perception(person(True))) is None


def test_a_no_from_claude_allows_a_recheck_soon():
    t, d = fake_clock()
    assert hold_down(d, t, HOLD_S + 0.2) is not None     # suspected; Claude says no (no confirmed())
    assert hold_down(d, t, RECHECK_S - 1) is None        # too soon to ask again
    assert hold_down(d, t, 1.5) is not None              # still down: asks again, long before COOLDOWN_S


def test_cooldown_starts_only_after_a_confirmed_alert():
    t = [0.0]
    d = FallDetector(clock=lambda: t[0])
    answers = iter(["no, she is stretching on a mat", "yes, a woman is lying on the floor"])
    raised = []

    async def confirm(jpeg):
        return next(answers)

    current = [None]
    w = FallWatcher(lambda: current[0], lambda: b"jpeg", raised.append, confirm=confirm, detector=d)

    def step(p, dt=0.2):
        t[0] += dt
        current[0] = perception(p)       # a new object each time, like vision.latest()
        return asyncio.run(w.check_once())

    while not step(person(False)) and t[0] < RECHECK_S + HOLD_S + 2:
        pass
    assert raised == ["a woman is lying on the floor"]   # the no didn't blind it for two minutes
    alert_t = t[0]
    while t[0] < alert_t + REARM_S + 1:                  # she gets up (re-armed) ...
        assert step(person(True)) is False
    while t[0] < alert_t + COOLDOWN_S - 1:               # ... and goes down again: still cooling down
        assert step(person(False)) is False
    while t[0] < alert_t + COOLDOWN_S + 2:
        step(person(False))
    assert len(raised) == 2                              # after the cooldown it may alert again


def test_brief_dropout_keeps_the_hold():
    t, d = fake_clock()
    assert d.update(perception(person(False))) is None   # down at 0
    for dt in (0.8, 1.2):                                # pose loses her for 0.4 s (< RESET_S)
        t[0] = dt
        assert d.update(perception()) is None
    t[0] = 1.5
    assert d.update(perception(person(True))) is None    # one bad "upright" frame too
    t[0] = HOLD_S + 0.1
    assert d.update(perception(person(False))) is not None


def test_long_gap_resets_the_hold():
    t, d = fake_clock()
    d.update(perception(person(False)))                  # down at 0
    t[0] = 1.0
    d.update(perception())
    t[0] = 1.0 + RESET_S + 0.05                          # gone for longer than RESET_S
    d.update(perception())
    t[0] = 2.0
    d.update(perception(person(False)))                  # down again: the hold starts over here
    t[0] = HOLD_S + 0.1
    assert d.update(perception(person(False))) is None
    t[0] = 2.0 + HOLD_S + 0.1
    assert d.update(perception(person(False))) is not None


def test_cropped_box_is_not_lying_but_a_whole_wide_box_is():
    no_kps = lambda box: Person(box, 0.9, {})
    assert lying(no_kps(Box(0.1, 0.6, 0.9, 1.0)), 640, 360) is False    # head and shoulders cut off at the bottom
    assert lying(no_kps(Box(0.0, 0.3, 0.7, 0.6)), 640, 360) is False    # cut off at the left edge
    assert lying(no_kps(Box(0.1, 0.6, 0.9, 0.9)), 640, 360) is True     # whole box, wider than tall
    cropped_down = Person(Box(0.2, 0.75, 0.8, 1.0), 0.9, person(False).keypoints)
    assert lying(cropped_down, 640, 360) is True                         # keypoints: tilt decides, as before


def test_one_fall_gives_one_alert_until_she_gets_up():
    t, d = fake_clock()
    assert hold_down(d, t, HOLD_S + 0.2) is not None
    d.confirmed()                                        # the alert went out
    assert hold_down(d, t, COOLDOWN_S + 30) is None      # she stays down: no repeat after the cooldown
    t[0] += 0.2
    assert d.update(perception(person(True), person(False))) is None    # someone else standing doesn't re-arm
    assert hold_down(d, t, HOLD_S + 0.2) is None
    stand_up(d, t, REARM_S - 0.6)                        # up, but not for long enough
    assert hold_down(d, t, HOLD_S + 0.4) is None
    stand_up(d, t, REARM_S + 0.5)                        # really up: re-armed
    assert hold_down(d, t, HOLD_S + 0.4) is not None     # a new fall alerts again
