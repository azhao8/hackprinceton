"""VisionWorker with a fake frame source, detector and lock: no camera, no model."""

from __future__ import annotations

import threading
import time

import numpy as np

from app.vision.types import Box, Detections, Frame, Person, TargetState, TargetStatus
from app.vision.worker import Perception, VisionWorker

PERSON = Person(box=Box(0.4, 0.2, 0.6, 0.9), score=0.9)


class FakeSource:
    """Hands out `n` small frames (or forever if n is None), one per read_next()."""

    def __init__(self, n: int | None = None, delay_s: float = 0.005) -> None:
        self.n = n
        self.delay_s = delay_s
        self.i = 0
        self.started = False
        self.stopped = threading.Event()

    def start(self) -> None:
        self.started = True

    def read_next(self, timeout: float | None = 1.0) -> Frame | None:
        if self.stopped.is_set() or (self.n is not None and self.i >= self.n):
            return None
        time.sleep(self.delay_s)
        frame = Frame(t=time.monotonic(), index=self.i, image=np.zeros((48, 64, 3), np.uint8))
        self.i += 1
        return frame

    def latest(self) -> Frame | None:
        return None

    @property
    def ended(self) -> bool:
        return self.stopped.is_set() or (self.n is not None and self.i >= self.n)

    def stop(self) -> None:
        self.stopped.set()


class FakeDetector:
    def __init__(self, people: list[Person] | None = None) -> None:
        self.people = [PERSON] if people is None else people
        self.calls: list[int] = []

    def detect(self, frame: Frame) -> Detections:
        self.calls.append(frame.index)
        return Detections(frame.t, frame.index, frame.width, frame.height, list(self.people), latency_s=0.001)


class FakeLock:
    def __init__(self, engage_ok: bool = True) -> None:
        self.engage_ok = engage_ok
        self._state = TargetState(TargetStatus.IDLE)
        self.turn_rates: list[float] = []
        self.engages = 0
        self.disengages = 0

    @property
    def state(self) -> TargetState:
        return self._state

    def engage(self, detections, image) -> TargetState:
        self.engages += 1
        if self.engage_ok and detections.people:
            self._state = TargetState(TargetStatus.LOCKED, person=detections.people[0])
        else:
            self._state = TargetState(TargetStatus.IDLE)
        return self._state

    def disengage(self) -> None:
        self.disengages += 1
        self._state = TargetState(TargetStatus.IDLE)

    def update(self, detections, image, turn_rate: float = 0.0) -> TargetState:
        self.turn_rates.append(turn_rate)
        return self._state


def wait_for(cond, timeout: float = 2.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.005)
    return cond()


def test_publishes_latest_and_stops_cleanly():
    src, det = FakeSource(), FakeDetector()
    worker = VisionWorker(src, det, FakeLock(), warmup=True)
    assert worker.latest() is None
    worker.start()
    assert wait_for(lambda: (p := worker.latest()) is not None and p.frame_index >= 5)
    p = worker.latest()
    assert isinstance(p, Perception)
    assert p.people == [PERSON] and p.target.status is TargetStatus.IDLE
    assert p.fps > 0 and p.latency_s >= 0
    assert det.calls[0] == -1  # warmed up on a blank frame first
    assert worker.status == "running"

    worker.stop()
    assert not worker.alive
    assert src.stopped.is_set()
    assert worker.status == "stopped"
    assert worker.error is None
    worker.stop()  # twice is fine


def test_latest_never_blocks_while_the_detector_is_slow():
    class SlowDetector(FakeDetector):
        def detect(self, frame):
            time.sleep(0.3)
            return super().detect(frame)

    worker = VisionWorker(FakeSource(), SlowDetector(), FakeLock(), warmup=False)
    worker.start()
    try:
        start = time.monotonic()
        for _ in range(100):
            worker.latest()
        assert time.monotonic() - start < 0.05
    finally:
        worker.stop()


def test_engage_disengage_and_turn_rate():
    lock = FakeLock()
    worker = VisionWorker(FakeSource(), FakeDetector(), lock, warmup=False)
    worker.start()
    try:
        assert wait_for(lambda: worker.latest() is not None)
        seq = worker.request_engage()
        assert wait_for(lambda: worker.latest().target.status is TargetStatus.LOCKED)
        p = worker.latest()
        assert p.engaged_seq == seq and not p.engage_pending
        assert p.target.person == PERSON

        worker.set_turn_rate(0.7)
        assert wait_for(lambda: 0.7 in lock.turn_rates)

        worker.disengage()
        assert wait_for(lambda: worker.latest().target.status is TargetStatus.IDLE)
        assert lock.disengages == 1
    finally:
        worker.stop()


def test_engage_stays_pending_until_someone_is_found():
    det = FakeDetector(people=[])
    worker = VisionWorker(FakeSource(), det, FakeLock(), warmup=False)
    worker.start()
    try:
        worker.request_engage()
        assert wait_for(lambda: (p := worker.latest()) is not None and p.engage_pending)
        det.people = [PERSON]
        assert wait_for(lambda: worker.latest().target.status is TargetStatus.LOCKED)
        assert not worker.latest().engage_pending
    finally:
        worker.stop()


def test_ends_when_the_clip_ends():
    worker = VisionWorker(FakeSource(n=3), FakeDetector(), FakeLock(), warmup=False)
    worker.start()
    assert wait_for(lambda: not worker.alive)
    assert worker.latest().frame_index == 2
    assert worker.status.startswith("ended")
    worker.stop()


def test_a_crash_is_reported_not_raised():
    class Broken(FakeDetector):
        def detect(self, frame):
            raise RuntimeError("boom")

    worker = VisionWorker(FakeSource(), Broken(), FakeLock(), warmup=False)
    worker.start()
    assert wait_for(lambda: not worker.alive)
    assert isinstance(worker.error, RuntimeError)
    assert worker.status.startswith("failed")
    worker.stop()


def test_debug_view_renders_a_perception():
    from app.vision.debug_view import Hud, render
    from app.vision.types import DriveCommand

    image = np.zeros((1080, 1920, 3), np.uint8)
    frame = Frame(t=1.0, index=7, image=image)
    dets = Detections(1.0, 7, 1920, 1080, [PERSON, Person(Box(0.1, 0.3, 0.2, 0.8), 0.8)])
    p = Perception(frame, dets, TargetState(TargetStatus.LOCKED, person=PERSON), False, 1, 0.05, 14.0, 1.0)
    hud = Hud(robot="real", source="estop", skill="follow", follow=DriveCommand(0.1, -0.2, "following", 1.6),
              connected=True)
    out = render(p, hud)
    assert out.shape == (720, 1280, 3) and out.any()
    assert not image.any()  # never draws on the worker's frame
    assert render(None, Hud(vision_status="warming up detector")).any()
