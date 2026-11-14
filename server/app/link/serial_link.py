"""USB serial robot link: speaks what firmware/balance/balance.ino speaks today (firmware/README.md).

- Out: `{"t":"cmd","v":..,"w":..,"mode":..,"seq":N}` + newline, about 20 times a second (the caller's
  loop). The firmware reads `v`, `w` and `mode` and ignores the rest, so `seq` is ready for acks (#14).
- Out: one-letter commands: `g` (arm, only from `arm()`), `P` (park), `x` (motors off). Never `G`.
- In: the readable status line the firmware prints 10 times a second over USB on its own
  (`RUN pitch ... (err ...) rate ... v ... x ... vt ... wt ...`), the `{"t":"tel",...}` JSON if it
  ever appears on serial, `STOP: <why>` lines (faults) and the `V` version reply.
  The link never sends `i`: in balance.ino it *toggles* that status line, which is on at boot.

Safety (firmware/README.md "Safety rules"): `close()`, `__exit__` and an `atexit` handler all send
`x`; `g` goes out only through `arm()`; drive values are clamped to the firmware limits; a pulled cable
(which reboots the ESP32) makes `connected` False without raising, and the link reopens the port when
it comes back (the firmware boots with the motors off and ignores drive commands until someone arms it).
"""

from __future__ import annotations

import atexit
import collections
import glob
import json
import logging
import math
import re
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Protocol, runtime_checkable

log = logging.getLogger("app.link")

V_MAX = 0.6     # m/s, firmware clamp (balance.ino handleJson)
W_MAX = 1.5     # rad/s
MODES = ("drive", "balance", "idle")
FIRMWARE_TAG = "json-serial"   # in the reply to "V" ("FW balance json-serial v1"), as drive.py checks

# balance.ino loop(): "%s pitch %6.2f (err %6.2f) rate %7.1f  v %5.2f  x %5.2f  vt %4.1f wt %4.1f"
# Same prefix as drive.py's TEL_RE, plus the optional vt / wt targets.
STATUS_RE = re.compile(
    r"^(RUN|off) pitch\s+(-?[\d.]+) \(err\s+(-?[\d.]+)\) rate\s+(-?[\d.]+)\s+v\s+(-?[\d.]+)\s+x\s+(-?[\d.]+)"
    r"(?:\s+vt\s+(-?[\d.]+)\s+wt\s+(-?[\d.]+))?"
)


@dataclass(frozen=True)
class Telemetry:
    """Latest robot state; fields are None when unknown."""

    t: float                  # time.monotonic() when received
    state: str | None         # "idle" | "balance" | "drive" ...
    pitch_deg: float | None
    v: float | None           # wheel speed, m/s if available
    batt: float | None
    fault: str | None
    raw: str                  # the raw line


@runtime_checkable
class RobotLink(Protocol):
    def open(self) -> None: ...
    def send(self, v: float, w: float, mode: str = "drive") -> None: ...
    def arm(self) -> None: ...
    def park(self) -> None: ...
    def motors_off(self) -> None: ...
    @property
    def telemetry(self) -> Telemetry | None: ...
    @property
    def connected(self) -> bool: ...
    def close(self) -> None: ...


def find_serial_port() -> str | None:
    """The robot's USB port: the ESP32's CH343 COM port shows up as /dev/cu.usbmodem* on a Mac (drive.py)."""
    for pattern in ("/dev/cu.usbmodem*", "/dev/cu.wchusbserial*", "/dev/ttyACM*", "/dev/ttyUSB*"):
        ports = sorted(glob.glob(pattern))
        if ports:
            return ports[0]
    return None


def _clamp(x: float, limit: float) -> float:
    x = float(x)
    if not math.isfinite(x):
        return 0.0
    return max(-limit, min(limit, x))


def make_cmd(v: float, w: float, mode: str, seq: int) -> str:
    """The drive command line, clamped and rounded to 3 decimals."""
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}, not {mode!r}")
    msg = {"t": "cmd", "v": round(_clamp(v, V_MAX), 3), "w": round(_clamp(w, W_MAX), 3), "mode": mode, "seq": seq}
    return json.dumps(msg, separators=(",", ":")) + "\n"


def _num(x: Any) -> float | None:
    return float(x) if isinstance(x, (int, float)) and not isinstance(x, bool) else None


