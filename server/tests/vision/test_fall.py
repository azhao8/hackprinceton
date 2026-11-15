"""Possible-fall detection: pose on every frame, Claude confirms, then the alert."""

import asyncio
import types

import numpy as np

from app.vision.fall import FallDetector, FallWatcher, HOLD_S, torso_tilt_deg
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
