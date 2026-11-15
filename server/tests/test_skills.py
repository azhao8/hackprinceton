import asyncio

from app.arbiter import Arbiter
from app.skills import SkillContext, SkillResult, SkillRunner


class DriveForever:
    name = "drive_forever"

    async def run(self, ctx: SkillContext) -> SkillResult:
        while True:
            ctx.drive(0.2, 0.0)
            await asyncio.sleep(0.01)


class Quick:
    name = "quick"

    async def run(self, ctx: SkillContext) -> SkillResult:
        ctx.drive(0.1, 0.3)
        return SkillResult(True, "done")


def test_skill_drives_through_the_arbiter_and_stops_when_cancelled():
    async def scenario():
        arb = Arbiter()
        runner = SkillRunner(SkillContext(arb))
        task = runner.start(DriveForever())
        await asyncio.sleep(0.05)
        assert arb.decide().source == "skill"
        assert runner.running == "drive_forever"
        runner.cancel()
        result = await task
        assert result == SkillResult(False, "cancelled")
        assert arb.decide().source == "none"
        assert runner.running is None

    asyncio.run(scenario())


def test_new_skill_replaces_the_old_one():
    async def scenario():
        arb = Arbiter()
        runner = SkillRunner(SkillContext(arb))
        first = runner.start(DriveForever())
        await asyncio.sleep(0.02)
        second = runner.start(Quick())
        assert (await first).detail == "cancelled"
        assert await second == SkillResult(True, "done")
        assert arb.decide().source == "none"   # a finished skill leaves no request behind

    asyncio.run(scenario())


def test_context_telemetry_is_optional_and_never_raises():
    arb = Arbiter()
    assert SkillContext(arb).telemetry() is None                     # no link wired in
    tel = {"t": "tel", "yaw": 12.5, "x": 0.3}
    assert SkillContext(arb, telemetry=lambda: tel).telemetry() is tel
    assert SkillContext(arb, None, None, telemetry=lambda: None).telemetry() is None

    def broken() -> dict:
        raise RuntimeError("link gone")

    assert SkillContext(arb, telemetry=broken).telemetry() is None
    assert SkillContext(arb, telemetry=lambda: "not a dict").telemetry() is None  # type: ignore[arg-type,return-value]
