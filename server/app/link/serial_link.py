"""USB serial robot link: Alex's `RobotLink` (app/link/__init__.py) over the ESP32's USB port.

It speaks contract v1 (contract/README.md) as far as `firmware/balance/balance.ino` on main does today:

- Out: `cmd` as compact JSON plus a newline (`{"t":"cmd","seq":N,"v":..,"w":..,"mode":..}`), about 20
  times a second (the app's drive loop). The firmware reads `v`, `w` and `mode`; `seq` is ready for
  acks (#14).
- Out: one-letter commands from `ALLOWED_LETTERS` (`x`, `P`, `5`, `L`, `R`, `F`, `B`), each plus a
  newline. `send_letter` never sends `g`, `G` or `i` (`i` toggles the status line this link reads).
- In: the readable status line the firmware prints 10 times a second over USB on its own
  (`RUN pitch ... (err ...) rate ... v ... x ... vt ... wt ...`), turned into a contract `tel` dict
  (see `status_to_tel`); `STOP: <why>` lines (the `fault`); the `V` version reply; and `{"t":"tel"}`
  JSON lines (used as is, acks included).

Yaw over USB (issue #62): the status line has no `yaw`, but `J` makes balance.ino print one
contract `tel` JSON line (`formatTelemetry()`, the same as the Wi-Fi one: `yaw` %.1f degrees since
`g`, + left, and `ack`). The writer thread sends `J` about `yaw_poll_hz` (5) times a second, from
the first status line or `V` reply after the port (re)opens: both are printed from loop(), so the
firmware is reading commands. `J` is sent internally only: it is NOT in `ALLOWED_LETTERS`, and
`send_letter("J")` still raises. If no JSON reply arrives within `yaw_poll_give_up_s` (3 s) of
the firmware first talking (a firmware without `J` ignores the unknown letter), polling stops and
that is logged once; a reconnect tries again. While the last JSON reply is fresh (< FRESH_S), each
status-line dict also carries its `yaw` (not its `ack`), so `telemetry` keeps a yaw between replies
(at most one poll, ~0.2 s, old). With replies, `health()` requires fresh acks (they come at the poll
rate, < FRESH_S), and `lag_ms` includes up to one drive period of waiting for the next poll.

Arming is separate on purpose: `arm()` sends `g` and is not part of `RobotLink`. Over USB the server
holds the serial port, so drive.py can't be run next to it to arm the robot; `arm()` exists only for a
person's keypress (the debug view's G) while someone holds the robot upright. Skills, the LLM and the
drive loop never call it.

Health over USB (`health()`): the firmware on main doesn't send acks over serial, so `ack_age` and
`lag_ms` stay None (we don't make them up). Until an ack is seen, `ok` means: the port is open and the
status line is fresh (< FRESH_S). A USB cable is point-to-point and a failed write marks the link
down, so fresh telemetry on an open port is the best evidence there is. Once the firmware sends acks
(a `tel` JSON line with `ack`), `ok` also requires a fresh ack, exactly like `UdpLink`.

Threads: pyserial blocks, so a reader thread reads lines and a writer thread writes; `send_cmd` and
`send_letter` only queue bytes and return at once, so they never block the event loop. A queued drive
command not yet written is replaced by the next one (only the newest matters).

Safety (firmware/README.md "Safety rules"): `close()` sends `x` before closing the port, and an
`atexit` handler sends `x` if the process exits without closing; `g` goes out only through `arm()`;
drive values are clamped to the firmware limits. A pulled cable (which reboots the ESP32) marks the link
down without raising; the reader reopens the port when it comes back (the firmware boots with the
motors off and ignores drive commands until a person arms it).
"""

from __future__ import annotations

import asyncio
import atexit
import collections
import glob
import json
import logging
import math
import random
import re
import threading
import time
from collections import OrderedDict
from typing import Any, Callable

from app.link import ALLOWED_LETTERS, FRESH_S, Health

log = logging.getLogger("app.link")

V_MAX = 1.0     # m/s, balance.ino handleJson clamp (VMAX)
W_MAX = 1.5     # rad/s
MODES = ("drive", "balance", "idle")    # contract/schema/cmd.schema.json
HALF_TRACK = 0.0775   # m, wheel centre to robot centre (balance.ino), for vl / vr from v and wt
FIRMWARE_TAG = "json-serial"   # in the reply to "V" ("FW balance json-serial v1"), as drive.py checks

