"""Calibration (issue #62): the math, the file, the apply helpers, and the guided run's
capture/session logic on fake detections. No camera, window, robot or network."""

from __future__ import annotations

import json
import logging
import math
from datetime import datetime, timezone

import cv2
import numpy as np
import pytest

from app.vision import calibration as cal_mod
from app.vision.calibrate import (
    Capture,
    CaptureError,
    Session,
    default_steps,
    key_action,
    marker_values,
    person_values,
    pick_marker,
    pick_person,
    resolve_source,
    text_action,
)
from app.vision.calibration import Calibration
from app.vision.follow import CameraGeometry, FollowConfig
from app.vision.markers import MarkerDetector
from app.vision.types import Box, Keypoint, Marker, Person

W, H = 1280, 720
TRUE_HFOV = 60.0  # the "real" camera in these tests; the detector guesses 67


def focal_px(hfov_deg: float, width: int = W) -> float:
    return (width / 2) / math.tan(math.radians(hfov_deg) / 2)


def person(box_w: float, gap: float, cx: float = 0.5, shoulders_conf: float = 0.9) -> Person:
    kps = {
        "left_shoulder": Keypoint(cx + gap / 2, 0.3, shoulders_conf),
        "right_shoulder": Keypoint(cx - gap / 2, 0.3, shoulders_conf),
    }
    return Person(Box(cx - box_w / 2, 0.1, cx + box_w / 2, 0.95), 0.9, kps)


def synthetic_person(d: float, hfov: float = TRUE_HFOV, shoulders_m: float = 0.37, width_m: float = 0.5) -> Person:
    """A person `d` m away seen by a pinhole camera with this hfov (fractions of the width)."""
    span = 2 * d * math.tan(math.radians(hfov) / 2)  # meters across the picture at that distance
    return person(width_m / span, shoulders_m / span)


# --- math ---


def test_hfov_from_a_marker_reading_recovers_the_true_fov():
    side_px = focal_px(TRUE_HFOV) * 0.15 / 1.0  # a 15 cm marker at 1 m, by the true camera
    read = MarkerDetector(geometry=CameraGeometry(hfov_deg=67.0)).distance_for(side_px, W)
    assert read == pytest.approx(0.8725, abs=1e-3)  # the 67 deg guess reads it short
    assert cal_mod.hfov_from_marker_reading(read, 1.0, 67.0) == pytest.approx(TRUE_HFOV, rel=1e-6)
    # reading the true distance means the guess was right
    assert cal_mod.hfov_from_marker_reading(2.0, 2.0, 67.0) == pytest.approx(67.0)
    with pytest.raises(ValueError):
        cal_mod.hfov_from_marker_reading(0.0, 1.0, 67.0)


def test_hfov_recovered_from_a_rendered_marker_within_a_few_percent():
    aruco = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    side = 168  # pixels, a multiple of the 6 cells
    img = np.full((H, W, 3), 255, np.uint8)
    marker = cv2.cvtColor(cv2.aruco.generateImageMarker(aruco, 1, side), cv2.COLOR_GRAY2BGR)
    y0, x0 = (H - side) // 2, (W - side) // 2
    img[y0:y0 + side, x0:x0 + side] = marker
    true_d = focal_px(TRUE_HFOV) * 0.15 / side  # where a 15 cm marker this big really is

    (m,) = MarkerDetector(geometry=CameraGeometry(hfov_deg=67.0)).detect(img)
    hfov = cal_mod.hfov_from_marker_reading(m.distance_m, true_d, 67.0)
    assert hfov == pytest.approx(TRUE_HFOV, rel=0.03)
    # and the calibrated detector then reads the true distance
    cal = Calibration(hfov_deg=hfov, marker_size_m=0.15)
    (m2,) = MarkerDetector(**cal_mod.marker_kwargs(cal)).detect(img)
    assert m2.distance_m == pytest.approx(true_d, rel=0.01)


def test_vfov_follows_from_the_aspect():
    v = cal_mod.vfov_from_hfov(60.0, 1280, 720)
    assert math.tan(math.radians(v) / 2) == pytest.approx(math.tan(math.radians(30)) * 720 / 1280)
    assert cal_mod.vfov_from_hfov(50.0, 100, 100) == pytest.approx(50.0)


def test_k_shoulder_from_synthetic_gaps():
    span = lambda d: 2 * d * math.tan(math.radians(TRUE_HFOV) / 2)  # noqa: E731
    samples = [(d, 0.37 / span(d)) for d in (1.0, 2.0)]
    k = cal_mod.k_shoulder_from(samples)
    assert k == pytest.approx(0.37 / (2 * math.tan(math.radians(30))))
    # the follow controller's shoulder cue then reads the right distance
    for d, gap in samples:
        assert k / gap == pytest.approx(d)
    with pytest.raises(ValueError):
        cal_mod.k_shoulder_from([])


