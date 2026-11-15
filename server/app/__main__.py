"""Start the server: `uv run python -m app` (mock robot over UDP, live camera 0, debug window).

One asyncio loop (open question T-7) runs at 20 Hz: the arbiter picks one command (e-stop >
joystick > skill) and the robot link sends it. Vision runs on its own thread (VisionWorker) and
hands over its newest result; the follow skill reads it and requests motion from the arbiter. The
OpenCV debug window is drawn from this loop (non-blocking), because macOS only allows windows on
the main thread.

    uv run python -m mock                                                 # terminal 1: the mock robot
    uv run python -m app --source 0                                       # terminal 2: server + camera
    uv run python -m app --robot mock --test-drive --no-vision            # forward 2 s, turn left 2 s
    uv run python -m app --robot real --link serial --someone-at-robot --turn-only   # robot over USB

Links (contract v1, contract/README.md): `--link udp` (default) talks to the mock robot on
127.0.0.1 or the real robot at $ROBOT_HOST / balancebot.local (`--host` overrides);
`--link serial` talks to the robot over its USB cable (`--port`, default: auto-detect).

Keys (debug window): F follow on/off, Space e-stop on/off, G arm (USB only; hold it upright),
P park, X motors off, Q or Esc quit.

Safety (CLAUDE.md, firmware/README.md "Safety rules"):
- `--robot real` refuses to start (exit 2) without `--someone-at-robot`, before opening anything.
- The server never starts balancing by itself. Over UDP it never sends `g` (the person at the
  robot arms it); over USB only a person's G keypress does, after cancelling any running skill.
- The e-stop sends `5` once when it goes on (cancels a 90-degree turn or 50 cm move), then
  v = w = 0 every tick; the robot keeps balancing (decision 0043).
- Quitting, Ctrl+C, SIGTERM or a crash cancels the skill, sends `x` (motors off), closes the
  link, stops vision and closes the window.

Voice: with CARTESIA_API_KEY set, the API serves Cartesia speech at `/tts` for the phone page and
makes the stock lines (api.STOCK_LINES) in the background at startup; without it the phone uses
Safari's built-in voice.

Voice agent (#54; needs the API): with ANTHROPIC_API_KEY set, the server builds the brain's ToolBox
(the skill runner, skill factories follow / find_person / go_to / bring, camera snapshots) and its
Agent, and runs `agent.run()` as a background task. Messages reach its inbox from the API
(`/agent/message`, the control page, `/ws`) and, with CARTESIA_API_KEY too, from the phone's mic
(`/mic`, speech-to-text, wake word `--wake-word`, default "Miguel"). Its events go to the API
(`/agent/events`, `/ws`); `say` events also go to the phone's say queue and open the mic's answer
window. find_person / go_to / bring need the camera; bring waits for the control page's Tray
loaded button (`/control/loaded`) at the station. Without the key it logs
"agent: off" and everything else runs as before. Shutdown cancels the agent before the skill.

"This is Mom" (#62): with a camera, ONE PeopleRegistry (saved looks, server/people.json) is shared by
find_person, bring, the agent's this_is tool and the control page's "This is" box
(`/control/this-is`, which works even with the agent off). Skills also get the robot's telemetry
through their context (`telemetry=`, when SkillContext takes it).
"""

from __future__ import annotations

import argparse
import asyncio
import inspect
import logging
import os
import signal
import threading
import time
from collections.abc import Callable, Coroutine
from types import SimpleNamespace
from typing import Any

from app import api
from app.arbiter import Arbiter, Command
from app.link import PORT, RobotLink, UdpLink
from app.skills import SkillContext, SkillResult, SkillRunner

SEND_HZ = 20
log = logging.getLogger("app")

ARM_REMINDER = ("Arming (g): someone must hold the robot upright (within 6 deg) and let go once it's "
                "holding itself. Press X or P before anyone touches it.")
UDP_ARM_NOTE = ("G: over the network the server never sends g. Arm on the robot side: the person holding "
                "it presses g (firmware/balance/teleop.py), or start the mock with `python -m mock --armed`.")


class TestDrive:
    """Forward 2 s, turn left 2 s, stop. Uses the skill path, so e-stop and joystick win."""

    name = "test_drive"

    async def run(self, ctx: SkillContext) -> SkillResult:
        for v, w, seconds in ((0.15, 0.0, 2.0), (0.0, 0.6, 2.0)):
            for _ in range(int(seconds * SEND_HZ)):
                ctx.drive(v, w)
                await asyncio.sleep(1 / SEND_HZ)
        return SkillResult(True, "test drive done")


