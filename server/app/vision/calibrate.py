"""Guided camera calibration (issue #62): about five minutes with a tape measure, one printed
marker and one person. It measures what follow.py and markers.py otherwise guess (the camera's
field of view, the shoulder and box-width distance cues, optionally the camera's tilt) and
writes server/calibration.json (git-ignored), which the server loads (app/vision/calibration.py).

    cd server
    uv run python -m app.vision.calibrate --source 0                      # camera 0, OpenCV window
    uv run python -m app.vision.calibrate --source phone                  # the iPhone (Continuity Camera)
    uv run python -m app.vision.calibrate --source clip.mp4 --no-window   # a clip, text only
    options: --marker-size-cm 15 (measure the printed black square with a ruler),
             --height-cm 40 (lens above the floor), --follow-distance-m 1.0, --rotate, --out PATH

Needs a camera only (no robot, no network). Use the SAME camera, orientation (--rotate) and
zoom the server uses: a field of view belongs to one picture. Print a marker first with
`uv run python -m app.vision.print_markers`. The steps (each shows live numbers; Space or Enter
captures about 1 s of frames, S skips, B goes back, Q quits without saving):

1. Marker at 1.00 m: tape the marker to a wall; put the camera 1.00 m from it (tape from the lens
   to the marker), the marker in the middle of the picture.  -> hfov_deg, vfov_deg
2. Person at 1.0 m, 3. person at 2.0 m: toes on a tape mark that far from the point under the lens,
   facing the robot, arms down.  -> k_shoulder_m, target_box_w (at the follow distance), too_close_box_w
4. Optional, tilt: a marker with its center at lens height, 2 m away, the robot held upright as it
   balances.  -> tilt_deg

Then the summary: Y or Enter saves, B goes back, Q quits without saving.

Frames with nothing to measure are rejected; a capture needs at least 3 usable frames and half
of the frames usable. The measuring is pure (Capture, Session, the readings below), so tests
feed it fake detections; run() is the camera and window loop around it.
"""

from __future__ import annotations

import argparse
import math
import queue
import statistics
import sys
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from app.vision import calibration as cal_mod
from app.vision.calibration import Calibration
from app.vision.follow import CameraGeometry, FollowConfig, shoulder_gap
from app.vision.types import Marker, Person

StepKind = Literal["marker", "person", "level"]
Phase = Literal["aim", "capturing", "review", "confirmed", "quit"]
Action = Literal["capture", "skip", "back", "save", "quit"]

CAPTURE_S = 1.0  # seconds of frames averaged per capture
MIN_USED = 3  # a capture needs at least this many usable frames...
MIN_FRACTION = 0.5  # ...and at least this fraction of its frames usable
UNSTEADY = 0.08  # relative spread (std / mean) above which a capture is flagged as unsteady
SIDE_EDGE = 0.02  # a person box this close to the left/right edge is cut off: its width is wrong
MAX_TOO_CLOSE_W = 0.95  # the box cue can't fire above ~1.0, so a wider extrapolation is capped
KEYS_HELP = "Space/Enter capture   S skip   B back   Q quit without saving"
REVIEW_KEYS = "Y/Enter save   B back   Q quit without saving"


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Step:
    key: str  # result key: "marker", "near", "far", "tilt"
    title: str
    how: tuple[str, ...]  # instructions, one short line each
    kind: StepKind  # what a frame is measured for
    distance_m: float  # the true distance the step is done at
    optional: bool = False


def default_steps(marker_m: float = 1.0, near_m: float = 1.0, far_m: float = 2.0, tilt_m: float = 2.0) -> tuple[Step, ...]:
    def person(key: str, d: float) -> Step:
        return Step(key, f"Person at {d:.1f} m", (
            f"One person stands with their toes {d:.1f} m from the point under the lens (tape mark),",
            "facing the robot, arms down, whole body width in the picture, nobody else close.",
        ), "person", d)

    return (
        Step("marker", f"Marker at {marker_m:.2f} m", (
            "Tape a printed marker flat on a wall. Put the camera exactly "
            f"{marker_m:.2f} m from it (tape from lens to marker),",
            "the marker in the middle of the picture, square on. Hold still while capturing.",
        ), "marker", marker_m),
        person("near", near_m),
        person("far", far_m),
        Step("tilt", "Tilt: marker at lens height", (
            "Tape a marker so its CENTER is exactly at lens height (tape measure from the floor).",
            f"Lens {tilt_m:.0f} m from the wall, the robot held upright the way it balances.",
        ), "level", tilt_m, optional=True),
    )