def test_box_width_at_the_follow_distance():
    pure = [(1.0, 0.40), (2.0, 0.20)]  # w = 0.4 / d
    assert cal_mod.box_width_at(pure, 1.0) == pytest.approx(0.40)
    assert cal_mod.box_width_at(pure, 0.7) == pytest.approx(0.40 / 0.7)
    offset = [(1.0, 0.05 + 0.35), (2.0, 0.05 + 0.175)]  # w = 0.05 + 0.35 / d: exact through both
    assert cal_mod.box_width_at(offset, 1.5) == pytest.approx(0.05 + 0.35 / 1.5)
    assert cal_mod.box_width_at(offset, 2.0) == pytest.approx(0.225)
    assert cal_mod.box_width_at([(2.0, 0.2)], 1.0) == pytest.approx(0.4)  # one distance: 1/d
    with pytest.raises(ValueError):
        cal_mod.box_width_at([], 1.0)


def test_tilt_from_a_point_at_lens_height():
    vfov, tilt = 41.0, 10.0  # camera pitched 10 deg up: a level point sits below the center
    y = 0.5 + math.tan(math.radians(tilt)) / (2 * math.tan(math.radians(vfov) / 2))
    assert y > 0.5
    assert cal_mod.tilt_from_level_point(y, vfov) == pytest.approx(tilt)
    assert cal_mod.tilt_from_level_point(0.5, vfov) == pytest.approx(0.0)
    # consistent with CameraGeometry: with the measured tilt, the level point is AT the horizon
    geo = CameraGeometry(tilt_deg=tilt, vfov_deg=vfov)
    assert geo.ground_distance(y) is None and geo.ground_distance(y + 0.2) is not None


# --- file ---


def test_save_load_round_trip(tmp_path):
    cal = Calibration(hfov_deg=62.5, vfov_deg=37.4, tilt_deg=8.0, height_m=0.41, k_shoulder_m=0.3,
                      target_box_w=0.38, d_target_m=1.0, too_close_box_w=0.52, marker_size_m=0.148,
                      marker_focal_scale=1.0, measured_at="2026-11-14T18:00:00-05:00", notes="camera 0")
    path = cal_mod.save(cal, tmp_path / "calibration.json")
    assert json.loads(path.read_text())["version"] == cal_mod.FILE_VERSION
    assert cal_mod.load(path) == cal
    partial = Calibration(k_shoulder_m=0.29)  # skipped steps stay None
    assert cal_mod.load(cal_mod.save(partial, tmp_path / "p.json")) == partial


def test_load_missing_is_none(tmp_path):
    assert cal_mod.load(tmp_path / "nope.json") is None


@pytest.mark.parametrize("text", [
    "{not json",
    "[1, 2]",
    '{"version": 99, "hfov_deg": 60}',
    '{"version": 1, "hfov_deg": "wide"}',
    '{"version": 1, "hfov_deg": 400}',
    '{"version": 1, "hfov_deg": NaN}',
    '{"version": 1, "k_shoulder_m": true}',
    '{"version": 1, "target_box_w": 0.6, "too_close_box_w": 0.5}',
    '{"version": 1, "notes": 5}',
])
def test_load_corrupt_warns_and_is_none(tmp_path, caplog, text):
    path = tmp_path / "calibration.json"
    path.write_text(text)
    with caplog.at_level(logging.WARNING):
        assert cal_mod.load(path) is None
    assert "calibration" in caplog.text


def test_load_ignores_unknown_keys_and_nulls(tmp_path):
    path = tmp_path / "c.json"
    path.write_text('{"version": 1, "hfov_deg": 60, "future_field": 3, "tilt_deg": null}')
    assert cal_mod.load(path) == Calibration(hfov_deg=60)


def test_save_refuses_bad_values(tmp_path):
    with pytest.raises(ValueError):
        cal_mod.save(Calibration(hfov_deg=5.0), tmp_path / "c.json")
    assert not (tmp_path / "c.json").exists()


# --- apply helpers ---


