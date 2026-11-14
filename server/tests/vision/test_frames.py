"""Tests for app.vision.frames. They never open a real camera: cameras are fakes."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import cv2
import numpy as np
import pytest

from app.vision import frames
from app.vision.frames import (
    CameraInfo,
    CameraSource,
    FrameSource,
    FrameSourceError,
    VideoFileSource,
    list_cameras,
    open_source,
    parse_camera_names,
)

W, H = 64, 48
BITS = 8  # each frame shows its index in binary: 8 vertical stripes, white = 1
STRIPE = W // BITS


def encode(i: int) -> np.ndarray:
    image = np.zeros((H, W, 3), np.uint8)
    for k in range(BITS):
        if i >> k & 1:
            image[:, k * STRIPE:(k + 1) * STRIPE] = 255
    return image


def decode(image: np.ndarray) -> int:
    """Index drawn by encode(); stripe centers only, so mp4v blur at the edges doesn't matter."""
    gray = image.mean(axis=2)
    return sum(1 << k for k in range(BITS) if gray[:, k * STRIPE + 2:(k + 1) * STRIPE - 2].mean() > 127)


def make_video(path: Path, n: int, fps: float) -> Path:
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (W, H))
    assert writer.isOpened(), "this OpenCV build can't write mp4v"
    for i in range(n):
        writer.write(encode(i))
    writer.release()
    return path