# ---------------------------------------------------------------------------
# Per-frame readings (pure)
# ---------------------------------------------------------------------------


def pick_marker(markers: Sequence[Marker], marker_id: int | None = None) -> Marker | None:
    """The marker to measure: `marker_id` if given, else the biggest one in view."""
    candidates = [m for m in markers if marker_id is None or m.id == marker_id]
    return max(candidates, key=lambda m: m.size) if candidates else None


def marker_values(m: Marker) -> dict[str, float]:
    values = {"cx": m.cx, "cy": m.cy, "size": m.size}
    if m.distance_m is not None:
        values["distance_m"] = m.distance_m
    return values


def pick_person(people: Sequence[Person]) -> Person | None:
    """The person to measure: the biggest box (the one standing on the mark)."""
    return max(people, key=lambda p: p.box.area) if people else None


def person_values(p: Person, min_conf: float = 0.5, side_edge: float = SIDE_EDGE) -> dict[str, float] | None:
    """Box width and shoulder gap of `p`, or None if the frame can't measure them: a shoulder
    missing or unsure (turned, occluded) or the box cut off at the left/right edge."""
    gap = shoulder_gap(p, min_conf)
    if gap is None or p.box.x1 < side_edge or p.box.x2 > 1.0 - side_edge:
        return None
    return {"box_w": p.box.w, "gap": gap, "cx": p.box.cx}


class CaptureError(ValueError):
    """A capture had too few usable frames."""


@dataclass(frozen=True)
class CaptureResult:
    mean: dict[str, float]
    std: dict[str, float]
    used: int  # frames that had something to measure
    frames: int  # frames seen

    def spread(self, name: str) -> float:
        """Relative spread std / |mean| of one value (0 if the mean is 0)."""
        m = self.mean[name]
        return self.std[name] / abs(m) if m else 0.0


class Capture:
    """Collects about `duration_s` of per-frame readings (None = nothing to measure in that frame,
    rejected) and averages them. Times are Frame.t, so clips and fakes behave like a camera."""

    def __init__(self, duration_s: float = CAPTURE_S, min_used: int = MIN_USED, min_fraction: float = MIN_FRACTION) -> None:
        self.duration_s = duration_s
        self.min_used = min_used
        self.min_fraction = min_fraction
        self.frames = 0
        self.values: list[dict[str, float]] = []
        self._t0: float | None = None
        self._t = 0.0

    def add(self, t: float, values: Mapping[str, float] | None) -> None:
        if self._t0 is None:
            self._t0 = t
        self._t = t
        self.frames += 1
        if values is not None:
            self.values.append(dict(values))

    @property
    def elapsed_s(self) -> float:
        return 0.0 if self._t0 is None else self._t - self._t0

    @property
    def done(self) -> bool:
        return self._t0 is not None and self.elapsed_s >= self.duration_s

    def result(self) -> CaptureResult:
        used = len(self.values)
        if used == 0 or used < self.min_used or used < self.min_fraction * self.frames:
            raise CaptureError(f"only {used} of {self.frames} frames had something to measure")
        names = set.intersection(*(set(v) for v in self.values))
        mean = {n: statistics.fmean(v[n] for v in self.values) for n in names}
        std = {n: statistics.pstdev([v[n] for v in self.values]) for n in names}
        return CaptureResult(mean, std, used, self.frames)


# ---------------------------------------------------------------------------
# The guided run as a state machine (pure: frames and keys in, text and a Calibration out)
# ---------------------------------------------------------------------------