class Sender:
    """One tick of arbiter -> link: `5` on the e-stop edge, one `cmd`, a health log every second."""

    def __init__(self, arbiter: Arbiter, link: RobotLink) -> None:
        self.arbiter = arbiter
        self.link = link
        self.was_estopped = False
        self.ticks = 0
        self.errors = 0

    def step(self) -> Command:
        cmd = self.arbiter.decide()
        estopped = self.arbiter.estopped
        if estopped and not self.was_estopped:
            self._try(self.link.send_letter, "5")   # cancel any 90-degree turn or 50 cm move in progress
        self.was_estopped = estopped
        self._try(self.link.send_cmd, cmd.v, cmd.w, "drive")   # drive 0,0 holds position without cancelling L/R/F/B
        if self.ticks % SEND_HZ == 0:
            self._log(cmd)
        self.ticks += 1
        return cmd

    def _try(self, fn: Callable[..., Any], *args: Any) -> None:
        try:
            fn(*args)
        except Exception as e:   # a cable tug: the robot's 300 ms watchdog stops it; keep the loop alive
            self.errors += 1
            if self.errors == 1 or self.errors % SEND_HZ == 0:
                log.warning("link send failed (%d so far): %s", self.errors, e)

    def _log(self, cmd: Command) -> None:
        try:
            h = self.link.health()
        except Exception:
            return
        tel = self.link.telemetry or {}
        log.info("send v=%.2f w=%.2f (%s) | robot %s pitch=%s x=%s yaw=%s | link %s%s",
                 cmd.v, cmd.w, cmd.source, tel.get("state", "?"), tel.get("pitch", "?"),
                 tel.get("x", "?"), tel.get("yaw", "?"), "ok" if h.ok else "DOWN",
                 f" lag {h.lag_ms:.0f} ms" if h.lag_ms is not None else "")


async def drive_loop(arbiter: Arbiter, link: RobotLink, stop: asyncio.Event | None = None) -> None:
    """Send the arbiter's decision to the robot, SEND_HZ times a second (no window, no keys)."""
    sender = Sender(arbiter, link)
    while not (stop and stop.is_set()):
        sender.step()
        await asyncio.sleep(1 / SEND_HZ)


def make_skill_context(arbiter: Arbiter, vision: Any, link: RobotLink) -> SkillContext:
    """The skills' context: the arbiter, vision and (#62) the robot's newest telemetry dict."""
    return SkillContext(arbiter, vision, telemetry=lambda: link.telemetry)   # read live, not copied