@pytest.fixture(scope="module")
def clip(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """30 frames at 20 fps, for offline tests."""
    return make_video(tmp_path_factory.mktemp("video") / "clip.mp4", n=30, fps=20.0)


@pytest.fixture(scope="module")
def fast_clip(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """30 frames at 60 fps (0.5 s), so realtime tests stay fast."""
    return make_video(tmp_path_factory.mktemp("video") / "fast.mp4", n=30, fps=60.0)


@pytest.fixture(autouse=True)
def no_real_camera(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(index: int) -> None:
        raise AssertionError(f"a test tried to open real camera {index}")

    monkeypatch.setattr(frames, "default_capture", refuse)


def read_all(src: FrameSource, slow_s: float = 0.0, deadline_s: float = 5.0) -> list:
    """read_next() until the source ends, sleeping `slow_s` after each frame."""
    got = []
    deadline = time.monotonic() + deadline_s
    while time.monotonic() < deadline:
        frame = src.read_next(timeout=1.0)
        if frame is None:
            if src.ended:
                return got
            continue
        got.append(frame)
        time.sleep(slow_s)
    raise AssertionError("source never ended")


# ---- offline video -------------------------------------------------------------------------


def test_offline_returns_every_frame_in_order_then_ends(clip: Path) -> None:
    with VideoFileSource(clip, realtime=False) as src:
        assert isinstance(src, FrameSource)
        assert src.fps == pytest.approx(20.0)
        assert not src.ended
        got = []
        while (frame := src.read_next()) is not None:
            got.append(frame)
        assert src.ended
        assert src.read_next() is None
        assert src.latest() is got[-1]

    assert [f.index for f in got] == list(range(30))
    assert [decode(f.image) for f in got] == list(range(30))
    assert [f.t for f in got] == pytest.approx([i / 20.0 for i in range(30)])
    assert got[0].image.shape == (H, W, 3) and got[0].image.dtype == np.uint8


def test_offline_loop_keeps_counting(clip: Path) -> None:
    with VideoFileSource(clip, realtime=False, loop=True) as src:
        got = [src.read_next() for _ in range(70)]
        assert not src.ended

    assert [f.index for f in got] == list(range(70))
    assert [decode(f.image) for f in got] == [i % 30 for i in range(70)]
    assert got[-1].t == pytest.approx(69 / 20.0)


@pytest.mark.parametrize(
    ("rotate", "shape"),
    [(None, (H, W, 3)), ("left", (W, H, 3)), ("right", (W, H, 3)), ("180", (H, W, 3))],
)
def test_rotate_changes_shape(clip: Path, rotate: str | None, shape: tuple) -> None:
    with VideoFileSource(clip, realtime=False, rotate=rotate) as src:
        frame = src.read_next()
    assert frame is not None and frame.image.shape == shape
    assert (frame.width, frame.height) == (shape[1], shape[0])


def test_bad_rotate_and_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="rotate"):
        VideoFileSource(tmp_path / "x.mp4", rotate="up")  # type: ignore[arg-type]
    with pytest.raises(FileNotFoundError):
        VideoFileSource(tmp_path / "missing.mp4").start()


def test_read_next_before_start_raises(clip: Path) -> None:
    src = VideoFileSource(clip, realtime=False)
    assert src.latest() is None
    with pytest.raises(RuntimeError, match="start"):
        src.read_next()


# ---- realtime video ------------------------------------------------------------------------


def test_realtime_slow_consumer_drops_frames_but_sees_the_last(fast_clip: Path) -> None:
    with VideoFileSource(fast_clip) as src:  # realtime is the default
        got = read_all(src, slow_s=0.1)  # ~6 frame periods per read
        assert src.ended

    idx = [f.index for f in got]
    assert idx == sorted(set(idx)), "indexes must strictly increase"
    assert len(idx) < 20, f"a slow consumer should miss frames, got {idx}"
    assert idx[-1] == 29, "the final frame is still handed out"
    assert all(decode(f.image) == f.index for f in got)


def test_realtime_latest_is_newest_and_paced_at_file_fps(fast_clip: Path) -> None:
    t_start = time.monotonic()
    with VideoFileSource(fast_clip) as src:
        first = src.read_next(timeout=2.0)
        assert first is not None
        time.sleep(0.15)  # ~9 frame periods
        newest = src.latest()
        assert newest is not None and newest.index > first.index + 1
        after = src.read_next(timeout=2.0)
        assert after is not None and after.index >= newest.index
        assert abs(after.t - time.monotonic()) < 0.5  # monotonic clock, not file time
        rest = read_all(src)
    elapsed = time.monotonic() - t_start

    last = rest[-1] if rest else after
    assert last.index == 29
    assert elapsed >= 29 / 60.0 - 0.02, "frames came out faster than the file's fps"
    assert last.t - first.t >= (last.index - first.index) / 60.0 - 0.05


def test_realtime_loop(fast_clip: Path) -> None:
    with VideoFileSource(fast_clip, loop=True) as src:
        deadline = time.monotonic() + 3.0
        frame = None
        while time.monotonic() < deadline:
            frame = src.read_next(timeout=1.0)
            if frame is not None and frame.index >= 35:
                break
        assert not src.ended
    assert frame is not None and frame.index >= 35
    assert decode(frame.image) == frame.index % 30


# ---- open_source ---------------------------------------------------------------------------


def test_open_source_parsing() -> None:
    cam = open_source("0")
    assert isinstance(cam, CameraSource) and cam.index == 0
    cam = open_source(" 2 ", rotate="left", width=1280)
    assert isinstance(cam, CameraSource) and (cam.index, cam.rotate, cam.width) == (2, "left", 1280)

    video = open_source("clips/walk.mp4", realtime=False, loop=True)
    assert isinstance(video, VideoFileSource)
    assert video.path == Path("clips/walk.mp4") and video.realtime is False and video.loop is True
    assert isinstance(open_source("1.mov"), VideoFileSource)
    # Nothing was opened: the autouse fixture would have raised.


# ---- camera (fake capture) -----------------------------------------------------------------


class FakeCapture:
    """Stands in for cv2.VideoCapture. Image value = number of successful grabs so far."""

    def __init__(self, opened: bool = True, size: tuple[int, int] = (W, H), period: float = 0.002,
                 fail_after: int | None = None, image: np.ndarray | None = None) -> None:
        self.opened = opened
        self.w, self.h = size
        self.period = period
        self.fail_after = fail_after
        self.image = image
        self.grabs = 0
        self.props: dict[int, float] = {}
        self.released = False

    def isOpened(self) -> bool:  # noqa: N802 (OpenCV's name)
        return self.opened

    def set(self, prop: int, value: float) -> bool:
        self.props[prop] = value
        return True

    def get(self, prop: int) -> float:
        return {cv2.CAP_PROP_FRAME_WIDTH: self.w, cv2.CAP_PROP_FRAME_HEIGHT: self.h}.get(prop, 0.0)

    def grab(self) -> bool:
        time.sleep(self.period)
        if self.fail_after is not None and self.grabs >= self.fail_after:
            return False
        self.grabs += 1
        return True

    def retrieve(self) -> tuple[bool, np.ndarray]:
        if self.image is not None:
            return True, self.image.copy()
        return True, np.full((self.h, self.w, 3), self.grabs % 256, np.uint8)

    def read(self) -> tuple[bool, np.ndarray | None]:
        return self.retrieve() if self.grab() else (False, None)

    def release(self) -> None:
        self.released = True


def camera_threads(index: int) -> list[threading.Thread]:
    return [t for t in threading.enumerate() if t.name == f"CameraSource-{index}" and t.is_alive()]


def test_camera_serves_newest_frame() -> None:
    fake = FakeCapture()
    opened = []
    src = CameraSource(3, capture_factory=lambda i: opened.append(i) or fake)
    with src:
        assert opened == [3]
        assert src.latest() is not None, "start() returns once the first frame is in"
        first = src.read_next(timeout=1.0)
        time.sleep(0.05)  # the fake makes a frame every ~2 ms
        newest = src.latest()
        second = src.read_next(timeout=1.0)

    assert first is not None and newest is not None and second is not None
    assert second.index >= newest.index > first.index + 5, "old frames are dropped"
    for f in (first, newest, second):
        assert f.image[0, 0, 0] == (f.index + 1) % 256, "image and index belong together"
    assert first.t < second.t <= time.monotonic()


def test_camera_stop_joins_thread_and_releases() -> None:
    fake = FakeCapture()
    src = CameraSource(4, capture_factory=lambda i: fake)
    src.start()
    assert camera_threads(4)
    src.stop()
    assert not camera_threads(4)
    assert fake.released
    assert src.ended
    t0 = time.monotonic()
    assert src.read_next(timeout=5.0) is None
    assert time.monotonic() - t0 < 0.5, "read_next must not block after stop()"
    src.stop()  # twice is fine
    with pytest.raises(RuntimeError):
        src.start()


def test_camera_open_failure_mentions_permission() -> None:
    fake = FakeCapture(opened=False)
    with pytest.raises(FrameSourceError) as err:
        CameraSource(0, capture_factory=lambda i: fake).start()
    message = str(err.value)
    assert "camera 0" in message and "Privacy & Security > Camera" in message and "Terminal" in message
    assert fake.released


def test_camera_that_opens_but_sends_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(CameraSource, "OPEN_TIMEOUT_S", 0.1)
    fake = FakeCapture(fail_after=0)
    with pytest.raises(FrameSourceError, match="Privacy & Security"):
        CameraSource(1, capture_factory=lambda i: fake).start()
    assert fake.released
    assert not camera_threads(1)


def test_camera_ends_after_it_stops_delivering(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(CameraSource, "FAIL_AFTER_S", 0.1)
    fake = FakeCapture(fail_after=5)
    with CameraSource(2, capture_factory=lambda i: fake) as src:
        got = read_all(src, deadline_s=3.0)
    assert got and got[-1].index == 4, "the last good frame is still handed out"
    assert fake.released


def test_camera_requests_size_and_rotates() -> None:
    image = np.zeros((2, 3, 3), np.uint8)
    image[0, 0] = 255  # marker in the top-left corner
    expected_corner = {"left": (2, 0), "right": (0, 1), "180": (1, 2)}  # (row, col) after rotating

    fake = FakeCapture(image=image)
    with CameraSource(0, width=1280, height=720, capture_factory=lambda i: fake) as src:
        assert fake.props == {cv2.CAP_PROP_FRAME_WIDTH: 1280, cv2.CAP_PROP_FRAME_HEIGHT: 720}
        assert src.read_next(timeout=1.0).image.shape == (2, 3, 3)

    for rotate, (row, col) in expected_corner.items():
        fake = FakeCapture(image=image)
        with CameraSource(0, rotate=rotate, capture_factory=lambda i: fake) as src:
            out = src.read_next(timeout=1.0).image
        assert out.shape == ((3, 2, 3) if rotate != "180" else (2, 3, 3))
        assert out[row, col, 0] == 255 and int(out[..., 0].sum()) == 255, rotate

    with pytest.raises(ValueError):
        CameraSource(0, rotate=90, capture_factory=lambda i: fake)  # type: ignore[arg-type]


# ---- listing cameras -----------------------------------------------------------------------


def test_list_cameras_with_fakes() -> None:
    fakes = {0: FakeCapture(size=(1920, 1080)), 1: FakeCapture(size=(1280, 720))}
    made: list[FakeCapture] = []

    def factory(index: int) -> FakeCapture:
        cap = fakes.get(index, FakeCapture(opened=False))
        made.append(cap)
        return cap

    assert list_cameras(max_index=4, capture_factory=factory) == [
        CameraInfo(0, 1920, 1080), CameraInfo(1, 1280, 720),
    ]
    assert len(made) == 4 and all(cap.released for cap in made)


def test_parse_camera_names() -> None:
    text = (
        "Camera:\n\n"
        "    FaceTime HD Camera:\n\n"
        "      Model ID: FaceTime HD Camera\n"
        "      Unique ID: 1111\n\n"
        "    iPhone Camera:  \n\n"
        "      Model ID: iPhone18,3\n"
    )
    assert parse_camera_names(text) == ["FaceTime HD Camera", "iPhone Camera"]
    assert parse_camera_names("") == []
