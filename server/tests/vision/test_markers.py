"""ArUco markers, places and the worker's marker output, on synthetic scenes: no camera.

Markers come from cv2.aruco.generateImageMarker and are pasted (with their white margin)
into a textured 1920x1080 scene at known positions, sizes and rotations, plus sensor-like
noise. With a 67 deg horizontal FOV the focal length is 960 / tan(33.5 deg) = 1449.6 px,
so a 15 cm marker is 217 px wide at 1 m and 109 px at 2 m.
"""

from __future__ import annotations

import math
import threading
import time

import cv2
import numpy as np
import pytest

from app.vision import places
from app.vision.follow import CameraGeometry
from app.vision.markers import MarkerDetector
from app.vision.types import Detections, Frame, Marker, TargetState, TargetStatus
from app.vision.worker import Perception, VisionWorker

W, H = 1920, 1080
HFOV = 67.0
SIZE_M = 0.15
FOCAL_PX = (W / 2) / math.tan(math.radians(HFOV) / 2)
DICT = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)


def side_px_at(distance_m: float) -> float:
    return FOCAL_PX * SIZE_M / distance_m


def background(seed: int = 0) -> np.ndarray:
    """A cluttered-ish room: gradient, random colored rectangles, noise."""
    rng = np.random.default_rng(seed)
    img = np.zeros((H, W, 3), np.float32)
    img += np.linspace(60, 170, W, dtype=np.float32)[None, :, None]
    for _ in range(25):
        x, y = int(rng.integers(0, W - 50)), int(rng.integers(0, H - 50))
        w, h = int(rng.integers(30, 400)), int(rng.integers(30, 300))
        img[y : y + h, x : x + w] = rng.integers(20, 235, 3)
    return img


def paste(img: np.ndarray, marker_id: int, cx: float, cy: float, side: float, angle_deg: float = 0.0) -> None:
    """Paste a marker (black square `side` px) centered at normalized (cx, cy), rotated in-plane."""
    cells = 6  # 4x4 bits + 1-cell border
    cell = 20
    patch = cv2.aruco.generateImageMarker(DICT, marker_id, cells * cell, borderBits=1)
    patch = cv2.copyMakeBorder(patch, cell, cell, cell, cell, cv2.BORDER_CONSTANT, value=255)  # quiet zone
    scale = side / (cells * cell)
    center_src = (patch.shape[1] / 2, patch.shape[0] / 2)
    m = cv2.getRotationMatrix2D(center_src, angle_deg, scale)
    m[0, 2] += cx * W - center_src[0]
    m[1, 2] += cy * H - center_src[1]
    warped = cv2.warpAffine(patch.astype(np.float32), m, (W, H), flags=cv2.INTER_LINEAR, borderValue=-1)
    mask = warped >= 0
    img[mask] = warped[mask][:, None]


def finish(img: np.ndarray, noise: float = 6.0, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed + 100)
    img = img + rng.normal(0, noise, img.shape)
    return np.clip(img, 0, 255).astype(np.uint8)


def detector(**kw) -> MarkerDetector:
    return MarkerDetector(marker_size_m=SIZE_M, geometry=CameraGeometry(hfov_deg=HFOV), **kw)


# --- detection ---


@pytest.mark.parametrize("max_width", [None, 960])
def test_detects_markers_with_ids_positions_and_sizes(max_width):
    img = background()
    specs = [(1, 0.2, 0.3, 150, 0), (2, 0.7, 0.6, 90, 8), (4, 0.5, 0.8, 60, -12), (3, 0.85, 0.2, 220, 4)]
    for mid, cx, cy, side, angle in specs:
        paste(img, mid, cx, cy, side, angle)
    found = detector(max_width=max_width).detect(finish(img))

    assert [m.id for m in found] == [1, 2, 3, 4]  # sorted by id
    by_id = {m.id: m for m in found}
    for mid, cx, cy, side, _ in specs:
        m = by_id[mid]
        assert m.cx == pytest.approx(cx, abs=0.005)
        assert m.cy == pytest.approx(cy, abs=0.005)
        assert m.size == pytest.approx((side / W + side / H) / 2, rel=0.06)


@pytest.mark.parametrize("distance_m", [0.7, 1.0, 2.0, 3.0])
@pytest.mark.parametrize("max_width", [None, 960])
def test_distance_from_known_size_and_fov(distance_m, max_width):
    img = background(seed=1)
    paste(img, 1, 0.45, 0.5, side_px_at(distance_m), angle_deg=5)
    (m,) = detector(max_width=max_width).detect(finish(img, seed=1))
    assert m.id == 1
    assert m.distance_m == pytest.approx(distance_m, rel=0.06)


