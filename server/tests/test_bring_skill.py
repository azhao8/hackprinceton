"""Bring: station -> ask to load the tray -> wait -> find the person -> hand over."""

from __future__ import annotations

import asyncio

import pytest

from app.arbiter import Arbiter
from app.skills import SkillContext, SkillResult
from app.skills.bring import Bring
from tests.test_search_skills import Body, FakeRegistry, Tag, at, look_of, run, setup, sim


class FakeSkill:
    def __init__(self, name: str, log: list[str], result: SkillResult) -> None:
        self.name = name
        self.log = log
        self.result = result

    async def run(self, ctx: SkillContext) -> SkillResult:
        self.log.append(self.name)
        ctx.drive(0.1, 0.0)
        return self.result


def make(log: list[str], *, loaded: bool | None = True, find_ok: bool = True, go_ok: bool = True, **kw) -> Bring:
    async def wait_loaded() -> bool:
        log.append("wait_loaded")
        if loaded is None:
            await asyncio.Event().wait()  # nobody ever confirms
        return bool(loaded)

    return Bring(
        "water",
        "Mom",
        wait_loaded,
        lambda text: log.append(f"say: {text}"),
        go_to=FakeSkill("go_to", log, SkillResult(go_ok, "at the station (0.5 m)" if go_ok else "station not found")),
        find_person=FakeSkill("find_person", log, SkillResult(find_ok, "found Mom at ~1.0 m" if find_ok else "not found")),
        **kw,
    )


def test_happy_path_runs_the_steps_in_order():
    log: list[str] = []
    steps: list[str] = []
    arb = Arbiter()
    result = run(make(log, on_step=lambda stage, text: steps.append(text)).run(SkillContext(arb)))

    assert result.ok and result.detail.startswith("brought the water to Mom")
    assert log == [
        "go_to",
        "say: Please put the water in my tray",
        "wait_loaded",
        "find_person",
        "say: Here is your water!",
    ]
    assert steps == [
        "going to the station",
        "waiting for the water to be put in the tray",
        "bringing the water to Mom",
        "delivered",
    ]
    assert arb.decide().source == "none"


def test_nobody_loads_the_tray():
    log: list[str] = []
    result = run(make(log, loaded=None, load_timeout_s=0.05).run(SkillContext(Arbiter())))
    assert not result.ok and "nobody loaded the tray" in result.detail
    assert "find_person" not in log


def test_loading_declined():
    log: list[str] = []
    result = run(make(log, loaded=False).run(SkillContext(Arbiter())))
    assert not result.ok and "nobody loaded the tray" in result.detail


def test_station_not_reached():
    log: list[str] = []
    result = run(make(log, go_ok=False).run(SkillContext(Arbiter())))
    assert result == SkillResult(False, "couldn't get to the station: station not found")
    assert log == ["go_to"]


def test_person_not_found():
    log: list[str] = []
    result = run(make(log, find_ok=False).run(SkillContext(Arbiter())))
    assert not result.ok
    assert result.detail == "I have the water but couldn't find Mom: not found"
    assert log[-1] == "find_person"  # never said "Here is your water!"


def test_cancel_while_waiting_stops_the_robot():
    async def scenario():
        log: list[str] = []
        arb = Arbiter()
        task = asyncio.create_task(make(log, loaded=None).run(SkillContext(arb)))
        while "wait_loaded" not in log:
            await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert arb.decide().source == "none"

    asyncio.run(scenario())


def test_bring_in_the_simulated_room():
    """Real GoTo + FindPerson: the station marker ahead, Mom behind the robot."""
    station = Tag(1, *at(0, 2.0))
    mom = Body("Mom", -2.0, 0.0, "blue")
    world, vision, ctx = setup([mom], [station])
    said: list[str] = []

    async def wait_loaded() -> bool:
        return True

    skill = Bring(
        "water", "Mom", wait_loaded, said.append,
        registry=FakeRegistry({"mom": look_of("blue")}),
        marker_for={"station": 1}.get, known_places=["station"],
        **sim(world),
    )
    result = run(skill.run(ctx))

    assert result.ok, result.detail
    assert said == ["Please put the water in my tray", "Here is your water!"]
    assert world.dist(mom.x, mom.y) == pytest.approx(1.05, abs=0.1)
    assert world.arb.decide().source == "none"
