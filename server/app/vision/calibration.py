"""Camera calibration: what follow.py and markers.py otherwise guess, measured once (issue #62).

`python -m app.vision.calibrate` measures it (about five minutes, a tape measure, one printed
marker and one person) and writes server/calibration.json (git-ignored). The server loads it:

    cal = calibration.load()                          # None if there is no file (or it's corrupt)
    config = calibration.follow_config(cal, base)     # FollowConfig with the measured values
    markers = MarkerDetector(**calibration.marker_kwargs(cal))
    lock = TargetLock(calibration.lock_config(cal))

Every measured field is optional: None means "not measured, keep the default" (a skipped step).
The apply helpers are pure (dataclasses.replace on the base you pass): values in the calibration
replace the base's, so apply command-line overrides AFTER them if flags should win.

The measurements (all pinhole model, normalized image coordinates as in types.py):

- Focal length / FOV from a marker at a known distance. A marker the detector (using a guessed
  hfov H0) reads at d_read meters while it really is d_true away means the real focal length is
  d_true / d_read times the guessed one: tan(hfov / 2) = tan(H0 / 2) * d_read / d_true.
  vfov follows from the picture's aspect: tan(vfov / 2) = tan(hfov / 2) * height / width.
- k_shoulder_m: the shoulder gap g (fraction of the picture width) of a person at d meters;
  d = k / g, so k = d * g, averaged over the distances measured.
- target_box_w: a person's box width w (fraction of the width) vs distance, w = a + b / d fitted
  to the distances measured (exact through two), read at the follow distance. One distance: w ~ 1/d.
- tilt_deg: a point at lens height is level with the lens, so its row says how far the optical
  axis is pitched: tilt = atan((y - 0.5) * 2 * tan(vfov / 2)) (positive = pitched UP, the
  convention of CameraGeometry.tilt_deg; a level point then sits BELOW the picture's center).
"""

from __future__ import annotations

import json
import logging
import math
import os
import tempfile
from collections.abc import Iterable
from dataclasses import asdict, dataclass, fields, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.vision.follow import CameraGeometry, FollowConfig

if TYPE_CHECKING:
    from app.vision.tracking import LockConfig

log = logging.getLogger(__name__)

DEFAULT_PATH = Path(__file__).resolve().parents[2] / "calibration.json"  # server/calibration.json
FILE_VERSION = 1


@dataclass(frozen=True)
class Calibration:
    """Measured camera and follow numbers. None = not measured (the default stays)."""

    hfov_deg: float | None = None  # horizontal field of view of the picture vision sees
    vfov_deg: float | None = None  # vertical field of view (from hfov and the picture's aspect)
    tilt_deg: float | None = None  # pitch of the optical axis, positive = UP (CameraGeometry.tilt_deg)
    height_m: float | None = None  # lens above the floor (tape measure)
    k_shoulder_m: float | None = None  # distance (m) x shoulder gap (fraction of width): FollowConfig.k_shoulder_m
    target_box_w: float | None = None  # person box width at the follow distance: FollowConfig.target_box_w
    d_target_m: float | None = None  # the follow distance target_box_w was read at: FollowConfig.d_target_m
    too_close_box_w: float | None = None  # box width at the back-off distance: FollowConfig.too_close_box_w
    marker_size_m: float | None = None  # printed black square, measured with a ruler
    marker_focal_scale: float = 1.0  # extra factor on the marker focal length, ON TOP of hfov_deg
    # (the guided run measures hfov, so it saves 1.0; change it by hand only if marker distances still read off)
    measured_at: str = ""  # ISO 8601 local time of the run
    notes: str = ""  # free text: source, picture size, rotation, raw readings

    def problems(self) -> list[str]:
        """What is wrong with the values (empty list = fine)."""
        out = []
        for name, (lo, hi) in _RANGES.items():
            value = getattr(self, name)
            if value is None:
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                out.append(f"{name} must be a number, got {value!r}")
            elif not lo <= value <= hi:
                out.append(f"{name} = {value} is outside {lo}..{hi}")
        if not out and self.target_box_w is not None and self.too_close_box_w is not None:
            if self.too_close_box_w <= self.target_box_w:
                out.append(f"too_close_box_w ({self.too_close_box_w}) must be wider than "
                           f"target_box_w ({self.target_box_w})")
        for name in ("measured_at", "notes"):
            if not isinstance(getattr(self, name), str):
                out.append(f"{name} must be text")
        return out


# Sanity limits (inclusive). A value outside them is a bad measurement, not a camera.
_RANGES: dict[str, tuple[float, float]] = {
    "hfov_deg": (20.0, 150.0),
    "vfov_deg": (10.0, 150.0),
    "tilt_deg": (-60.0, 60.0),
    "height_m": (0.05, 3.0),
    "k_shoulder_m": (0.02, 2.0),
    "target_box_w": (0.02, 1.0),
    "d_target_m": (0.2, 10.0),
    "too_close_box_w": (0.02, 1.0),
    "marker_size_m": (0.01, 2.0),
    "marker_focal_scale": (0.2, 5.0),
}


# ---------------------------------------------------------------------------
# File
# ---------------------------------------------------------------------------


def load(path: str | Path = DEFAULT_PATH) -> Calibration | None:
    """The calibration in `path`, or None if there is no file. A corrupt file (not JSON, wrong
    version or types, values outside sane limits) logs a warning and also gives None."""
    path = Path(path)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        if not isinstance(data, dict):
            raise ValueError("not a JSON object")
        if data.get("version") != FILE_VERSION:
            raise ValueError(f"version {data.get('version')!r}, expected {FILE_VERSION}")
        known = {f.name for f in fields(Calibration)}
        cal = Calibration(**{k: v for k, v in data.items() if k in known and v is not None})
        problems = cal.problems()
        if problems:
            raise ValueError("; ".join(problems))
    except (OSError, ValueError, TypeError) as e:
        log.warning("calibration: ignoring %s (%s); using the defaults", path, e)
        return None
    if isinstance(cal.marker_focal_scale, int):
        cal = replace(cal, marker_focal_scale=float(cal.marker_focal_scale))
    return cal