def test_marker_seen_at_an_angle_still_reads_about_the_right_distance():
    """Turned ~40 deg about the vertical axis: the longest edge keeps the distance close."""
    img = background(seed=2)
    patch = cv2.aruco.generateImageMarker(DICT, 2, 120, borderBits=1)
    patch = cv2.copyMakeBorder(patch, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)
    s = side_px_at(1.5)
    cx, cy = 0.6 * W, 0.5 * H
    half_w = 0.77 * s / 2  # cos(40 deg) foreshortening
    margin = 20 / 120  # quiet zone as a fraction of the black square
    src = np.float32([[0, 0], [160, 0], [160, 160], [0, 160]])
    left, right = 1.04 * s, 0.96 * s  # near edge a bit taller than the far one
    lm, rm = left * margin, right * margin
    wm = 2 * half_w * margin
    dst = np.float32(
        [
            [cx - half_w - wm, cy - left / 2 - lm],
            [cx + half_w + wm, cy - right / 2 - rm],
            [cx + half_w + wm, cy + right / 2 + rm],
            [cx - half_w - wm, cy + left / 2 + lm],
        ]
    )
    warped = cv2.warpPerspective(
        patch.astype(np.float32), cv2.getPerspectiveTransform(src, dst), (W, H), borderValue=-1
    )
    img[warped >= 0] = warped[warped >= 0][:, None]
    (m,) = detector().detect(finish(img, seed=2))
    assert m.id == 2
    assert m.distance_m == pytest.approx(1.5, rel=0.1)


def test_no_false_positives_on_noise_or_clutter():
    rng = np.random.default_rng(7)
    noise = rng.integers(0, 256, (H, W, 3), dtype=np.uint8)
    det = detector()
    assert det.detect(noise) == []
    for seed in range(5):
        assert det.detect(finish(background(seed=seed), seed=seed)) == []
    assert det.detect(np.zeros((H, W, 3), np.uint8)) == []
    assert det.detect(np.zeros((0, 0, 3), np.uint8)) == []


def test_no_distance_without_a_known_size():
    img = background()
    paste(img, 3, 0.5, 0.5, 150)
    (m,) = MarkerDetector(marker_size_m=None).detect(finish(img))
    assert m.id == 3 and m.distance_m is None


def test_focal_scale_calibrates_distance():
    img = background()
    paste(img, 1, 0.5, 0.5, side_px_at(1.0))
    image = finish(img)
    d0 = detector().detect(image)[0].distance_m
    d1 = detector(focal_scale=1.2).detect(image)[0].distance_m
    assert d1 == pytest.approx(1.2 * d0)


def test_unknown_dictionary_is_rejected():
    with pytest.raises(ValueError):
        MarkerDetector(dictionary="DICT_NOPE")


def test_fast_enough_for_every_frame_at_1080p():
    img = background(seed=3)
    for mid, cx in ((1, 0.2), (2, 0.5), (3, 0.8)):
        paste(img, mid, cx, 0.5, 100)
    image = finish(img, seed=3)
    det = detector()
    det.detect(image)
    n = 10
    t0 = time.perf_counter()
    for _ in range(n):
        assert len(det.detect(image)) == 3
    per_frame_ms = (time.perf_counter() - t0) / n * 1000
    print(f"marker detection: {per_frame_ms:.1f} ms per 1920x1080 frame")
    assert per_frame_ms < 50  # generous for slow CI; ~5 ms on an M-series laptop


# --- worker ---


class FakeSource:
    def __init__(self) -> None:
        self.i = 0
        self.stopped = threading.Event()

    def start(self) -> None:
        pass

    def read_next(self, timeout=1.0):
        if self.stopped.is_set():
            return None
        time.sleep(0.005)
        self.i += 1
        return Frame(t=time.monotonic(), index=self.i - 1, image=np.zeros((48, 64, 3), np.uint8))

    def latest(self):
        return None

    @property
    def ended(self) -> bool:
        return self.stopped.is_set()

    def stop(self) -> None:
        self.stopped.set()


class FakeDetector:
    def detect(self, frame):
        return Detections(frame.t, frame.index, frame.width, frame.height, [])


class FakeLock:
    _state = TargetState(TargetStatus.IDLE)

    @property
    def state(self):
        return self._state

    def engage(self, detections, image):
        return self._state

    def disengage(self):
        pass

    def update(self, detections, image, turn_rate=0.0):
        return self._state