# balance.ino loop(): "%s pitch %6.2f (err %6.2f) rate %7.1f  v %5.2f  x %5.2f  vt %4.1f wt %4.1f"
# Same prefix as drive.py's TEL_RE, plus the optional vt / wt targets.
STATUS_RE = re.compile(
    r"^(RUN|off) pitch\s+(-?[\d.]+) \(err\s+(-?[\d.]+)\) rate\s+(-?[\d.]+)\s+v\s+(-?[\d.]+)\s+x\s+(-?[\d.]+)"
    r"(?:\s+vt\s+(-?[\d.]+)\s+wt\s+(-?[\d.]+))?"
)


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


def make_cmd(v: float, w: float, mode: str, seq: int) -> bytes:
    """One contract v1 `cmd` line: clamped, rounded to 3 decimals, compact JSON plus newline."""
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}, not {mode!r}")
    msg = {"t": "cmd", "seq": seq, "v": round(_clamp(v, V_MAX), 3), "w": round(_clamp(w, W_MAX), 3), "mode": mode}
    return (json.dumps(msg, separators=(",", ":")) + "\n").encode()


def status_to_tel(line: str, fault: str | None = None) -> dict | None:
    """The firmware's readable status line -> a contract v1 `tel` dict, or None if it isn't one.

    Units are the contract's and the line's alike (degrees, deg/s, m/s, m), so nothing is converted.
    `yaw` and `ack` are left out: the line doesn't carry them. `batt` is null (nothing measures it).
    `fault` is the last `STOP:` reason seen; the line itself doesn't carry one.
    """
    m = STATUS_RE.match(line.strip())
    if not m:
        return None
    pitch, rate, v, x = float(m[2]), float(m[4]), float(m[5]), float(m[6])
    vt = float(m[7]) if m[7] is not None else 0.0
    wt = float(m[8]) if m[8] is not None else 0.0
    if m[1] == "off":
        state = "idle"
    else:   # balance.ino sendTelemetry(): moving or turning targets -> "drive"
        state = "drive" if (vt != 0 or wt != 0) else "balance"
    return {
        "t": "tel",
        "pitch": pitch,
        "rate": rate,
        "vl": round(v - wt * HALF_TRACK, 3),   # as sendTelemetry(): left turn = right wheel faster
        "vr": round(v + wt * HALF_TRACK, 3),
        "batt": None,
        "state": state,
        "fault": fault,
        "x": x,
    }


