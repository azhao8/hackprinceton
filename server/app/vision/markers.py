"""ArUco marker detection: printed markers tell the robot where places are (issue #55).

Each place (the medication station, the couch, ...) has a printed ArUco marker taped up
where the robot can see it; app/vision/places.py maps place names to marker ids, and
`python -m app.vision.print_markers` makes the printouts. ArUco is OpenCV's standard
fiducial marker system (cv2.aruco.ArucoDetector, OpenCV >= 4.7).

    detector = MarkerDetector()                 # DICT_4X4_50, 15 cm markers
    for m in detector.detect(frame.image):      # list[Marker], normalized coords
        print(m.id, m.cx, m.distance_m)

Distance (pinhole model): a marker whose printed black square is S meters wide, seen
s pixels wide in an image W pixels wide by a camera with horizontal field of view HFOV,
is at

    distance = f * S / s,   f = (W / 2) / tan(HFOV / 2)   (focal length in pixels)

HFOV comes from CameraGeometry.hfov_deg, which is a GUESS (67 deg, iPhone 1x camera in a
16:9 stream; see app/vision/follow.py). The side s is the LONGEST of the marker's four
edges in the image, so a marker seen at an angle (foreshortened) still reads about right.

Calibration (two minutes, needs the real camera): tape a marker to a wall, put the camera
exactly 1.00 m in front of it, facing it, and read `distance_m`. If it says d (meters),
set `focal_scale=1/d` (or, equivalently, change CameraGeometry.hfov_deg so that
tan(hfov/2) is multiplied by d; that also fixes follow.py's bearings). Check again at 2 m.
Also measure the printed black square with a ruler and pass it as `marker_size_m`
(printers scale pages). The camera must be at the resolution/zoom it streams at.
"""

from __future__ import annotations

import math
import time

import cv2
import numpy as np

from app.vision.follow import CameraGeometry
from app.vision.types import Marker

DEFAULT_DICTIONARY = "DICT_4X4_50"  # 4x4 bits: big cells, readable from far away; 50 ids is plenty
DEFAULT_MARKER_SIZE_M = 0.15  # side of the printed black square (print_markers.py makes 15 cm)
DEFAULT_MAX_WIDTH = 960  # downscale wider frames to this before detecting (speed; see detect())


class MarkerDetector:
    """Finds ArUco markers in BGR images and returns them as `Marker`s.

    dictionary: name of an OpenCV predefined dictionary (cv2.aruco.DICT_*); must match the
        printouts. marker_size_m: side of the printed black square, for distance (None = no
        distance). geometry: camera FOV for distance (default CameraGeometry(), a guess).
    max_width: frames wider than this are downscaled first (None = never). Detection costs
        grow with pixel count; at 960 px wide a 15 cm marker is still ~20 px at 5 m.
    focal_scale: calibration factor on the focal length (see the module docstring).
    """

    def __init__(
        self,
        dictionary: str = DEFAULT_DICTIONARY,
        marker_size_m: float | None = DEFAULT_MARKER_SIZE_M,
        geometry: CameraGeometry | None = None,
        *,
        max_width: int | None = DEFAULT_MAX_WIDTH,
        focal_scale: float = 1.0,
    ) -> None:
        if not hasattr(cv2.aruco, dictionary):
            raise ValueError(f"unknown ArUco dictionary {dictionary!r} (expected a cv2.aruco.DICT_* name)")
        self.dictionary_name = dictionary
        self.dictionary = cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, dictionary))
        self.marker_size_m = marker_size_m
        self.geometry = geometry if geometry is not None else CameraGeometry()
        self.max_width = max_width
        self.focal_scale = focal_scale
        self._detector = cv2.aruco.ArucoDetector(self.dictionary, cv2.aruco.DetectorParameters())
        self.last_latency_s = 0.0

    def detect(self, image_bgr: np.ndarray) -> list[Marker]:
        """Every marker of this dictionary in the image, sorted by id. Never raises on empty input."""
        t0 = time.perf_counter()
        if image_bgr is None or image_bgr.size == 0:
            return []
        gray = image_bgr if image_bgr.ndim == 2 else cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
        h, w = gray.shape[:2]
        if self.max_width is not None and w > self.max_width:
            scale = self.max_width / w
            gray = cv2.resize(gray, (self.max_width, max(1, round(h * scale))), interpolation=cv2.INTER_AREA)
            h, w = gray.shape[:2]

        corners, ids, _rejected = self._detector.detectMarkers(gray)
        markers: list[Marker] = []
        if ids is not None:
            for quad, marker_id in zip(corners, ids.ravel()):
                markers.append(self._to_marker(int(marker_id), quad.reshape(4, 2), w, h))
        markers.sort(key=lambda m: m.id)
        self.last_latency_s = time.perf_counter() - t0
        return markers

    def distance_for(self, side_px: float, image_width_px: int) -> float | None:
        """Pinhole distance (m) to a marker whose side spans `side_px` in an image this wide."""
        if self.marker_size_m is None or side_px <= 0:
            return None
        focal_px = self.focal_scale * (image_width_px / 2.0) / math.tan(math.radians(self.geometry.hfov_deg) / 2.0)
        return focal_px * self.marker_size_m / side_px

    def _to_marker(self, marker_id: int, quad: np.ndarray, w: int, h: int) -> Marker:
        edges = np.linalg.norm(quad - np.roll(quad, -1, axis=0), axis=1)
        side_px = float(edges.mean())
        center = quad.mean(axis=0)
        return Marker(
            id=marker_id,
            cx=float(center[0]) / w,
            cy=float(center[1]) / h,
            size=(side_px / w + side_px / h) / 2.0,
            distance_m=self.distance_for(float(edges.max()), w),
        )
