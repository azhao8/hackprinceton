"""SerialLink (the USB robot link) against a fake serial port. Never opens a real port."""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import threading
import time
from pathlib import Path

import jsonschema
import pytest

from app.link import ALLOWED_LETTERS, FRESH_S, Health, RobotLink
from app.link.serial_link import SerialLink, find_serial_port, make_cmd, status_to_tel

CONTRACT = Path(__file__).resolve().parents[2] / "contract"
CMD_SCHEMA = json.loads((CONTRACT / "schema" / "cmd.schema.json").read_text())
TEL_SCHEMA = json.loads((CONTRACT / "schema" / "tel.schema.json").read_text())
# The status line has no yaw: check everything else the schema asks for.
TEL_SCHEMA_NO_YAW = {**TEL_SCHEMA, "required": [k for k in TEL_SCHEMA["required"] if k != "yaw"]}

# balance.ino loop(): Serial.printf("%s pitch %6.2f (err %6.2f) rate %7.1f  v %5.2f  x %5.2f  vt %4.1f wt %4.1f\n", ...)
FW_FMT = "%s pitch %6.2f (err %6.2f) rate %7.1f  v %5.2f  x %5.2f  vt %4.1f wt %4.1f\r\n"
RUN_LINE = FW_FMT % ("RUN", 5.71, 0.11, -1.3, 0.05, 0.12, 0.0, 0.0)
DRIVE_LINE = FW_FMT % ("RUN", 6.40, 0.80, 12.5, 0.28, 1.50, 0.3, -0.5)
OFF_LINE = FW_FMT % ("off", 11.2, 5.6, 0.0, 0.0, 0.0, 0.0, 0.0)
# contract/samples/tel-drive.json, as a later firmware might print it over USB
TEL_JSON = (CONTRACT / "samples" / "tel-drive.json").read_text().strip()


