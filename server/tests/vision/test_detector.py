"""Tests for the person detector adapter.

Unit tests feed fake arrays to the pure conversion (no model). Integration tests run
the real weights on the sample images Ultralytics ships, and skip if the weights
haven't been fetched (uv run python -m app.vision.fetch_models).
"""

import importlib.util
from pathlib import Path

import cv2
import numpy as np
import pytest

from app.vision.detector import (
    PersonDetector,
    YoloPoseDetector,
    default_model_path,
    people_from_arrays,
    resolve_device,
)
from app.vision.types import KEYPOINT_NAMES, Frame, Person

K = len(KEYPOINT_NAMES)
ASSETS = Path(importlib.util.find_spec("ultralytics").origin).parent / "assets"


def fake_keypoints(n: int, seed: int = 0) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    return rng.uniform(0.1, 0.9, (n, K, 2)), rng.uniform(0.0, 1.0, (n, K))


# ---------------------------------------------------------------- pure conversion


def test_converts_boxes_scores_and_keypoints_in_coco_order():
    boxes = np.array([[0.1, 0.2, 0.3, 0.9], [0.5, 0.1, 0.8, 0.95]])
    scores = np.array([0.5, 0.9])
    xy, conf = fake_keypoints(2)

    people = people_from_arrays(boxes, scores, xy, conf)

    assert [p.score for p in people] == pytest.approx([0.9, 0.5])  # highest score first
    top = people[0]
    assert (top.box.x1, top.box.y1, top.box.x2, top.box.y2) == pytest.approx((0.5, 0.1, 0.8, 0.95))
    assert tuple(top.keypoints) == KEYPOINT_NAMES
    ankle = top.keypoints["left_ankle"]
    i = KEYPOINT_NAMES.index("left_ankle")
    assert (ankle.x, ankle.y, ankle.conf) == pytest.approx((xy[1, i, 0], xy[1, i, 1], conf[1, i]))
    assert all(type(v) is float for v in (top.score, top.box.x1, ankle.x, ankle.conf))


def test_zero_detections():
    assert people_from_arrays(np.zeros((0, 4)), np.zeros(0), np.zeros((0, K, 2)), np.zeros((0, K))) == []
    assert people_from_arrays(np.zeros((0, 4)), np.zeros(0)) == []


def test_keypoints_at_origin_are_dropped_low_confidence_ones_kept():
    xy, conf = fake_keypoints(1)
    xy[0, KEYPOINT_NAMES.index("nose")] = (0.0, 0.0)  # Ultralytics' "no position"
    conf[0, KEYPOINT_NAMES.index("nose")] = 0.0
    xy[0, KEYPOINT_NAMES.index("left_eye")] = (np.nan, 0.5)
    conf[0, KEYPOINT_NAMES.index("right_ankle")] = 0.05

    (person,) = people_from_arrays(np.array([[0.1, 0.1, 0.5, 0.9]]), np.array([0.8]), xy, conf)

    assert "nose" not in person.keypoints
    assert "left_eye" not in person.keypoints
    assert person.keypoints["right_ankle"].conf == pytest.approx(0.05)
    assert person.keypoint("right_ankle") is None  # below the default min_conf


def test_keypoints_optional():
    xy, _ = fake_keypoints(1)
    box, score = np.array([[0.1, 0.1, 0.5, 0.9]]), np.array([0.8])
    assert people_from_arrays(box, score)[0].keypoints == {}
    no_conf = people_from_arrays(box, score, xy, None)[0]
    assert all(kp.conf == 1.0 for kp in no_conf.keypoints.values())


def test_boxes_clipped_to_unit_range():
    (person,) = people_from_arrays(np.array([[-0.01, 0.2, 1.02, 1.0]]), np.array([0.7]))
    assert (person.box.x1, person.box.x2) == (0.0, 1.0)


