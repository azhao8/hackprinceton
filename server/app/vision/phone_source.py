"""The robot's phone as a frame source: the phone page POSTs JPEG frames to the server's API
(`/frame`), and vision reads them like any other camera (Alex's design: the phone is the robot's
eye, the server does the seeing).

Like the camera source, it keeps only the newest frame. If no frame has arrived for a while, read
calls just time out; the source doesn't end, because the phone may reconnect (a page reload).
"""

from __future__ import annotations

import logging
import threading
import time

import cv2
import numpy as np

from app.vision.frames import FrameSource, _NewestFrame
from app.vision.types import Frame

log = logging.getLogger(__name__)

MAX_JPEG_BYTES = 2_000_000


class PhoneFrameSource(FrameSource):
    def __init__(self, clock=time.monotonic) -> None:
        self._slot = _NewestFrame()
        self._clock = clock
        self._index = 0
        self._lock = threading.Lock()
        self._stopped = False
        self.received = 0
        self.last_at: float | None = None

    def start(self) -> None:
        pass  # frames arrive through push_jpeg(); nothing to open

    def push_jpeg(self, data: bytes) -> bool:
        """A frame from the phone. Returns False (and drops it) if it isn't a decodable image."""
        if self._stopped or not data or len(data) > MAX_JPEG_BYTES:
            return False
        image = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            return False
        with self._lock:
            frame = Frame(t=self._clock(), index=self._index, image=image)
            self._index += 1
        self._slot.put(frame)
        self.received += 1
        self.last_at = frame.t
        return True

    def age(self) -> float | None:
        """Seconds since the last frame, None if none yet."""
        return None if self.last_at is None else self._clock() - self.last_at

    def latest(self) -> Frame | None:
        return self._slot.latest()

    def read_next(self, timeout: float | None = 1.0) -> Frame | None:
        return self._slot.next(timeout)

    def stop(self) -> None:
        self._stopped = True
        self._slot.finish()

    @property
    def ended(self) -> bool:
        return self._stopped