class Session:
    """Walks through `steps`. Call feed() once per frame and press() for each key."""

    def __init__(
        self,
        steps: Sequence[Step] = default_steps(),
        *,
        marker_size_m: float = 0.15,
        base: CameraGeometry = CameraGeometry(),
        follow_distance_m: float = FollowConfig().d_target_m,
        too_close_m: float = FollowConfig().d_min_m,
        height_m: float | None = None,
        marker_id: int | None = None,
        capture_s: float = CAPTURE_S,
        min_used: int = MIN_USED,
        source_note: str = "",
        now: Callable[[], datetime] = lambda: datetime.now().astimezone(),
    ) -> None:
        self.steps = tuple(steps)
        self.marker_size_m = marker_size_m
        self.base = base
        self.follow_distance_m = follow_distance_m
        self.too_close_m = too_close_m
        self.height_m = height_m
        self.marker_id = marker_id
        self.capture_s = capture_s
        self.min_used = min_used
        self.source_note = source_note
        self._now = now

        self.index = 0
        self.phase: Phase = "aim" if self.steps else "review"
        self.results: dict[str, CaptureResult] = {}
        self.skipped: set[str] = set()
        self.live: dict[str, float] | None = None  # this frame's reading for the current step
        self.live_id: int | None = None  # marker id of that reading
        self.message = ""  # last event, shown under the live numbers
        self.size: tuple[int, int] | None = None  # picture width, height (pixels)
        self._capture: Capture | None = None
        self._capture_id: int | None = None  # a capture sticks to the marker it started on

    # --- state ---

    @property
    def step(self) -> Step | None:
        return self.steps[self.index] if self.phase in ("aim", "capturing") else None

    @property
    def needs_people(self) -> bool:
        """The current step measures people (run the pose detector)."""
        return self.step is not None and self.step.kind == "person"

    @property
    def finished(self) -> bool:
        return self.phase in ("confirmed", "quit")

    def _step(self, key: str) -> Step | None:
        return next((s for s in self.steps if s.key == key), None)

    # --- input ---

    def feed(self, t: float, markers: Sequence[Marker], people: Sequence[Person], width: int, height: int) -> None:
        """One frame's detections (`people` may be empty outside person steps)."""
        self.size = (width, height)
        step = self.step
        self.live, self.live_id = None, None
        if step is None:
            return
        if step.kind == "person":
            p = pick_person(people)
            self.live = None if p is None else person_values(p)
        else:
            m = pick_marker(markers, self._capture_id if self.phase == "capturing" else self.marker_id)
            if m is not None and (step.kind != "marker" or m.distance_m is not None):
                self.live, self.live_id = marker_values(m), m.id
        if self.phase == "capturing" and self._capture is not None:
            self._capture.add(t, self.live)
            if self._capture.done:
                self._finish_capture(step)

    def press(self, action: Action) -> None:
        if action == "quit":
            self.phase = "quit"
        elif self.phase == "capturing":
            if action in ("back", "skip"):
                self.phase, self._capture = "aim", None
                self.message = "capture cancelled"
        elif self.phase == "aim":
            step = self.steps[self.index]
            if action == "capture":
                self._capture = Capture(self.capture_s, self.min_used)
                self._capture_id = self.live_id if step.kind != "person" else None
                self.phase = "capturing"
                self.message = "capturing: hold still"
            elif action == "skip":
                self.results.pop(step.key, None)
                self.skipped.add(step.key)
                self.message = f"skipped: {step.title}"
                self._advance()
            elif action == "back" and self.index > 0:
                self.index -= 1
                self.live, self.live_id, self.message = None, None, ""
        elif self.phase == "review":
            if action in ("save", "capture"):
                problems = self.problems()
                if problems:
                    self.message = "can't save: " + "; ".join(problems)
                else:
                    self.phase = "confirmed"
            elif action == "back" and self.steps:
                self.index, self.phase, self.message = len(self.steps) - 1, "aim", ""
                self.live, self.live_id = None, None

    def _advance(self) -> None:
        self.live, self.live_id = None, None  # the reading was for the step just finished
        self.index += 1
        if self.index >= len(self.steps):
            self.index, self.phase = len(self.steps) - 1, "review"
        else:
            self.phase = "aim"

    def _finish_capture(self, step: Step) -> None:
        assert self._capture is not None
        try:
            res = self._capture.result()
        except CaptureError as e:
            self.phase, self._capture = "aim", None
            self.message = f"capture failed: {e}. Fix the view and press Space again."
            return
        self._capture = None
        self.results[step.key] = res
        self.skipped.discard(step.key)
        main = {"marker": "distance_m", "person": "gap", "level": "cy"}[step.kind]
        unsteady = main in res.mean and res.spread(main) > UNSTEADY
        self.message = f"captured {step.title}: {res.used} of {res.frames} frames" + (
            " (unsteady: B and Space to redo)" if unsteady else "")
        self._advance()

    # --- output ---

    def _fovs(self) -> tuple[float | None, float | None]:
        """Measured (hfov, vfov), or (None, None) before the marker step."""
        res, step = self.results.get("marker"), self._step("marker")
        if res is None or step is None or self.size is None or "distance_m" not in res.mean:
            return None, None
        hfov = cal_mod.hfov_from_marker_reading(res.mean["distance_m"], step.distance_m, self.base.hfov_deg)
        return hfov, cal_mod.vfov_from_hfov(hfov, *self.size)

    def _person_samples(self, name: str) -> list[tuple[float, float]]:
        return [(s.distance_m, self.results[s.key].mean[name]) for s in self.steps
                if s.kind == "person" and s.key in self.results and name in self.results[s.key].mean]

    def calibration(self) -> Calibration:
        """What the captures so far measure (fields of skipped steps stay None)."""
        values: dict[str, Any] = {"marker_size_m": self.marker_size_m}
        notes = [self.source_note] if self.source_note else []
        if self.size is not None:
            notes.append(f"picture {self.size[0]}x{self.size[1]}")
        hfov, vfov = self._fovs()
        if hfov is not None and vfov is not None:
            values.update(hfov_deg=round(hfov, 2), vfov_deg=round(vfov, 2), marker_focal_scale=1.0)
            notes.append(f"marker read {self.results['marker'].mean['distance_m']:.3f} m at "
                         f"{self._step('marker').distance_m:.2f} m with hfov {self.base.hfov_deg:g}")  # type: ignore[union-attr]
        gaps, widths = self._person_samples("gap"), self._person_samples("box_w")
        if gaps:
            values["k_shoulder_m"] = round(cal_mod.k_shoulder_from(gaps), 4)
            target = cal_mod.box_width_at(widths, self.follow_distance_m)
            too_close = min(MAX_TOO_CLOSE_W, cal_mod.box_width_at(widths, self.too_close_m))
            values.update(target_box_w=round(target, 4), d_target_m=self.follow_distance_m,
                          too_close_box_w=round(too_close, 4))
            notes.append("person " + ", ".join(f"{d:.1f} m: box {w:.3f} gap {g:.3f}"
                                               for (d, w), (_, g) in zip(widths, gaps)))
            notes.append(f"too_close_box_w at {self.too_close_m:.2f} m")
        tilt = self.results.get("tilt")
        if tilt is not None:
            v = vfov if vfov is not None else self.base.vfov_deg
            values["tilt_deg"] = round(cal_mod.tilt_from_level_point(tilt.mean["cy"], v), 2)
            notes.append(f"tilt marker at row {tilt.mean['cy']:.3f}")
        if self.height_m is not None:
            values["height_m"] = self.height_m
        return Calibration(**values, measured_at=self._now().isoformat(timespec="seconds"), notes="; ".join(notes))

    def problems(self) -> list[str]:
        if not self.results and self.height_m is None:
            return ["nothing measured (B goes back)"]
        return self.calibration().problems()

    def live_text(self) -> str:
        """The live measurement line for the current step."""
        step = self.step
        if step is None:
            return ""
        v = self.live
        if step.kind == "person":
            if v is None:
                return "no person with both shoulders in view (face the camera, arms down, not cut off)"
            return (f"box width {v['box_w']:.3f}   shoulder gap {v['gap']:.3f}   "
                    f"-> k_shoulder {step.distance_m * v['gap']:.3f} m")
        if v is None:
            return "no marker in view" + (f" (looking for id {self.marker_id})" if self.marker_id is not None else "")
        if step.kind == "marker":
            hfov = cal_mod.hfov_from_marker_reading(v["distance_m"], step.distance_m, self.base.hfov_deg)
            extra = ""
            if self.size is not None:
                extra = f", vfov {cal_mod.vfov_from_hfov(hfov, *self.size):.1f}"
            return (f"marker {self.live_id}: reads {v['distance_m']:.3f} m with the {self.base.hfov_deg:g} deg guess"
                    f" -> hfov {hfov:.1f}{extra} deg")
        vfov = self._fovs()[1] or self.base.vfov_deg
        tilt = cal_mod.tilt_from_level_point(v["cy"], vfov)
        return f"marker {self.live_id} at row {v['cy']:.3f} -> tilt {tilt:+.1f} deg ({'up' if tilt >= 0 else 'down'})"

    def lines(self) -> list[tuple[str, str]]:
        """What to show now, as (text, kind); kind: title, how, live, none, note, keys."""
        step = self.step
        if step is None:
            return self.summary_lines()
        title = f"Step {self.index + 1}/{len(self.steps)}: {step.title}" + (" (optional, S skips)" if step.optional else "")
        out = [(title, "title"), *((h, "how") for h in step.how), (self.live_text(), "live" if self.live else "none")]
        if self.phase == "capturing" and self._capture is not None:
            c = self._capture
            out.append((f"capturing {c.elapsed_s:.1f}/{c.duration_s:.1f} s: {len(c.values)} of {c.frames} frames usable", "note"))
        elif self.message:
            out.append((self.message, "note"))
        out.append((KEYS_HELP, "keys"))
        return out

    def summary_lines(self) -> list[tuple[str, str]]:
        cal = self.calibration()
        geo, fc = CameraGeometry(), FollowConfig()
        rows = [
            ("hfov_deg", cal.hfov_deg, geo.hfov_deg, ".2f", ""),
            ("vfov_deg", cal.vfov_deg, geo.vfov_deg, ".2f", ""),
            ("tilt_deg", cal.tilt_deg, geo.tilt_deg, "+.2f", "positive = up"),
            ("height_m", cal.height_m, geo.height_m, ".3f", "--height-cm"),
            ("k_shoulder_m", cal.k_shoulder_m, fc.k_shoulder_m, ".4f", ""),
            ("target_box_w", cal.target_box_w, fc.target_box_w, ".4f", f"at {self.follow_distance_m:.2f} m"),
            ("too_close_box_w", cal.too_close_box_w, fc.too_close_w, ".4f", f"at {self.too_close_m:.2f} m"),
            ("marker_size_m", cal.marker_size_m, 0.15, ".3f", "--marker-size-cm"),
        ]
        out = [("Calibration to save:", "title")]
        for name, value, default, fmt, note in rows:
            shown = "not measured" if value is None else format(value, fmt)
            out.append((f"  {name:<16} {shown:>12}   (default {default:g}) {note}".rstrip(),
                        "live" if value is not None else "none"))
        if self.skipped:
            out.append(("skipped: " + ", ".join(s.title for s in self.steps if s.key in self.skipped), "none"))
        if self.message and not self.message.startswith("skipped"):
            out.append((self.message, "note"))
        out.append((REVIEW_KEYS, "keys"))
        return out


