"""Debug view: printed markers drawn on the picture (issue #62). No window is opened."""

from __future__ import annotations

import numpy as np

from app.vision.debug_view import Hud, draw_markers, marker_label, render
from app.vision.types import Detections, Frame, Marker, TargetState, TargetStatus
from app.vision.worker import Perception


def perception(markers=()) -> Perception:
    image = np.zeros((720, 1280, 3), np.uint8)
    return Perception(Frame(1.0, 0, image), Detections(1.0, 0, 1280, 720, []), TargetState(TargetStatus.IDLE),
                      False, 0, 0.0, 10.0, 1.0, markers=tuple(markers))


def test_marker_label_uses_the_place_and_distance(monkeypatch):
    monkeypatch.delenv("PLACES", raising=False)
    assert marker_label(Marker(1, 0.5, 0.5, 0.1, 1.84)) == "station 1.8 m"
    assert marker_label(Marker(42, 0.5, 0.5, 0.1)) == "marker 42"
    monkeypatch.setenv("PLACES", "garbage")  # malformed: still a label, never an exception
    assert marker_label(Marker(1, 0.5, 0.5, 0.1)) == "marker 1"


def test_markers_are_drawn_where_they_are():
    m = Marker(1, 0.7, 0.6, 0.1, 1.8)
    with_marker = render(perception([m]), Hud())
    without = render(perception(), Hud())
    diff = np.any(with_marker != without, axis=2)
    assert diff.any()

    side = 2 * 0.1 * 1280 * 720 / (1280 + 720)  # ~92 px
    cx, cy = 0.7 * 1280, 0.6 * 720
    x1, x2 = int(cx - side / 2) - 3, int(cx + side / 2) + 3
    y1, y2 = int(cy - side / 2) - 40, int(cy + side / 2) + 3  # the label sits just above the square
    inside = np.zeros_like(diff)
    inside[y1:y2, x1:max(x2, x1 + 200)] = True
    assert diff[inside].any() and not diff[~inside].any()  # changed around the marker only
    assert diff[int(cy - side / 2), int(cx)]  # the square's top edge


def test_nothing_drawn_without_markers():
    img = np.zeros((360, 640, 3), np.uint8)
    draw_markers(img, [])
    assert not img.any()
    draw_markers(img, [Marker(2, 0.5, 0.5, 0.05)])
    assert img.any()
