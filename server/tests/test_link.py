"""The UDP link and the app's drive loop, against the mock robot over real UDP."""

import asyncio
import socket

import pytest

from app.__main__ import drive_loop
from app.arbiter import Arbiter, Source
from app.link import UdpLink
from mock.__main__ import serve


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def start_mock(port: int, armed: bool = False) -> asyncio.Task:
    ready = asyncio.Event()
    task = asyncio.create_task(serve("127.0.0.1", port, verbose=False, ready=ready, armed=armed))
    await ready.wait()
    return task


async def send_for(link: UdpLink, seconds: float, v=0.0, w=0.0) -> None:
    for _ in range(int(seconds * 20)):
        link.send_cmd(v, w)
        await asyncio.sleep(0.05)


def test_link_gets_telemetry_and_acks():
    async def scenario():
        port = free_port()
        mock = await start_mock(port)
        link = UdpLink("127.0.0.1", port)
        await link.start()
        assert not link.health().ok                     # nothing sent yet
        await send_for(link, 0.4)
        h = link.health()
        assert h.ok and h.lag_ms is not None and h.lag_ms < 200
        assert link.telemetry["t"] == "tel" and link.telemetry["state"] == "idle"
        await link.close()
        mock.cancel()

    asyncio.run(scenario())


def test_link_reports_down_when_no_robot():
    async def scenario():
        link = UdpLink("127.0.0.1", free_port())       # nobody listening
        await link.start()
        await send_for(link, 0.3)
        assert not link.health().ok and link.telemetry is None
        await link.close()

    asyncio.run(scenario())


def test_link_refuses_to_send_g():
    link = UdpLink("127.0.0.1", 9)
    with pytest.raises(ValueError):
        link.send_letter("g")


def test_drive_loop_moves_the_armed_mock_and_estop_stops_it():
    async def scenario():
        port = free_port()
        mock = await start_mock(port, armed=True)
        arb = Arbiter()
        link = UdpLink("127.0.0.1", port)
        await link.start()
        stop = asyncio.Event()
        loop_task = asyncio.create_task(drive_loop(arb, link, stop))

        for _ in range(30):                             # 1.5 s of a skill driving forward
            arb.request(Source.SKILL, 0.3, 0.0)
            await asyncio.sleep(0.05)
        tel = link.telemetry
        assert tel["state"] == "drive" and tel["x"] > 0.1 and link.health().ok

        arb.estop(True)
        await asyncio.sleep(1.5)                        # ramps down at 0.5 m/s^2
        tel = link.telemetry
        assert tel["state"] == "balance" and abs(tel["vl"]) < 0.01

        stop.set()
        await loop_task
        await link.close()
        mock.cancel()

    asyncio.run(scenario())


def test_trim_goes_in_one_packet():
    link = UdpLink("127.0.0.1", 9)
    sent = []
    link._send = sent.append
    link.send_trim(-3)
    link.send_trim(2)
    link.send_trim(0)
    assert sent == [b"yyy", b"tt"]


def test_mock_robot_shifts_its_trim():
    from mock.robot import TRIM, MockRobot
    robot = MockRobot()
    for c in "yyyyt":
        robot.handle_char(c, 0.0)
    assert robot.trim == pytest.approx(TRIM - 0.75)


def test_reversed_link_swaps_forward_and_backward():
    from app.link import ReversedLink

    class Inner:
        telemetry = {"t": "tel", "pitch": 2.0, "vl": 0.1, "vr": 0.3, "x": 0.5, "yaw": 10.0}

        def __init__(self):
            self.sent = []

        def send_cmd(self, v, w, mode="drive"):
            self.sent.append(("cmd", v, w, mode))

        def send_letter(self, c):
            self.sent.append(("letter", c))

        def health(self):
            return "healthy"

    inner = Inner()
    link = ReversedLink(inner)
    link.send_cmd(0.2, 0.5)
    for c in "FBLx":
        link.send_letter(c)
    assert inner.sent == [("cmd", -0.2, 0.5, "drive"), ("letter", "B"), ("letter", "F"), ("letter", "L"), ("letter", "x")]
    tel = link.telemetry
    assert (tel["vl"], tel["vr"], tel["x"], tel["pitch"], tel["yaw"]) == (-0.3, -0.1, -0.5, 2.0, 10.0)
    assert link.health() == "healthy"   # everything else passes through


def test_reversed_link_follows_a_changing_camera():
    from app.link import ReversedLink

    class Inner:
        telemetry = {"vl": 0.2, "vr": 0.2, "x": 1.0}

        def __init__(self):
            self.v = []

        def send_cmd(self, v, w, mode="drive"):
            self.v.append(v)

    settings = {"camera": "back"}
    inner = Inner()
    link = ReversedLink(inner, lambda: True != (settings["camera"] == "front"))   # as serve() wires it
    link.send_cmd(0.3, 0.0)
    settings["camera"] = "front"
    link.send_cmd(0.3, 0.0)
    assert inner.v == [-0.3, 0.3] and link.telemetry["x"] == 1.0