def test_camera_geometry_and_follow_config_apply_only_measured_values():
    base = FollowConfig(turn_only=True, camera=CameraGeometry(height_m=0.5))
    assert cal_mod.follow_config(None, base) == base
    cal = Calibration(hfov_deg=60.0, tilt_deg=7.5, k_shoulder_m=0.31, target_box_w=0.4, d_target_m=1.2,
                      too_close_box_w=0.6)
    fc = cal_mod.follow_config(cal, base)
    assert fc.turn_only and fc.k_v == base.k_v  # everything else stays
    assert fc.camera == CameraGeometry(height_m=0.5, tilt_deg=7.5, vfov_deg=41.0, hfov_deg=60.0)
    assert (fc.k_shoulder_m, fc.target_box_w, fc.d_target_m, fc.too_close_w) == (0.31, 0.4, 1.2, 0.6)
    assert cal_mod.camera_geometry(Calibration(height_m=0.42)) == CameraGeometry(height_m=0.42)


def test_marker_kwargs_and_lock_config():
    assert MarkerDetector(**cal_mod.marker_kwargs(None)).geometry == CameraGeometry()
    kw = cal_mod.marker_kwargs(Calibration(hfov_deg=60.0, marker_size_m=0.2, marker_focal_scale=1.1))
    det = MarkerDetector(**kw)
    assert (det.geometry.hfov_deg, det.marker_size_m, det.focal_scale) == (60.0, 0.2, 1.1)
    assert "marker_size_m" not in cal_mod.marker_kwargs(Calibration(hfov_deg=60.0))
    assert cal_mod.lock_config(Calibration(hfov_deg=58.0)).hfov_deg == 58.0
    assert cal_mod.lock_config(None).hfov_deg == 67.0


# --- calibrate: readings and capture ---


def test_readings_pick_and_reject():
    small, big = Marker(1, 0.5, 0.5, 0.05, 2.0), Marker(2, 0.4, 0.5, 0.1, 1.0)
    assert pick_marker([small, big]) is big
    assert pick_marker([small, big], marker_id=1) is small
    assert pick_marker([small], marker_id=7) is None
    assert marker_values(Marker(1, 0.5, 0.6, 0.1)) == {"cx": 0.5, "cy": 0.6, "size": 0.1}  # no distance

    near, far = person(0.4, 0.28), person(0.2, 0.14)
    assert pick_person([far, near]) is near and pick_person([]) is None
    assert person_values(near) == pytest.approx({"box_w": 0.4, "gap": 0.28, "cx": 0.5})
    assert person_values(person(0.4, 0.28, shoulders_conf=0.2)) is None  # shoulders unsure
    one_shoulder = Person(near.box, 0.9, {"left_shoulder": near.keypoints["left_shoulder"]})
    assert person_values(one_shoulder) is None  # turned sideways
    assert person_values(person(0.4, 0.28, cx=0.21)) is None  # cut off at the left edge


def test_capture_averages_and_rejects():
    c = Capture(duration_s=1.0, min_used=3)
    for i in range(31):  # 30 fps for 1 s; every third frame has nothing
        t = i / 30
        c.add(t, None if i % 3 == 0 else {"gap": 0.28 + (0.01 if i % 2 else -0.01)})
        if i < 30:
            assert not c.done
    assert c.done
    r = c.result()
    assert (r.used, r.frames) == (20, 31)
    assert r.mean["gap"] == pytest.approx(0.28, abs=0.002)
    assert r.std["gap"] == pytest.approx(0.01, abs=0.001)


def test_capture_fails_without_enough_detections():
    c = Capture(duration_s=1.0, min_used=3)
    for i in range(10):
        c.add(i / 9, {"gap": 0.3} if i < 2 else None)
    with pytest.raises(CaptureError):
        c.result()
    mostly_empty = Capture(duration_s=1.0, min_used=3)
    for i in range(30):
        mostly_empty.add(i / 29, {"gap": 0.3} if i < 10 else None)  # 10 of 30: under half
    with pytest.raises(CaptureError):
        mostly_empty.result()
    with pytest.raises(CaptureError):
        Capture().result()


# --- calibrate: the guided session on fake detections ---

NOW = lambda: datetime(2026, 11, 14, 18, 0, tzinfo=timezone.utc)  # noqa: E731


def feed_for(session: Session, seconds: float, markers=(), people=(), t0: float = 0.0, fps: float = 30.0) -> float:
    t = t0
    for i in range(int(seconds * fps) + 1):
        t = t0 + i / fps
        session.feed(t, list(markers), list(people), W, H)
    return t


