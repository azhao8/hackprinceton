"""The drift watch and auto-start (app/robot_watch.py), and the mock's matching hooks."""

import math
import re
from pathlib import Path

from app.robot_watch import FIRMWARE_TRIM, AutoStart, DriftWatch, FallWatch, is_fall
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


# --- #88: falls and the auto-restart after one ------------------------------------------------------

FELL = "fell over (tilt > 30 deg)"


def test_the_fall_fault_matches_the_firmware():
    assert '"' + FELL + '"' in BALANCE_INO.read_text() and is_fall(FELL)
    assert not is_fall("stop command") and not is_fall("idle command (Wi-Fi)") and not is_fall(None)


def test_a_fall_is_balancing_then_idle_with_the_fall_fault():
    w = FallWatch()
    assert not w.feed({"state": "balance", "fault": None}, 0.0)
    assert w.feed({"state": "idle", "fault": FELL}, 0.05)
    assert not w.feed({"state": "idle", "fault": FELL}, 0.10)          # once, not every message after
    for stop in ("stop command", "idle command (Wi-Fi)", None):          # Cut motor power, Wi-Fi idle, Park
        w.feed({"state": "drive", "fault": None}, 1.0)
        assert not w.feed({"state": "idle", "fault": stop}, 1.05)
    w.feed({"state": "idle", "fault": None}, 2.0)
    assert not w.feed({"state": "idle", "fault": FELL}, 2.05)          # was already idle: a stale fault


def test_the_restart_count_resets_after_balancing_a_while():
    w = FallWatch(stable_s=30.0)
    w.restarts = 2
    w.feed({"state": "balance"}, 0.0)
    w.feed({"state": "balance"}, 29.0)
    assert w.restarts == 2
    w.feed({"state": "balance"}, 30.5)
    assert w.restarts == 0


def run(a, seconds, t0, pitch=FIRMWARE_TRIM, rate=0.0, wobble=0.0, wobble_rate=0.0):
    """Feed `seconds` of 20 Hz idle telemetry; wobble = tilt amplitude (deg) at 1 Hz."""
    sent_before, t = None, t0
    for i in range(int(seconds * 20)):
        ph = 2 * math.pi * i * 0.05
        a.feed({"state": "idle", "pitch": pitch + wobble * math.sin(ph), "rate": rate + wobble_rate * math.cos(ph)}, t)
        t += 0.05
    return t


def test_after_a_fall_lying_down_or_being_carried_never_starts():
    def fresh():
        sent = []
        a = AutoStart(lambda: sent.append("g"), lambda: FIRMWARE_TRIM)
        a.start(0.0, fall=True)
        return a, sent

    a, _ = fresh()
    assert a.view() == {"waiting": True, "note": "I fell: hold me upright and steady", "fall": True}
    for kw in (dict(pitch=FIRMWARE_TRIM + 80.0),                   # lying on the floor
               dict(pitch=11.2),                                    # lying on the back
               dict(wobble=2.5, wobble_rate=6.0),                   # carried upright: it rocks with each step
               dict(wobble=1.5, wobble_rate=4.0, rate=3.5),         # carried and slowly turning over
               dict(wobble=0.5, wobble_rate=15.0)):                 # jostled
        a, sent = fresh()
        run(a, 10.0, 0.0, **kw)
        assert sent == [] and a.waiting, kw
    a, sent = fresh()
    t = run(a, 1.5, 0.0)                                            # 1.5 s steady: a manual Start would go...
    assert sent == []                                               # ...after a fall it wants 2 s
    run(a, 1.0, t, wobble=0.4, wobble_rate=1.5)                     # held upright and steady
    assert sent == ["g"]


def test_a_fall_wait_times_out_with_its_own_note():
    a = AutoStart(lambda: None, lambda: FIRMWARE_TRIM)
    a.start(0.0, fall=True)
    assert a.feed({"state": "idle", "pitch": 60.0, "rate": 0.0}, 121.0) == "timeout"
    assert not a.waiting and not a.fall and "after the fall" in a.note


def test_the_mock_can_fall():
    r = MockRobot()
    r.handle_char("g", 0.0)
    r.fall()
    assert not r.running and r.fault == FELL and r.telemetry()["state"] == "idle"
    r = MockRobot()
    r.handle_char("x", 0.0)
    assert r.fault is None                     # x while idle: no fault
