"""Saved looks for people: "this is Mom", then later "go find Mom" (issue #55).

A person's look is the same torso + legs color histograms the target lock uses
(app/vision/tracking.py `BodyParts`), compared with `parts_distance` (Bhattacharyya
distance, 0 = same colors, 1 = nothing in common). This recognizes CLOTHES, not faces:
it works for the same outfit on the same day, and fails after a change of clothes or under
very different light. Saved looks persist to server/people.json (git-ignored) so they
survive a restart; save again to refresh one.

    registry = PeopleRegistry()                         # loads server/people.json
    registry.save_from_lock("Mom", target_lock)         # while following her
    hit = registry.match(parts)                         # ("Mom", 0.21) or None
    hit = registry.match(parts, name="mom")             # only consider Mom
    hit = registry.match_person(image, person, people)  # histograms + match in one call

Thread-safe: every method takes one lock, so the vision thread and the asyncio loop can
share a registry. Names are matched case-insensitively and returned as first saved.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Protocol

import numpy as np

from app.vision.tracking import BodyParts, LockConfig, body_part_histograms, parts_distance
from app.vision.types import Person

log = logging.getLogger(__name__)

DEFAULT_PATH = Path(__file__).resolve().parents[2] / "people.json"  # server/people.json
# Accept a match at or below this distance. Same as LockConfig.max_dist_lost, the lock's
# strict "is this the person I lost?" threshold (a guess there too; tune on real video).
DEFAULT_MAX_DIST = LockConfig().max_dist_lost
FILE_VERSION = 1


class HasAppearance(Protocol):
    """What save_from_lock needs: app.vision.tracking.TargetLock fits."""

    @property
    def appearance_model(self) -> BodyParts | None: ...


class PeopleRegistry:
    """Named appearance models, persisted to a JSON file (path=None keeps them in memory only)."""

    def __init__(
        self,
        path: str | Path | None = DEFAULT_PATH,
        *,
        max_dist: float = DEFAULT_MAX_DIST,
        config: LockConfig = LockConfig(),
    ) -> None:
        self.path = None if path is None else Path(path)
        self.max_dist = max_dist
        self.config = config
        self._lock = threading.RLock()
        self._people: dict[str, tuple[str, BodyParts]] = {}  # key (lowercase) -> (display name, look)
        self._load()

    # --- edit ---

    def save(self, name: str, parts: BodyParts) -> None:
        """Remember (or replace) what `name` looks like, and write the file."""
        key = _key(name)
        if not key:
            raise ValueError("a person needs a non-empty name")
        if parts.torso is None and parts.legs is None:
            raise ValueError("nothing to save: neither torso nor legs is visible")
        with self._lock:
            self._people[key] = (name.strip(), parts.copy())
            self._write()

    def save_from_lock(self, name: str, lock: HasAppearance) -> BodyParts:
        """Save the lock's current appearance model (the person being followed) as `name`.

        Raises ValueError if the lock has no model (not locked onto anyone)."""
        model = lock.appearance_model
        if model is None:
            raise ValueError("the target lock isn't following anyone, so there's no look to save")
        self.save(name, model)
        return model

    def forget(self, name: str) -> bool:
        """Delete a saved look. Returns False if there was none."""
        with self._lock:
            if self._people.pop(_key(name), None) is None:
                return False
            self._write()
            return True

    # --- read ---

    def names(self) -> list[str]:
        """Saved names, as first written, in save order."""
        with self._lock:
            return [display for display, _ in self._people.values()]

    def get(self, name: str) -> BodyParts | None:
        """A copy of the saved look, or None."""
        with self._lock:
            entry = self._people.get(_key(name))
            return None if entry is None else entry[1].copy()

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and self.get(name) is not None

    def match(
        self, parts: BodyParts, name: str | None = None, max_dist: float | None = None
    ) -> tuple[str, float] | None:
        """The saved person who looks most like `parts`, as (name, distance), if within `max_dist`.

        `name` restricts the search to that one person (None if unknown or too different).
        Distance is `parts_distance` over the parts visible in both; looks that share no
        visible part with `parts` never match."""
        limit = self.max_dist if max_dist is None else max_dist
        with self._lock:
            if name is not None:
                entry = self._people.get(_key(name))
                candidates = [] if entry is None else [entry]
            else:
                candidates = list(self._people.values())
            best: tuple[str, float] | None = None
            for display, look in candidates:
                d = parts_distance(look, parts, self.config)
                if d is not None and d <= limit and (best is None or d < best[1]):
                    best = (display, d)
            return best

    def match_person(
        self,
        image: np.ndarray,
        person: Person,
        people: Iterable[Person] = (),
        name: str | None = None,
        max_dist: float | None = None,
    ) -> tuple[str, float] | None:
        """Histogram `person` in `image` (masking `people` in front of them), then match()."""
        parts = body_part_histograms(image, person, people, self.config)
        return None if parts is None else self.match(parts, name=name, max_dist=max_dist)

    # --- file ---

    def reload(self) -> None:
        """Re-read the file (drops unsaved in-memory state; there is none, saves write through)."""
        with self._lock:
            self._people.clear()
            self._load()

    def _load(self) -> None:
        if self.path is None or not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text())
            for entry in data.get("people", []):
                display = str(entry["name"])
                parts = BodyParts(
                    torso=_array(entry.get("torso")),
                    legs=_array(entry.get("legs")),
                    torso_px=int(entry.get("torso_px", 0)),
                    legs_px=int(entry.get("legs_px", 0)),
                )
                if _key(display) and (parts.torso is not None or parts.legs is not None):
                    self._people[_key(display)] = (display, parts)
        except (OSError, ValueError, KeyError, TypeError) as e:
            log.warning("people registry: couldn't read %s (%s); starting empty", self.path, e)
            self._people.clear()

    def _write(self) -> None:
        if self.path is None:
            return
        data = {
            "version": FILE_VERSION,
            "saved_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "people": [
                {
                    "name": display,
                    "torso": None if p.torso is None else [float(x) for x in p.torso],
                    "legs": None if p.legs is None else [float(x) for x in p.legs],
                    "torso_px": int(p.torso_px),
                    "legs_px": int(p.legs_px),
                }
                for display, p in self._people.values()
            ],
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".people-", suffix=".json", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(data, f)
            os.replace(tmp, self.path)  # atomic: a crash mid-write never leaves a half file
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise


def _key(name: str) -> str:
    return " ".join(name.strip().lower().split())


def _array(values: list[float] | None) -> np.ndarray | None:
    return None if values is None else np.asarray(values, dtype=np.float32)
