"""Bring skill (issue #55, open questions P-5/P-6): fetch an item from the station to a person.

    go to the station -> "Please put the <item> in my tray" -> wait until someone confirms it is
    loaded (voice or a control-page button, injected as `wait_loaded`) -> find the person ->
    "Here is your <item>!"

No gripper: the item goes in a tray at the station (P-5). Each step's failure ends the skill with
a text that says which step failed, so the agent can recover (retry, ask, tell the family).
Progress goes to an optional `on_step(stage, text)` callback (the control page / family app). `stage` is a
fixed name the family app shows (contract/web/family.md): sent, loading, on_the_way, delivered, failed.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import time
from collections.abc import Awaitable, Callable, Iterable

from app.skills import Skill, SkillContext, SkillResult
from app.skills.search import Clock, FindPerson, GoTo, Matcher, Registry, SearchConfig, Sleep

log = logging.getLogger(__name__)


class Bring:
    name = "bring"

    def __init__(
        self,
        item: str,
        person: str | None,
        wait_loaded: Callable[[], Awaitable[bool]],
        say: Callable[[str], object],
        *,
        description: str | None = None,
        registry: Registry | None = None,
        matcher: Matcher | None = None,
        station: str = "station",
        config: SearchConfig = SearchConfig(),
        load_timeout_s: float = 60.0,  # GUESS: how long to wait at the station for someone to load the tray
        on_step: Callable[[str, str], None] | None = None,
        marker_for: Callable[[str], int | None] | None = None,
        known_places: Iterable[str] | None = None,
        go_to: Skill | None = None,  # override the sub-skills (tests); defaults are built from the above
        find_person: Skill | None = None,
        clock: Clock = time.monotonic,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self.item = item
        self.person = person
        self.station = station
        self.wait_loaded = wait_loaded
        self.say = say
        self.load_timeout_s = load_timeout_s
        self.on_step = on_step
        self.go_to: Skill = go_to or GoTo(
            station, config, marker_for=marker_for, known_places=known_places, clock=clock, sleep=sleep
        )
        self.find_person: Skill = find_person or FindPerson(
            person, description, registry, matcher, config, clock=clock, sleep=sleep
        )
        self.step: str | None = None  # the current step's text (debug view)

    @property
    def who(self) -> str:
        return self.person or "you"

    async def run(self, ctx: SkillContext) -> SkillResult:
        item, station = self.item, self.station
        try:
            self._step(f"going to the {station}", "sent")
            r = await self.go_to.run(ctx)
            if not r.ok:
                return self._fail(f"couldn't get to the {station}: {r.detail}")

            ctx.stop()  # hold still at the station while it is loaded
            self._step(f"waiting for the {item} to be put in the tray", "loading")
            await self._say(f"Please put the {item} in my tray")
            try:
                loaded = await asyncio.wait_for(self.wait_loaded(), self.load_timeout_s)
                why = "loading was cancelled"
            except TimeoutError:
                loaded, why = False, f"no confirmation in {self.load_timeout_s:.0f} s"
            if not loaded:
                return self._fail(f"nobody loaded the tray ({why}); I'm at the {station}")

            self._step(f"bringing the {item} to {self.who}", "on_the_way")
            r = await self.find_person.run(ctx)
            if not r.ok:
                return self._fail(f"I have the {item} but couldn't find {self.who}: {r.detail}")

            ctx.stop()
            await self._say(f"Here is your {item}!")
            self._step("delivered", "delivered")
            return SkillResult(True, f"brought the {item} to {self.who} ({r.detail})")
        except asyncio.CancelledError:
            # stop, e-stop or another skill (#71): report it, or the family app's delivery stays mid-way
            if self.step != "delivered":
                self._step("stopped before delivering", "failed")
            raise
        finally:
            ctx.stop()

    def _step(self, text: str, stage: str) -> None:
        self.step = text
        log.info("bring: %s (%s)", text, stage)
        if self.on_step is not None:
            try:
                self.on_step(stage, text)
            except Exception:
                log.exception("bring: on_step callback failed")

    def _fail(self, why: str) -> SkillResult:
        self._step(why, "failed")
        return SkillResult(False, why)

    async def _say(self, text: str) -> None:
        result = self.say(text)
        if inspect.isawaitable(result):
            await result
