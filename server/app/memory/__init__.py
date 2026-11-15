"""Miguel's memory in SQLite (server/miguel.db, git-ignored): facts, places and the day's events.

Was Grant's placeholder for world memory kept while the server runs (decisions 0014, 0039); now it
survives restarts.

Survives restarts (Alex's design, Sat night; it replaces the RAM-only world memory). One small file,
standard library only. Everything is read whole: it's a few KB, so it goes into every request to
Claude ("What Miguel knows") with no search step.

- facts:  key -> value, who set it and when. The agent's remember / recall / forget, the control
          page's memory page. `Memory.facts` is a dict-like view, so the ToolBox uses it as before.
- places: name -> marker id (printed ArUco card) and/or a description, with aliases. learn_place,
          the memory page; go_to and bring look markers up here (the env var PLACES only seeds it).
- events: what happened today (deliveries, check-ins, alerts, messages), for "Mom's day" in the
          family app.

People's saved looks stay in server/people.json (PeopleRegistry, #62) for now.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from collections.abc import Iterator, MutableMapping
from pathlib import Path
from typing import Any

DEFAULT_PATH = Path(__file__).resolve().parents[2] / "miguel.db"   # server/miguel.db

SCHEMA = """
CREATE TABLE IF NOT EXISTS facts (
    key TEXT PRIMARY KEY, value TEXT NOT NULL, source TEXT NOT NULL DEFAULT '', updated_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS places (
    name TEXT PRIMARY KEY, marker INTEGER, aliases TEXT NOT NULL DEFAULT '[]',
    description TEXT NOT NULL DEFAULT '', updated_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, at REAL NOT NULL, kind TEXT NOT NULL, title TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '', data TEXT NOT NULL DEFAULT '{}');
"""


class Memory:
    def __init__(self, path: str | Path = DEFAULT_PATH, *, seed_places: dict[str, int] | None = None,
                 seed_aliases: dict[str, str] | None = None):
        self.path = str(path)
        self._db = sqlite3.connect(self.path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock, self._db:
            self._db.executescript(SCHEMA)
        self.facts = Facts(self)
        if seed_places and not self.places():
            aliases: dict[str, list[str]] = {}
            for alias, name in (seed_aliases or {}).items():
                aliases.setdefault(name, []).append(alias)
            for name, marker in seed_places.items():
                self.set_place(name, marker=marker, aliases=aliases.get(name, []))

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def _q(self, sql: str, args: tuple = ()) -> list[sqlite3.Row]:
        with self._lock, self._db:
            return self._db.execute(sql, args).fetchall()

    # --- places ---------------------------------------------------------------------------------

    def places(self) -> list[dict[str, Any]]:
        return [{"name": r["name"], "marker": r["marker"], "aliases": json.loads(r["aliases"]),
                 "description": r["description"]} for r in self._q("SELECT * FROM places ORDER BY name")]

    def set_place(self, name: str, *, marker: int | None = None, aliases: list[str] | None = None,
                  description: str = "") -> dict[str, Any]:
        name = name.strip().lower()
        if not name:
            raise ValueError("a place needs a name")
        if marker is not None:   # one marker marks one place
            self._q("UPDATE places SET marker = NULL WHERE marker = ? AND name != ?", (marker, name))
        clean = sorted({a.strip().lower() for a in (aliases or []) if a.strip() and a.strip().lower() != name})
        self._q("INSERT INTO places (name, marker, aliases, description, updated_at) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(name) DO UPDATE SET marker = excluded.marker, aliases = excluded.aliases, "
                "description = excluded.description, updated_at = excluded.updated_at",
                (name, marker, json.dumps(clean), description.strip(), time.time()))
        return {"name": name, "marker": marker, "aliases": clean, "description": description.strip()}

    def delete_place(self, name: str) -> bool:
        return bool(self._q("DELETE FROM places WHERE name = ? RETURNING name", (name.strip().lower(),)))

    def find_place(self, said: str, *, with_marker: bool = False) -> dict[str, Any] | None:
        """A place by name or alias, forgiving: 'the medication station', 'Pills' and 'meds' all work.
        with_marker: only places that have a marker card (what go_to and bring can steer to)."""
        s = said.strip().lower()
        for prefix in ("the ", "my ", "your "):
            if s.startswith(prefix):
                s = s[len(prefix):]
        places = [p for p in self.places() if p["marker"] is not None or not with_marker]
        for p in places:
            if s == p["name"] or s in p["aliases"]:
                return p
        for p in places:   # "medication station" contains "station"; "water" in "water station"
            words = [p["name"], *p["aliases"]]
            if any(w and (w in s or s in w) for w in words):
                return p
        return None

    def marker_for(self, said: str) -> int | None:
        p = self.find_place(said, with_marker=True)
        return None if p is None else p["marker"]

    def place_for(self, marker: int) -> str | None:
        rows = self._q("SELECT name FROM places WHERE marker = ?", (marker,))
        return rows[0]["name"] if rows else None

    def known_places(self) -> list[str]:
        return [p["name"] for p in self.places()]

    # --- events ---------------------------------------------------------------------------------

    def add_event(self, kind: str, title: str, note: str = "", data: dict[str, Any] | None = None,
                  at: float | None = None) -> dict[str, Any]:
        at = time.time() if at is None else at
        rows = self._q("INSERT INTO events (at, kind, title, note, data) VALUES (?, ?, ?, ?, ?) RETURNING id",
                       (at, kind, title, note, json.dumps(data or {})))
        return {"id": rows[0]["id"], "at": at, "kind": kind, "title": title, "note": note, "data": data or {}}

    def events_since(self, since: float) -> list[dict[str, Any]]:
        return [{"id": r["id"], "at": r["at"], "kind": r["kind"], "title": r["title"], "note": r["note"],
                 "data": json.loads(r["data"])}
                for r in self._q("SELECT * FROM events WHERE at >= ? ORDER BY id", (since,))]

    def today(self) -> list[dict[str, Any]]:
        lt = time.localtime()
        midnight = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1))
        return self.events_since(midnight)

    # --- what goes to Claude ---------------------------------------------------------------------

    def summary(self, max_events: int = 8) -> str:
        places = [f"{p['name']}" + (f" (marker {p['marker']})" if p["marker"] is not None else "")
                  for p in self.places()]
        events = [f"{time.strftime('%H:%M', time.localtime(e['at']))} {e['title']}" for e in self.today()[-max_events:]]
        return (f"Places you know: {', '.join(places) or 'none yet'}. "
                f"Today so far: {'; '.join(events) or 'nothing logged yet'}.")


class Facts(MutableMapping[str, str]):
    """facts as a dict (insertion order = last updated first to last), so the ToolBox works unchanged."""

    def __init__(self, mem: Memory):
        self._mem = mem
        self.source = "agent"   # who the next write is from (the API sets "control page" around its writes)

    def __getitem__(self, key: str) -> str:
        rows = self._mem._q("SELECT value FROM facts WHERE key = ?", (key,))
        if not rows:
            raise KeyError(key)
        return rows[0]["value"]

    def __setitem__(self, key: str, value: str) -> None:
        self._mem._q("INSERT INTO facts (key, value, source, updated_at) VALUES (?, ?, ?, ?) ON CONFLICT(key) "
                     "DO UPDATE SET value = excluded.value, source = excluded.source, updated_at = excluded.updated_at",
                     (key, value, self.source, time.time()))

    def __delitem__(self, key: str) -> None:
        if not self._mem._q("DELETE FROM facts WHERE key = ? RETURNING key", (key,)):
            raise KeyError(key)

    def __iter__(self) -> Iterator[str]:
        return iter([r["key"] for r in self._mem._q("SELECT key FROM facts ORDER BY updated_at, key")])

    def __len__(self) -> int:
        return self._mem._q("SELECT COUNT(*) AS n FROM facts")[0]["n"]

    def rows(self) -> list[dict[str, Any]]:
        return [dict(r) for r in self._mem._q("SELECT * FROM facts ORDER BY updated_at DESC")]
