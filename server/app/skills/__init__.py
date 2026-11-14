"""Skills (owner: Grant). DRAFT skill API (open question T-8): Grant owns it and can change it.

A skill is plain code that runs a fast loop (follow, stop, turn...) until it succeeds or fails.
The agent picks which skill runs; the skill never decides priority. It only *requests* motion
from the arbiter, which lets e-stop and the joystick win.

- One skill runs at a time (one body). Each runs as an asyncio task, so the stop gesture, a new
  request or the e-stop cancels it by cancelling the task (open question T-7).
- A skill reads perception and memory through its context and sends targets with
  `ctx.drive(v, w)`, at least every 0.3 s while it wants to keep moving.
- It returns a `SkillResult` that the agent reads.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Protocol

from app.arbiter import Arbiter, Source


@dataclass(frozen=True)
class SkillResult:
    ok: bool
    detail: str = ""


class SkillContext:
    """What a skill can see and do. Grows as vision and memory land."""

    def __init__(self, arbiter: Arbiter, perception: Any = None, memory: Any = None):
        self._arbiter = arbiter
        self.perception = perception   # vision's latest result (#3)
        self.memory = memory           # world memory

    def drive(self, v: float, w: float) -> None:
        """Ask for a speed (m/s, + forward) and turn (rad/s, + left)."""
        self._arbiter.request(Source.SKILL, v, w)

    def stop(self) -> None:
        """Withdraw this skill's request; the robot holds position."""
        self._arbiter.clear(Source.SKILL)


class Skill(Protocol):
    name: str

    async def run(self, ctx: SkillContext) -> SkillResult: ...


class SkillRunner:
    """Runs one skill at a time. Starting a new one cancels the old one."""

    def __init__(self, ctx: SkillContext):
        self._ctx = ctx
        self._task: asyncio.Task[SkillResult] | None = None

    @property
    def running(self) -> str | None:
        return self._task.get_name() if self._task and not self._task.done() else None

    def start(self, skill: Skill) -> asyncio.Task[SkillResult]:
        self.cancel()
        self._task = asyncio.create_task(self._run(skill), name=skill.name)
        return self._task

    def cancel(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
        self._ctx.stop()

    async def _run(self, skill: Skill) -> SkillResult:
        try:
            return await skill.run(self._ctx)
        except asyncio.CancelledError:
            return SkillResult(False, "cancelled")
        finally:
            # Only the current skill clears the request: a cancelled skill finishing late
            # must not wipe the targets of the skill that replaced it. (cancel() already cleared.)
            if asyncio.current_task() is self._task:
                self._ctx.stop()