def save(cal: Calibration, path: str | Path = DEFAULT_PATH) -> Path:
    """Write `cal` to `path` (atomically: a crash never leaves half a file). Raises ValueError
    on values load() would reject."""
    problems = cal.problems()
    if problems:
        raise ValueError("calibration not saved: " + "; ".join(problems))
    path = Path(path)
    data = {"version": FILE_VERSION, **asdict(cal)}
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".calibration-", suffix=".json", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return path


# ---------------------------------------------------------------------------
# Applying it (pure)
# ---------------------------------------------------------------------------


def _set(cal: Calibration | None, names: Iterable[str]) -> dict[str, float]:
    if cal is None:
        return {}
    return {n: float(v) for n in names if (v := getattr(cal, n)) is not None}


def camera_geometry(cal: Calibration | None, base: CameraGeometry = CameraGeometry()) -> CameraGeometry:
    """`base` with the measured height, tilt and FOVs."""
    return replace(base, **_set(cal, ("height_m", "tilt_deg", "vfov_deg", "hfov_deg")))


def follow_config(cal: Calibration | None, base: FollowConfig = FollowConfig()) -> FollowConfig:
    """`base` with the measured camera geometry and distance cues (k_shoulder_m, target_box_w,
    d_target_m, too_close_box_w). Everything else (gains, modes) stays as in `base`."""
    return replace(
        base,
        camera=camera_geometry(cal, base.camera),
        **_set(cal, ("k_shoulder_m", "target_box_w", "d_target_m", "too_close_box_w")),
    )


def marker_kwargs(cal: Calibration | None, base: CameraGeometry = CameraGeometry()) -> dict[str, Any]:
    """Keyword arguments for MarkerDetector: geometry (with the measured hfov), focal_scale and,
    if measured, marker_size_m. Pass all of them: focal_scale is relative to this geometry."""
    kwargs: dict[str, Any] = {"geometry": camera_geometry(cal, base)}
    if cal is not None:
        kwargs["focal_scale"] = float(cal.marker_focal_scale)
        if cal.marker_size_m is not None:
            kwargs["marker_size_m"] = float(cal.marker_size_m)
    return kwargs


def lock_config(cal: Calibration | None, base: LockConfig | None = None) -> LockConfig:
    """The target lock's config (tracking.LockConfig) with the measured hfov (it turns the
    robot's own rotation into image motion)."""
    from app.vision.tracking import LockConfig

    base = LockConfig() if base is None else base
    return replace(base, **_set(cal, ("hfov_deg",)))


# ---------------------------------------------------------------------------
# Measurement math (pure; see the module docstring)
# ---------------------------------------------------------------------------


def hfov_from_marker_reading(read_m: float, true_m: float, base_hfov_deg: float) -> float:
    """The real hfov (deg), given a marker the detector read at `read_m` (with hfov
    `base_hfov_deg` and focal_scale 1) while it was really `true_m` away."""
    if read_m <= 0 or true_m <= 0:
        raise ValueError("distances must be positive")
    half = math.tan(math.radians(base_hfov_deg) / 2.0) * read_m / true_m
    return math.degrees(2.0 * math.atan(half))


def vfov_from_hfov(hfov_deg: float, width_px: int, height_px: int) -> float:
    """Vertical FOV (deg) of a picture `width_px` x `height_px` (square pixels) with this hfov."""
    if width_px <= 0 or height_px <= 0:
        raise ValueError("picture size must be positive")
    return math.degrees(2.0 * math.atan(math.tan(math.radians(hfov_deg) / 2.0) * height_px / width_px))


def k_shoulder_from(samples: Iterable[tuple[float, float]]) -> float:
    """FollowConfig.k_shoulder_m from (distance m, shoulder gap) pairs: the mean of distance x gap."""
    products = [d * g for d, g in samples]
    if not products:
        raise ValueError("no shoulder samples")
    return sum(products) / len(products)


def box_width_at(samples: Iterable[tuple[float, float]], distance_m: float) -> float:
    """A person's box width at `distance_m`, from (distance m, box width) pairs.

    Two or more distances: least-squares w = a + b / d (exact through two points), so the
    width at a measured distance is the measured width. One distance: w = b / d."""
    pts = [(1.0 / d, w) for d, w in samples]
    if not pts:
        raise ValueError("no box samples")
    if distance_m <= 0:
        raise ValueError("distance must be positive")
    xs = [x for x, _ in pts]
    if max(xs) - min(xs) < 1e-6:  # one distance (maybe several captures of it)
        b = sum(w / x for x, w in pts) / len(pts)
        return b / distance_m
    n = len(pts)
    mx = sum(xs) / n
    my = sum(w for _, w in pts) / n
    b = sum((x - mx) * (w - my) for x, w in pts) / sum((x - mx) ** 2 for x in xs)
    a = my - b * mx
    return a + b / distance_m


def tilt_from_level_point(y: float, vfov_deg: float) -> float:
    """Camera pitch (deg, positive = UP) from the image row `y` (normalized, y down) of a point
    at the lens's own height."""
    return math.degrees(math.atan((y - 0.5) * 2.0 * math.tan(math.radians(vfov_deg) / 2.0)))
