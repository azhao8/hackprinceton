"""The server loop (`python -m app`) with a fake link: no robot, camera or serial port."""

from __future__ import annotations

import asyncio

import pytest

import app.__main__ as server
from app.__main__ import App, parse_args
from app.skills import SkillResult


class FakeLink:
    def __init__(self) -> None:
        self.sent: list[tuple[float, float]] = []
        self.letters: list[str] = []
        self.closed = False
        self.telemetry = None
        self.connected = True

    def send(self, v: float, w: float, mode: str = "drive") -> None:
        self.sent.append((v, w))

    def arm(self) -> None:
        self.letters.append("g")

    def park(self) -> None:
        self.letters.append("P")

    def motors_off(self) -> None:
        self.letters.append("x")

    def close(self) -> None:
        self.letters.append("x")  # like SerialLink.close(): motors off first
        self.closed = True


class FakeVision:
    def __init__(self) -> None:
        self.turn_rates: list[float] = []
        self.stopped = False

    def set_turn_rate(self, w: float) -> None:
        self.turn_rates.append(w)

    def latest(self):
        return None

    def request_engage(self) -> int:
        return 1

    def disengage(self) -> None:
        pass

    def stop(self) -> None:
        self.stopped = True


class Drive:
    """A skill that keeps asking for a fixed speed and turn."""

    name = "follow"

    def __init__(self, v: float = 0.2, w: float = -0.5) -> None:
        self.v, self.w = v, w
        self.last_command = None

    async def run(self, ctx) -> SkillResult:
        while True:
            ctx.drive(self.v, self.w)
            await asyncio.sleep(0.01)


def test_real_robot_needs_someone_at_it():
    with pytest.raises(SystemExit):
        parse_args(["--robot", "real"])
    assert parse_args(["--robot", "real", "--someone-at-robot"]).robot == "real"
    assert parse_args([]).robot == "mock"


def test_main_refuses_real_before_touching_anything(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("must not open a link or a camera")

    monkeypatch.setattr(server, "make_link", boom)
    monkeypatch.setattr(server, "make_vision", boom)
    with pytest.raises(SystemExit) as e:
        server.main(["--robot", "real", "--port", "/dev/null"])
    assert e.value.code == 2


def test_loop_sends_arbiter_output_and_closes_the_link():
    async def scenario():
        link, vision = FakeLink(), FakeVision()
        app = App(link, robot="real", vision=vision, follow_factory=Drive, hz=100)
        app.toggle_follow()
        await asyncio.sleep(0.05)
        await app.run(max_ticks=5)
        return app, link, vision

    app, link, vision = asyncio.run(scenario())
    assert link.sent[-1] == (0.2, -0.5)  # the skill's request went through the arbiter to the link
    assert vision.turn_rates[-1] == -0.5  # the real robot's turn goes to the lock for ego-motion
    assert link.closed and link.letters[-1] == "x"
    assert vision.stopped
    assert app.skills.running is None


def test_mock_robot_never_reports_turning_to_vision_and_ignores_arm():
    async def scenario():
        link, vision = FakeLink(), FakeVision()
        app = App(link, robot="mock", vision=vision, follow_factory=Drive, hz=100)
        app.toggle_follow()
        await asyncio.sleep(0.05)
        app.handle_key("g")
        await app.run(max_ticks=3)
        return link, vision

    link, vision = asyncio.run(scenario())
    assert set(vision.turn_rates) == {0.0}
    assert "g" not in link.letters


def test_keys():
    async def scenario():
        link = FakeLink()
        app = App(link, robot="real", vision=FakeVision(), follow_factory=Drive, hz=100)

        app.handle_key("f")
        await asyncio.sleep(0.03)
        assert app.skills.running == "follow"
        app.handle_key(" ")  # e-stop: zero output and the skill ends
        await asyncio.sleep(0.01)
        assert app.tick().source == "estop" and link.sent[-1] == (0.0, 0.0)
        assert app.skills.running is None
        app.handle_key("f")  # refused while e-stopped
        assert app.skills.running is None
        app.handle_key(" ")
        assert app.tick().source == "none"

        app.handle_key("f")
        await asyncio.sleep(0.03)
        app.handle_key("g")  # arming cancels the skill so it can't drive off while held
        await asyncio.sleep(0.01)
        assert app.skills.running is None and link.letters == ["g"]

        app.handle_key("f")
        await asyncio.sleep(0.03)
        app.handle_key("f")  # F again stops it
        await asyncio.sleep(0.01)
        assert app.skills.running is None

        app.handle_key("p")
        app.handle_key("x")
        assert link.letters == ["g", "P", "x"]

        app.handle_key("q")
        await app.run()  # returns at once because of q, and closes
        assert link.closed

    asyncio.run(scenario())


def test_link_errors_dont_kill_the_loop():
    class Flaky(FakeLink):
        def send(self, v, w, mode="drive"):
            raise OSError("cable tugged")

    async def scenario():
        link = Flaky()
        await App(link, hz=100).run(max_ticks=3)
        return link

    assert asyncio.run(scenario()).closed


def test_window_keys_are_read_each_tick():
    class FakeWindow:
        def __init__(self, keys):
            self.keys = list(keys)
            self.shown = 0
            self.closed = False

        def show(self, image):
            self.shown += 1
            return self.keys.pop(0) if self.keys else -1

        def close(self):
            self.closed = True

    async def scenario():
        window = FakeWindow([-1, ord("q")])
        link = FakeLink()
        app = App(link, window=window, render=lambda p, hud: hud, hz=100)
        await app.run(max_ticks=50)
        return window, link

    window, link = asyncio.run(scenario())
    assert window.shown == 2 and window.closed and link.closed
