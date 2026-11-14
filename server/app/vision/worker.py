"""Vision worker: frame source -> person detector -> target lock, on its own thread.

YOLO is blocking (tens of ms per frame, ~7.5 s for the first GPU call), so it can't run in
the server's asyncio loop (open question T-7). This thread does the blocking work and hands
over only its newest result, an immutable `Perception`, through `latest()`. Readers never
wait on the detector: they get whatever was published last.

    worker = VisionWorker(open_source("0"), YoloPoseDetector(), TargetLock())
    worker.start()                  # returns at once; the thread opens the camera and warms up
    worker.request_engage()         # lock onto the close person nearest the center
    p = worker.latest()             # Perception | None, from any thread
    worker.set_turn_rate(w)         # the robot's commanded turn, for the lock's ego-motion
    worker.stop()

Engage and disengage are requests: the worker applies them on its next frame, because
TargetLock isn't thread-safe and only this thread touches it. An engage request stays
pending until the lock finds someone (`Perception.engage_pending`); a later disengage
replaces it.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

import numpy as np

from app.vision.frames import FrameSource
from app.vision.types import Detections, Frame, Person, TargetState, TargetStatus

log = logging.getLogger(__name__)

WARMUP_SHAPE = (1080, 1920, 3)  # the first GPU call is slow (~7.5 s); pay it on a blank 1080p frame
STOP_TIMEOUT_S = 5.0
FPS_SMOOTHING = 0.1  # EMA weight of each new frame interval


class Detector(Protocol):
    def detect(self, frame: Frame) -> Detections: ...


class Lock(Protocol):
    """What the worker needs from app.vision.tracking.TargetLock."""

    @property
    def state(self) -> TargetState: ...

    def engage(self, detections: Detections, image: np.ndarray) -> TargetState: ...

    def disengage(self) -> None: ...

    def update(self, detections: Detections, image: np.ndarray, turn_rate: float = 0.0) -> TargetState: ...


@dataclass(frozen=True)
class Perception:
    """One processed frame: everything a skill or the debug view needs, never mutated."""

    frame: Frame  # the image the detector saw (also what the debug view draws on)
    detections: Detections
    target: TargetState
    engage_pending: bool  # an engage request hasn't found anyone yet
    engaged_seq: int  # sequence number of the last engage request that locked on (0 = none)
    latency_s: float  # capture to publish (meaningful for live sources)
    fps: float  # frames processed per second (smoothed)
    published_at: float  # worker clock (time.monotonic) when this was published

    @property
    def frame_t(self) -> float:
        return self.frame.t

    @property
    def frame_index(self) -> int:
        return self.frame.index

    @property
    def people(self) -> list[Person]:
        return self.detections.people

    @property
    def detect_s(self) -> float:
        return self.detections.latency_s


class VisionWorker:
    """Runs the vision pipeline on a background thread and publishes the newest Perception."""

    def __init__(
        self,
        source: FrameSource,
        detector: Detector,
        lock: Lock,
        *,
        warmup: bool = True,
        read_timeout_s: float = 0.5,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._source = source
        self._detector = detector
        self._lock = lock
        self._warmup = warmup
        self._read_timeout_s = read_timeout_s
        self._clock = clock

        self._mutex = threading.Lock()
        self._latest: Perception | None = None
        self._turn_rate = 0.0
        self._seq = 0  # bumped by every engage/disengage request
        self._pending: tuple[str, int] | None = None  # ("engage" | "disengage", seq)
        self._engaged_seq = 0
        self._status = "not started"
        self._error: BaseException | None = None

        self._stopping = threading.Event()
        self._thread: threading.Thread | None = None

    # --- control (any thread) ---

    def start(self) -> None:
        """Start the thread. Returns at once; opening the source and warm-up happen on the thread."""
        if self._thread is not None:
            return
        self._status = "starting"
        self._thread = threading.Thread(target=self._run, name="vision-worker", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = STOP_TIMEOUT_S) -> None:
        """Stop the thread and release the source. Safe to call twice."""
        self._stopping.set()
        try:
            self._source.stop()  # unblocks read_next() at once
        except Exception:
            log.exception("vision worker: stopping the frame source failed")
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout)
            if self._thread.is_alive():
                log.warning("vision worker didn't stop within %.1fs (stuck in the detector?)", timeout)

    def latest(self) -> Perception | None:
        """The newest Perception, or None before the first processed frame."""
        with self._mutex:
            return self._latest

    def request_engage(self) -> int:
        """Ask the lock to engage on the next frames (until it finds someone). Returns its sequence number."""
        with self._mutex:
            self._seq += 1
            self._pending = ("engage", self._seq)
            return self._seq

    def disengage(self) -> None:
        """Forget the target (applied on the next frame). Cancels a pending engage."""
        with self._mutex:
            self._seq += 1
            self._pending = ("disengage", self._seq)

    def set_turn_rate(self, w: float) -> None:
        """The robot's current commanded turn (rad/s, + left), so the lock can allow for ego-motion."""
        with self._mutex:
            self._turn_rate = float(w)

    @property
    def status(self) -> str:
        """Human-readable: starting, opening source, warming up detector, running, ended, failed: ..."""
        return self._status

    @property
    def error(self) -> BaseException | None:
        """What stopped the thread, if it crashed."""
        return self._error

    @property
    def alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # --- the thread ---

    def _run(self) -> None:
        try:
            self._status = "opening source"
            self._source.start()
            if self._warmup and not self._stopping.is_set():
                self._status = "warming up detector"
                t0 = time.perf_counter()
                self._detector.detect(Frame(t=0.0, index=-1, image=np.zeros(WARMUP_SHAPE, dtype=np.uint8)))
                log.info("vision worker: detector warm-up took %.1fs", time.perf_counter() - t0)
            self._status = "running"
            self._loop()
            self._status = "stopped" if self._stopping.is_set() else "ended (no more frames)"
        except Exception as e:
            if self._stopping.is_set():
                self._status = "stopped"  # e.g. stop() during start(): not an error
            else:
                log.exception("vision worker crashed")
                self._error = e
                self._status = f"failed: {e}"
        finally:
            try:
                self._source.stop()
            except Exception:
                log.exception("vision worker: stopping the frame source failed")

    def _loop(self) -> None:
        fps = 0.0
        last_done: float | None = None
        while not self._stopping.is_set():
            frame = self._source.read_next(timeout=self._read_timeout_s)
            if frame is None:
                if self._source.ended:
                    return
                continue
            detections = self._detector.detect(frame)
            target, engage_pending = self._apply_lock(detections, frame.image)

            now = self._clock()
            if last_done is not None and now > last_done:
                inst = 1.0 / (now - last_done)
                fps = inst if fps == 0.0 else (1 - FPS_SMOOTHING) * fps + FPS_SMOOTHING * inst
            last_done = now
            perception = Perception(
                frame=frame,
                detections=detections,
                target=target,
                engage_pending=engage_pending,
                engaged_seq=self._engaged_seq,
                latency_s=max(0.0, now - frame.t),
                fps=fps,
                published_at=now,
            )
            with self._mutex:
                self._latest = perception

    def _apply_lock(self, detections: Detections, image: np.ndarray) -> tuple[TargetState, bool]:
        """Apply a pending engage/disengage, then track. Returns (state, engage still pending)."""
        with self._mutex:
            pending = self._pending
            turn_rate = self._turn_rate
        lock = self._lock

        if pending is not None and pending[0] == "disengage":
            lock.disengage()
            self._clear_pending(pending)
            pending = None

        if pending is not None and pending[0] == "engage":
            state = lock.engage(detections, image)
            if state.status is not TargetStatus.IDLE:
                self._engaged_seq = pending[1]
                self._clear_pending(pending)
                return state, False
            return state, True

        if lock.state.status is TargetStatus.IDLE:
            return lock.state, False
        return lock.update(detections, image, turn_rate=turn_rate), False

    def _clear_pending(self, handled: tuple[str, int]) -> None:
        """Drop the request we just handled, unless a newer one arrived meanwhile."""
        with self._mutex:
            if self._pending == handled:
                self._pending = None