def parse_line(line: str, now: float, fault: str | None = None) -> Telemetry | None:
    """One line from the robot -> Telemetry, or None if it isn't telemetry.

    `fault` is the last `STOP:` reason seen; the readable status line doesn't carry one.
    """
    line = line.strip()
    if line.startswith("{"):
        try:
            d = json.loads(line)
        except ValueError:
            return None
        if not isinstance(d, dict) or d.get("t") != "tel":
            return None
        vl, vr = _num(d.get("vl")), _num(d.get("vr"))
        v = _num(d.get("v"))
        if v is None and vl is not None and vr is not None:
            v = (vl + vr) / 2
        state = d.get("state")
        f = d.get("fault")
        return Telemetry(t=now, state=state if isinstance(state, str) else None, pitch_deg=_num(d.get("pitch")),
                         v=v, batt=_num(d.get("batt")), fault=f if isinstance(f, str) else None, raw=line)
    m = STATUS_RE.match(line)
    if not m:
        return None
    if m[1] == "off":
        state = "idle"
    else:   # same rule as balance.ino sendTelemetry(): moving targets -> "drive"
        moving = m[7] is not None and (float(m[7]) != 0 or float(m[8]) != 0)
        state = "drive" if moving else "balance"
    return Telemetry(t=now, state=state, pitch_deg=float(m[2]), v=float(m[5]), batt=None, fault=fault, raw=line)


def _default_serial_factory(port: str, baud: int) -> Any:
    import serial  # pyserial

    # pyserial's defaults (DTR and RTS on at open) behave like drive.py's plain open() of the tty.
    return serial.Serial(port, baud, timeout=0.1, write_timeout=0.5)


class SerialLink:
    """RobotLink over the ESP32's USB serial port (115200 baud)."""

    def __init__(self, port: str | None = None, baud: int = 115200, *,
                 serial_factory: Callable[[str, int], Any] | None = None,
                 reconnect: bool = True, clock: Callable[[], float] = time.monotonic):
        self._port_arg = port
        self.port: str | None = port
        self._baud = baud
        self._factory = serial_factory or _default_serial_factory
        self._reconnect = reconnect
        self._clock = clock
        self._ser: Any = None
        self._io = threading.Lock()
        self._seq = 0
        self._telemetry: Telemetry | None = None
        self._fault: str | None = None
        self._connected = False
        self._closing = False
        self._reader: threading.Thread | None = None
        self.firmware: str | None = None              # the "V" reply, once seen
        self.messages: collections.deque[str] = collections.deque(maxlen=20)   # other robot printouts

    # ---- lifecycle
    def open(self) -> None:
        """Open the port and start reading. Raises if the port can't be opened (robot not plugged in)."""
        if self._ser is not None:
            return
        port = self._port_arg or find_serial_port()
        if port is None:
            raise RuntimeError("Robot not found on USB. Plug the cable into the ESP32's COM port.")
        self._ser = self._factory(port, self._baud)
        self.port = port
        self._connected = True
        self._closing = False
        atexit.register(self._atexit_motors_off)
        self._reader = threading.Thread(target=self._read_loop, name="serial-link-reader", daemon=True)
        self._reader.start()
        self._write("V\n")    # harmless: asks for the firmware version (drive.py does the same)
        log.info("robot link on %s", port)

    def wait_for_firmware(self, timeout: float = 8.0) -> bool:
        """Like drive.py: ask with "V" until the json-serial firmware answers. It may be rebooting (2 s gyro calibration)."""
        end, next_v = time.monotonic() + timeout, 0.0
        while time.monotonic() < end:
            if self.firmware and FIRMWARE_TAG in self.firmware:
                return True
            if time.monotonic() >= next_v:
                self._write("V\n")
                next_v = time.monotonic() + 0.75
            time.sleep(0.05)
        return bool(self.firmware and FIRMWARE_TAG in self.firmware)

    def close(self) -> None:
        """Motors off first, then close the port. Safe to call twice."""
        if self._closing and self._ser is None:
            return
        self.motors_off()
        self._closing = True
        with self._io:
            ser, self._ser = self._ser, None
            self._connected = False
            if ser is not None:
                _quiet(getattr(ser, "flush", None))
                _quiet(ser.close)
        if self._reader is not None and self._reader is not threading.current_thread():
            self._reader.join(timeout=1.0)
        atexit.unregister(self._atexit_motors_off)

    def __enter__(self) -> SerialLink:
        self.open()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ---- commands
    def send(self, v: float, w: float, mode: str = "drive") -> None:
        """Drive command; the robot holds position by itself 300 ms after the last one."""
        with self._io:
            self._seq += 1
            line = make_cmd(v, w, mode, self._seq)
        self._write(line)

    def arm(self) -> None:
        """Start balancing ("g"). Call ONLY on a person's keypress, with someone holding the robot upright."""
        self._write("g\n")

    def park(self) -> None:
        self._write("P\n")

    def motors_off(self) -> None:
        self._write("x\n")

    # ---- state
    @property
    def telemetry(self) -> Telemetry | None:
        return self._telemetry

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def seq(self) -> int:
        """The seq of the last drive command sent."""
        return self._seq

    # ---- internals
    def _write(self, text: str) -> bool:
        with self._io:
            ser = self._ser
            if ser is None or not self._connected:
                log.debug("not connected; dropped %r", text.strip())
                return False
            try:
                ser.write(text.encode())
                return True
            except Exception as e:   # unplugged mid-write: the reader notices too and reconnects
                log.warning("robot link write failed (%s); marking disconnected", e)
                self._connected = False
                return False

    def _atexit_motors_off(self) -> None:
        """Best effort on interpreter exit (crash, Ctrl+C): motors off."""
        try:
            ser = self._ser
            if ser is not None:
                ser.write(b"x\n")
                _quiet(getattr(ser, "flush", None))
        except Exception:
            pass

    def _drop_port(self) -> None:
        with self._io:
            ser, self._ser = self._ser, None
            self._connected = False
        if ser is not None:
            _quiet(ser.close)

    def _read_loop(self) -> None:
        buf = b""
        warned_quiet = False
        opened_at = self._clock()
        while not self._closing:
            ser = self._ser
            if ser is None or not self._connected:
                if ser is not None:
                    self._drop_port()
                    log.warning("robot link lost (cable pulled? the ESP32 reboots); keep it still for 3 s")
                if not self._reconnect or self._closing:
                    return
                if not self._try_reopen():
                    time.sleep(1.0)
                    continue
                buf, warned_quiet, opened_at = b"", False, self._clock()
                continue
            try:
                n = getattr(ser, "in_waiting", 0) or 1
                data = ser.read(n)
            except Exception as e:
                if self._closing:
                    return
                log.debug("robot link read failed: %s", e)
                with self._io:
                    self._connected = False
                continue
            if data:
                buf += data
                *lines, buf = buf.split(b"\n")
                if len(buf) > 4096:   # no newline in a long time: garbage
                    buf = b""
                for raw in lines:
                    try:
                        self._handle_line(raw.decode(errors="replace").strip())
                    except Exception:   # never let one bad line kill the reader
                        log.exception("robot link: bad line %r", raw[:120])
            elif not warned_quiet and self._telemetry is None and self._clock() - opened_at > 5.0:
                warned_quiet = True
                log.warning("no telemetry from the robot after 5 s. If its status line was toggled off, "
                            "send 'i' once by hand (the link never sends it: it toggles)")

    def _try_reopen(self) -> bool:
        port = self._port_arg or find_serial_port()
        if port is None:
            return False
        try:
            ser = self._factory(port, self._baud)
        except Exception:
            return False
        with self._io:
            if self._closing:
                _quiet(ser.close)
                return False
            self._ser, self.port, self._connected = ser, port, True
        log.info("robot link back on %s (motors are off after a reboot; arm again by hand)", port)
        self._write("V\n")
        return True

    def _handle_line(self, line: str) -> None:
        if not line:
            return
        if line.startswith("STOP: "):           # balance.ino motorsOff()
            self._fault = line[6:]
        elif line.startswith("BALANCING"):       # "g" clears the firmware's lastFault
            self._fault = None
        elif "json-serial" in line:
            self.firmware = line
        tel = parse_line(line, self._clock(), self._fault)
        if tel is not None:
            self._telemetry = tel
        elif line.isprintable():
            self.messages.append(line)