class FakeSerial:
    def __init__(self) -> None:
        self.written: list[bytes] = []
        self._incoming: list[bytes] = []
        self._lock = threading.Lock()
        self.closed = False
        self.fail_reads = False
        self.fail_writes = False

    def feed(self, data: bytes | str) -> None:
        with self._lock:
            self._incoming.append(data.encode() if isinstance(data, str) else data)

    def read(self, n: int = 1) -> bytes:
        if self.closed or self.fail_reads:
            raise OSError("device disconnected")
        with self._lock:
            if self._incoming:
                return self._incoming.pop(0)
        time.sleep(0.005)
        return b""

    def write(self, data: bytes) -> int:
        if self.closed or self.fail_writes:
            raise OSError("device disconnected")
        with self._lock:
            self.written.append(data)
        return len(data)

    def flush(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True

    def text(self) -> str:
        with self._lock:
            return b"".join(self.written).decode()

    def lines(self) -> list[str]:
        return self.text().splitlines()


class FakeClock:
    def __init__(self) -> None:
        self.t = 100.0

    def __call__(self) -> float:
        return self.t


def make_link(**kw) -> tuple[SerialLink, FakeSerial]:
    fake = FakeSerial()
    link = SerialLink("/dev/fake", serial_factory=lambda port, baud: fake, reconnect=kw.pop("reconnect", False), **kw)
    asyncio.run(link.start())
    assert link._drain()
    return link, fake


def close(link: SerialLink) -> None:
    asyncio.run(link.close())


def wait_for(cond, timeout: float = 2.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


def cmds(link: SerialLink, fake: FakeSerial) -> list[dict]:
    assert link._drain()
    return [json.loads(line) for line in fake.lines() if line.startswith("{")]


def letters(fake: FakeSerial) -> list[str]:
    return [ln for ln in fake.lines() if not ln.startswith("{")]


# ---- interface

def test_fw_format_is_what_the_firmware_prints():
    assert RUN_LINE == "RUN pitch   5.71 (err   0.11) rate    -1.3  v  0.05  x  0.12  vt  0.0 wt  0.0\r\n"


def test_matches_robotlink_protocol():
    # RobotLink isn't runtime_checkable: check the structure against the Protocol itself.
    link = SerialLink("/dev/fake", serial_factory=lambda p, b: FakeSerial())
    for name in ("start", "close", "send_cmd", "send_letter", "health"):
        want = inspect.signature(getattr(RobotLink, name))
        got = inspect.signature(getattr(SerialLink, name))
        assert list(got.parameters) == list(want.parameters), name
        assert [p.default for p in got.parameters.values()] == [p.default for p in want.parameters.values()], name
        assert inspect.iscoroutinefunction(getattr(SerialLink, name)) == inspect.iscoroutinefunction(getattr(RobotLink, name)), name
    assert link.telemetry is None
    assert isinstance(link.health(), Health)
    assert "arm" not in RobotLink.__dict__   # arm() is USB-only, never part of the interface


def test_start_asks_for_version_only():
    link, fake = make_link()
    try:
        assert fake.lines() == ["V"]
        assert link.connected
    finally:
        close(link)


def test_start_without_robot_raises(monkeypatch):
    monkeypatch.setattr("app.link.serial_link.find_serial_port", lambda: None)
    link = SerialLink(serial_factory=lambda p, b: FakeSerial())
    with pytest.raises(RuntimeError):
        asyncio.run(link.start())
    assert not link.connected


def test_find_serial_port_none_without_devices(monkeypatch):
    monkeypatch.setattr("app.link.serial_link.glob.glob", lambda pattern: [])
    assert find_serial_port() is None


# ---- cmd

def test_send_cmd_is_contract_v1():
    link, fake = make_link()
    try:
        link.send_cmd(0.3, 0.0)
        assert link._drain()
        link.send_cmd(-0.12345, 0.5, mode="balance")
        assert link._drain()
        link.send_cmd(0, 0, mode="idle")
        got = cmds(link, fake)
        for c in got:
            jsonschema.validate(c, CMD_SCHEMA)
        first = got[0]["seq"]
        assert [c["seq"] for c in got] == [first, first + 1, first + 2]
        assert got[0] == {"t": "cmd", "seq": first, "v": 0.3, "w": 0.0, "mode": "drive"}
        assert got[1] == {"t": "cmd", "seq": first + 1, "v": -0.123, "w": 0.5, "mode": "balance"}
        assert got[2]["mode"] == "idle"
        raw = [ln for ln in fake.lines() if ln.startswith("{")]
        assert raw[0] == '{"t":"cmd","seq":%d,"v":0.3,"w":0.0,"mode":"drive"}' % first   # compact
        assert all(len(ln) < 159 for ln in raw)     # balance.ino's JSON buffer is 160 bytes
        assert fake.text().count("\n") == 4         # V + three commands, one per line
    finally:
        close(link)


def test_make_cmd_matches_schema_and_newline():
    line = make_cmd(0.2, -0.4, "drive", 4294967295)
    assert line.endswith(b"\n") and line.count(b"\n") == 1
    jsonschema.validate(json.loads(line), CMD_SCHEMA)


def test_send_cmd_clamps_to_firmware_limits():
    link, fake = make_link()
    try:
        for v, w in ((5.0, -9.0), (-1.7, 1.6), (float("nan"), float("inf"))):
            link.send_cmd(v, w)
            assert link._drain()
        a, b, c = cmds(link, fake)
        assert (a["v"], a["w"]) == (1.0, -1.5)
        assert (b["v"], b["w"]) == (-1.0, 1.5)
        assert (c["v"], c["w"]) == (0.0, 0.0)
    finally:
        close(link)


def test_unknown_mode_rejected_before_sending():
    link, fake = make_link()
    try:
        seq = link.seq
        with pytest.raises(ValueError):
            link.send_cmd(0.1, 0.0, mode="kickstand")
        assert cmds(link, fake) == [] and link.seq == seq
    finally:
        close(link)


def test_send_cmd_does_not_block_on_a_stuck_port():
    link, fake = make_link()
    stuck = threading.Event()
    real_write = fake.write

    def slow_write(data: bytes) -> int:
        stuck.wait(2.0)
        return real_write(data)

    fake.write = slow_write
    try:
        t0 = time.monotonic()
        for _ in range(20):
            link.send_cmd(0.1, 0.0)
        assert time.monotonic() - t0 < 0.1           # queued, not written in the caller
        stuck.set()
        got = cmds(link, fake)
        assert 1 <= len(got) <= 2 and got[-1]["seq"] == link.seq   # stale drive commands coalesce
    finally:
        stuck.set()
        close(link)


# ---- letters

def test_allowed_letters_go_out():
    link, fake = make_link()
    try:
        for c in sorted(ALLOWED_LETTERS):
            link.send_letter(c)
        assert link._drain()
        assert letters(fake) == ["V", *sorted(ALLOWED_LETTERS)]
    finally:
        close(link)


@pytest.mark.parametrize("letter", ["g", "G", "i", "T", "V", "xx", ""])
def test_forbidden_letters_raise(letter):
    link, fake = make_link()
    try:
        with pytest.raises(ValueError):
            link.send_letter(letter)
        assert link._drain()
        assert letters(fake) == ["V"]
    finally:
        close(link)


def test_arm_is_separate_and_sends_g():
    link, fake = make_link()
    try:
        link.arm()
        assert link._drain()
        assert letters(fake) == ["V", "g"]
    finally:
        close(link)


def test_never_sends_g_unless_armed_explicitly():
    link, fake = make_link()
    try:
        for _ in range(5):
            link.send_cmd(0.2, 0.1)
            link._drain()
        link.send_letter("P")
    finally:
        close(link)
    sent = letters(fake)
    assert "g" not in sent and "G" not in sent and "i" not in sent


# ---- close / safety

def test_close_sends_x_then_closes_port():
    link, fake = make_link()
    link.send_cmd(0.2, 0.0)
    close(link)
    assert fake.lines()[-1] == "x"
    assert fake.closed and not link.connected
    close(link)                  # twice is fine
    link.send_cmd(0.2, 0.0)      # after close: dropped, no exception
    link.send_letter("x")
    assert fake.lines()[-1] == "x" and fake.lines().count("x") == 1


def test_async_context_manager_sends_x():
    fake = FakeSerial()

    async def scenario():
        async with SerialLink("/dev/fake", serial_factory=lambda p, b: fake, reconnect=False) as link:
            link.send_cmd(0.3, 0.0)
            raise RuntimeError("skill crashed")

    with pytest.raises(RuntimeError):
        asyncio.run(scenario())
    assert fake.lines()[-1] == "x"


def test_atexit_handler_sends_x():
    link, fake = make_link()
    try:
        link._atexit_motors_off()
        assert fake.lines()[-1] == "x"
    finally:
        close(link)


# ---- telemetry

def test_status_line_becomes_contract_tel():
    tel = status_to_tel(RUN_LINE)
    jsonschema.validate(tel, TEL_SCHEMA_NO_YAW)
    assert tel == {"t": "tel", "pitch": 5.71, "rate": -1.3, "vl": 0.05, "vr": 0.05, "batt": None,
                   "state": "balance", "fault": None, "x": 0.12}
    assert "yaw" not in tel and "ack" not in tel       # the line doesn't carry them

    drive = status_to_tel(DRIVE_LINE)
    jsonschema.validate(drive, TEL_SCHEMA_NO_YAW)
    assert drive["state"] == "drive"
    # w = -0.5 rad/s (turning right): left wheel faster, as balance.ino sendTelemetry()
    assert drive["vl"] == pytest.approx(0.28 + 0.5 * 0.0775, abs=1e-3)
    assert drive["vr"] == pytest.approx(0.28 - 0.5 * 0.0775, abs=1e-3)

    off = status_to_tel(OFF_LINE, fault="stop command")
    jsonschema.validate(off, TEL_SCHEMA_NO_YAW)
    assert off["state"] == "idle" and off["fault"] == "stop command"
    # drive.py's form without the vt / wt tail still parses
    assert status_to_tel("RUN pitch   1.00 (err  -4.60) rate     0.0  v  0.00  x  0.00")["state"] == "balance"
    assert status_to_tel("drive commands stopped: holding position") is None


def test_link_parses_status_line():
    link, fake = make_link()
    try:
        fake.feed(RUN_LINE)
        assert wait_for(lambda: link.telemetry is not None)
        jsonschema.validate(link.telemetry, TEL_SCHEMA_NO_YAW)
        assert link.telemetry["state"] == "balance" and link.telemetry["pitch"] == 5.71
    finally:
        close(link)


def test_json_tel_split_across_reads_validates_fully():
    link, fake = make_link()
    try:
        fake.feed(TEL_JSON[:30])
        fake.feed(TEL_JSON[30:] + "\n")
        assert wait_for(lambda: link.telemetry is not None)
        jsonschema.validate(link.telemetry, TEL_SCHEMA)
        assert link.telemetry == json.loads(TEL_JSON)
    finally:
        close(link)


def test_fault_from_stop_line_until_rearmed():
    link, fake = make_link()
    try:
        fake.feed("STOP: fell over (tilt > 30 deg)\r\n" + OFF_LINE)
        assert wait_for(lambda: link.telemetry is not None)
        assert link.telemetry["fault"] == "fell over (tilt > 30 deg)"
        assert link.telemetry["state"] == "idle"
        fake.feed("BALANCING (1800 s max)\r\n" + RUN_LINE)
        assert wait_for(lambda: link.telemetry["state"] == "balance")
        assert link.telemetry["fault"] is None
    finally:
        close(link)


def test_reader_survives_garbage():
    link, fake = make_link()
    try:
        fake.feed(b"\xff\xfe\x00garbage{not json\n")
        fake.feed(b'{"t":"tel","pitch":"oops"}\n[1,2]\n{"t":"other"}\n')
        fake.feed(b"x" * 10000)          # no newline for a long time
        fake.feed(b"\n=== Balance test ===\r\n")
        fake.feed("FW balance json-serial v1\r\n" + RUN_LINE)
        assert wait_for(lambda: link.telemetry is not None and link.telemetry["pitch"] == 5.71)
        assert link.firmware == "FW balance json-serial v1"
        assert link.connected
    finally:
        close(link)


def test_wait_for_firmware():
    link, fake = make_link()
    try:
        fake.feed("FW balance json-serial v1\r\n")
        assert asyncio.run(link.wait_for_firmware(timeout=2.0))
    finally:
        close(link)


# ---- health

def test_health_without_acks_is_telemetry_freshness():
    clock = FakeClock()
    link, fake = make_link(clock=clock)
    try:
        h = link.health()
        assert not h.ok and h.telemetry_age is None and h.ack_age is None and h.lag_ms is None
        fake.feed(RUN_LINE)
        assert wait_for(lambda: link.telemetry is not None)
        clock.t += FRESH_S / 2
        h = link.health()
        assert h.ok and h.telemetry_age == pytest.approx(FRESH_S / 2)
        assert h.ack_age is None and h.lag_ms is None    # no acks over USB yet: not made up
        clock.t += FRESH_S
        assert not link.health().ok                       # stale
    finally:
        close(link)
    assert not link.health().ok                           # port closed


def test_health_requires_acks_once_the_firmware_sends_them():
    clock = FakeClock()
    link, fake = make_link(clock=clock)
    try:
        link.send_cmd(0.0, 0.0)
        seq = link.seq
        clock.t += 0.02
        tel = {**json.loads(TEL_JSON), "ack": seq}
        fake.feed(json.dumps(tel) + "\n")
        assert wait_for(lambda: link.telemetry is not None)
        h = link.health()
        assert h.ok and h.ack_age == 0 and h.lag_ms == pytest.approx(20)
        clock.t += FRESH_S / 2
        fake.feed(RUN_LINE)                                # fresh telemetry, but no new ack
        assert wait_for(lambda: link.telemetry.get("ack") is None)
        clock.t += FRESH_S
        fake.feed(RUN_LINE)
        time.sleep(0.05)
        assert not link.health().ok                        # ack stale: down, like UdpLink
    finally:
        close(link)


def test_old_ack_from_another_run_is_ignored():
    clock = FakeClock()
    link, fake = make_link(clock=clock)
    try:
        link.send_cmd(0.0, 0.0)
        fake.feed(json.dumps({**json.loads(TEL_JSON), "ack": 5}) + "\n")
        assert wait_for(lambda: link.telemetry is not None)
        assert link.health().ack_age is None
    finally:
        close(link)


# ---- disconnects

def test_disconnect_marks_down_without_raising():
    link, fake = make_link()
    try:
        fake.feed(RUN_LINE)
        assert wait_for(lambda: link.telemetry is not None)
        fake.fail_reads = True
        fake.fail_writes = True
        assert wait_for(lambda: not link.connected)
        link.send_cmd(0.3, 0.0)      # no exception
        link.send_letter("x")
        assert link.telemetry is not None and not link.health().ok   # last state readable, link down
    finally:
        close(link)


def test_write_failure_marks_disconnected():
    link, fake = make_link()
    try:
        fake.fail_writes = True
        link.send_cmd(0.3, 0.0)
        assert wait_for(lambda: not link.connected)
    finally:
        close(link)


def test_reconnects_after_cable_tug():
    fakes = [FakeSerial(), FakeSerial()]
    opened: list[FakeSerial] = []

    def factory(port, baud):
        f = fakes[len(opened)]
        opened.append(f)
        return f

    link = SerialLink("/dev/fake", serial_factory=factory, reconnect=True)
    asyncio.run(link.start())
    try:
        fakes[0].feed("STOP: stop command\r\n")
        assert wait_for(lambda: link._fault == "stop command")
        fakes[0].fail_reads = True
        assert wait_for(lambda: len(opened) == 2 and link.connected, timeout=3.0)
        assert fakes[0].closed
        fakes[1].feed(RUN_LINE)
        assert wait_for(lambda: link.telemetry is not None)
        assert link.telemetry["fault"] is None            # the ESP32 rebooted: no fault
        link.send_cmd(0.1, 0.0)
        assert link._drain()
        # (J: the yaw poll starts again once the rebooted firmware talks)
        assert [ln for ln in fakes[1].lines() if ln != "J"] == [
            "V", '{"t":"cmd","seq":%d,"v":0.1,"w":0.0,"mode":"drive"}' % link.seq]
    finally:
        close(link)
    assert fakes[1].lines()[-1] == "x"


# ---- J polling: yaw over USB (#62)

def tel_reply(**changes) -> str:
    """What balance.ino prints for J (formatTelemetry), as the sample with some values changed."""
    return json.dumps({**json.loads(TEL_JSON), **changes}, separators=(",", ":")) + "\r\n"


def test_j_polls_start_once_the_firmware_talks_and_j_is_not_a_public_letter():
    link, fake = make_link(yaw_poll_hz=50)
    try:
        time.sleep(0.1)
        assert fake.lines() == ["V"]                      # not heard from yet: no J
        fake.feed(RUN_LINE)                               # printed from loop(): it reads commands
        assert wait_for(lambda: fake.lines().count("J") >= 3)
        assert "J" not in ALLOWED_LETTERS
        with pytest.raises(ValueError):
            link.send_letter("J")
    finally:
        close(link)
    assert fake.lines()[-1] == "x"                        # no J after the motors-off on close


def test_v_reply_also_starts_the_polls():
    link, fake = make_link(yaw_poll_hz=50)
    try:
        fake.feed("FW balance json-serial v1\r\n")       # e.g. the status line was toggled off with i
        assert wait_for(lambda: "J" in fake.lines())
    finally:
        close(link)


def test_j_replies_give_telemetry_a_yaw_and_polling_goes_on():
    link, fake = make_link(yaw_poll_hz=50, yaw_poll_give_up_s=0.3)
    try:
        fake.feed(RUN_LINE)
        assert wait_for(lambda: "J" in fake.lines())
        fake.feed(tel_reply(yaw=12.5))
        assert wait_for(lambda: link.telemetry.get("yaw") == 12.5)
        jsonschema.validate(link.telemetry, TEL_SCHEMA)
        fake.feed(DRIVE_LINE)                             # a status line between replies keeps that yaw
        assert wait_for(lambda: link.telemetry["pitch"] == 6.40)
        assert link.telemetry["yaw"] == 12.5 and "ack" not in link.telemetry
        jsonschema.validate(link.telemetry, TEL_SCHEMA)
        fake.feed(tel_reply(yaw=-171.2, pitch=5.9))
        assert wait_for(lambda: link.telemetry.get("yaw") == -171.2)
        n = fake.lines().count("J")
        time.sleep(0.5)                                   # past the give-up time: answered, so it keeps polling
        assert fake.lines().count("J") >= n + 5
    finally:
        close(link)


def test_status_lines_drop_a_stale_yaw():
    clock = FakeClock()
    link, fake = make_link(clock=clock, yaw_poll_hz=50)
    try:
        fake.feed(tel_reply(yaw=-7.0))
        assert wait_for(lambda: link.telemetry is not None)
        fake.feed(RUN_LINE)
        assert wait_for(lambda: link.telemetry["pitch"] == 5.71)
        assert link.telemetry["yaw"] == -7.0
        clock.t += FRESH_S
        fake.feed(DRIVE_LINE)
        assert wait_for(lambda: link.telemetry["pitch"] == 6.40)
        assert "yaw" not in link.telemetry                # the last reply is too old to stand for now
    finally:
        close(link)


def test_j_polling_stops_when_the_firmware_never_answers(caplog):
    caplog.set_level(logging.INFO, logger="app.link")
    link, fake = make_link(yaw_poll_hz=50, yaw_poll_give_up_s=0.2)
    try:
        fake.feed(RUN_LINE)
        assert wait_for(lambda: "J" in fake.lines())
        assert wait_for(lambda: any("no reply to J" in r.getMessage() for r in caplog.records))
        n = fake.lines().count("J")
        assert 2 <= n <= 20                               # ~0.2 s of polls at 50 Hz
        for _ in range(3):
            fake.feed(RUN_LINE)                           # still talking, still no JSON: stays stopped
        time.sleep(0.2)
        assert fake.lines().count("J") == n
        assert link.telemetry is not None and "yaw" not in link.telemetry
        link.send_cmd(0.0, 0.0)                           # driving is unaffected
        assert cmds(link, fake)
    finally:
        close(link)
    assert sum("no reply to J" in r.getMessage() for r in caplog.records) == 1   # logged once


def test_no_polls_when_disabled():
    link, fake = make_link(yaw_poll_hz=0)
    try:
        fake.feed(RUN_LINE)
        assert wait_for(lambda: link.telemetry is not None)
        time.sleep(0.1)
        assert "J" not in fake.lines()
    finally:
        close(link)