# ---------------------------------------------------------------------------
# Camera, window and keyboard
# ---------------------------------------------------------------------------


def resolve_source(spec: str, camera_names: Sequence[str] | None = None) -> str:
    """"phone" -> the OpenCV index of the iPhone (Continuity Camera) by its place in macOS's
    camera list; anything else unchanged. OpenCV's order usually but not always matches macOS's,
    so check the picture (or pass the index)."""
    if spec.strip().lower() != "phone":
        return spec
    if camera_names is None:
        from app.vision.frames import macos_camera_names

        camera_names = macos_camera_names()
    for i, name in enumerate(camera_names):
        if "iphone" in name.lower():
            return str(i)
    raise ValueError("No iPhone camera found (Continuity Camera: phone near the Mac, same Apple ID, "
                     f"Wi-Fi and Bluetooth on). Cameras: {list(camera_names) or 'none'}. Pass --source <index>.")


def key_action(code: int, phase: Phase) -> Action | None:
    """An OpenCV waitKey code -> an action (None for no key / other keys)."""
    if code < 0:
        return None
    c = code & 0xFF
    if c in (13, 10, 32):
        return "save" if phase == "review" else "capture"
    if c == 27:
        return "quit"
    return {"s": "skip", "b": "back", "q": "quit", "y": "save"}.get(chr(c).lower())