class LoggingLink:
    """RobotLink with no hardware: records and logs what it would send (for --robot mock until the mock robot exists)."""

    def __init__(self, record_limit: int = 10_000):
        self.sent: collections.deque[str] = collections.deque(maxlen=record_limit)   # exact lines, newline included
        self._seq = 0
        self._open = False
        self._telemetry: Telemetry | None = None

    def open(self) -> None:
        self._open = True
        log.info("logging link: commands are recorded, nothing is sent")

    def send(self, v: float, w: float, mode: str = "drive") -> None:
        self._seq += 1
        line = make_cmd(v, w, mode, self._seq)
        self.sent.append(line)
        log.debug("would send %s", line.strip())

    def _letter(self, c: str) -> None:
        self.sent.append(c + "\n")
        log.info("would send %r", c)

    def arm(self) -> None:
        self._letter("g")

    def park(self) -> None:
        self._letter("P")

    def motors_off(self) -> None:
        self._letter("x")

    @property
    def telemetry(self) -> Telemetry | None:
        return self._telemetry

    @property
    def connected(self) -> bool:
        return self._open

    def close(self) -> None:
        self.motors_off()
        self._open = False

    def __enter__(self) -> LoggingLink:
        self.open()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def _quiet(fn: Callable[[], Any] | None) -> None:
    if fn is None:
        return
    try:
        fn()
    except Exception:
        pass