class FakeMarkers:
    def __init__(self, markers=(), fail=False) -> None:
        self.markers = list(markers)
        self.fail = fail
        self.calls = 0

    def detect(self, image):
        self.calls += 1
        if self.fail:
            raise RuntimeError("boom")
        return list(self.markers)


def run_worker(**kw) -> tuple[Perception, VisionWorker]:
    worker = VisionWorker(FakeSource(), FakeDetector(), FakeLock(), warmup=False, **kw)
    worker.start()
    try:
        end = time.monotonic() + 2.0
        while time.monotonic() < end:
            p = worker.latest()
            if p is not None and p.frame_index >= 3:
                return p, worker
            time.sleep(0.005)
        raise AssertionError(f"worker published nothing: {worker.status}")
    finally:
        worker.stop()


def test_worker_publishes_markers():
    mk = Marker(id=1, cx=0.3, cy=0.4, size=0.1, distance_m=1.2)
    fake = FakeMarkers([mk])
    p, _ = run_worker(marker_detector=fake)
    assert p.markers == (mk,)
    assert fake.calls >= 4


def test_worker_with_markers_disabled_publishes_none():
    p, _ = run_worker(marker_detector=None)
    assert p.markers == ()


def test_worker_default_marker_detector_runs_on_real_frames():
    p, worker = run_worker()
    assert p.markers == ()  # blank frames
    assert isinstance(worker._markers, MarkerDetector)


def test_a_failing_marker_detector_does_not_stop_tracking():
    p, worker = run_worker(marker_detector=FakeMarkers(fail=True))
    assert p.markers == () and worker.error is None


def test_perception_markers_default_keeps_old_constructors_working():
    frame = Frame(0.0, 0, np.zeros((4, 4, 3), np.uint8))
    p = Perception(frame, Detections(0.0, 0, 4, 4, []), TargetState(TargetStatus.IDLE), False, 0, 0.0, 0.0, 0.0)
    assert p.markers == ()


# --- places ---


def test_default_places_and_reverse_lookup():
    env: dict[str, str] = {}
    assert places.marker_for("station", env) == 1
    assert places.marker_for("couch", env) == 2
    assert places.marker_for("door", env) == 3
    assert places.marker_for("kitchen", env) == 4
    assert places.place_for(1, env) == "station"
    assert places.place_for(4, env) == "kitchen"
    assert places.place_for(42, env) is None
    assert places.marker_for("garage", env) is None


@pytest.mark.parametrize(
    "said", ["medication station", "Medication Station", "PILLS", "the pills", "  medication   station "]
)
def test_aliases_are_case_insensitive(said):
    assert places.marker_for(said, {}) == 1
    assert places.canonical(said, {}) == "station"


def test_env_override_replaces_the_mapping():
    env = {"PLACES": "station=7, couch=2,Bedroom=5"}
    assert places.places(env) == {"station": 7, "couch": 2, "bedroom": 5}
    assert places.marker_for("pills", env) == 7
    assert places.marker_for("bedroom", env) == 5
    assert places.place_for(5, env) == "bedroom"
    assert places.marker_for("kitchen", env) is None  # not in the override
    assert places.marker_for("front door", env) is None  # alias of a place that isn't mapped


def test_env_override_from_os_environ(monkeypatch):
    monkeypatch.setenv("PLACES", "door=9")
    assert places.marker_for("front door") == 9
    monkeypatch.delenv("PLACES")
    assert places.marker_for("front door") == 3


def test_bad_env_override_raises():
    with pytest.raises(ValueError):
        places.places({"PLACES": "station"})
    with pytest.raises(ValueError):
        places.places({"PLACES": "station=one"})


# --- printable markers ---


def test_printed_markers_are_detectable_and_the_right_size(tmp_path):
    from app.vision import print_markers

    page = print_markers.marker_page(2, "couch", size_cm=15.0, dpi=300)
    assert page.shape == (3300, 2550)  # US Letter at 300 dpi
    found = MarkerDetector(max_width=None).detect(cv2.cvtColor(page, cv2.COLOR_GRAY2BGR))
    assert [m.id for m in found] == [2]
    side_px = found[0].size * 2 / (1 / page.shape[1] + 1 / page.shape[0])
    assert side_px / 300 * 2.54 == pytest.approx(15.0, abs=0.1)

    files = print_markers.write_markers(tmp_path, mapping={"station": 1, "couch": 2})
    names = sorted(f.name for f in files)
    assert names == ["1-station.png", "2-couch.png", "markers.pdf"]