def text_action(line: str, phase: Phase) -> Action | None:
    """A typed line (text mode) -> an action: Enter, s, b, q, y."""
    cmd = line.strip().lower()
    if cmd == "":
        return "save" if phase == "review" else "capture"
    return {"s": "skip", "b": "back", "q": "quit", "y": "save", "c": "capture"}.get(cmd[0])


def _stdin_lines() -> queue.Queue[str]:
    q: queue.Queue[str] = queue.Queue()

    def reader() -> None:
        for line in sys.stdin:
            q.put(line)
        q.put("q")  # end of input quits

    threading.Thread(target=reader, name="calibrate-stdin", daemon=True).start()
    return q


def draw(image: Any, session: Session, markers: Sequence[Marker], people: Sequence[Person], max_width: int = 1280) -> Any:
    """The frame with the markers, the measured person and the session's text drawn on it."""
    import cv2

    from app.vision.debug_view import GRAY, GREEN, ORANGE, WHITE, YELLOW, draw_markers, draw_person, draw_text

    h, w = image.shape[:2]
    img = cv2.resize(image, (max_width, int(h * max_width / w)), interpolation=cv2.INTER_AREA) if w > max_width else image.copy()
    draw_markers(img, markers)
    if session.needs_people:
        picked = pick_person(people)
        for p in people:
            if p is not picked:
                draw_person(img, p, GRAY, 2)
        if picked is not None:
            draw_person(img, picked, GREEN if session.live else ORANGE, 4)
    colors = {"title": YELLOW, "how": WHITE, "live": GREEN, "none": ORANGE, "note": YELLOW, "keys": GRAY}
    scale = max(0.45, min(0.75, img.shape[1] / 1700))
    draw_text(img, [(text, colors[kind]) for text, kind in session.lines()], scale)
    return img


