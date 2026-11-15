"""Which printed marker marks which place (issue #55).

    marker_for("medication station")  -> 1
    marker_for("Pills")               -> 1   (aliases, case-insensitive)
    place_for(1)                      -> "station"
    place_for(42)                     -> None

The default mapping is PLACES. Override it with the env var PLACES, e.g.
PLACES="station=1,couch=2,bedroom=5" (replaces the whole mapping; names are lowercased).
Print the markers with `uv run python -m app.vision.print_markers`.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

PLACES: dict[str, int] = {"station": 1, "couch": 2, "door": 3, "kitchen": 4}

# Other ways people say a place -> its canonical name. Aliases of places missing from the
# active mapping are ignored.
ALIASES: dict[str, str] = {
    "medication station": "station",
    "medicine station": "station",
    "medication": "station",
    "medicine": "station",
    "meds": "station",
    "pills": "station",
    "pill station": "station",
    "sofa": "couch",
    "front door": "door",
    "entrance": "door",
}

ENV_VAR = "PLACES"


def parse_places(spec: str) -> dict[str, int]:
    """Parse "station=1,couch=2" into {"station": 1, "couch": 2}. Raises ValueError if malformed."""
    places: dict[str, int] = {}
    for item in spec.split(","):
        item = item.strip()
        if not item:
            continue
        name, sep, value = item.partition("=")
        name = _norm(name)
        if not sep or not name:
            raise ValueError(f"bad {ENV_VAR} entry {item!r}: expected name=id")
        try:
            places[name] = int(value.strip())
        except ValueError:
            raise ValueError(f"bad {ENV_VAR} entry {item!r}: id must be an integer") from None
    return places


def places(env: Mapping[str, str] | None = None) -> dict[str, int]:
    """The active place -> marker id mapping: $PLACES if set and non-empty, else PLACES."""
    spec = (os.environ if env is None else env).get(ENV_VAR, "").strip()
    return parse_places(spec) if spec else dict(PLACES)


def canonical(place: str, env: Mapping[str, str] | None = None) -> str | None:
    """The canonical place name for a name or alias ("Pills" -> "station"), or None if unknown."""
    mapping = places(env)
    name = _norm(place)
    for candidate in (name, _strip_article(name)):
        if candidate in mapping:
            return candidate
        alias = ALIASES.get(candidate)
        if alias is not None and alias in mapping:
            return alias
    return None


def marker_for(place: str, env: Mapping[str, str] | None = None) -> int | None:
    """The marker id of a place (name or alias, any case), or None if it isn't a known place."""
    name = canonical(place, env)
    return None if name is None else places(env)[name]


def place_for(marker_id: int, env: Mapping[str, str] | None = None) -> str | None:
    """The canonical place name a marker id stands for, or None if no place uses it."""
    for name, mid in places(env).items():
        if mid == marker_id:
            return name
    return None


def _norm(s: str) -> str:
    return " ".join(s.strip().lower().replace("_", " ").split())


def _strip_article(s: str) -> str:
    for article in ("the ", "my ", "a "):
        if s.startswith(article):
            return s[len(article):]
    return s
