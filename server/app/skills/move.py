"""Move skill: drive straight or turn in place, for a time, a distance or an angle ("go forward",
"go back 2 meters", "turn left 90 degrees").

    Move("forward", drive_speed=lambda: 0.8, turn_rate=lambda: 0.8)            # 1 s at the drive speed
    Move("backward", meters=2, drive_speed=..., turn_rate=...)                 # until telemetry x moved 2 m
    Move("left", degrees=90, drive_speed=..., turn_rate=...)                   # until telemetry yaw turned 90°

Directions follow ROS REP 103: forward = +v (m/s), left = +w (rad/s). Left and right turn in
place. `speed` is m/s for forward/backward and rad/s for left/right; without it the skill reads
`drive_speed()` / `turn_rate()` (the control page's settings) when it starts.

Give at most one of `seconds`, `meters` (forward/backward only) or `degrees` (left/right only);
none means 1 second. Meters and degrees stop on telemetry (`x` in m, `yaw` in degrees + left,
see app/skills/__init__.py) with a timeout of twice the expected time plus 3 s; with no
telemetry they fall back to driving for the expected time. The robot ramps its speed at
0.5 m/s², so a short timed move covers less than speed x time: the detail only reports a
distance or angle when telemetry measured it.

It re-sends its request every 1/hz s (the arbiter drops requests older than 0.3 s), always
withdraws it at the end (cancelled too), and fails at once while the e-stop is on.
"""

from __future__ import annotations

import asyncio
import math
import time
from collections.abc import Callable

from app.skills import SkillContext, SkillResult

DIRECTIONS = ("forward", "backward", "left", "right")
_ALIASES = {"back": "backward", "backwards": "backward", "forwards": "forward"}

V_RANGE = (0.05, 3.2)        # m/s (3.2 = the arbiter's V_MAX)
W_RANGE = (0.1, 1.5)         # rad/s (1.5 = the arbiter's W_MAX)
SECONDS_RANGE = (0.1, 10.0)
METERS_RANGE = (0.05, 5.0)
DEGREES_RANGE = (5.0, 720.0)
DEFAULT_SECONDS = 1.0


def _clamp(x: float, lo_hi: tuple[float, float]) -> float:
    return max(lo_hi[0], min(lo_hi[1], x))


def _num(tel: dict | None, key: str) -> float | None:
    value = tel.get(key) if tel else None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return float(value)


def _estopped(ctx: SkillContext) -> bool:
    return bool(getattr(ctx, "estopped", False))   # fakes in tests may not have it


class Move:
    name = "move"

    def __init__(
        self,
        direction: str,
        *,
        seconds: float | None = None,
        meters: float | None = None,
        degrees: float | None = None,
        speed: float | None = None,
        drive_speed: Callable[[], float],
        turn_rate: Callable[[], float],
        hz: float = 20.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        d = str(direction).strip().lower()
        d = _ALIASES.get(d, d)
        if d not in DIRECTIONS:
            raise ValueError(f"direction must be one of {', '.join(DIRECTIONS)} (got {direction!r})")
        if sum(x is not None for x in (seconds, meters, degrees)) > 1:
            raise ValueError("give only one of seconds, meters or degrees")
        self.turning = d in ("left", "right")
        if meters is not None and self.turning:
            raise ValueError("meters is for forward or backward; use degrees to turn")
        if degrees is not None and not self.turning:
            raise ValueError("degrees is for left or right; use meters to drive straight")
        self.direction = d
        self.seconds = None if seconds is None else _clamp(float(seconds), SECONDS_RANGE)
        self.meters = None if meters is None else _clamp(float(meters), METERS_RANGE)
        self.degrees = None if degrees is None else _clamp(float(degrees), DEGREES_RANGE)
        self.speed = speed
        self._drive_speed = drive_speed
        self._turn_rate = turn_rate
        self.period_s = 1.0 / hz
        self._clock = clock

    async def run(self, ctx: SkillContext) -> SkillResult:
        if _estopped(ctx):
            return SkillResult(False, "the e-stop is on: release it first")
        rng = W_RANGE if self.turning else V_RANGE
        speed = _clamp(abs(float(self.speed if self.speed is not None
                                 else (self._turn_rate() if self.turning else self._drive_speed()))), rng)
        sign = -1.0 if self.direction in ("backward", "right") else 1.0
        v, w = (0.0, sign * speed) if self.turning else (sign * speed, 0.0)
        key, unit = ("yaw", "°") if self.turning else ("x", " m")
        start = _num(ctx.telemetry(), key)

        # target: how far (metres or degrees), measured on telemetry; None = by time only
        target: float | None = None
        if self.meters is not None:
            target, expected = self.meters, self.meters / speed
        elif self.degrees is not None:
            target, expected = self.degrees, math.radians(self.degrees) / speed
        else:
            expected = self.seconds if self.seconds is not None else DEFAULT_SECONDS
        by_telemetry = target is not None and start is not None
        limit = expected * 2 + 3 if by_telemetry else expected

        def moved() -> float | None:
            now_value = _num(ctx.telemetry(), key)
            return None if start is None or now_value is None else abs(now_value - start)

        t0 = self._clock()
        try:
            while True:
                if _estopped(ctx):
                    return SkillResult(False, "stopped: the e-stop is on")
                elapsed = self._clock() - t0
                if by_telemetry:
                    done = moved()
                    if done is not None and done >= target:
                        break
                    if elapsed >= limit:
                        return SkillResult(False, f"{self._verb()} {self.direction} only {self._amount(done or 0.0)} "
                                                  f"of {self._amount(target)}{unit}, then gave up after {elapsed:.1f} s")
                elif elapsed >= limit:
                    break
                ctx.drive(v, w)
                await asyncio.sleep(self.period_s)
        finally:
            ctx.stop()
        done = moved()
        if done is not None:
            return SkillResult(True, f"{self._verb()} {self.direction} {self._amount(done)}{unit}")
        rate = f"{speed:.2f} rad/s" if self.turning else f"{speed:.2f} m/s"
        return SkillResult(True, f"{'turned' if self.turning else 'drove'} {self.direction} "
                                 f"for {expected:.1f} s at {rate}")

    def _verb(self) -> str:
        return "turned" if self.turning else "moved"

    def _amount(self, x: float) -> str:
        return f"{x:.0f}" if self.turning else f"{x:.2f}"
