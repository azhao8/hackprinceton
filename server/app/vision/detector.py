"""Person detector: a YOLO pose model (Ultralytics) behind a small interface.

This is the only module that imports Ultralytics or torch. Everything else uses
`PersonDetector` and the types in app/vision/types.py, so the model can be swapped
without touching the rest of the pipeline.

Weights live in server/models/ (git-ignored). Fetch them once with:
    cd server && uv run python -m app.vision.fetch_models
Loading never downloads: a missing file is an error that says how to fetch it.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from app.vision.types import KEYPOINT_NAMES, Box, Detections, Frame, Keypoint, Person

# Newest nano pose model this Ultralytics version knows: the YOLO26 family is the newest
# in ultralytics.utils.downloads.GITHUB_ASSETS_NAMES (ultralytics 8.4.212, downloads.py:26).
DEFAULT_MODEL_NAME = "yolo26n-pose.pt"
MODELS_DIR = Path(__file__).resolve().parents[2] / "models"  # server/models

FETCH_HINT = "cd server && uv run python -m app.vision.fetch_models"


class PersonDetector(Protocol):
    """Finds people in a frame."""

    def detect(self, frame: Frame) -> Detections: ...


def default_model_path() -> Path:
    """Where the default pose weights live (server/models/yolo26n-pose.pt). May not exist yet."""
    return MODELS_DIR / DEFAULT_MODEL_NAME


def fetch_default_model() -> Path:
    """Download the default weights with Ultralytics' own downloader. No-op if already present."""
    path = default_model_path()
    if not path.is_file():
        from ultralytics.utils.downloads import attempt_download_asset

        # An absolute path makes Ultralytics save there, not in the current directory.
        attempt_download_asset(path)
    if not path.is_file():
        raise RuntimeError(f"Download of {DEFAULT_MODEL_NAME} to {path} failed")
    return path


def resolve_device(device: str) -> str:
    """'auto' -> 'mps' on Apple Silicon if available, else 'cpu'. Other values pass through."""
    if device != "auto":
        return device
    import torch

    return "mps" if torch.backends.mps.is_available() else "cpu"


def people_from_arrays(
    boxes_xyxyn: np.ndarray,
    scores: np.ndarray,
    kpts_xyn: np.ndarray | None = None,
    kpts_conf: np.ndarray | None = None,
) -> list[Person]:
    """Convert raw detector arrays to Persons, highest score first.

    boxes_xyxyn: (N, 4) normalized x1, y1, x2, y2. scores: (N,).
    kpts_xyn: (N, 17, 2) normalized x, y in KEYPOINT_NAMES (COCO) order, or None.
    kpts_conf: (N, 17) per-keypoint confidence, or None (then treated as 1.0).

    Keypoints at exactly (0, 0) or non-finite are left out: Ultralytics uses (0, 0)
    for "no position". Low-confidence keypoints are kept with their conf, so callers
    filter with Person.keypoint(name, min_conf).
    """
    boxes = np.asarray(boxes_xyxyn, dtype=np.float64).reshape(-1, 4)
    scores = np.asarray(scores, dtype=np.float64).reshape(-1)
    n = len(boxes)
    if len(scores) != n:
        raise ValueError(f"{n} boxes but {len(scores)} scores")
    if n == 0:
        return []

    xy = conf = None
    if kpts_xyn is not None:
        xy = np.asarray(kpts_xyn, dtype=np.float64)
        if xy.shape != (n, len(KEYPOINT_NAMES), 2):
            raise ValueError(f"keypoints shape {xy.shape}, expected ({n}, {len(KEYPOINT_NAMES)}, 2)")
        if kpts_conf is None:
            conf = np.ones(xy.shape[:2])
        else:
            conf = np.asarray(kpts_conf, dtype=np.float64)
            if conf.shape != xy.shape[:2]:
                raise ValueError(f"keypoint conf shape {conf.shape}, expected {xy.shape[:2]}")

    boxes = np.clip(boxes, 0.0, 1.0)
    people = []
    for i in np.argsort(-scores, kind="stable"):
        keypoints: dict[str, Keypoint] = {}
        if xy is not None and conf is not None:
            for name, (x, y), c in zip(KEYPOINT_NAMES, xy[i], conf[i]):
                if not (np.isfinite(x) and np.isfinite(y) and np.isfinite(c)) or (x == 0.0 and y == 0.0):
                    continue
                keypoints[name] = Keypoint(float(x), float(y), float(c))
        x1, y1, x2, y2 = (float(v) for v in boxes[i])
        people.append(Person(box=Box(x1, y1, x2, y2), score=float(scores[i]), keypoints=keypoints))
    return people


class YoloPoseDetector:
    """PersonDetector backed by an Ultralytics YOLO pose model."""

    def __init__(
        self,
        model_path: str | Path | None = None,
        device: str = "auto",
        conf: float = 0.35,
        imgsz: int = 640,
    ) -> None:
        path = Path(model_path) if model_path is not None else default_model_path()
        if not path.is_file():
            # Checked here because YOLO() would otherwise download known asset names.
            raise FileNotFoundError(f"Model weights not found at {path}. Fetch them with: {FETCH_HINT}")

        from ultralytics import YOLO

        self.model_path = path
        self.device = resolve_device(device)
        self.conf = conf
        self.imgsz = imgsz
        self._model: Any = YOLO(str(path))
        if self._model.task != "pose":
            raise ValueError(f"{path} is a '{self._model.task}' model; a pose model is required")

    def detect(self, frame: Frame) -> Detections:
        t0 = time.perf_counter()
        result = self._model.predict(
            frame.image,  # numpy arrays are read as BGR by Ultralytics, matching Frame.image
            conf=self.conf,
            imgsz=self.imgsz,
            device=self.device,
            verbose=False,
        )[0]
        boxes = result.boxes
        kpts = result.keypoints
        people = people_from_arrays(
            boxes.xyxyn.cpu().numpy(),
            boxes.conf.cpu().numpy(),
            kpts.xyn.cpu().numpy() if kpts is not None else None,
            kpts.conf.cpu().numpy() if kpts is not None and kpts.conf is not None else None,
        )
        return Detections(
            frame_t=frame.t,
            frame_index=frame.index,
            width=frame.width,
            height=frame.height,
            people=people,
            latency_s=time.perf_counter() - t0,
        )