def _is_number(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _default_serial_factory(port: str, baud: int) -> Any:
    import serial  # pyserial

    # pyserial's defaults (DTR and RTS on at open) behave like drive.py's plain open() of the tty.
    return serial.Serial(port, baud, timeout=0.1, write_timeout=0.5)


class SerialLink:
    """`RobotLink` over the ESP32's USB serial port (115200 baud)."""

    def __init__(self, port: str | None = None, baud: int = 115200, *,
                 serial_factory: Callable[[str, int], Any] | None = None,
                 reconnect: bool = True, clock: Callable[[], float] = time.monotonic,
                 yaw_poll_hz: float = 5.0, yaw_poll_give_up_s: float = 3.0):
        self._port_arg = port
        self.port: str | None = port
        self._baud = baud
        self._factory = serial_factory or _default_serial_factory
        self._reconnect = reconnect
        self._clock = clock
        self.telemetry: dict | None = None       # latest contract v1 `tel`; kept while disconnected
        self.firmware: str | None = None         # the "V" reply, once seen
        self.messages: collections.deque[str] = collections.deque(maxlen=20)   # other robot printouts
        self._ser: Any = None
        self._io = threading.Lock()              # guards _ser and every write to it
        self._out: collections.deque[tuple[str, bytes]] = collections.deque()
        self._out_cv = threading.Condition()     # guards _out and _writing
        self._writing = False
        self._connected = False
        self._closing = False
        self._reader: threading.Thread | None = None
        self._writer: threading.Thread | None = None
        self._fault: str | None = None
        # Start at a random seq, like UdpLink: once the firmware acks (#14) it remembers the last seq,
        # and an old ack from an earlier run must not look like one of ours.
        self._seq = random.randint(1_000_000, 2_000_000_000)
        self._sent: OrderedDict[int, float] = OrderedDict()
        self._tel_at: float | None = None
        self._ack_at: float | None = None
        self._lag: float | None = None
        self._best_ack = 0
        # J polling (module docstring). State, guarded by _out_cv: "off" (disabled or gave up),
        # "waiting" (port open, firmware not heard yet), "polling" (no reply yet), "answered".
        # Poll timing is wall time (time.monotonic); `clock` is only for telemetry/ack ages.
        self._poll_period = 1.0 / yaw_poll_hz if yaw_poll_hz > 0 else None
        self._poll_give_up_s = yaw_poll_give_up_s
        self._poll_state = "off"
        self._poll_since = 0.0     # first status line / V reply since (re)open
        self._poll_next = 0.0
        self._json_at: float | None = None    # last JSON tel line (clock)
        self._json_yaw: float | None = None

    # ---- RobotLink
    async def start(self) -> None:
        """Open the port and start the reader and writer threads.

        Raises RuntimeError if no robot is plugged in. Opening runs in a thread (pyserial blocks).
        """
        await asyncio.to_thread(self._open)

    async def close(self) -> None:
        """Motors off (`x`) first, then close the port. Safe to call twice."""
        await asyncio.to_thread(self._close)

    def send_cmd(self, v: float, w: float, mode: str = "drive") -> None:
        """Queue one `cmd` with the next seq; the robot holds position by itself 300 ms after the last one."""
        if mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}, not {mode!r}")
        with self._out_cv:
            self._seq += 1
            seq = self._seq
            self._sent[seq] = self._clock()
            while len(self._sent) > 200:
                self._sent.popitem(last=False)
        self._enqueue("cmd", make_cmd(v, w, mode, seq))

    def send_letter(self, letter: str) -> None:
        """Queue a one-letter command from ALLOWED_LETTERS (never g / G / i)."""
        if letter not in ALLOWED_LETTERS:
            raise ValueError(f"the server may not send {letter!r} (allowed: {''.join(sorted(ALLOWED_LETTERS))})")
        self._enqueue("letter", (letter + "\n").encode())

    def send_trim(self, steps: int) -> None:
        """Shift the balance angle (trim) by steps x 0.25 deg: t raises it, y lowers it."""
        if steps:
            self._enqueue("letter", (('t' if steps > 0 else 'y') * abs(steps) + "\n").encode())

    def health(self) -> Health:
        """See the module docstring: without acks over USB, ok = port open and telemetry fresh."""
        now = self._clock()
        tel_age = None if self._tel_at is None else now - self._tel_at
        ack_age = None if self._ack_at is None else now - self._ack_at
        ok = self._connected and tel_age is not None and tel_age < FRESH_S
        if self._ack_at is not None:     # the firmware acks: require it, like UdpLink
            ok = ok and ack_age is not None and ack_age < FRESH_S
        return Health(ok, tel_age, ack_age, None if self._lag is None else self._lag * 1000)

    # ---- USB only (not RobotLink)
    def arm(self) -> None:
        """Start balancing (`g`). ONLY on a person's keypress, with someone holding the robot upright.

        Not part of RobotLink and never called by skills or the drive loop: over USB the server holds
        the port, so this is the only way to arm without stopping the server to run drive.py.
        """
        log.warning("arming: sending g (someone must be holding the robot upright)")
        self._enqueue("letter", b"g\n")

    async def wait_for_firmware(self, timeout: float = 8.0) -> bool:
        """Like drive.py: ask with `V` until the json-serial firmware answers (it may be rebooting: 2 s gyro calibration)."""
        loop = asyncio.get_running_loop()
        end, next_v = loop.time() + timeout, 0.0
        while loop.time() < end:
            if self._firmware_ok():
                return True
            if loop.time() >= next_v:
                self._enqueue("letter", b"V\n")   # harmless: only prints the version
                next_v = loop.time() + 0.75
            await asyncio.sleep(0.05)
        return self._firmware_ok()

    @property
    def connected(self) -> bool:
        """The port is open (says nothing about whether the robot is talking: see health())."""
        return self._connected

    @property
    def seq(self) -> int:
        """The seq of the last drive command."""
        return self._seq

    async def __aenter__(self) -> SerialLink:
        await self.start()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()

    # ---- lifecycle internals (blocking; run in a thread from start() / close())
    def _open(self) -> None:
        if self._ser is not None:
            return
        port = self._port_arg or find_serial_port()
        if port is None:
            raise RuntimeError("Robot not found on USB. Plug the cable into the ESP32's COM port.")
        ser = self._factory(port, self._baud)
        with self._io:
            self._ser, self.port, self._connected, self._closing = ser, port, True, False
        self._reset_poll()
        atexit.register(self._atexit_motors_off)
        self._reader = threading.Thread(target=self._read_loop, name="serial-link-reader", daemon=True)
        self._writer = threading.Thread(target=self._write_loop, name="serial-link-writer", daemon=True)
        self._reader.start()
        self._writer.start()
        self._enqueue("letter", b"V\n")    # harmless: asks for the firmware version (drive.py does the same)
        log.info("robot link: USB serial on %s", port)

    def _close(self) -> None:
        with self._out_cv:
            if self._closing:
                return
            self._closing = True
            self._out.clear()               # nothing queued goes out after x
            self._out_cv.notify_all()
        if self._writer is not None and self._writer is not threading.current_thread():
            self._writer.join(timeout=1.0)
        with self._io:
            ser, self._ser = self._ser, None
            if ser is not None:
                if self._connected:
                    try:
                        ser.write(b"x\n")
                    except Exception as e:
                        log.warning("robot link: couldn't send x on close (%s)", e)
                    _quiet(getattr(ser, "flush", None))
                _quiet(ser.close)
            self._connected = False
        if self._reader is not None and self._reader is not threading.current_thread():
            self._reader.join(timeout=1.0)
        atexit.unregister(self._atexit_motors_off)

    def _atexit_motors_off(self) -> None:
        """Best effort on interpreter exit (crash, Ctrl+C) without close(): motors off."""
        if not self._io.acquire(timeout=0.5):
            return
        try:
            ser = self._ser
            if ser is not None:
                ser.write(b"x\n")
                _quiet(getattr(ser, "flush", None))
        except Exception:
            pass
        finally:
            self._io.release()

    # ---- writing
    def _enqueue(self, kind: str, data: bytes) -> bool:
        with self._out_cv:
            if self._closing or not self._connected:
                log.debug("robot link down; dropped %r", data.strip())
                return False
            if kind == "cmd" and self._out and self._out[-1][0] == "cmd":
                self._out[-1] = (kind, data)   # an unwritten drive command is stale once a newer one comes
            else:
                self._out.append((kind, data))
            self._out_cv.notify_all()
            return True

    def _write_loop(self) -> None:
        while True:
            with self._out_cv:
                while not self._out and not self._closing:
                    due = self._poll_due_in(time.monotonic())
                    if due is not None and due <= 0:
                        break
                    self._out_cv.wait(0.5 if due is None else min(0.5, due))
                if self._closing:
                    return
                if self._out:     # queued commands first; J only when nothing else waits
                    _, data = self._out.popleft()
                else:
                    data = b"J\n"
                    self._poll_next = time.monotonic() + (self._poll_period or 0.0)
                self._writing = True
            try:
                self._write_now(data)
            finally:
                with self._out_cv:
                    self._writing = False
                    self._out_cv.notify_all()

    def _write_now(self, data: bytes) -> bool:
        with self._io:
            ser = self._ser
            if ser is None or not self._connected:
                return False
            try:
                ser.write(data)
                return True
            except Exception as e:   # unplugged mid-write: the reader notices too and reconnects
                log.warning("robot link write failed (%s); marking disconnected", e)
                self._connected = False
        self._clear_queue()
        return False

    def _clear_queue(self) -> None:
        with self._out_cv:
            self._out.clear()
            self._out_cv.notify_all()

    # ---- J polling (yaw over USB; module docstring)
    def _reset_poll(self) -> None:
        """Port (re)opened: wait for the firmware to talk before polling."""
        with self._out_cv:
            self._poll_state = "waiting" if self._poll_period is not None else "off"

    def _poll_due_in(self, now: float) -> float | None:
        """Seconds until the next J (<= 0: now), or None while not polling. Caller holds _out_cv."""
        if self._poll_state not in ("polling", "answered") or not self._connected:
            return None
        if self._poll_state == "polling" and now - self._poll_since >= self._poll_give_up_s:
            self._poll_state = "off"
            log.warning("robot link: no reply to J in %.0f s (firmware without JSON telemetry over USB?); "
                        "no yaw over USB, so searches turn by time", self._poll_give_up_s)
            return None
        return self._poll_next - now

    def _firmware_talking(self) -> None:
        """A status line or V reply (printed from loop(): the firmware reads commands): start polling."""
        if self._poll_state != "waiting":   # unlocked peek: the reader is the only one leaving "waiting"
            return
        with self._out_cv:
            if self._poll_state == "waiting":
                self._poll_state = "polling"
                self._poll_since = self._poll_next = time.monotonic()
                self._out_cv.notify_all()

    def _got_json(self) -> None:
        if self._poll_state == "answered" or self._poll_period is None:
            return
        with self._out_cv:
            if self._poll_state != "answered":
                self._poll_state = "answered"
                self._poll_next = time.monotonic()
                self._out_cv.notify_all()
        log.info("robot link: the robot answers J; telemetry has yaw over USB (%.0f Hz)", 1.0 / self._poll_period)

    def _drain(self, timeout: float = 1.0) -> bool:
        """Wait until everything queued is written (for tests and scripts)."""
        end = time.monotonic() + timeout
        with self._out_cv:
            while self._out or self._writing:
                left = end - time.monotonic()
                if left <= 0:
                    return False
                self._out_cv.wait(left)
        return True

    # ---- reading
    def _drop_port(self) -> None:
        with self._io:
            ser, self._ser = self._ser, None
            self._connected = False
        self._clear_queue()
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
            elif not warned_quiet and self._tel_at is None and self._clock() - opened_at > 5.0:
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
        self._fault = None   # the ESP32 rebooted: its lastFault is null again
        self._json_at = self._json_yaw = None   # ...and its yaw is 0 again
        self._reset_poll()
        log.info("robot link back on %s (motors are off after a reboot; arm again by hand)", port)
        self._enqueue("letter", b"V\n")
        return True

    def _handle_line(self, line: str) -> None:
        if not line:
            return
        if line.startswith("STOP: "):           # balance.ino motorsOff()
            self._fault = line[6:]
        elif line.startswith(("BALANCING", "STANDING UP")):   # g / G clear the firmware's lastFault
            self._fault = None
        elif FIRMWARE_TAG in line:
            self.firmware = line
            self._firmware_talking()
        if line.startswith("{"):
            self._handle_json(line)
            return
        tel = status_to_tel(line, self._fault)
        if tel is not None:
            now = self._clock()
            if self._json_yaw is not None and self._json_at is not None and now - self._json_at < FRESH_S:
                tel["yaw"] = self._json_yaw    # the line has none: the last J reply's
            self.telemetry, self._tel_at = tel, now
            self._firmware_talking()
        elif line.isprintable():
            self.messages.append(line)

    def _handle_json(self, line: str) -> None:
        try:
            msg = json.loads(line)
        except ValueError:
            return
        if not isinstance(msg, dict) or msg.get("t") != "tel":
            return
        if not _is_number(msg.get("pitch")) or not isinstance(msg.get("state"), str):
            return   # not usable telemetry
        now = self._clock()
        self.telemetry, self._tel_at = msg, now
        yaw = msg.get("yaw")
        self._json_at, self._json_yaw = now, (float(yaw) if _is_number(yaw) and math.isfinite(yaw) else None)
        self._got_json()
        ack = msg.get("ack")
        if isinstance(ack, int) and ack in self._sent and ack > self._best_ack:
            self._best_ack, self._ack_at = ack, now
            self._lag = now - self._sent[ack]

    def _firmware_ok(self) -> bool:
        return bool(self.firmware and FIRMWARE_TAG in self.firmware)


def _quiet(fn: Callable[[], Any] | None) -> None:
    if fn is None:
        return
    try:
        fn()
    except Exception:
        pass
