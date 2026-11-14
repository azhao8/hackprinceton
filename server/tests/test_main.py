"""The server loop (`python -m app`) with fake links and fake vision: no robot, camera or port."""

from __future__ import annotations

import asyncio

import pytest

import app.__main__ as server
from app.__main__ import App, parse_args
from app.link import ALLOWED_LETTERS, Health
from app.skills import SkillResult


class FakeUdpLink:
    """RobotLink like UdpLink: refuses g, keeps a contract-v1 telemetry dict."""

    def __init__(self, telemetry: dict | None = None) -> None:
        self.sent: list[tuple[float, float, str]] = []
        self.letters: list[str] = []
        self.started = False
        self.closed = False
        self.telemetry = telemetry
        self.events: list[str] = []

    async def start(self) -> None:
        self.started = True

    async def close(self) -> None:
        self.closed = True
        self.events.append("close")

    def send_cmd(self, v: float, w: float, mode: str = "drive") -> None:
        self.sent.append((v, w, mode))

    def send_letter(self, letter: str) -> None:
        if letter not in ALLOWED_LETTERS:
            raise ValueError(letter)
        self.letters.append(letter)
        self.events.append(letter)

    def health(self) -> Health:
        return Health(self.telemetry is not None, 0.05, 0.05, 12.0)


class FakeSerialLink(FakeUdpLink):
    """RobotLink plus arm(), like SerialLink."""

    def arm(self) -> None:
        self.letters.append("g")


class FakeVision:
    def __init__(self) -> None:
        self.turn_rates: list[float] = []
        self.started = False
        self.stopped = False

    def start(self) -> None:
        self.started = True

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


class FakeWindow:
    def __init__(self, keys=()):
        self.keys = list(keys)
        self.shown: list = []
        self.closed = False

    def show(self, image):
        self.shown.append(image)
        k = self.keys.pop(0) if self.keys else -1
        return ord(k) if isinstance(k, str) else k

    def close(self):
        self.closed = True


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


TEL = {"t": "tel", "pitch": 5.71, "rate": -1.8, "vl": 0.0, "vr": 0.0, "batt": None,
       "state": "balance", "fault": None, "x": 0.012, "yaw": 0.4, "ack": 814}


# --- command line and safety ---


def test_real_robot_needs_someone_at_it():
    with pytest.raises(SystemExit):
        parse_args(["--robot", "real"])
    with pytest.raises(SystemExit):
        parse_args(["--robot", "real", "--link", "serial"])
    assert parse_args(["--robot", "real", "--someone-at-robot"]).robot == "real"
    args = parse_args([])
    assert (args.robot, args.link, args.window) == ("mock", "udp", True)


def test_serial_link_is_only_for_the_real_robot():
    with pytest.raises(SystemExit):
        parse_args(["--link", "serial"])
    args = parse_args(["--robot", "real", "--link", "serial", "--someone-at-robot", "--turn-only"])
    assert (args.link, args.turn_only, args.port) == ("serial", True, None)