class App:
    """The server's 20 Hz loop: arbiter -> link, keys, debug view. No I/O of its own beyond what it's given."""

    def __init__(
        self,
        link: RobotLink,
        *,
        robot: str = "mock",
        link_kind: str = "udp",
        vision: Any = None,
        follow_factory: Callable[[], Any] | None = None,
        window: Any = None,
        render: Callable[..., Any] | None = None,
        hz: float = SEND_HZ,
    ) -> None:
        self.link = link
        self.robot = robot
        self.link_kind = link_kind
        self.vision = vision
        self.arbiter = Arbiter()
        self.skills = SkillRunner(make_skill_context(self.arbiter, vision, link))
        self.sender = Sender(self.arbiter, link)
        self._follow_factory = follow_factory
        self._window = window
        self._render = render
        self.period_s = 1.0 / hz
        self.follow: Any = None  # the current/last follow skill (for its last command)
        self.face_events: Any = None  # app.vision.face_state.FaceEvents, made on first use (vision only)
        self.note = ""
        self.last: Command = Command(0.0, 0.0, "none")
        self.background: list[asyncio.Task] = []   # e.g. the voice agent: cancelled first on shutdown
        self._quit = False
        self._closed = False

    def start_background(self, coro: Coroutine[Any, Any, Any], name: str) -> asyncio.Task:
        """Run a task (the voice agent) until shutdown; a crash is logged, never takes the loop down."""
        task = asyncio.create_task(coro, name=name)

        def done(t: asyncio.Task) -> None:
            if not t.cancelled() and t.exception() is not None:
                log.error("%s stopped: %r", name, t.exception())

        task.add_done_callback(done)
        self.background.append(task)
        return task

    # --- keys (also callable from the API later) ---

    def handle_key(self, key: str) -> None:
        key = key.lower()
        if key in ("q", "\x1b"):
            self.quit()
        elif key == "f":
            self.toggle_follow()
        elif key == " ":
            self.toggle_estop()
        elif key == "g":
            self.arm()
        elif key == "p":
            self.skills.cancel()
            self._letter("P")
            self._say("park (P) sent; skill stopped")
        elif key == "x":
            self.skills.cancel()
            self._letter("x")
            self._say("motors off (x) sent; skill stopped")

    def start_skill(self, skill: Any) -> asyncio.Task:
        task = self.skills.start(skill)
        task.add_done_callback(self._skill_done)
        return task

    def toggle_follow(self) -> None:
        if self.skills.running == "follow":
            self.skills.cancel()
            self._say("follow: stopped")
            return
        if self._follow_factory is None or self.vision is None:
            self._say("follow: no vision in this run")
            return
        if self.arbiter.estopped:
            self._say("follow: release the e-stop first (Space)")
            return
        self.follow = self._follow_factory()
        self.start_skill(self.follow)
        self._say("follow: started, locking onto the person in front")

    def toggle_estop(self) -> None:
        if self.arbiter.estopped:
            self.arbiter.estop(False)
            self._say("e-stop released")
        else:
            self.arbiter.estop(True)   # the next tick sends 5, then v 0 w 0
            self.skills.cancel()       # the e-stop also ends the running skill
            self._say("E-STOP on")

    def arm(self) -> None:
        """G: arm the robot (g) over USB only, on a person's keypress. Over UDP the robot side arms it."""
        arm = getattr(self.link, "arm", None)
        if self.link_kind != "serial" or arm is None:
            self._say(UDP_ARM_NOTE)
            return
        print(ARM_REMINDER, flush=True)
        if self.skills.running:
            self.skills.cancel()  # never arm into a running skill: it would drive off while being held
        try:
            arm()
        except Exception as e:
            self._say(f"arm (g) failed: {e}")
            return
        self._say("arm (g) sent: hold it upright, let go once it holds itself; then F to follow")

    def quit(self) -> None:
        self._quit = True

    def _letter(self, letter: str) -> None:
        try:
            self.link.send_letter(letter)
        except Exception as e:
            log.warning("sending %r failed: %s", letter, e)

    def _say(self, text: str) -> None:
        self.note = text
        log.info("%s", text)

    def _skill_done(self, task: asyncio.Task) -> None:
        if task.cancelled():
            return
        if task.exception() is not None:
            self._say(f"{task.get_name()}: crashed: {task.exception()!r}")
            return
        result = task.result()
        if result.detail != "cancelled":
            self._say(f"{task.get_name()}: {'done' if result.ok else 'failed'}: {result.detail}")

    # --- the loop ---

    def tick(self) -> Command:
        """One step: decide and send, tell vision how the robot is turning, draw, read a key."""
        cmd = self.sender.step()
        self.last = cmd
        if self.vision is not None:
            self.vision.set_turn_rate(self._turn_rate(cmd))
            try:
                self.face()   # every tick, so a short lock/lost change between status polls still counts
            except Exception:
                log.exception("face state failed")   # never let the face stop the drive loop
        if self._window is not None and self._render is not None:
            key = self._window.show(self._render(self._perception(), self.hud()))
            if key is not None and key >= 0:
                self.handle_key(chr(key & 0xFF))
        return cmd

    def _turn_rate(self, cmd: Command) -> float:
        # The camera only turns with the real robot, and only while it balances.
        if self.robot != "real":
            return 0.0
        tel = self.link.telemetry
        if isinstance(tel, dict) and tel.get("state") == "idle":
            return 0.0
        return cmd.w

    def _perception(self) -> Any:
        return self.vision.latest() if self.vision is not None else None

    def face(self) -> dict | None:
        """The phone face's view (app/vision/face_state.py): where the locked person is and the latest
        follow event. None without vision."""
        if self.vision is None:
            return None
        if self.face_events is None:
            from app.vision.face_state import FaceEvents

            self.face_events = FaceEvents()
        mirrored = bool(getattr(getattr(self.vision, "_source", None), "mirror", False))
        return self.face_events.update(self._perception(), self.skills.running == "follow",
                                       getattr(self.follow, "last_command", None), time.monotonic(), mirrored)

    def robot_status(self) -> tuple[bool, Any]:
        """(connected, telemetry for the debug view) from link.health() and the contract-v1 telemetry dict."""
        tel = self.link.telemetry
        if not isinstance(tel, dict):
            return False, None
        parts = [str(tel.get("state", "?"))]
        if isinstance(tel.get("x"), (int, float)):
            parts.append(f"x {tel['x']:+.2f} m")
        if isinstance(tel.get("yaw"), (int, float)):
            parts.append(f"yaw {tel['yaw']:+.0f} deg")
        try:
            h = self.link.health()
            link = "link ok" if h.ok else "link DOWN"
            if h.lag_ms is not None:
                link += f" lag {h.lag_ms:.0f} ms"
            if not h.ok and h.telemetry_age is not None:
                link += f" (telemetry {h.telemetry_age:.1f} s old)"
            parts.append(link)
        except Exception:
            pass
        pitch = tel.get("pitch")
        fault = tel.get("fault")
        return True, SimpleNamespace(
            state="  ".join(parts),
            pitch_deg=float(pitch) if isinstance(pitch, (int, float)) else None,
            fault=fault if isinstance(fault, str) else None,   # why the motors last turned off; null after g
        )

    def hud(self) -> Any:
        from app.vision.debug_view import Hud

        running = self.skills.running
        connected, telemetry = self.robot_status()
        return Hud(
            robot=f"{self.robot}, {self.link_kind}",
            sent_v=self.last.v,
            sent_w=self.last.w,
            source=self.last.source,
            skill=running,
            follow=getattr(self.follow, "last_command", None) if running == "follow" else None,
            connected=connected,
            telemetry=telemetry,
            vision_status=getattr(self.vision, "status", "") if self.vision is not None else "off",
            note=self.note,
        )

    async def run(self, max_ticks: int | None = None) -> None:
        """Run until quit (or max_ticks, for tests). Always shuts down cleanly."""
        loop = asyncio.get_running_loop()
        try:
            loop.add_signal_handler(signal.SIGTERM, self.quit)
        except (NotImplementedError, RuntimeError, ValueError):
            pass  # not on the main thread, or not supported here
        next_t = time.monotonic()
        ticks = 0
        try:
            while not self._quit and (max_ticks is None or ticks < max_ticks):
                self.tick()
                ticks += 1
                next_t += self.period_s
                delay = next_t - time.monotonic()
                if delay < -0.5:  # fell far behind (a slow window?): don't try to catch up
                    next_t = time.monotonic()
                await asyncio.sleep(max(0.0, delay))
        finally:
            await self.shutdown()
            try:
                loop.remove_signal_handler(signal.SIGTERM)
            except (NotImplementedError, RuntimeError, ValueError):
                pass

    async def shutdown(self) -> None:
        """Cancel the skill, send x, close the link, stop vision, close the window. Safe to call twice."""
        if self._closed:
            return
        self._closed = True
        for t in self.background:   # first, so the agent can't start a skill while we stop
            t.cancel()
        if self.background:
            await asyncio.wait(self.background, timeout=1.0)
        task = self.skills.task
        self.skills.cancel()
        if task is not None and not task.done():
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=1.0)
            except (asyncio.TimeoutError, asyncio.CancelledError, Exception):
                pass
        self._letter("x")   # motors off: end every run with x (firmware/README.md)
        try:
            await self.link.close()
        except Exception:
            log.exception("closing the link failed")
        if self.vision is not None:
            close_quietly(self.vision.stop, "vision")
        if self._window is not None:
            close_quietly(self._window.close, "window")


