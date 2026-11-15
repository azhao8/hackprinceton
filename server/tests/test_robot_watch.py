"""The drift watch and auto-start (app/robot_watch.py), and the mock's matching hooks."""

import math
import re
from pathlib import Path

from app.robot_watch import FIRMWARE_TRIM, AutoStart, DriftWatch
from mock.robot import MockRobot

BALANCE_INO = Path(__file__).resolve().parents[2] / "firmware" / "balance" / "balance.ino"


def feed(w, samples, t0=0.0):
    hits = 0
    for i, (pitch, rate) in enumerate(samples):
        hits += bool(w.feed({"state": "idle", "pitch": pitch, "rate": rate}, t0 + i * 0.05))
    return hits


def test_trim_matches_the_firmware():
    m = re.search(r"^float trim = (-?[\d.]+)f;", BALANCE_INO.read_text(), re.M)
    assert m and float(m.group(1)) == FIRMWARE_TRIM


def test_a_steady_rate_with_a_flat_tilt_is_drift():
    w = DriftWatch()
    assert feed(w, [(70.0, 27.0 + 0.1 * math.sin(i)) for i in range(50)]) == 1
    assert w.on and w.rate == 27.0


def test_a_small_bias_counts_and_clears_when_fixed():
    w = DriftWatch()
    feed(w, [(12.0, -4.0)] * 50)
    assert w.on
    feed(w, [(12.0, 0.2)] * 50, t0=10.0)
    assert not w.on


def test_a_real_rotation_is_not_drift():
    w = DriftWatch()   # turned steadily at 5 deg/s: the tilt follows it
    feed(w, [(i * 0.05 * 5.0, 5.0) for i in range(60)])
    assert not w.on


def test_handling_and_noise_are_not_drift():
    w = DriftWatch()
    feed(w, [(0.0, 0.2 * math.sin(i)) for i in range(60)])   # sensor noise
    feed(w, [(30 * math.sin(i / 5), 40 * math.cos(i / 5)) for i in range(80)], t0=10)       # carried around
    assert not w.on


def test_only_judged_with_the_motors_off():
    w = DriftWatch()
    for i in range(60):
        w.feed({"state": "balance", "pitch": -3.6, "rate": 27.0}, i * 0.05)
    assert not w.on


def test_a_runaway_bias_counts_even_when_the_tilt_follows_it():
    w = DriftWatch()   # above 30 deg/s the firmware is gyro-only: the tilt runs away with the bias
    feed(w, [(i * 0.05 * 40.0, 40.0) for i in range(50)])
    assert w.on


def test_after_a_recalibration_it_waits_then_judges_again():
    w = DriftWatch()
    feed(w, [(12.0, 9.0)] * 50)
    w.reset(now=10.0)
    assert not w.on
    feed(w, [(12.0, 9.0)] * 50, t0=10.0)     # ignored while it measures (3 s)...
    assert not w.on
    feed(w, [(12.0, 9.0)] * 50, t0=13.0)     # ...then still bad: on again
    assert w.on


def test_autostart_retries_when_the_firmware_refuses_and_times_out():
    sent = []
    a = AutoStart(lambda: sent.append("g"), lambda: FIRMWARE_TRIM, timeout_s=10.0)
    a.start(0.0)
    t = 0.0
    for _ in range(30):
        a.feed({"state": "idle", "pitch": FIRMWARE_TRIM, "rate": 0.0}, t)
        t += 0.05
    assert sent == ["g"]
    for _ in range(80):                                       # still idle: it tries again
        a.feed({"state": "idle", "pitch": FIRMWARE_TRIM, "rate": 0.0}, t)
        t += 0.05
    assert sent == ["g", "g"]
    assert a.feed({"state": "idle", "pitch": 20.0, "rate": 0.0}, 11.0) == "timeout" and not a.waiting


def test_the_mock_can_be_held_upright_and_drift():
    r = MockRobot(held=True)
    r.step(0.01, 1.0)
    assert abs(r.pitch - r.trim) < 1.0
    r.handle_char("g", 1.0)
    assert r.running
    r = MockRobot(gyro_bias=27.0)
    r.step(0.01, 1.0)
    assert abs(r.rate - 27.0) < 0.2
    r.handle_char("c", 1.0)
    r.step(0.01, 2.0)
    assert abs(r.rate) < 0.2
