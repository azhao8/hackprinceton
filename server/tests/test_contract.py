"""Contract v1: samples and the mock robot's telemetry match the schemas, and the mock behaves
like the firmware (contract/README.md)."""

import asyncio
import json
import socket
from pathlib import Path

import jsonschema
import pytest

from mock.__main__ import serve
from mock.robot import KICK_ANGLE, TRIM, MockRobot

CONTRACT = Path(__file__).resolve().parents[2] / "contract"
SCHEMAS = {name: json.loads((CONTRACT / "schema" / f"{name}.schema.json").read_text()) for name in ("cmd", "tel")}
SAMPLES = sorted((CONTRACT / "samples").glob("*.json"))


def check(msg: dict) -> None:
    jsonschema.validate(msg, SCHEMAS[msg["t"]])


@pytest.mark.parametrize("path", SAMPLES, ids=lambda p: p.name)
def test_samples_match_schema(path):
    check(json.loads(path.read_text()))


def test_schemas_are_valid():
    for schema in SCHEMAS.values():
        jsonschema.Draft202012Validator.check_schema(schema)


# ---- the mock, driven directly

def cmd(robot: MockRobot, now: float, **kw) -> None:
    robot.handle_packet(json.dumps({"t": "cmd", **kw}).encode(), now)


def run(robot: MockRobot, start: float, seconds: float, dt: float = 0.01, feed=None) -> float:
    t = start
    while t < start + seconds:
        if feed:
            feed(t)
        t += dt
        robot.step(dt, t)
        check(robot.telemetry())
    return t


def test_starts_idle_and_upright():
    r = MockRobot()
    tel = r.telemetry()
    check(tel)
    assert tel["state"] == "idle" and tel["pitch"] == TRIM and tel["ack"] == 0


def test_drive_is_ignored_until_g():
    r = MockRobot()
    cmd(r, 0.0, seq=1, v=0.3, w=0.0, mode="drive")
    run(r, 0.0, 0.2)
    assert r.telemetry()["state"] == "idle" and r.vcmd == 0
    assert r.telemetry()["ack"] == 1                  # seq still counts, like the firmware


def test_g_arms_and_drive_ramps_and_clamps():
    r = MockRobot()
    r.handle_packet(b"g", 0.0)
    assert r.telemetry()["state"] == "balance" and r.pitch == TRIM
    t = run(r, 0.0, 2.0, feed=lambda t: cmd(r, t, seq=int(t * 100), v=5.0, w=0.0, mode="drive"))
    assert r.vt == 1.0                                # clamped
    assert 0.95 < r.vcmd <= 1.0                       # ramped at 0.5 m/s^2 for 2 s
    assert r.telemetry()["state"] == "drive" and r.x > 0
    assert t > 0


def test_watchdog_stops_and_holds():
    r = MockRobot()
    r.handle_packet(b"g", 0.0)
    cmd(r, 0.0, v=0.3, w=0.5, mode="drive")
    run(r, 0.0, 0.5)                                  # no more commands
    assert r.vt == 0 and r.wt == 0 and r.telemetry()["state"] == "balance"


def test_idle_turns_the_motors_off_with_a_fault():
    r = MockRobot()
    r.handle_packet(b"g", 0.0)
    cmd(r, 0.1, mode="idle")
    tel = r.telemetry()
    assert tel["state"] == "idle" and tel["fault"] == "idle command (Wi-Fi)"
    r.handle_packet(b"g", 0.2)
    assert r.telemetry()["fault"] is None


def test_left_turn_reaches_90_degrees():
    r = MockRobot()
    r.handle_packet(b"g", 0.0)
    r.handle_packet(b"L", 0.0)
    run(r, 0.0, 6.0)
    assert not r.turning and 88 <= r.yaw <= 92


def test_park_ends_idle_on_the_kickstand():
    r = MockRobot()
    r.handle_packet(b"g", 0.0)
    r.handle_packet(b"P", 0.0)
    run(r, 0.0, 1.5)
    tel = r.telemetry()
    assert tel["state"] == "idle" and tel["pitch"] == KICK_ANGLE and tel["fault"] is None


def test_broken_packets_are_dropped():
    r = MockRobot()
    r.handle_packet(b"{not json", 0.0)
    r.handle_packet(b"[1,2]", 0.0)
    assert r.telemetry()["state"] == "idle"


# ---- the mock over real UDP

def test_mock_over_udp_acks_and_streams_telemetry():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:   # a free port
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]

    async def real():
        ready = asyncio.Event()
        task = asyncio.create_task(serve("127.0.0.1", port, verbose=False, ready=ready))
        await ready.wait()
        loop = asyncio.get_running_loop()
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setblocking(False)
        sock.sendto(b'{"t":"cmd","seq":42,"mode":"balance"}', ("127.0.0.1", port))
        received = []
        deadline = loop.time() + 1.0
        while loop.time() < deadline and len(received) < 5:
            try:
                data = await asyncio.wait_for(loop.sock_recv(sock, 2048), 0.2)
                received.append(json.loads(data))
            except asyncio.TimeoutError:
                pass
        sock.close()
        task.cancel()
        return received

    tels = asyncio.run(real())
    assert len(tels) >= 5                             # about 20 a second
    for tel in tels:
        check(tel)
    assert tels[-1]["ack"] == 42 and tels[-1]["state"] == "idle"