def close_quietly(fn: Callable[[], Any], what: str) -> None:
    try:
        fn()
    except Exception:
        log.exception("closing the %s failed", what)


# --- command line ---


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="python -m app", description="Miguel.exe server",
                                 epilog="Keys in the window: F follow, Space e-stop, G arm (USB only), P park, "
                                        "X motors off, Q quit.")
    ap.add_argument("--robot", choices=["mock", "real"], default="mock",
                    help="mock: the mock robot on this laptop (`python -m mock`, default); real: the robot")
    ap.add_argument("--someone-at-robot", action="store_true",
                    help="required with --robot real: a person is at the robot, ready to catch it")
    ap.add_argument("--reverse-drive", action=argparse.BooleanOptionalAction,
                    default=os.environ.get("ROBOT_REVERSE_DRIVE", "").strip().lower() in ("1", "true", "yes", "on"),
                    help="swap forward and backward for every drive command (default: $ROBOT_REVERSE_DRIVE)")
    ap.add_argument("--link", choices=["udp", "serial"], default="udp",
                    help="udp: Wi-Fi, or the mock on this laptop (default); serial: the robot's USB cable")
    ap.add_argument("--host", help="robot address for --link udp (default: 127.0.0.1 for mock; "
                                   "$ROBOT_HOST or balancebot.local for real)")
    ap.add_argument("--port", default=None, help="serial port for --link serial (default: auto-detect)")
    ap.add_argument("--test-drive", action="store_true", help="drive forward, then turn, through the arbiter")
    ap.add_argument("--source", default="phone",
                    help="phone: the robot's phone page streams its camera to the server (default); "
                         "or a camera index (0, 1, ...) or a video file path")
    ap.add_argument("--no-vision", action="store_true", help="run without camera and detector")
    ap.add_argument("--rotate", choices=["left", "right", "180"], help="if people show up sideways")
    ap.add_argument("--turn-only", action="store_true", help="follow only turns toward the person, never drives")
    ap.add_argument("--camera-back", action="store_true", help="the camera faces the robot's back")
    ap.add_argument("--height-m", type=float, default=None, help="camera height above the floor")
    ap.add_argument("--tilt-deg", type=float, default=None, help="camera tilt, up positive")
    ap.add_argument("--calibration", default=None, metavar="PATH",
                    help="camera calibration file (default server/calibration.json; "
                         "make one with python -m app.vision.calibrate)")
    ap.add_argument("--follow", action="store_true", help="start the follow skill at once (useful with --no-window)")
    ap.add_argument("--window", action=argparse.BooleanOptionalAction, default=True,
                    help="show the debug window (keys only work in it)")
    ap.add_argument("--api", action=argparse.BooleanOptionalAction, default=True,
                    help="serve the phone page, the control page and the dashboard WebSocket")
    ap.add_argument("--http-port", type=int, default=8080, help="control page, dashboard WebSocket, certificate page")
    ap.add_argument("--https-port", type=int, default=8443, help="the robot's phone page (0 = off)")
    ap.add_argument("--wake-word", default="Miguel",
                    help="the voice agent only hears mic speech that starts with this word ('' = hears everything)")
    return ap


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = build_parser()
    args = ap.parse_args(argv)
    if args.robot == "real" and not args.someone_at_robot:
        ap.error("--robot real sends motor commands: add --someone-at-robot only when a person is at the "
                 "robot, ready to catch it (firmware/README.md, Safety rules)")
    if args.link == "serial" and args.robot != "real":
        ap.error("--link serial talks to the robot over its USB cable: use --robot real --someone-at-robot "
                 "(the mock robot speaks UDP only)")
    if args.link == "udp" and args.port is not None:
        ap.error("--port is the serial port for --link serial; for UDP use --host")
    if args.link == "serial" and args.host is not None:
        ap.error("--host is for --link udp; for USB use --port")
    return args


def make_link(args: argparse.Namespace) -> RobotLink:
    """The link for these flags, not started yet, wrapped so forward is where the camera faces
    (app.link.ReversedLink; serve() ties it to the camera setting). --reverse-drive (or
    ROBOT_REVERSE_DRIVE=1) means: with the phone's BACK camera, forward is the firmware's backward
    (how this robot's phone is mounted); the front camera is then the other way."""
    if args.link == "serial":
        from app.link.serial_link import SerialLink

        link: Any = SerialLink(args.port)
    else:
        default = "127.0.0.1" if args.robot == "mock" else os.environ.get("ROBOT_HOST", "balancebot.local")
        link = UdpLink(args.host or default, PORT)
    from app.link import ReversedLink

    back_flipped = bool(args.reverse_drive)
    log.info("link: forward = the camera's direction (back camera %s the firmware's forward)",
             "is opposite to" if back_flipped else "matches")
    return ReversedLink(link, lambda: back_flipped)