def run(
    source: Any,
    session: Session,
    *,
    out_path: Path = cal_mod.DEFAULT_PATH,
    window: bool = True,
    marker_detector: Any = None,
    pose_factory: Callable[[], Any] | None = None,
    print_every_s: float = 1.0,
) -> Calibration | None:
    """Run `session` on a started FrameSource until it's saved or quit. Returns what was saved."""
    from app.vision.markers import MarkerDetector

    if marker_detector is None:
        marker_detector = MarkerDetector(marker_size_m=session.marker_size_m, geometry=session.base)
    if pose_factory is None:
        from app.vision.detector import YoloPoseDetector

        pose_factory = YoloPoseDetector
    pose: Any = None
    pose_failed = False
    win = None
    if window:
        from app.vision.debug_view import DebugWindow

        win = DebugWindow("Miguel.exe calibration")
    typed = None if window else _stdin_lines()
    last_img: Any = None
    shown: tuple[Any, ...] = ()  # (step index, review?) the text mode last printed in full
    shown_message = ""
    last_print = 0.0

    def say(lines: list[tuple[str, str]]) -> None:
        for text, _ in lines:
            print(text, flush=True)

    try:
        while not session.finished:
            frame = source.read_next(timeout=0.5)
            if frame is None:
                if source.ended:
                    print("The camera or clip ended.", flush=True)
                    break
                if win is not None:
                    action = key_action(win.show(last_img if last_img is not None else _blank()), session.phase)
                    if action:
                        session.press(action)
                continue

            people: list[Person] = []
            if session.needs_people and pose is None and not pose_failed:
                print("Loading the pose model ...", flush=True)
                try:
                    pose = pose_factory()
                except (FileNotFoundError, ImportError, ValueError) as e:
                    pose_failed = True
                    session.message = f"no pose model ({e}); S skips the person steps"
            if session.needs_people and pose is not None:
                people = pose.detect(frame).people
            markers = marker_detector.detect(frame.image)
            session.feed(frame.t, markers, people, frame.width, frame.height)

            if win is not None:
                last_img = draw(frame.image, session, markers, people)
                action = key_action(win.show(last_img), session.phase)
            else:
                state = (session.index, session.phase == "review")
                if state != shown:
                    shown, shown_message = state, session.message
                    print(flush=True)
                    say(session.lines())
                    print("(type Enter to " + ("save" if session.phase == "review" else "capture")
                          + ", s skip, b back, q quit)", flush=True)
                elif session.message != shown_message:
                    shown_message = session.message
                    print(session.message, flush=True)
                elif session.phase in ("aim", "capturing") and time.monotonic() - last_print >= print_every_s:
                    last_print = time.monotonic()
                    print("  " + session.live_text(), flush=True)
                action = None
                assert typed is not None
                while action is None and not typed.empty():
                    action = text_action(typed.get(), session.phase)
            if action:
                session.press(action)
    except KeyboardInterrupt:
        session.press("quit")
    finally:
        if win is not None:
            win.close()

    if session.phase != "confirmed":
        print("Not saved.", flush=True)
        return None
    cal = session.calibration()
    path = cal_mod.save(cal, out_path)
    if window:  # text mode already printed the summary
        say(session.summary_lines()[:-1])
    print(f"Saved {path}. The server uses it from its next start.", flush=True)
    return cal


