"""A fake robot that behaves like firmware/balance/balance.ino, for testing without the robot.

It follows contract v1 (contract/README.md): the same JSON `cmd` and one-letter commands in, the
same `tel` out, the same clamps, ramps, watchdog, arming rule and turn logic. It doesn't simulate
balancing physics: pitch is the trim plus a lean into acceleration, which is enough for the
dashboard and the skills. `MockRobot` has no I/O, so tests can drive it directly; `mock/__main__.py`
puts it on UDP.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field

# Numbers from balance.ino
TRIM = 5.6               # deg: balance point with the phone tilted up
KICK_ANGLE = 11.24       # deg: resting on the kickstand
V_LIMIT, W_LIMIT = 0.6, 1.5
VT_ACC = 0.5             # m/s^2: how fast the speed ramps
HALF_TRACK = 0.0775      # m
WATCHDOG_S = 0.3
RUN_LIMIT_S = 30 * 60
ARM_WINDOW = 6.0         # deg from trim
PARK_S = 1.0
MOVE_DIST, MOVE_V = 0.5, 0.2
FF_RR = 0.5              # deg of extra lean while moving
TURN_TIMEOUT_S = 8.0


def _clamp(x: float, lim: float) -> float:
    return max(-lim, min(lim, x))


@dataclass
class MockRobot:
    running: bool = False
    pitch: float = KICK_ANGLE
    rate: float = 0.0
    vt: float = 0.0          # target speed, m/s
    wt: float = 0.0          # target turn, rad/s
    vcmd: float = 0.0        # ramped wheel speed, m/s
    x: float = 0.0
    yaw: float = 0.0         # deg
    fault: str | None = None
    last_seq: int = 0
    net_driving: bool = False
    last_net_cmd: float = 0.0
    turning: bool = False
    turn_target: float = 0.0
    turn_start: float = 0.0
    moving: bool = False
    move_target: float = 0.0
    park_start: float | None = None
    run_start: float = 0.0
    log: list[str] = field(default_factory=list)

    # ---- input

    def handle_packet(self, data: bytes, now: float) -> None:
        if data[:1] == b"{":
            self.handle_json(data, now)
        else:
            for c in data.decode(errors="ignore"):
                self.handle_char(c, now)

    def handle_json(self, data: bytes, now: float) -> None:
        try:
            msg = json.loads(data)
        except ValueError:
            return                                   # broken packet: dropped, like the firmware
        if not isinstance(msg, dict):
            return
        seq = msg.get("seq")
        if isinstance(seq, int) and 0 <= seq <= 0xFFFFFFFF:
            self.last_seq = seq
        mode = msg.get("mode", "drive")
        if mode == "idle":
            self.motors_off("idle command (Wi-Fi)")
            return
        if not self.running:
            return                                   # only g starts balancing
        if mode == "balance":
            self.vt = self.wt = 0.0
            self.turning = False
            self.net_driving, self.last_net_cmd = True, now
        elif mode == "drive":
            v = _clamp(float(msg.get("v", 0) or 0), V_LIMIT)
            w = _clamp(float(msg.get("w", 0) or 0), W_LIMIT)
            if abs(v) > 0.001 or abs(w) > 0.001:
                self.moving = self.turning = False
                self.vt, self.wt = v, w
            elif not self.moving and not self.turning:
                self.vt = self.wt = 0.0
            self.net_driving, self.last_net_cmd = True, now

    def handle_char(self, c: str, now: float) -> None:
        if c == "g":
            if abs(self.pitch - TRIM) > ARM_WINDOW:
                self._say(f"Not upright (pitch-trim = {self.pitch - TRIM:.1f}). Hold it upright first.")
                return
            self.running, self.fault, self.park_start = True, None, None
            self.vt = self.wt = self.vcmd = self.x = self.yaw = 0.0
            self.turning = self.moving = False
            self.pitch, self.run_start = TRIM, now
            self._say("BALANCING")
        elif c == "x":
            self.motors_off("stop command")
        elif c == "5":
            self.vt = self.wt = 0.0
            self.turning = self.moving = False
        elif c in "LR" and self.running:
            step = 90 if c == "L" else -90
            self.turn_target = round(self.yaw / 90) * 90 + step
            self.turning, self.turn_start = True, now
        elif c == "P" and self.running:
            self.vt = self.wt = 0.0
            self.turning = self.moving = False
            self.park_start = now
            self._say("PARKING on the kickstand")
        elif c in "FB" and self.running and self.park_start is None:
            sign = 1 if c == "F" else -1
            self.move_target = self.x + sign * MOVE_DIST
            self.vt, self.wt = sign * MOVE_V, 0.0
            self.turning, self.moving = False, True

    def motors_off(self, why: str) -> None:
        if self.running:
            self.fault = why
            self._say(f"STOP: {why}")
        self.running = self.net_driving = self.moving = self.turning = False
        self.park_start = None
        self.vcmd = 0.0

    # ---- time

    def step(self, dt: float, now: float) -> None:
        if self.net_driving and now - self.last_net_cmd > WATCHDOG_S:
            if not self.moving and not self.turning:
                self.vt = self.wt = 0.0
            self.net_driving = False
        if self.running and self.park_start is None and now - self.run_start > RUN_LIMIT_S:
            self._say("run time limit reached: parking")
            self.handle_char("P", now)
        if not self.running:
            self.vcmd, self.rate = 0.0, 0.0
            self.pitch = KICK_ANGLE
            return
        if self.park_start is not None:
            if now - self.park_start >= PARK_S:
                self.running, self.park_start, self.net_driving = False, None, False
                self.vcmd, self.pitch, self.rate = 0.0, KICK_ANGLE, 0.0
                self._say("parked")
                return
        if self.turning:
            e = self.turn_target - self.yaw
            w = _clamp(0.035 * e, 1.0)
            if abs(e) > 3 and abs(w) < 0.3:
                w = 0.3 if e > 0 else -0.3
            self.wt = w
            if abs(e) < 1.0 or now - self.turn_start > TURN_TIMEOUT_S:
                self.turning, self.wt = False, 0.0
        if self.moving and ((self.vt > 0 and self.x >= self.move_target) or (self.vt < 0 and self.x <= self.move_target)):
            self.moving, self.vt = False, 0.0
        old_v = self.vcmd
        dv = _clamp(self.vt - self.vcmd, VT_ACC * dt)
        self.vcmd += dv
        accel = (self.vcmd - old_v) / dt if dt > 0 else 0.0
        self.x += self.vcmd * dt
        self.yaw += math.degrees(self.wt) * dt
        old_pitch = self.pitch
        lean = math.degrees(math.atan(accel / 9.81)) + (FF_RR if abs(self.vcmd) > 0.01 else 0.0) * math.copysign(1, self.vcmd)
        self.pitch = TRIM + lean
        self.rate = (self.pitch - old_pitch) / dt if dt > 0 else 0.0

    # ---- output

    @property
    def state(self) -> str:
        if not self.running:
            return "idle"
        return "drive" if (self.vt != 0 or self.wt != 0 or self.turning) else "balance"

    def telemetry(self) -> dict:
        return {
            "t": "tel",
            "pitch": round(self.pitch, 2),
            "rate": round(self.rate, 1),
            "vl": round(self.vcmd - self.wt * HALF_TRACK, 3),
            "vr": round(self.vcmd + self.wt * HALF_TRACK, 3),
            "batt": None,
            "state": self.state,
            "fault": self.fault,
            "x": round(self.x, 3),
            "yaw": round(self.yaw, 1),
            "ack": self.last_seq,
        }

    def _say(self, line: str) -> None:
        self.log.append(line)