def load_calibration(path: str | None) -> Any:
    """The camera calibration (#62; app/vision/calibration.py, written by
    `python -m app.vision.calibrate`), or None: then the built-in guesses are used."""
    try:
        from app.vision import calibration
    except Exception as e:
        log.warning("calibration: unavailable (%s); using the default camera guesses", e)
        return None
    where = path or calibration.DEFAULT_PATH
    cal = calibration.load(where)   # a corrupt file logs a warning and gives None
    if cal is None:
        log.info("calibration: none at %s; using the default camera guesses (python -m app.vision.calibrate)", where)
    else:
        log.info("calibration: %s (measured %s)", where, cal.measured_at or "?")
    return cal


def make_follow_config(args: argparse.Namespace, cal: Any = None) -> Any:
    """The follow skill's config: the calibration's measurements, then --height-m / --tilt-deg on top."""
    from dataclasses import replace

    from app.vision import calibration
    from app.vision.follow import FollowConfig

    config = calibration.follow_config(cal, FollowConfig(turn_only=args.turn_only, camera_back=args.camera_back))
    geo: dict[str, float] = {}
    if args.height_m is not None:
        geo["height_m"] = args.height_m
    if args.tilt_deg is not None:
        geo["tilt_deg"] = args.tilt_deg
    return replace(config, camera=replace(config.camera, **geo)) if geo else config


def make_vision(args: argparse.Namespace, cal: Any = None) -> Any:
    from app.vision import calibration
    from app.vision.detector import YoloPoseDetector
    from app.vision.frames import open_source
    from app.vision.markers import MarkerDetector
    from app.vision.tracking import TargetLock
    from app.vision.worker import VisionWorker

    detector = YoloPoseDetector()  # loads the weights now, so a missing file fails before anything starts
    if args.source == "phone":
        # Alex's design: the robot's phone streams its camera to the server (POST /frame), the server sees.
        from app.vision.phone_source import PhoneFrameSource

        source = PhoneFrameSource()
    else:
        source = open_source(args.source, rotate=args.rotate)
    return VisionWorker(source, detector, TargetLock(calibration.lock_config(cal)),
                        marker_detector=MarkerDetector(**calibration.marker_kwargs(cal)))


def api_state(app: App, link: RobotLink, vision: Any, tts: Any) -> api.ApiState:
    """The API's view of the server. With vision, Follow on the control page runs the server's follow skill
    and the control page shows the server's view; with the phone as the camera, /frame feeds vision."""
    state = api.ApiState(app.arbiter, link, skills=app.skills, tts=tts)
    if vision is None:
        return state
    state.phone_frames = getattr(vision, "_source", None) if args_source_is_phone(vision) else None
    base = getattr(app._follow_factory, "config", None)
    if base is not None:
        import dataclasses

        from app.skills.follow import FollowSkill

        def factory() -> Any:
            # The control page's follow settings: speed cap and stop distance ("bigger = stays closer",
            # the same upper-body width fraction as John's phone page). They apply when Follow starts.
            # One "closeness" setting moves both distance cues together, so neither stops it early:
            # the box target is the setting, and the shoulder target in meters scales inversely
            # (John's 0.45 <-> 1.0 m). It backs off inside 70% of the target distance.
            closeness = float(state.settings["distance"])
            d_target = 0.45 / closeness
            return FollowSkill(dataclasses.replace(base, v_max=float(state.settings["speed"]),
                                                   target_box_w=closeness, d_target_m=d_target,
                                                   d_min_m=0.7 * d_target))
        factory.config = base  # type: ignore[attr-defined]
        app._follow_factory = factory
    state.follow_start = lambda: None if app.skills.running == "follow" else app.toggle_follow()
    state.follow_stop = lambda: app.toggle_follow() if app.skills.running == "follow" else None
    state.follow_running = lambda: app.skills.running == "follow"
    state.vision_status = lambda: vision.status
    state.view_jpeg = ViewEncoder(app).jpeg
    state.vision_debug = lambda: vision_debug(vision)
    state.face = app.face
    return state


def args_source_is_phone(vision: Any) -> bool:
    from app.vision.phone_source import PhoneFrameSource

    return isinstance(getattr(vision, "_source", None), PhoneFrameSource)


def vision_debug(vision: Any) -> dict:
    """The sizes follow uses to judge distance, for every person in the newest frame."""
    from app.vision.follow import shoulder_gap

    p = vision.latest()
    if p is None:
        return {"frame": None, "people": []}
    people = []
    for person in p.detections.people:
        b = person.box
        people.append({"box_w": round(b.x2 - b.x1, 3), "box_h": round(b.y2 - b.y1, 3), "cx": round((b.x1 + b.x2) / 2, 3),
                       "top": round(b.y1, 3), "bottom": round(b.y2, 3), "shoulder_gap": shoulder_gap(person),
                       "score": round(person.score, 2)})
    return {"frame": [p.frame.width, p.frame.height], "age_s": round(time.monotonic() - p.frame_t, 2),
            "target": p.target.status.value if hasattr(p.target.status, "value") else str(p.target.status),
            "people": people}