def test_session_walks_the_steps_and_builds_the_calibration():
    s = Session(default_steps(), marker_size_m=0.15, height_m=0.40, now=NOW)
    assert s.step.key == "marker" and not s.needs_people

    # 1. marker at 1.00 m, seen by the 60 deg camera, read with the 67 deg guess
    side_px = focal_px(TRUE_HFOV) * 0.15 / 1.0
    read = MarkerDetector().distance_for(side_px, W)
    marker = Marker(1, 0.5, 0.5, side_px / W, read)
    feed_for(s, 0.2, markers=[marker])
    assert "hfov 60.0" in s.live_text()
    s.press("capture")
    t = feed_for(s, 1.1, markers=[marker])
    assert s.step.key == "near" and s.needs_people, s.message

    # 2./3. person at 1 m and 2 m (frames without shoulders are rejected, not averaged)
    for key, d in (("near", 1.0), ("far", 2.0)):
        s.press("capture")
        good, bad = synthetic_person(d), person(0.9, 0.5, shoulders_conf=0.1)
        for i in range(34):
            t += 1 / 30
            s.feed(t, [], [bad if i % 4 == 0 else good], W, H)
        assert key in s.results, s.message
        assert s.results[key].used < s.results[key].frames

    # 4. tilt: skipped
    assert s.step.key == "tilt"
    s.press("skip")
    assert s.phase == "review"

    cal = s.calibration()
    assert cal.hfov_deg == pytest.approx(TRUE_HFOV, abs=0.05)
    assert cal.vfov_deg == pytest.approx(cal_mod.vfov_from_hfov(TRUE_HFOV, W, H), abs=0.05)
    assert cal.k_shoulder_m == pytest.approx(0.37 / (2 * math.tan(math.radians(30))), rel=1e-3)
    assert cal.target_box_w == pytest.approx(synthetic_person(1.0).box.w, rel=1e-3)
    assert cal.d_target_m == 1.0
    assert cal.too_close_box_w == pytest.approx(synthetic_person(0.7).box.w, rel=1e-3)
    assert cal.tilt_deg is None and cal.height_m == 0.40 and cal.marker_size_m == 0.15
    assert cal.measured_at.startswith("2026-11-14T18:00") and "1280x720" in cal.notes
    assert any("not measured" in text for text, _ in s.summary_lines())  # the tilt row

    s.press("save")
    assert s.phase == "confirmed" and s.finished


def test_session_tilt_step_and_failed_capture():
    steps = [st for st in default_steps() if st.key == "tilt"]
    s = Session(steps, now=NOW)
    s.press("capture")
    feed_for(s, 1.1)  # no marker at all
    assert s.phase == "aim" and "capture failed" in s.message and "tilt" not in s.results

    y = 0.5 + math.tan(math.radians(8.0)) / (2 * math.tan(math.radians(41.0) / 2))
    s.press("capture")
    feed_for(s, 1.1, markers=[Marker(3, 0.5, y, 0.05, 2.0)], t0=5.0)
    assert s.phase == "review"
    assert s.calibration().tilt_deg == pytest.approx(8.0, abs=0.01)  # the default vfov (no marker step)


def test_session_back_skip_quit_and_nothing_to_save():
    s = Session(default_steps(), now=NOW)
    s.press("back")
    assert s.index == 0  # nothing before the first step
    for _ in range(4):
        s.press("skip")
    assert s.phase == "review"
    s.press("save")
    assert s.phase == "review" and "nothing measured" in s.message  # won't save an empty file
    s.press("back")
    assert s.phase == "aim" and s.step.key == "tilt"
    s.press("capture")
    s.press("back")
    assert s.phase == "aim" and "cancelled" in s.message
    s.press("quit")
    assert s.phase == "quit" and s.finished


def test_draw_shows_the_step_without_a_window():
    from app.vision.calibrate import draw

    s = Session(default_steps(), now=NOW)
    image = np.zeros((1080, 1920, 3), np.uint8)
    m = Marker(1, 0.5, 0.5, 0.1, 0.9)
    s.feed(0.0, [m], [], 1920, 1080)
    out = draw(image, s, [m], [])
    assert out.shape == (720, 1280, 3) and out.any() and not image.any()
    s.press("skip")
    p = synthetic_person(1.0)
    s.feed(0.1, [], [p], 1920, 1080)
    assert s.needs_people and s.live is not None
    assert draw(image, s, [], [p]).any()


def test_keys_and_source():
    assert key_action(-1, "aim") is None
    assert key_action(32, "aim") == "capture" and key_action(13, "review") == "save"
    assert key_action(ord("s"), "aim") == "skip" and key_action(27, "aim") == "quit"
    assert text_action("", "aim") == "capture" and text_action(" Q ", "aim") == "quit"
    assert resolve_source("0") == "0" and resolve_source("clip.mp4") == "clip.mp4"
    assert resolve_source("phone", ["FaceTime HD Camera", "Grant's iPhone Camera"]) == "1"
    with pytest.raises(ValueError):
        resolve_source("phone", ["FaceTime HD Camera"])
