"""SerialLink and LoggingLink against a fake serial port. Never opens a real port."""

from __future__ import annotations

import json
import threading
import time

import pytest

from app.link import LoggingLink, RobotLink, SerialLink, Telemetry
from app.link.serial_link import parse_line

# balance.ino loop(): Serial.printf("%s pitch %6.2f (err %6.2f) rate %7.1f  v %5.2f  x %5.2f  vt %4.1f wt %4.1f\n", ...)
FW_FMT = "%s pitch %6.2f (err %6.2f) rate %7.1f  v %5.2f  x %5.2f  vt %4.1f wt %4.1f\r\n"
RUN_LINE = FW_FMT % ("RUN", 5.71, 0.11, -1.3, 0.05, 0.12, 0.0, 0.0)
DRIVE_LINE = FW_FMT % ("RUN", 6.40, 0.80, 12.5, 0.28, 1.50, 0.3, -0.5)
OFF_LINE = FW_FMT % ("off", 11.2, 5.6, 0.0, 0.0, 0.0, 0.0, 0.0)
# balance.ino sendTelemetry()
TEL_JSON = ('{"t":"tel","pitch":5.62,"rate":-0.4,"vl":0.100,"vr":0.200,"batt":null,'
            '"state":"drive","fault":null,"x":0.512,"yaw":3.1}')


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
        self.written.append(data)
        return len(data)

    def flush(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True

    def text(self) -> str:
        return b"".join(self.written).decode()

    def lines(self) -> list[str]:
        return self.text().splitlines()


def make_link(**kw) -> tuple[SerialLink, FakeSerial]:
    fake = FakeSerial()
    link = SerialLink("/dev/fake", serial_factory=lambda port, baud: fake, reconnect=False, **kw)
    link.open()
    return link, fake


def wait_for(cond, timeout: float = 2.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


def cmds(fake: FakeSerial) -> list[dict]:
    return [json.loads(line) for line in fake.lines() if line.startswith("{")]


def test_fw_format_is_what_the_firmware_prints():
    assert RUN_LINE == "RUN pitch   5.71 (err   0.11) rate    -1.3  v  0.05  x  0.12  vt  0.0 wt  0.0\r\n"


def test_implements_protocol():
    link, _ = make_link()
    try:
        assert isinstance(link, RobotLink)
        assert isinstance(LoggingLink(), RobotLink)
    finally:
        link.close()


def test_open_asks_for_version_only():
    link, fake = make_link()
    try:
        assert fake.lines() == ["V"]
        assert link.connected
    finally:
        link.close()


def test_send_payload_and_seq():
    link, fake = make_link()
    try:
        link.send(0.3, 0.0)
        link.send(-0.12345, 0.5, mode="balance")
        link.send(0, 0, mode="idle")
        lines = [ln for ln in fake.lines() if ln.startswith("{")]
        assert lines[0] == '{"t":"cmd","v":0.3,"w":0.0,"mode":"drive","seq":1}'
        got = cmds(fake)
        assert got[1] == {"t": "cmd", "v": -0.123, "w": 0.5, "mode": "balance", "seq": 2}
        assert got[2]["mode"] == "idle" and got[2]["seq"] == 3
        assert all(len(ln) < 159 for ln in lines)   # balance.ino's JSON buffer is 160 bytes
        assert fake.text().count("\n") == 4         # V + three commands, one per line
    finally:
        link.close()


def test_send_clamps_to_firmware_limits():
    link, fake = make_link()
    try:
        link.send(5.0, -9.0)
        link.send(-0.7, 1.6)
        link.send(float("nan"), float("inf"))
        a, b, c = cmds(fake)
        assert (a["v"], a["w"]) == (0.6, -1.5)
        assert (b["v"], b["w"]) == (-0.6, 1.5)
        assert (c["v"], c["w"]) == (0.0, 0.0)
    finally:
        link.close()


def test_bad_mode_rejected_before_sending():
    link, fake = make_link()
    try:
        with pytest.raises(ValueError):
            link.send(0.1, 0.0, mode="kickstand")
        assert cmds(fake) == []
    finally:
        link.close()


def test_one_letter_commands():
    link, fake = make_link()
    try:
        link.arm()
        link.park()
        link.motors_off()
        assert fake.lines() == ["V", "g", "P", "x"]
    finally:
        link.close()


def test_never_sends_arm_or_standup_unless_asked():
    link, fake = make_link()
    try:
        for _ in range(5):
            link.send(0.2, 0.1)
        link.park()
    finally:
        link.close()
    letters = [ln for ln in fake.lines() if not ln.startswith("{")]
    assert "g" not in letters and "G" not in letters and "i" not in letters


def test_close_sends_x_then_closes_port():
    link, fake = make_link()
    link.send(0.2, 0.0)
    link.close()
    assert fake.lines()[-1] == "x"
    assert fake.closed
    assert not link.connected
    link.close()   # twice is fine
    link.send(0.2, 0.0)   # after close: dropped, no exception
    assert fake.lines()[-1] == "x"


def test_context_manager_sends_x():
    fake = FakeSerial()
    with pytest.raises(RuntimeError):
        with SerialLink("/dev/fake", serial_factory=lambda p, b: fake, reconnect=False) as link:
            link.send(0.3, 0.0)
            raise RuntimeError("skill crashed")
    assert fake.lines()[-1] == "x"


def test_atexit_handler_sends_x():
    link, fake = make_link()
    try:
        link._atexit_motors_off()
        assert fake.lines()[-1] == "x"
    finally:
        link.close()


def test_parses_status_line():
    link, fake = make_link()
    try:
        fake.feed(RUN_LINE)
        assert wait_for(lambda: link.telemetry is not None)
        t = link.telemetry
        assert isinstance(t, Telemetry)
        assert t.state == "balance" and t.pitch_deg == 5.71 and t.v == 0.05
        assert t.batt is None and t.fault is None
        assert t.raw == RUN_LINE.strip()
    finally:
        link.close()


def test_status_line_states():
    now = 1.0
    assert parse_line(DRIVE_LINE, now).state == "drive"
    assert parse_line(DRIVE_LINE, now).v == 0.28
    assert parse_line(OFF_LINE, now).state == "idle"
    # drive.py's regex form without the vt / wt tail still parses
    assert parse_line("RUN pitch   1.00 (err  -4.60) rate     0.0  v  0.00  x  0.00", now).state == "balance"


def test_parses_json_telemetry_split_across_reads():
    link, fake = make_link()
    try:
        fake.feed(TEL_JSON[:30])
        fake.feed(TEL_JSON[30:] + "\n")
        assert wait_for(lambda: link.telemetry is not None)
        t = link.telemetry
        assert t.state == "drive" and t.pitch_deg == 5.62
        assert t.v == pytest.approx(0.15) and t.batt is None and t.fault is None
    finally:
        link.close()


def test_fault_from_stop_line_until_rearmed():
    link, fake = make_link()
    try:
        fake.feed("STOP: fell over (tilt > 30 deg)\r\n" + OFF_LINE)
        assert wait_for(lambda: link.telemetry is not None)
        assert link.telemetry.fault == "fell over (tilt > 30 deg)"
        assert link.telemetry.state == "idle"
        fake.feed("BALANCING (1800 s max)\r\n" + RUN_LINE)
        assert wait_for(lambda: link.telemetry.state == "balance")
        assert link.telemetry.fault is None
    finally:
        link.close()


def test_reader_survives_garbage():
    link, fake = make_link()
    try:
        fake.feed(b"\xff\xfe\x00garbage{not json\n")
        fake.feed(b'{"t":"tel","pitch":"oops"}\n[1,2]\n{"t":"other"}\n')
        fake.feed(b"x" * 10000)          # no newline for a long time
        fake.feed(b"\n=== Balance test ===\r\n")
        fake.feed("FW balance json-serial v1\r\n" + RUN_LINE)
        assert wait_for(lambda: link.telemetry is not None and link.telemetry.pitch_deg == 5.71)
        assert link.firmware == "FW balance json-serial v1"
        assert link.connected
    finally:
        link.close()


def test_wait_for_firmware():
    link, fake = make_link()
    try:
        fake.feed("FW balance json-serial v1\r\n")
        assert link.wait_for_firmware(timeout=2.0)
    finally:
        link.close()


def test_disconnect_marks_not_connected_without_raising():
    link, fake = make_link()
    try:
        fake.feed(RUN_LINE)
        assert wait_for(lambda: link.telemetry is not None)
        fake.fail_reads = True
        fake.fail_writes = True
        assert wait_for(lambda: not link.connected)
        link.send(0.3, 0.0)      # no exception
        link.motors_off()
        assert link.telemetry is not None   # last known state stays readable
    finally:
        link.close()


def test_write_failure_marks_disconnected():
    link, fake = make_link()
    try:
        fake.fail_writes = True
        link.send(0.3, 0.0)
        assert not link.connected
    finally:
        link.close()


def test_reconnects_after_cable_tug():
    fakes = [FakeSerial(), FakeSerial()]
    opened: list[FakeSerial] = []

    def factory(port, baud):
        f = fakes[len(opened)]
        opened.append(f)
        return f

    link = SerialLink("/dev/fake", serial_factory=factory, reconnect=True)
    link.open()
    try:
        fakes[0].fail_reads = True
        assert wait_for(lambda: len(opened) == 2 and link.connected, timeout=3.0)
        assert fakes[0].closed
        fakes[1].feed(RUN_LINE)
        assert wait_for(lambda: link.telemetry is not None)
        link.send(0.1, 0.0)
        assert fakes[1].lines() == ["V", '{"t":"cmd","v":0.1,"w":0.0,"mode":"drive","seq":1}']
    finally:
        link.close()
    assert fakes[1].lines()[-1] == "x"


def test_open_without_robot_raises(monkeypatch):
    monkeypatch.setattr("app.link.serial_link.find_serial_port", lambda: None)
    link = SerialLink(serial_factory=lambda p, b: FakeSerial())
    with pytest.raises(RuntimeError):
        link.open()
    assert not link.connected


def test_logging_link_records():
    link = LoggingLink()
    link.open()
    assert link.connected and link.telemetry is None
    link.send(0.9, 0.2)
    link.arm()
    link.park()
    link.close()
    assert list(link.sent) == ['{"t":"cmd","v":0.6,"w":0.2,"mode":"drive","seq":1}\n', "g\n", "P\n", "x\n"]
    assert not link.connected