class ViewEncoder:
    """The server's view for the control page: the latest frame with the overlay (boxes, target, command),
    as JPEG. Re-encoded only when a new frame has been processed, at most ~10 times a second."""

    def __init__(self, app: App, max_width: int = 640) -> None:
        self._app = app
        self._max_width = max_width
        self._key: Any = None
        self._jpeg: bytes | None = None
        self._lock = threading.Lock()

    def jpeg(self) -> bytes | None:
        import cv2

        from app.vision.debug_view import render

        perception = self._app._perception()
        key = None if perception is None else perception.frame_index
        with self._lock:
            if key is not None and key == self._key and self._jpeg is not None:
                return self._jpeg
            img = render(perception, self._app.hud(), max_width=self._max_width)
            ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 70])
            if ok:
                self._key, self._jpeg = key, buf.tobytes()
            return self._jpeg


def make_tts() -> Any:
    """The phone's voice: Cartesia (default), or Kokoro on this Mac with MIGUEL_TTS=local (#81).
    The local voice falls back to Cartesia when its model is missing; None means Safari's built-in voice."""
    choice = (os.environ.get("MIGUEL_TTS") or "cartesia").strip().lower()
    if choice == "local":
        try:
            from app.speech.tts_local import KokoroTTS

            local = KokoroTTS.from_env()   # None, with a log line saying why, if the model is missing
        except Exception as e:   # broken install: run without it
            log.warning("voice: local voice unavailable (%s)", e)
            local = None
        if local is not None:
            log.info("voice: local (Kokoro, voice %s); loading in the background", local.voice)
            return local
        log.warning("voice: MIGUEL_TTS=local but the local voice is unavailable; trying Cartesia")
    elif choice != "cartesia":
        log.warning("voice: MIGUEL_TTS=%r is not 'local' or 'cartesia'; using Cartesia", choice)
    try:
        from app.speech.tts import CartesiaTTS

        tts = CartesiaTTS.from_env()
    except Exception as e:   # the module or its settings are broken: run without it
        log.warning("voice: Cartesia unavailable (%s); using Safari's built-in voice", e)
        return None
    if tts is None:
        log.info("voice: Safari's built-in (CARTESIA_API_KEY not set)")
    else:
        log.info("voice: Cartesia")
    return tts


async def prewarm_voice(tts: Any) -> None:
    """Make the stock lines ahead of time (in the background), so the first time each plays it's instant."""
    try:
        n = await tts.prewarm(api.STOCK_LINES)
        log.info("voice: %d of %d stock lines ready", n, len(api.STOCK_LINES))
    except Exception:   # prewarm shouldn't raise; never let it take the server down
        log.exception("voice: prewarming the stock lines failed")


# --- the voice agent (#54) ---

SNAPSHOT_MAX_WIDTH = 960   # photos for the family app: small enough to send, big enough to see


def make_snapshot(vision: Any) -> Callable[[], bytes | None]:
    """A function that returns the camera's newest frame as JPEG bytes, or None (no frame yet)."""

    def snapshot() -> bytes | None:
        p = vision.latest()
        if p is None:
            return None
        import cv2

        img = p.frame.image
        h, w = img.shape[:2]
        if w > SNAPSHOT_MAX_WIDTH:
            img = cv2.resize(img, (SNAPSHOT_MAX_WIDTH, round(h * SNAPSHOT_MAX_WIDTH / w)), interpolation=cv2.INTER_AREA)
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 80])
        return buf.tobytes() if ok else None

    return snapshot


def make_registry() -> Any:
    """The saved looks (server/people.json; app/vision/people.py), or None if it can't load.
    Make ONE and share it: find_person, bring, this_is and /control/this-is must see the same looks."""
    try:
        from app.vision.people import PeopleRegistry

        return PeopleRegistry()
    except Exception as e:
        log.warning("people: no saved looks for find_person or this_is (%s)", e)
        return None


def make_this_is(registry: Any, vision: Any) -> Callable[[str], Any] | None:
    """The control page's "This is" box (/control/this-is): the this_is tool's save path, or None."""
    if registry is None or vision is None:
        return None
    try:
        from app.brain.tools import save_look
    except Exception as e:
        log.warning("people: this is unavailable (%s)", e)
        return None
    return lambda name: save_look(name, registry, vision.latest())


def make_skill_factories(follow_factory: Callable[[], Any] | None, *, say: Callable[[str], Any] | None = None,
                         wait_loaded: Callable[[], Any] | None = None, registry: Any = None,
                         memory: Any = None, on_step: Callable[[str, str], None] | None = None
                         ) -> dict[str, Callable[..., Any]]:
    """Skills the agent may start, by tool name (app/brain/tools.py: each factory takes the tool's
    arguments as keywords). Only with a camera (`follow_factory` is None without vision): every
    physical skill needs to see. bring also needs `say` and `wait_loaded` (the Tray loaded button).
    `registry` (make_registry) is the saved looks find_person and bring match against.
    `memory` (app.memory.Memory): places by marker for go_to and bring (which station holds the item).
    `on_step(stage, text)`: bring's progress, for the family app (app/family.py)."""
    factories: dict[str, Callable[..., Any]] = {}
    if follow_factory is None:
        return factories
    factories["follow"] = lambda **_: follow_factory()
    try:
        from app.skills.search import FindPerson, GoTo
    except Exception as e:   # not landed yet, or broken: the agent runs with follow only
        log.warning("agent: find_person, go_to and bring unavailable (%s)", e)
        return factories
    matcher = None
    try:
        from app.brain.vision_check import matches_description as matcher
    except Exception as e:
        log.warning("agent: no description check for find_person (%s)", e)
    factories["find_person"] = lambda name=None, description=None, **_: FindPerson(name, description, registry, matcher)
    places: dict[str, Any] = {}
    if memory is not None:
        places = {"marker_for": memory.marker_for, "known_places": memory.known_places()}

    def go_to(place: str, **_: Any) -> Any:
        if memory is not None:
            places["known_places"] = memory.known_places()   # learn_place may have added one since
        return GoTo(place, **places)

    def station_for(item: str) -> str:
        p = memory.find_place(item, with_marker=True) if memory is not None else None   # "water" -> "water station"
        return p["name"] if p is not None else "station"

    factories["go_to"] = go_to
    if say is not None and wait_loaded is not None:
        try:
            from app.skills.bring import Bring

            factories["bring"] = lambda item, person=None, **_: Bring(
                item, person, wait_loaded, say, registry=registry, matcher=matcher, station=station_for(item),
                on_step=(lambda stage, text, _item=item: on_step(stage, text, item=_item)) if on_step else None,
                **({"marker_for": memory.marker_for, "known_places": memory.known_places()}
                   if memory is not None else {}))
        except Exception as e:
            log.warning("agent: bring unavailable (%s)", e)
    return factories