def _blank() -> Any:
    import numpy as np

    return np.zeros((360, 640, 3), np.uint8)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="python -m app.vision.calibrate",
                                 description="Guided camera calibration: writes server/calibration.json")
    ap.add_argument("--source", default="0",
                    help="camera index (0, 1, ...), 'phone' (the iPhone over Continuity Camera) or a video file")
    ap.add_argument("--rotate", choices=["left", "right", "180"], default=None,
                    help="turn the picture, as the server's --rotate (must match it)")
    ap.add_argument("--marker-size-cm", type=float, default=15.0,
                    help="side of the printed black square, measured with a ruler (default 15)")
    ap.add_argument("--marker-id", type=int, default=None, help="only measure this marker id (default: the biggest)")
    ap.add_argument("--height-cm", type=float, default=None, help="lens height above the floor (tape), saved as height_m")
    ap.add_argument("--follow-distance-m", type=float, default=FollowConfig().d_target_m,
                    help="where the robot keeps the person; target_box_w is read there (default 1.0)")
    ap.add_argument("--no-window", action="store_true", help="text only: type Enter / s / b / q / y")
    ap.add_argument("--out", type=Path, default=cal_mod.DEFAULT_PATH, help="where to save (default server/calibration.json)")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    for name in ("marker_size_cm", "follow_distance_m"):
        if not getattr(args, name) > 0 or not math.isfinite(getattr(args, name)):
            raise SystemExit(f"--{name.replace('_', '-')} must be positive")
    from app.vision.frames import FrameSourceError, open_source

    try:
        spec = resolve_source(args.source)
    except ValueError as e:
        print(e, file=sys.stderr)
        return 2
    note = f"source {args.source}" + (f" (camera {spec})" if spec != args.source else "") + f", rotate {args.rotate or 'none'}"
    if spec != args.source:
        print(f"Using camera {spec} for the iPhone. If the window shows another camera, pass --source <index>.")
    kw: dict[str, Any] = {"rotate": args.rotate}
    if not (spec.isascii() and spec.isdigit()):
        kw["loop"] = True  # a clip plays over and over, so every step can be captured from it
    session = Session(
        default_steps(),
        marker_size_m=args.marker_size_cm / 100.0,
        follow_distance_m=args.follow_distance_m,
        height_m=None if args.height_cm is None else args.height_cm / 100.0,
        marker_id=args.marker_id,
        source_note=note,
    )
    try:
        with open_source(spec, **kw) as src:
            saved = run(src, session, out_path=args.out, window=not args.no_window)
    except (FrameSourceError, FileNotFoundError) as e:
        print(e, file=sys.stderr)
        return 2
    return 0 if saved is not None else 1


if __name__ == "__main__":
    sys.exit(main())
