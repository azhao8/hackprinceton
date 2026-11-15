"""Arbiter (owner: Alex): the one place that decides what the robot is told to do.

Priority: e-stop > manual joystick > skill (CLAUDE.md). Everything that wants the robot to move
*requests* a speed and turn here; the robot link sends whatever `decide()` returns, about
20 times a second.

- E-stop stays on until someone releases it (open question C-2, recommended answer). While it's
  on, speed and turn are 0 and the robot keeps balancing (decision 0043).
- Releasing the e-stop drops every pending request, so a skill's old target can't make the robot
  lurch the moment it's released. The skill runner cancels the task itself.
- A request goes stale after `stale_after` seconds (default 0.3 s, like the robot's own watchdog),
  so a joystick or skill that stops sending stops the robot.
- Speed and turn are clamped to the robot's limits (firmware/README.md: ±1.0 m/s, ±1.5 rad/s).

Units are SI with ROS REP 103 directions: v in m/s (+ forward), w in rad/s (+ turning left).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import IntEnum
from typing import Callable


class Source(IntEnum):
    """Who is asking. A higher value wins."""

    SKILL = 1
    JOYSTICK = 2


@dataclass(frozen=True)
class Command:
    """What the robot should do right now."""

    v: float          # m/s, + forward
    w: float          # rad/s, + turning left
    source: str       # "estop", "joystick", "skill" or "none"


V_MAX = 1.0   # the wheels' limit (VMAX in balance.ino); uncapped Sat 10 pm, Alex tests the real top speed
W_MAX = 1.5


def _clamp(x: float, limit: float) -> float:
    return max(-limit, min(limit, x))


@dataclass
class _Request:
    v: float
    w: float
    at: float


class Arbiter:
    def __init__(self, stale_after: float = 0.3, clock: Callable[[], float] = time.monotonic):
        self._stale_after = stale_after
        self._clock = clock
        self._requests: dict[Source, _Request] = {}
        self._estop = False

    @property
    def estopped(self) -> bool:
        return self._estop

    def estop(self, on: bool) -> None:
        """Turn the e-stop on or off. Releasing it also drops every pending request."""
        if self._estop and not on:
            self._requests.clear()
        self._estop = on

    def request(self, source: Source, v: float, w: float) -> None:
        """Ask for a speed and turn. Call it again at least every `stale_after` seconds to keep it."""
        self._requests[source] = _Request(_clamp(v, V_MAX), _clamp(w, W_MAX), self._clock())

    def clear(self, source: Source) -> None:
        """Withdraw a source's request (a skill finished, the joystick was let go)."""
        self._requests.pop(source, None)

    def decide(self) -> Command:
        if self._estop:
            return Command(0.0, 0.0, "estop")
        now = self._clock()
        for source in sorted(self._requests, reverse=True):
            req = self._requests[source]
            if now - req.at <= self._stale_after:
                return Command(req.v, req.w, source.name.lower())
        return Command(0.0, 0.0, "none")
