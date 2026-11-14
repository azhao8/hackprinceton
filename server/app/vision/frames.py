"""Frame sources: the live camera or a recorded clip, behind one interface.

Vision is slower than the camera, so a live source keeps ONLY the newest frame:
a background thread grabs continuously and overwrites a single slot, and the
consumer always gets the freshest image (older ones are dropped). This is the
usual "threaded latest-frame" pattern for OpenCV capture; reading
cv2.VideoCapture directly from a slow loop would instead hand out stale,
buffered frames.

Live loop (camera, or a clip played like a camera):

    with open_source("0", rotate="right") as src:   # camera index 0
        while True:
            frame = src.read_next(timeout=1.0)
            if frame is None:
                if src.ended:
                    break                            # video over / camera gone
                continue                             # timed out; try again
            ...

Offline evaluation (every frame, in order, Frame.t = index / fps):

    with VideoFileSource("clip.mp4", realtime=False) as src:
        while (frame := src.read_next()) is not None:
            ...
"""

from __future__ import annotations

import logging
import subprocess
import sys
import threading
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Self

import cv2
import numpy as np

from app.vision.types import Frame

log = logging.getLogger(__name__)

Rotate = Literal["left", "right", "180"]

# "left" turns the picture a quarter turn counter-clockwise, "right" clockwise.
_ROTATIONS: dict[str, int] = {
    "left": cv2.ROTATE_90_COUNTERCLOCKWISE,
    "right": cv2.ROTATE_90_CLOCKWISE,
    "180": cv2.ROTATE_180,
}

DEFAULT_FPS = 30.0  # used when a video file doesn't report its frame rate
STOP_TIMEOUT_S = 3.0  # how long stop() waits for the capture thread

CAMERA_PERMISSION_HELP = (
    "On macOS, the app that runs Python (Terminal, iTerm, VS Code, ...) needs camera "
    "permission: System Settings > Privacy & Security > Camera, turn that app on, then quit "
    "and reopen it. Also check the index: list_cameras() shows which indexes open, and they "
    "can shift when the iPhone (Continuity Camera) connects."
)


class FrameSourceError(RuntimeError):
    """A camera or video file couldn't be opened or read."""


class FrameSource(ABC):
    """Where frames come from: a camera or a video file.

    Call start() (or use `with`), then read_next() for a processing loop or
    latest() to peek. read_next() is meant for ONE consumer (it remembers what
    it returned); any number of others may call latest().
    """

    @abstractmethod
    def start(self) -> None:
        """Open the camera or file and begin producing frames. Raises if it can't open."""

    @abstractmethod
    def latest(self) -> Frame | None:
        """The newest frame so far (may repeat between calls); None before the first one."""

    @abstractmethod
    def read_next(self, timeout: float | None = 1.0) -> Frame | None:
        """The newest frame newer than the last one this method returned.

        Waits up to `timeout` seconds (None waits forever). Returns None on
        timeout, at the end of a video, or after stop(): check `ended` to tell
        them apart.
        """

    @abstractmethod
    def stop(self) -> None:
        """Stop producing frames and release the camera or file. Safe to call twice."""

    @property
    @abstractmethod
    def ended(self) -> bool:
        """True once no more frames will come (video over, camera lost, or stopped)."""

    def __enter__(self) -> Self:
        self.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.stop()


def default_capture(index: int) -> Any:
    """cv2.VideoCapture for a camera index: AVFoundation on macOS, OpenCV's default elsewhere."""
    backend = cv2.CAP_AVFOUNDATION if sys.platform == "darwin" else cv2.CAP_ANY
    return cv2.VideoCapture(index, backend)


CaptureFactory = Callable[[int], Any]  # index -> object with cv2.VideoCapture's methods


def _check_rotate(rotate: object) -> None:
    if rotate is not None and rotate not in _ROTATIONS:
        raise ValueError(f"rotate must be None, 'left', 'right' or '180', not {rotate!r}")


class _NewestFrame:
    """Thread-safe slot that holds only the newest frame."""

    def __init__(self) -> None:
        self._cond = threading.Condition()
        self._frame: Frame | None = None
        self._returned = -1  # index of the last frame next() returned
        self._done = False

    def put(self, frame: Frame) -> None:
        with self._cond:
            self._frame = frame
            self._cond.notify_all()

    def finish(self) -> None:
        with self._cond:
            self._done = True
            self._cond.notify_all()

    @property
    def done(self) -> bool:
        return self._done

    def latest(self) -> Frame | None:
        return self._frame

    def next(self, timeout: float | None) -> Frame | None:
        with self._cond:
            def fresh() -> bool:
                return self._frame is not None and self._frame.index > self._returned

            # A frame that arrived just before the end is still handed out.
            self._cond.wait_for(lambda: fresh() or self._done, timeout)
            if not fresh():
                return None
            assert self._frame is not None
            self._returned = self._frame.index
            return self._frame