def test_rejects_mismatched_shapes():
    box, score = np.array([[0.1, 0.1, 0.5, 0.9]]), np.array([0.8])
    with pytest.raises(ValueError, match="keypoints shape"):
        people_from_arrays(box, score, np.zeros((1, 5, 2)), np.zeros((1, 5)))
    with pytest.raises(ValueError, match="scores"):
        people_from_arrays(box, np.array([0.8, 0.7]))


# ---------------------------------------------------------------- setup


def test_resolve_device():
    import torch

    assert resolve_device("cpu") == "cpu"
    assert resolve_device("auto") == ("mps" if torch.backends.mps.is_available() else "cpu")


def test_default_model_path_is_in_server_models():
    path = default_model_path()
    assert path.name == "yolo26n-pose.pt"
    assert path.parent == Path(__file__).resolve().parents[2] / "models"


def test_missing_weights_raise_helpful_error_without_downloading(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    missing = tmp_path / "yolo26n-pose.pt"  # a name Ultralytics would happily auto-download

    with pytest.raises(FileNotFoundError, match="app.vision.fetch_models"):
        YoloPoseDetector(model_path=missing)

    assert list(tmp_path.iterdir()) == []


# ---------------------------------------------------------------- real model

needs_weights = pytest.mark.skipif(
    not default_model_path().is_file(),
    reason="weights missing; run: uv run python -m app.vision.fetch_models",
)


@pytest.fixture(scope="module")
def detector() -> YoloPoseDetector:
    return YoloPoseDetector()


def frame_of(name: str, rows_from: float = 0.0, t: float = 0.0, index: int = 0) -> Frame:
    image = cv2.imread(str(ASSETS / name))
    assert image is not None, f"missing sample image {ASSETS / name}"
    image = np.ascontiguousarray(image[int(rows_from * image.shape[0]) :])
    return Frame(t=t, index=index, image=image)


def assert_well_formed(people: list[Person]) -> None:
    assert [p.score for p in people] == sorted((p.score for p in people), reverse=True)
    for p in people:
        assert 0.0 <= p.box.x1 < p.box.x2 <= 1.0
        assert 0.0 <= p.box.y1 < p.box.y2 <= 1.0
        assert 0.0 < p.score <= 1.0
        assert set(p.keypoints) <= set(KEYPOINT_NAMES)
        for kp in p.keypoints.values():
            assert 0.0 <= kp.x <= 1.0 and 0.0 <= kp.y <= 1.0 and 0.0 <= kp.conf <= 1.0


def with_ankle(people: list[Person], min_conf: float = 0.5) -> list[Person]:
    return [p for p in people if p.keypoint("left_ankle", min_conf) or p.keypoint("right_ankle", min_conf)]


@needs_weights
def test_bus_finds_standing_people_with_ankles(detector):
    frame = frame_of("bus.jpg", t=12.5, index=7)
    d: PersonDetector = detector

    dets = d.detect(frame)

    assert (dets.frame_t, dets.frame_index) == (12.5, 7)
    assert (dets.width, dets.height) == (810, 1080)
    assert dets.latency_s > 0
    assert len(dets.people) >= 3
    assert_well_formed(dets.people)
    assert len(with_ankle(dets.people)) >= 2


@needs_weights
def test_zidane_finds_two_people(detector):
    dets = detector.detect(frame_of("zidane.jpg"))
    assert len(dets.people) >= 2
    assert_well_formed(dets.people)


@needs_weights
def test_legs_only_crop_still_finds_people_and_ankles(detector):
    # bus.jpg from the hips down (hips sit near 0.6 of the image height): what a
    # camera 40 cm off the floor sees.
    dets = detector.detect(frame_of("bus.jpg", rows_from=0.6))
    assert_well_formed(dets.people)
    assert len([p for p in dets.people if p.score >= 0.5]) >= 3
    assert len(with_ankle(dets.people)) >= 2


@needs_weights
def test_blank_frame_has_no_people_and_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    detector = YoloPoseDetector(device="cpu")

    dets = detector.detect(Frame(t=0.0, index=0, image=np.zeros((480, 640, 3), np.uint8)))

    assert dets.people == []
    assert list(tmp_path.iterdir()) == []
