"""Move skill: time, distance and angle moves on a fake clock, clamps, cancel and the e-stop."""

import asyncio

import pytest

from app.arbiter import Arbiter
from app.skills import SkillContext, SkillRunner
from app.skills.move import Move


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


class Rig:
    """An arbiter and context whose clock advances one tick per drive request."""

    def __init__(self, tel=None, tick=0.0625, on_drive=None):   # 1/16 s: exact in binary
        self.clock = FakeClock()
        self.arbiter = Arbiter(clock=self.clock)
        self.tel = tel
        self.drives = []
        self.stops = 0
        self.tick = tick
        self.on_drive = on_drive
        rig = self

        class Ctx(SkillContext):
            def drive(self, v, w):
                super().drive(v, w)
                rig.drives.append((v, w))
                rig.clock.t += rig.tick
                if rig.on_drive:
                    rig.on_drive(rig)

            def stop(self):
                super().stop()
                rig.stops += 1

        self.ctx = Ctx(self.arbiter, telemetry=lambda: self.tel)

    def move(self, direction, **kw):
        kw.setdefault("drive_speed", lambda: 1.1)
        kw.setdefault("turn_rate", lambda: 0.8)
        return Move(direction, hz=1000.0, clock=self.clock, **kw)

    def run(self, skill):
        return asyncio.run(skill.run(self.ctx))


def test_forward_defaults_to_one_second_at_the_drive_speed():
    rig = Rig()
    r = rig.run(rig.move("forward"))
    assert r.ok and r.detail == "drove forward for 1.0 s at 1.10 m/s"
    assert set(rig.drives) == {(1.1, 0.0)}
    assert len(rig.drives) == 16   # 1 s of 1/16 s ticks
    assert rig.stops == 1 and rig.arbiter.decide().source == "none"


def test_back_is_backward_and_right_is_negative_w():
    rig = Rig()
    rig.run(rig.move("back", seconds=0.5))
    assert set(rig.drives) == {(-1.1, 0.0)}
    rig = Rig()
    r = rig.run(rig.move("right"))
    assert set(rig.drives) == {(0.0, -0.8)} and r.detail == "turned right for 1.0 s at 0.80 rad/s"
    rig = Rig()
    rig.run(rig.move("left"))
    assert set(rig.drives) == {(0.0, 0.8)}


def test_seconds_and_speed():
    rig = Rig()
    r = rig.run(rig.move("forward", seconds=3, speed=0.5))
    assert set(rig.drives) == {(0.5, 0.0)} and len(rig.drives) == 48
    assert r.detail == "drove forward for 3.0 s at 0.50 m/s"


def test_clamps():
    rig = Rig()
    rig.run(rig.move("forward", seconds=0.5, speed=9))
    assert set(rig.drives) == {(3.2, 0.0)}
    rig = Rig()
    rig.run(rig.move("left", seconds=0.5, speed=0.01))
    assert set(rig.drives) == {(0.0, 0.1)}
    rig = Rig()
    rig.run(rig.move("backward", seconds=0.5, speed=-0.02))   # sign comes from the direction
    assert set(rig.drives) == {(-0.05, 0.0)}
    m = Move("forward", seconds=60, drive_speed=lambda: 1, turn_rate=lambda: 1)
    assert m.seconds == 10.0
    assert Move("forward", meters=50, drive_speed=lambda: 1, turn_rate=lambda: 1).meters == 5.0
    assert Move("left", degrees=1, drive_speed=lambda: 1, turn_rate=lambda: 1).degrees == 5.0
    assert Move("left", degrees=2000, drive_speed=lambda: 1, turn_rate=lambda: 1).degrees == 720.0


def test_bad_arguments_raise():
    kw = {"drive_speed": lambda: 1, "turn_rate": lambda: 1}
    with pytest.raises(ValueError):
        Move("up", **kw)
    with pytest.raises(ValueError):
        Move("forward", seconds=1, meters=1, **kw)
    with pytest.raises(ValueError):
        Move("left", meters=1, **kw)
    with pytest.raises(ValueError):
        Move("forward", degrees=90, **kw)


