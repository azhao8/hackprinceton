"""Two watchers on the robot's telemetry (#79): a drifting tilt sensor, and auto-start.

Both are fed every new telemetry message (`feed(tel, now)`) and have no I/O of their own.

**Drift.** The firmware's tilt is a complementary filter (balance.ino: 99% gyro, 1% accelerometer
at 200 Hz, so the accelerometer pulls the tilt back with a time constant of about 0.5 s). When
the gyro's zero is wrong (it calibrated while the robot moved), `rate` reads a steady non-zero
value while the robot lies still, and the tilt settles at a wrong angle (Sat 11 pm: 27 deg/s while
still, and the tilt read 69 deg off). A real rotation can't look like that: if the robot really
turned at 3 deg/s for 2 s, the tilt would move about 6 deg with it. So "drifting" means, over the
last 2 s with the motors off:
- the rate is steady (spread <= 1.5 deg/s: nobody is holding or moving it),
- its average is at least 3 deg/s,
- and the tilt moved much less than that rate adds up to (<= 25% of it, or under 1 deg).
Above 30 deg/s the firmware ignores the accelerometer, so the tilt runs away with the bias; a
steady 30 deg/s for 2 s with that little spread doesn't come from hands, so that counts too.
It stays on until the rate reads steady near zero (|average| <= 1.5 deg/s) or a recalibration.
It only judges while the robot lies still; held in someone's hands the spread is too big to tell.

**Auto-start.** Start no longer needs the robot upright at the moment of the press. After `start()`
it waits (up to `timeout_s`) for the robot to be held upright and steady: within `window_deg` of
the trim, every rate sample under `max_rate`, and the average rate under `mean_rate`, for
`hold_s`. Then it calls `arm()` (g). If the robot doesn't start balancing within `retry_s` (the
firmware refused), it keeps waiting. A drifting sensor ends the wait.
"""

from __future__ import annotations

import math
import statistics
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field

# balance.ino `float trim` (tests/test_robot_watch.py checks it's still the firmware's value).
FIRMWARE_TRIM = -3.65


def _num(x: object) -> float | None:
    if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x):
        return None
    return float(x)


@dataclass
class DriftWatch:
    window_s: float = 2.0
    min_samples: int = 12          # telemetry is 20 Hz over Wi-Fi, ~10 Hz over USB
    min_rate: float = 3.0          # deg/s: the steady rate that counts as a bias
    runaway_rate: float = 30.0     # deg/s: above this the firmware is gyro-only (see the docstring)
    max_spread: float = 1.5        # deg/s: standard deviation of the rate; more means it's moving
    follow_ratio: float = 0.25     # the tilt may move at most this share of what the rate adds up to
    ok_rate: float = 1.5           # deg/s: steady and under this clears it
    settle_s: float = 3.0          # after a recalibration: ignore telemetry this long (it measures 2 s)
    on: bool = False
    rate: float | None = None      # the average rate when it was last judged
    _samples: deque = field(default_factory=deque, repr=False)
    _ignore_until: float = 0.0

    def reset(self, now: float) -> None:
        """A recalibration was sent: forget everything and judge again once it's done."""
        self.on = False
        self.rate = None
        self._samples.clear()
        self._ignore_until = now + self.settle_s

    def feed(self, tel: dict | None, now: float) -> bool:
        """One telemetry message. Returns True only when drift was just detected."""
        pitch, rate = _num((tel or {}).get("pitch")), _num((tel or {}).get("rate"))
        if not tel or tel.get("state") != "idle" or pitch is None or rate is None or now < self._ignore_until:
            self._samples.clear()   # only judge a robot with its motors off, from fresh samples
            return False
        self._samples.append((now, pitch, rate))
        while self._samples and now - self._samples[0][0] > self.window_s:
            self._samples.popleft()
        span = self._samples[-1][0] - self._samples[0][0]
        if len(self._samples) < self.min_samples or span < 0.9 * self.window_s:
            return False
        rates = [s[2] for s in self._samples]
        mean, spread = statistics.fmean(rates), statistics.pstdev(rates)
        moved = abs(self._samples[-1][1] - self._samples[0][1])
        self.rate = round(mean, 1)
        if spread > self.max_spread:
            return False                                       # moving or held: can't tell
        added_up = abs(mean) * span
        drifting = (abs(mean) >= self.min_rate and moved <= max(1.0, self.follow_ratio * added_up)) \
            or abs(mean) >= self.runaway_rate
        if drifting and not self.on:
            self.on = True
            return True
        if self.on and abs(mean) <= self.ok_rate:
            self.on = False
        return False


@dataclass
class AutoStart:
    arm: Callable[[], object]                     # sends g
    trim: Callable[[], float]                     # the balance angle now, deg
    window_deg: float = 3.0                       # the firmware allows 6; stricter here
    max_rate: float = 12.0                        # deg/s, every sample
    mean_rate: float = 5.0                        # deg/s, the average over hold_s
    hold_s: float = 1.0
    timeout_s: float = 60.0
    retry_s: float = 2.0
    waiting: bool = False
    note: str = ""
    _since: float = 0.0
    _armed_at: float | None = None
    _samples: deque = field(default_factory=deque, repr=False)

    def start(self, now: float) -> None:
        self.waiting, self.note = True, "Hold me upright and steady"
        self._since, self._armed_at = now, None
        self._samples.clear()

    def cancel(self, note: str = "") -> None:
        self.waiting, self.note, self._armed_at = False, note, None
        self._samples.clear()

    def view(self) -> dict:
        return {"waiting": self.waiting, "note": self.note}

    def feed(self, tel: dict | None, now: float) -> str | None:
        """One telemetry message. Returns "armed" when it sent g, "started" when the robot is balancing,
        "timeout" when it gave up; else None."""
        if not self.waiting:
            return None
        state = (tel or {}).get("state")
        if state in ("balance", "drive"):
            self.cancel()
            return "started"
        if now - self._since > self.timeout_s:
            self.cancel("Start timed out: press Start again")
            return "timeout"
        if self._armed_at is not None:
            if now - self._armed_at < self.retry_s:
                return None                               # give the firmware time to answer
            self._armed_at = None                         # it refused: keep waiting
            self.note = "Hold me upright and steady"
        pitch, rate = _num((tel or {}).get("pitch")), _num((tel or {}).get("rate"))
        if state != "idle" or pitch is None or rate is None:
            self._samples.clear()
            return None
        if abs(pitch - self.trim()) > self.window_deg or abs(rate) > self.max_rate:
            self._samples.clear()
            return None
        self._samples.append((now, rate))
        while self._samples and now - self._samples[0][0] > self.hold_s:
            self._samples.popleft()
        if now - self._samples[0][0] < 0.9 * self.hold_s or len(self._samples) < 5:
            return None
        if abs(statistics.fmean(r for _, r in self._samples)) > self.mean_rate:
            return None
        self._samples.clear()
        self._armed_at = now
        self.note = "Starting"
        self.arm()
        return "armed"