class _CaptureSource(FrameSource):
    """Shared plumbing: subclasses open a capture and produce (t, image) pairs.

    Threaded: a background thread calls _grab() in a loop and keeps only the
    newest frame. Not threaded: read_next() calls _grab() directly.
    """

    def __init__(self, rotate: Rotate | None, name: str, threaded: bool) -> None:
        _check_rotate(rotate)
        self.rotate = rotate
        self._name = name
        self._threaded = threaded
        self._cap: Any = None
        self._slot = _NewestFrame()
        self._stopping = threading.Event()
        self._thread: threading.Thread | None = None
        self._started = False
        self._count = 0  # Frame.index of the next frame

    @abstractmethod
    def _open(self) -> None:
        """Set self._cap or raise."""

    @abstractmethod
    def _grab(self) -> tuple[float, np.ndarray] | None:
        """The next (t, BGR image), or None when there are no more frames."""

    def _publish(self, t: float, image: np.ndarray) -> Frame:
        if self.rotate is not None:
            image = cv2.rotate(image, _ROTATIONS[self.rotate])
        frame = Frame(t=t, index=self._count, image=image)
        self._count += 1
        self._slot.put(frame)
        return frame

    def start(self) -> None:
        if self._stopping.is_set():
            raise RuntimeError(f"{self._name} was stopped; make a new source")
        if self._started:
            return
        self._open()
        self._started = True
        if self._threaded:
            self._thread = threading.Thread(target=self._run, name=self._name, daemon=True)
            self._thread.start()

    def _run(self) -> None:
        try:
            while not self._stopping.is_set():
                item = self._grab()
                if item is None:
                    break
                self._publish(*item)
        except Exception:
            log.exception("%s: capture thread crashed", self._name)
        finally:
            self._slot.finish()
            self._release()  # the thread owns the capture, so it releases it

    def _release(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    def latest(self) -> Frame | None:
        return self._slot.latest()

    def read_next(self, timeout: float | None = 1.0) -> Frame | None:
        if not self._started:
            raise RuntimeError(f"{self._name}: call start() first (or use `with`)")
        if self._stopping.is_set():
            return None
        if self._threaded:
            return self._slot.next(timeout)
        if self._slot.done:
            return None
        item = self._grab()
        if item is None:
            self._slot.finish()
            self._release()
            return None
        return self._publish(*item)

    def stop(self) -> None:
        self._stopping.set()
        self._slot.finish()
        if self._thread is not None:
            self._thread.join(timeout=STOP_TIMEOUT_S)
            if self._thread.is_alive():
                log.warning("%s: capture thread didn't stop within %.1fs", self._name, STOP_TIMEOUT_S)
        else:
            self._release()

    @property
    def ended(self) -> bool:
        return self._slot.done


class CameraSource(_CaptureSource):
    """A live camera by OpenCV index; always serves the newest frame.

    `width`/`height` are requests; the driver picks the nearest mode it has, so
    read the real size from Frame.width/height. Frame.t is time.monotonic() when
    the frame was grabbed. `capture_factory` (index -> VideoCapture-like) lets
    tests use a fake instead of a real camera.
    """

    OPEN_TIMEOUT_S = 5.0  # start() fails if no first frame within this
    FAIL_AFTER_S = 2.0  # the source ends after this long without a frame

    def __init__(
        self,
        index: int,
        rotate: Rotate | None = None,
        width: int | None = None,
        height: int | None = None,
        *,
        capture_factory: CaptureFactory | None = None,
    ) -> None:
        super().__init__(rotate, name=f"CameraSource-{index}", threaded=True)
        self.index = index
        self.width = width
        self.height = height
        self._factory = capture_factory

    def _open(self) -> None:
        factory = self._factory or default_capture  # looked up now, so tests can patch it
        cap = factory(self.index)
        if not cap.isOpened():
            cap.release()
            raise FrameSourceError(f"Could not open camera {self.index}. {CAMERA_PERMISSION_HELP}")
        if self.width:
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        if self.height:
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        self._cap = cap
        # Read the first frame here so a camera that opens but never delivers
        # (one way a missing permission can show up) fails loudly in start().
        first = self._grab(give_up_after=self.OPEN_TIMEOUT_S)
        if first is None:
            self._release()
            raise FrameSourceError(
                f"Camera {self.index} opened but sent no frame within {self.OPEN_TIMEOUT_S:.0f}s. "
                f"{CAMERA_PERMISSION_HELP}"
            )
        self._publish(*first)

    def _grab(self, give_up_after: float | None = None) -> tuple[float, np.ndarray] | None:
        give_up_after = self.FAIL_AFTER_S if give_up_after is None else give_up_after
        failing_since: float | None = None
        while not self._stopping.is_set():
            if self._cap.grab():
                t = time.monotonic()  # stamp at grab, before decoding
                ok, image = self._cap.retrieve()
                if ok and image is not None:
                    return t, image
            now = time.monotonic()
            failing_since = now if failing_since is None else failing_since
            if now - failing_since > give_up_after:
                log.error("%s: no frame for %.1fs; giving up", self._name, give_up_after)
                return None
            self._stopping.wait(0.01)
        return None


class VideoFileSource(_CaptureSource):
    """Plays a recorded clip through the FrameSource interface.

    realtime=True behaves like a camera: frames are released at the file's fps
    by a background thread, a slow consumer misses frames (Frame.index skips),
    and Frame.t is time.monotonic().

    realtime=False is for offline evaluation: no thread, read_next() returns
    every frame in order (its timeout is ignored), and Frame.t = index / fps so
    downstream controllers behave the same on every run.

    loop=True starts over at the end; Frame.index and Frame.t keep counting up.
    `fps` is known after start().
    """

    def __init__(
        self,
        path: str | Path,
        realtime: bool = True,
        loop: bool = False,
        rotate: Rotate | None = None,
    ) -> None:
        self.path = Path(path)
        super().__init__(rotate, name=f"VideoFileSource-{self.path.name}", threaded=realtime)
        self.realtime = realtime
        self.loop = loop
        self.fps: float | None = None
        self._t0 = 0.0

    def _open(self) -> None:
        if not self.path.is_file():
            raise FileNotFoundError(f"No video file at {self.path}")
        cap = cv2.VideoCapture(str(self.path))
        if not cap.isOpened():
            cap.release()
            raise FrameSourceError(f"OpenCV couldn't open {self.path} as a video")
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
        if not fps > 0:  # also catches NaN
            log.warning("%s reports no fps; assuming %.0f", self.path, DEFAULT_FPS)
            fps = DEFAULT_FPS
        self.fps = fps
        self._cap = cap
        self._t0 = time.monotonic()

    def _grab(self) -> tuple[float, np.ndarray] | None:
        ok, image = self._cap.read()
        if not ok and self.loop:
            self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ok, image = self._cap.read()
        if not ok or image is None:
            return None
        assert self.fps is not None
        if not self.realtime:
            return self._count / self.fps, image
        due = self._t0 + self._count / self.fps
        if self._stopping.wait(max(0.0, due - time.monotonic())):
            return None  # stop() was called while waiting
        return time.monotonic(), image


@dataclass(frozen=True)
class CameraInfo:
    index: int  # OpenCV camera index
    width: int  # pixels of the default mode
    height: int


def list_cameras(max_index: int = 5, capture_factory: CaptureFactory | None = None) -> list[CameraInfo]:
    """OpenCV camera indexes 0 .. max_index-1 that open, with their default resolution.

    OpenCV can't report camera names; macos_camera_names() gives the names, but
    OpenCV's index order isn't guaranteed to match that list, so look at a
    frame to be sure which camera is which. Opening a camera may briefly turn
    on its light.
    """
    factory = capture_factory or default_capture
    found = []
    for index in range(max_index):
        cap = factory(index)
        try:
            if not cap.isOpened():
                continue
            ok, image = cap.read()
            if ok and image is not None:
                height, width = image.shape[:2]
            else:
                width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            found.append(CameraInfo(index, width, height))
        finally:
            cap.release()
    return found


def macos_camera_names() -> list[str]:
    """Camera names macOS reports (`system_profiler SPCameraDataType`), in its order.

    Empty off macOS or if system_profiler fails. OpenCV's index order is NOT
    guaranteed to match this order (and indexes can shift when the iPhone
    connects), so treat it as a hint, not a mapping.
    """
    if sys.platform != "darwin":
        return []
    try:
        result = subprocess.run(
            ["system_profiler", "SPCameraDataType"],
            capture_output=True, text=True, timeout=15, check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    return parse_camera_names(result.stdout)


def parse_camera_names(text: str) -> list[str]:
    """Device names from system_profiler output: lines indented exactly 4 spaces ending in ':'."""
    names = []
    for line in text.splitlines():
        line = line.rstrip()
        if line.startswith("    ") and not line.startswith("     ") and line.endswith(":"):
            names.append(line.strip()[:-1])
    return names


def open_source(spec: str, **kw: Any) -> FrameSource:
    """A camera index ("0", "1", ...) -> CameraSource; anything else -> VideoFileSource path.

    Extra keyword arguments go to that class. The source isn't started yet: use
    `with open_source(...) as src:` or call start().
    """
    text = str(spec).strip()
    if text.isascii() and text.isdigit():
        return CameraSource(int(text), **kw)
    return VideoFileSource(text, **kw)