def test_meters_stops_on_telemetry_x():
    def advance(rig):   # 1 m/s for one tick
        rig.tel = {**rig.tel, "x": rig.tel["x"] + 0.0625}

    rig = Rig(tel={"x": 3.0, "yaw": 10.0}, on_drive=advance)
    r = rig.run(rig.move("forward", meters=0.5, speed=1.0))
    assert r.ok and r.detail == "moved forward 0.50 m"
    assert len(rig.drives) == 8 and rig.stops == 1


def test_meters_backward_counts_distance_either_sign():
    def advance(rig):
        rig.tel = {"x": rig.tel["x"] - 0.125}

    rig = Rig(tel={"x": 0.0}, on_drive=advance)
    r = rig.run(rig.move("backward", meters=1))
    assert r.ok and r.detail == "moved backward 1.00 m" and set(rig.drives) == {(-1.1, 0.0)}


def test_meters_times_out_when_the_robot_does_not_move():
    rig = Rig(tel={"x": 0.0})
    r = rig.run(rig.move("forward", meters=1, speed=0.5))   # expected 2 s: timeout 2*2+3 = 7 s
    assert not r.ok and "only 0.00 of 1.00 m" in r.detail and "7.0 s" in r.detail
    assert len(rig.drives) == 112 and rig.stops == 1


def test_meters_without_telemetry_drives_for_the_expected_time():
    rig = Rig(tel=None)
    r = rig.run(rig.move("forward", meters=1, speed=0.5))
    assert r.ok and r.detail == "drove forward for 2.0 s at 0.50 m/s" and len(rig.drives) == 32


def test_degrees_stops_on_telemetry_yaw():
    def turn(rig):
        rig.tel = {"yaw": rig.tel["yaw"] + 3.0}

    rig = Rig(tel={"yaw": -20.0}, on_drive=turn)
    r = rig.run(rig.move("left", degrees=90))
    assert r.ok and r.detail == "turned left 90°" and len(rig.drives) == 30


def test_degrees_without_yaw_turns_for_the_expected_time():
    rig = Rig(tel={"x": 0.0})   # USB without J: no yaw
    r = rig.run(rig.move("right", degrees=90, speed=1.0))
    assert r.ok and r.detail.startswith("turned right for 1.6 s")
    assert len(rig.drives) == 26   # pi/2 s of 1/16 s ticks


def test_estop_fails_at_once_and_mid_move():
    rig = Rig()
    rig.arbiter.estop(True)
    r = rig.run(rig.move("forward"))
    assert not r.ok and "e-stop" in r.detail and rig.drives == []

    def press(rig):
        if len(rig.drives) == 5:
            rig.arbiter.estop(True)

    rig = Rig(on_drive=press)
    r = rig.run(rig.move("forward"))
    assert not r.ok and "e-stop" in r.detail and len(rig.drives) == 5 and rig.stops == 1


def test_cancel_stops_the_robot():
    async def scenario():
        arb = Arbiter()
        stops = []

        class Ctx(SkillContext):
            def stop(self):
                super().stop()
                stops.append(1)

        ctx = Ctx(arb)
        runner = SkillRunner(ctx)
        task = runner.start(Move("forward", seconds=5, drive_speed=lambda: 0.4, turn_rate=lambda: 0.8))
        await asyncio.sleep(0.15)
        assert arb.decide().v == pytest.approx(0.4)   # still being re-sent past the 0.3 s staleness
        task.cancel()
        r = await task
        assert not r.ok and r.detail == "cancelled"
        assert arb.decide().source == "none" and stops

    asyncio.run(scenario())


def test_resends_often_enough_to_stay_fresh():
    async def scenario():
        arb = Arbiter()
        runner = SkillRunner(SkillContext(arb))
        task = runner.start(Move("left", seconds=0.8, drive_speed=lambda: 1, turn_rate=lambda: 0.6))
        seen = []
        for _ in range(6):
            await asyncio.sleep(0.1)
            seen.append(arb.decide().w)
        r = await task
        assert r.ok and all(w == pytest.approx(0.6) for w in seen)
        assert arb.decide().source == "none"

    asyncio.run(scenario())


def test_default_speed_is_read_when_the_move_starts():
    speed = {"v": 0.3}
    rig = Rig()
    m = rig.move("forward", seconds=0.2, drive_speed=lambda: speed["v"])
    speed["v"] = 0.9
    rig.run(m)
    assert set(rig.drives) == {(0.9, 0.0)}