def on_agent_event(state: Any, ev: Any) -> None:
    """An agent event: to the API (/agent/events, /ws) and, for `say`, to the phone's say queue."""
    d = state.publish_agent_event(ev)
    if getattr(state, "family", None) is not None:
        state.family.on_agent_event(d)
    if d.get("kind") == "say":
        state.add_say(str(d.get("text", "")))
        hub = getattr(state.mic, "hub", None)
        if hub is not None:
            hub.note_miguel_spoke()   # the senior can answer without the wake word for a few seconds
    elif d.get("kind") in ("reply", "error", "task"):
        log.info("agent %s: %s", d["kind"], str(d.get("text", ""))[:120])


def make_memory() -> Any:
    """Miguel's SQLite memory (server/miguel.db), with the printed-marker places as a first seed."""
    from app.memory import Memory
    from app.vision import places

    path = os.environ.get("MIGUEL_DB") or None   # tests point it at a temp file
    return Memory(**({"path": path} if path else {}), seed_places=places.places(), seed_aliases=places.ALIASES)


def make_agent(app: App, state: Any, follow_factory: Callable[[], Any] | None, registry: Any = None,
               memory: Any = None) -> Any:
    """The brain's Agent wired to this server, or None (no ANTHROPIC_API_KEY, or the brain is broken).
    `registry`: the one PeopleRegistry, for find_person, bring and the this_is tool."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        log.info("agent: off (ANTHROPIC_API_KEY not set)")
        return None
    try:
        from app.brain.agent import Agent
        from app.brain.tools import ToolBox

        family = getattr(state, "family", None)
        factories = make_skill_factories(follow_factory, say=state.add_say, wait_loaded=state.wait_loaded,
                                         registry=registry, memory=memory,
                                         on_step=family.on_bring_step if family is not None else None)
        toolbox = ToolBox(app.skills, factories, save_photo=state.save_photo,
                          snapshot=make_snapshot(app.vision) if app.vision is not None else None,
                          registry=registry,
                          perception=app.vision.latest if app.vision is not None else None,
                          wait_tray=state.wait_loaded,
                          memory=memory.facts if memory is not None else None, places=memory)
        agent = Agent(toolbox, events_cb=lambda ev: on_agent_event(state, ev))
    except Exception as e:
        log.warning("agent: off (%s)", e)
        return None
    state.agent_inbox = agent.inbox
    state.agent_working = lambda: agent.working   # the family app knows when he has stopped working
    log.info("agent: on (skills: %s)", ", ".join(factories) or "none, no camera")
    return agent


def make_hearing(state: Any, wake_word: str | None) -> Any:
    """The phone's /mic, through speech-to-text into the agent's inbox; returns the STT (to close) or None.
    MIGUEL_STT picks it: cartesia (default) or local (Parakeet + Silero on this Mac, app/speech/stt_local.py;
    if its packages or model are missing it says so and uses Cartesia when there is a key).
    Without any STT /mic is still mounted and drops the audio, so the phone page works the same."""
    try:
        from app.speech.mic import make_mic_handler
        from app.speech.stt import CartesiaSTT

        choice = (os.environ.get("MIGUEL_STT") or "cartesia").strip().lower()
        if choice not in ("cartesia", "local"):
            log.warning("hearing: MIGUEL_STT=%r is not cartesia or local: using cartesia", choice)
            choice = "cartesia"
        stt: Any = None
        if choice == "local":
            from app.speech.stt_local import LocalSTT

            stt = LocalSTT.from_env(fallback=CartesiaSTT.from_env)   # Cartesia only if loading fails later
            if stt is None:
                log.warning("hearing: local speech-to-text unavailable (see above); trying Cartesia")
                choice = "cartesia"
            else:
                stt.start_loading()          # load and warm up in the background
        if stt is None:
            stt = CartesiaSTT.from_env()
        state.mic = make_mic_handler(stt, state.agent_inbox, wake_word=wake_word)
    except Exception as e:
        log.warning("hearing: off (%s)", e)
        return None
    if stt is None:
        log.info("hearing: off (CARTESIA_API_KEY not set); /mic drops the phone's audio")
    else:
        log.info("hearing: on (%s), /mic (wake word: %s)", choice, wake_word or "none")
    return stt


async def close_async_quietly(obj: Any, what: str) -> None:
    """Call obj.aclose() or obj.close() (awaiting it if needed), if it has one."""
    fn = getattr(obj, "aclose", None) or getattr(obj, "close", None)
    if fn is None:
        return
    try:
        result = fn()
        if inspect.isawaitable(result):
            await result
    except Exception:
        log.exception("closing the %s failed", what)


def make_window() -> tuple[Any, Any]:
    from app.vision.debug_view import DebugWindow, render

    return DebugWindow(), render


async def serve(args: argparse.Namespace, link: RobotLink, *, vision: Any = None,
                follow_factory: Callable[[], Any] | None = None, window: Any = None,
                render: Callable[..., Any] | None = None) -> App:
    """Start the link, then run the App until quit. The App's shutdown closes everything."""
    app = App(link, robot=args.robot, link_kind=args.link, vision=vision, follow_factory=follow_factory,
              window=window, render=render)
    try:
        await link.start()
    except BaseException as e:
        app._closed = True   # the link never started: only clean up what exists
        if vision is not None:
            close_quietly(vision.stop, "vision")
        if window is not None:
            close_quietly(window.close, "window")
        if isinstance(e, Exception):
            raise SystemExit(f"Couldn't start the robot link: {e}") from e
        raise
    runner = tts = warm = agent = stt = None
    try:
        if args.api:
            tts = make_tts()
            state = api_state(app, link, vision, tts)
            if hasattr(link, "flipped"):   # forward follows the camera setting (front camera: the other way)
                back_flipped = link.flipped()
                link.flipped = lambda: back_flipped != (state.settings.get("camera") == "front")
            state.guardian_token = os.environ.get("GUARDIAN_TOKEN") or None
            registry = make_registry() if vision is not None else None   # ONE instance for everyone (#62)
            state.this_is = make_this_is(registry, vision)
            memory = make_memory()   # SQLite: facts, places, Mom's day (server/miguel.db)
            from app.family import FamilyHub

            state.family = FamilyHub(state, memory, snapshot=make_snapshot(vision) if vision is not None else None)
            state.memory, state.registry = memory, registry
            # The agent's follow uses the control page's follow settings (api_state wraps the factory).
            agent = make_agent(app, state, app._follow_factory or follow_factory, registry, memory)   # sets state.agent_inbox
            if agent is not None:
                stt = make_hearing(state, args.wake_word or None)   # sets state.mic, before the routes are made
            runner, _ = await api.start(state, args.http_port, args.https_port or None)
            if agent is not None:
                app.start_background(agent.run(), "agent")
            if vision is not None and state.family is not None and os.environ.get("ANTHROPIC_API_KEY"):
                from app.vision import fall

                if fall.enabled():   # FALL_DETECT=0 turns it off
                    watcher = fall.FallWatcher(vision.latest, make_snapshot(vision), state.family.raise_alert)
                    app.start_background(watcher.run(), "fall")
            if tts is not None:
                warm = asyncio.create_task(prewarm_voice(tts))   # don't hold up startup
        else:
            log.info("agent: off (--no-api: nothing to talk to it)")
        if args.robot == "real":
            if args.link == "serial":
                print("REAL robot on USB. Nothing moves until someone holds it upright and presses G.", flush=True)
            else:
                print("REAL robot over Wi-Fi. Nothing moves until the person at the robot arms it (g).", flush=True)
        if vision is not None:
            vision.start()
            print("Vision is starting (the detector warm-up takes several seconds).", flush=True)
        if args.follow:
            app.toggle_follow()
        if args.test_drive:
            log.info("test drive in 3 s (forward 2 s, turn left 2 s). The robot only moves if it's balancing (g).")

            async def later() -> None:
                await asyncio.sleep(3)
                if not app._closed:
                    app.start_skill(TestDrive())

            asyncio.create_task(later())
        await app.run()
    finally:
        await app.shutdown()   # already done by run() unless something failed before it: safe twice
        if agent is not None:
            await close_async_quietly(agent, "agent")
        if stt is not None:
            await close_async_quietly(stt, "speech-to-text")
        if warm is not None:
            warm.cancel()
            await asyncio.gather(warm, return_exceptions=True)
        if runner is not None:
            await runner.cleanup()
        if tts is not None:
            try:
                await tts.close()
            except Exception:
                log.exception("closing the voice failed")
    return app


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)   # exits 2 on unsafe flags, before anything is opened
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s", datefmt="%H:%M:%S")
    if args.robot == "real":
        log.warning("REAL ROBOT: only run this with someone at the robot (CLAUDE.md).")

    cal = None if args.no_vision else load_calibration(args.calibration)
    vision = None if args.no_vision else make_vision(args, cal)
    follow_factory = None
    if vision is not None:
        from app.skills.follow import FollowSkill

        config = make_follow_config(args, cal)
        follow_factory = lambda: FollowSkill(config)  # noqa: E731
        follow_factory.config = config  # type: ignore[attr-defined]  # api_state() applies the control page's settings

    window = render = None
    if args.window:
        window, render = make_window()

    link = make_link(args)
    try:
        asyncio.run(serve(args, link, vision=vision, follow_factory=follow_factory, window=window, render=render))
    except KeyboardInterrupt:
        pass
    finally:
        # serve() shuts down on every path it reaches; this is the backstop if the loop died first.
        if vision is not None:
            close_quietly(vision.stop, "vision")
        if window is not None:
            close_quietly(window.close, "window")


if __name__ == "__main__":
    main()