def test_main_refuses_real_before_touching_anything(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("must not open a link, a camera or a window")

    for name in ("make_link", "make_vision", "make_window"):
        monkeypatch.setattr(server, name, boom)
    for argv in (["--robot", "real"], ["--robot", "real", "--link", "serial", "--port", "/dev/null"]):
        with pytest.raises(SystemExit) as e:
            server.main(argv)
        assert e.value.code == 2


def test_make_link_picks_udp_host_or_serial(monkeypatch):
    monkeypatch.delenv("ROBOT_HOST", raising=False)
    assert server.make_link(parse_args([])).host == "127.0.0.1"
    real = parse_args(["--robot", "real", "--someone-at-robot"])
    assert server.make_link(real).host == "balancebot.local"
    monkeypatch.setenv("ROBOT_HOST", "10.0.0.7")
    assert server.make_link(real).host == "10.0.0.7"
    assert server.make_link(parse_args(["--host", "1.2.3.4"])).host == "1.2.3.4"

    import app.link.serial_link as serial_link

    made = []
    monkeypatch.setattr(serial_link, "SerialLink", lambda port: made.append(port) or "serial")
    args = parse_args(["--robot", "real", "--link", "serial", "--someone-at-robot", "--port", "/dev/cu.x"])
    assert server.make_link(args) == "serial" and made == ["/dev/cu.x"]


# --- the loop ---


def test_arbiter_output_reaches_send_cmd_and_shutdown_sends_x_then_closes():
    async def scenario():
        link, vision = FakeUdpLink(dict(TEL)), FakeVision()
        app = App(link, robot="real", vision=vision, follow_factory=Drive, hz=100)
        app.toggle_follow()
        await asyncio.sleep(0.05)
        await app.run(max_ticks=5)
        return app, link, vision

    app, link, vision = asyncio.run(scenario())
    assert link.sent[-1] == (0.2, -0.5, "drive")  # the skill's request went through the arbiter
    assert vision.turn_rates[-1] == -0.5  # the real robot's turn goes to the lock for ego-motion
    assert link.events[-2:] == ["x", "close"]  # motors off, then close
    assert vision.stopped
    assert app.skills.running is None


def test_estop_edge_sends_5_once_and_zero_speed():
    async def scenario():
        link = FakeUdpLink()
        app = App(link, vision=FakeVision(), follow_factory=Drive, hz=100)
        app.toggle_follow()
        await asyncio.sleep(0.03)
        app.tick()
        assert link.sent[-1][:2] == (0.2, -0.5) and "5" not in link.letters
        app.handle_key(" ")
        app.tick()
        app.tick()
        assert link.letters.count("5") == 1 and link.sent[-1] == (0.0, 0.0, "drive")
        assert app.last.source == "estop"
        app.handle_key(" ")  # released: no letter
        app.tick()
        app.handle_key(" ")  # on again: a second edge
        app.tick()
        assert link.letters.count("5") == 2
        await app.shutdown()

    asyncio.run(scenario())


def test_drive_loop_sends_5_on_the_estop_edge():
    from app.arbiter import Arbiter, Source

    async def scenario():
        arb, link, stop = Arbiter(), FakeUdpLink(), asyncio.Event()
        task = asyncio.create_task(server.drive_loop(arb, link, stop))
        arb.request(Source.SKILL, 0.3, 0.1)
        await asyncio.sleep(0.08)
        arb.estop(True)
        await asyncio.sleep(0.12)
        stop.set()
        await task
        return link

    link = asyncio.run(scenario())
    assert (0.3, 0.1, "drive") in link.sent
    assert link.letters == ["5"] and link.sent[-1] == (0.0, 0.0, "drive")


def test_mock_robot_never_reports_turning_to_vision():
    async def scenario():
        link, vision = FakeUdpLink(dict(TEL)), FakeVision()
        app = App(link, robot="mock", vision=vision, follow_factory=Drive, hz=100)
        app.toggle_follow()
        await asyncio.sleep(0.05)
        await app.run(max_ticks=3)
        return vision

    assert set(asyncio.run(scenario()).turn_rates) == {0.0}


def test_idle_real_robot_reports_no_turn():
    async def scenario():
        link, vision = FakeUdpLink(dict(TEL, state="idle")), FakeVision()
        app = App(link, robot="real", vision=vision, follow_factory=Drive, hz=100)
        app.toggle_follow()
        await asyncio.sleep(0.05)
        await app.run(max_ticks=3)
        return vision

    assert set(asyncio.run(scenario()).turn_rates) == {0.0}


def test_keys():
    async def scenario():
        link = FakeUdpLink()
        app = App(link, robot="real", vision=FakeVision(), follow_factory=Drive, hz=100)

        app.handle_key("f")
        await asyncio.sleep(0.03)
        assert app.skills.running == "follow"
        app.handle_key(" ")  # e-stop: zero output and the skill ends
        await asyncio.sleep(0.01)
        assert app.tick().source == "estop" and link.sent[-1][:2] == (0.0, 0.0)
        assert app.skills.running is None
        app.handle_key("f")  # refused while e-stopped
        assert app.skills.running is None
        app.handle_key(" ")
        assert app.tick().source == "none"

        app.handle_key("f")
        await asyncio.sleep(0.03)
        app.handle_key("F")  # F again stops it
        await asyncio.sleep(0.01)
        assert app.skills.running is None

        app.handle_key("f")
        await asyncio.sleep(0.03)
        app.handle_key("p")  # park ends the skill
        await asyncio.sleep(0.01)
        assert app.skills.running is None
        app.handle_key("f")
        await asyncio.sleep(0.03)
        app.handle_key("x")  # motors off ends the skill
        await asyncio.sleep(0.01)
        assert app.skills.running is None
        assert link.letters == ["5", "P", "x"]

        app.handle_key("q")
        await app.run()  # returns at once because of q, and closes
        assert link.closed and link.letters[-1] == "x"

    asyncio.run(scenario())


def test_g_over_serial_arms_after_cancelling_the_skill(capsys):
    async def scenario():
        link = FakeSerialLink()
        app = App(link, robot="real", link_kind="serial", vision=FakeVision(), follow_factory=Drive, hz=100)
        app.handle_key("f")
        await asyncio.sleep(0.03)
        app.handle_key("g")  # arming cancels the skill so it can't drive off while held
        await asyncio.sleep(0.01)
        assert app.skills.running is None and link.letters == ["g"]
        await app.shutdown()

    asyncio.run(scenario())
    assert "hold the robot upright" in capsys.readouterr().out


def test_g_over_udp_never_sends_g(capsys):
    async def scenario():
        for link in (FakeUdpLink(), FakeSerialLink()):  # even a link with arm(), if it's on UDP
            app = App(link, robot="real", link_kind="udp", vision=FakeVision(), follow_factory=Drive, hz=100)
            app.handle_key("f")
            await asyncio.sleep(0.03)
            app.handle_key("g")
            await asyncio.sleep(0.01)
            assert "g" not in link.letters
            assert app.skills.running == "follow"  # nothing was armed, so nothing to cancel
            assert "robot side" in app.note
            await app.shutdown()

    asyncio.run(scenario())
    assert "hold the robot upright" not in capsys.readouterr().out


def test_link_errors_dont_kill_the_loop():
    class Flaky(FakeUdpLink):
        def send_cmd(self, v, w, mode="drive"):
            raise OSError("cable tugged")

    async def scenario():
        link = Flaky()
        await App(link, hz=100).run(max_ticks=3)
        return link

    link = asyncio.run(scenario())
    assert link.closed and link.letters == ["x"]


def test_a_crash_in_the_loop_still_sends_x_and_closes():
    def bad_render(perception, hud):
        raise RuntimeError("boom")

    async def scenario():
        link, vision, window = FakeUdpLink(), FakeVision(), FakeWindow()
        app = App(link, vision=vision, follow_factory=Drive, window=window, render=bad_render, hz=100)
        app.toggle_follow()
        await asyncio.sleep(0.03)
        with pytest.raises(RuntimeError):
            await app.run()
        return app, link, vision, window

    app, link, vision, window = asyncio.run(scenario())
    assert link.events[-2:] == ["x", "close"] and vision.stopped and window.closed
    assert app.skills.running is None


def test_window_keys_are_read_each_tick():
    async def scenario():
        window = FakeWindow([-1, "q"])
        link = FakeUdpLink()
        app = App(link, window=window, render=lambda p, hud: hud, hz=100)
        await app.run(max_ticks=50)
        return window, link

    window, link = asyncio.run(scenario())
    assert len(window.shown) == 2 and window.closed and link.closed


def test_hud_shows_health_and_contract_telemetry():
    async def scenario():
        app = App(FakeUdpLink(dict(TEL)), robot="mock", hz=100)
        app.tick()
        return app.hud(), App(FakeUdpLink(None), hz=100).hud()

    hud, no_tel = asyncio.run(scenario())
    assert hud.connected and hud.robot == "mock, udp"
    assert "balance" in hud.telemetry.state and "link ok lag 12 ms" in hud.telemetry.state
    assert "x +0.01 m" in hud.telemetry.state and hud.telemetry.pitch_deg == pytest.approx(5.71)
    assert not no_tel.connected

    from app.vision.debug_view import render

    assert render(None, hud).shape[2] == 3  # the real overlay draws it


# --- serve(): link start, flags, shutdown ---


def test_serve_starts_the_link_and_vision_then_quits_cleanly():
    args = parse_args(["--follow", "--no-api"])
    link, vision, window = FakeUdpLink(dict(TEL)), FakeVision(), FakeWindow([-1, -1, -1, "q"])
    app = asyncio.run(server.serve(args, link, vision=vision, follow_factory=Drive, window=window,
                                   render=lambda p, hud: hud))
    assert link.started and vision.started
    assert any(s[:2] == (0.2, -0.5) for s in link.sent)  # --follow started the skill
    assert link.events[-2:] == ["x", "close"] and vision.stopped and window.closed
    assert app.skills.running is None


def test_serve_link_start_failure_exits_with_a_message():
    class NoRobot(FakeUdpLink):
        async def start(self):
            raise RuntimeError("Robot not found on USB")

    vision, window = FakeVision(), FakeWindow()
    with pytest.raises(SystemExit) as e:
        asyncio.run(server.serve(parse_args(["--no-api"]), NoRobot(), vision=vision, window=window, render=lambda p, h: h))
    assert "Robot not found" in str(e.value.code)
    assert vision.stopped and window.closed and not vision.started
