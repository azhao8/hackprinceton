"""Search-and-approach skills (issue #55): find a person or a marked place, then drive up to it.

Search (shared): the robot turns in place in steps (~40 deg, so the ~67 deg camera view of each
stop overlaps the next), stops, waits for a frame taken AFTER it stopped (the camera lags ~0.2 s
and a turning picture is blurred), then asks a `found(perception)` predicate. One full circle
without a hit is a failure. Turning is `ctx.drive(0, +-w)`, re-sent every tick (the arbiter
drops a request older than 0.3 s), and each step is one of (issue #62):

- By heading, when `ctx.telemetry()` has a fresh numeric `yaw` (contract v1: degrees since `g`,
  + left; UDP sends it at 20 Hz, USB only when the firmware answers `J`, ~5 Hz): turn until the
  heading has changed by `step_deg` (slowing over the last `turn_slow_deg`, never below
  `turn_w_min`), or give up after `turn_timeout_x` times the timed duration. The circle is counted
  by the heading actually turned (coasting after the stop included): the search ends once the
  next stop would land within half a step of the start heading (8 x 40 deg = 9 stops, as timed),
  at most 2 x `max_stops` stops. A step that turned less than `min_turn_frac` of a step (yaw with
  the wrong sign, robot stuck) stops trusting yaw for the rest of the search. Yaw going stale
  mid-turn finishes that step by time.
- By time otherwise (no telemetry, no yaw, or a yaw that stopped updating): `step_deg / turn_w`
  seconds, `max_stops` stops. A step is approximate (a robot that turns slower than asked turns
  less); the next stop's view overlaps it anyway.

The mode is logged once per search, and again if it changes. "Fresh" = a NEW telemetry dict seen
within `yaw_fresh_s` (the dict has no timestamp, but the links build a new one per message).

- `FindPerson` ("find_person"): picks a person at a stop by saved look (PeopleRegistry), else by
  a description checked by a vision model on a crop (slow, so only a few candidates per stop,
  once each), else (no criteria) the widest person near the center. A failing description
  check (network/API error) counts as "no match"; if every check in a search failed, the skill
  says the vision service is unavailable instead of "not found". It then tracks that person
  frame to frame and asks vision to engage ON THEIR BOX (`request_engage(near=box)`, so a
  closer bystander can't steal the lock), turning first only if they are near the frame edge
  (`edge_margin`) so the lock doesn't lose them at once; it checks the lock landed on that
  person and approaches with the follow controller until it is within the stop distance for
  ~1 s. If the lock is lost on the way it searches again, starting toward the side the person
  was last seen.
- `GoTo` ("go_to"): a place is a printed ArUco marker (app/vision/places.py). Search for its id,
  then steer on the marker's x and drive until its distance (or size) says the stop distance.
  A marker gone for a moment -> hold; gone longer -> search again.

Time comes from an injectable `clock` and `sleep` (defaults: time.monotonic, asyncio.sleep), so
tests run a simulated world deterministically. Perception timestamps (`published_at`,
`frame.t`) are on the same clock as the worker's (time.monotonic).

Cancellation (the stop gesture, a new request, the e-stop): every skill withdraws its drive
request and disengages vision in `finally`, so no turn request is left running.

Directions follow REP 103: w > 0 turns LEFT; a target right of the picture center needs w < 0.
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, replace
from typing import Any, Generic, Protocol, TypeVar

import cv2
import numpy as np

from app.skills import SkillContext, SkillResult
from app.vision.follow import FollowConfig, FollowController
from app.vision.tracking import BodyParts, LockConfig, body_part_histograms
from app.vision.types import Box, DriveCommand, Marker, Person, TargetStatus

log = logging.getLogger(__name__)

Clock = Callable[[], float]
Sleep = Callable[[float], Awaitable[None]]
# Claude-vision description check (app/brain/vision_check.py `matches_description`):
# (jpeg crop, description) -> (matches, short reason). Slow, ~1-3 s.
Matcher = Callable[[bytes, str], Awaitable[tuple[bool, str]]]

T = TypeVar("T")


class Registry(Protocol):
    """What FindPerson uses of app.vision.people.PeopleRegistry."""

    def match(self, parts: BodyParts, name: str | None = None) -> tuple[str, float] | None: ...


@dataclass(frozen=True)
class SearchConfig:
    """Tunables of search and approach. GUESS = not tried on the robot yet."""

    # --- Turning in steps ---
    step_deg: float = 40.0  # GUESS: < the ~67 deg hfov guess (follow.py CameraGeometry), so views overlap
    turn_w: float = 0.5  # rad/s, follow.swift SEARCH_W (tuned for searching); a step takes ~1.4 s
    pause_s: float = 0.5  # GUESS: hold still this long at each stop (camera lag ~0.2 s + settling)
    frame_after_stop_s: float = 0.3  # GUESS: only trust frames stamped this long after the stop
    max_stops: int = 9  # 9 x 40 deg = one full circle (the start heading counts as the first stop)
    max_searches: int = 3  # GUESS: search again at most this many times after losing the target

    # --- Turning by heading (telemetry `yaw`), when it is fresh ---
    yaw_fresh_s: float = 0.5  # = app.link.FRESH_S: a new telemetry dict within this long counts as fresh
    turn_timeout_x: float = 2.0  # a heading step gives up after this many times its timed duration (~2.8 s)
    turn_slow_deg: float = 10.0  # GUESS: slow down over the last this many degrees (USB yaw comes at ~5 Hz)
    turn_w_min: float = 0.15  # GUESS: rad/s floor while slowing down (= center_w_min, the robot's deadband)
    turn_tol_deg: float = 1.0  # GUESS: this close to step_deg counts as there (no creeping at the floor rate)
    min_turn_frac: float = 0.5  # a heading step that turned less than this x step_deg: stop trusting yaw
    circle_deg: float = 360.0

    # --- Picking a person at a stop ---
    min_person_w: float = 0.06  # GUESS: narrower boxes are too far away (~7 m) to bother
    center_window: float = 0.3  # no criteria: only people with |cx - 0.5| <= this count
    max_checks_per_stop: int = 3  # GUESS: description checks (~1-3 s each) per stop, widest first

    # --- Engaging the lock on a chosen person ---
    # GUESS: |cx - 0.5| above this: turn toward them first, so the lock doesn't lose them at once
    edge_margin: float = 0.35
    center_k_w: float = 2.0  # GUESS: rad/s per unit offset while turning toward them (follow uses 2.5)
    center_w_max: float = 0.6  # GUESS
    center_w_min: float = 0.15  # GUESS: smallest turn that still moves the robot (its deadband)
    track_gate: float = 0.2  # frame-to-frame cx jump allowed while tracking the candidate
    track_lost_s: float = 1.0  # candidate unseen this long before the lock takes -> search again
    lock_timeout_s: float = 6.0  # GUESS: turning + engaging must finish in this time
    lock_min_iou: float = 0.4  # the locked box must overlap the candidate this much

    # --- Approach ---
    person_stop_m: float = 1.0  # GUESS: stop this far from a person
    marker_stop_m: float = 0.5  # GUESS: stop this far from a place's marker
    # Size fallback for markers without a distance: normalized side length at the stop distance.
    # GUESS: a 10 cm marker at 0.5 m with the 67 deg hfov guess: 0.1 / (2 * 0.5 * tan(33.5 deg)) = 0.15
    marker_stop_size: float = 0.15
    arrive_ratio: float = 0.1  # within 10 % of the stop distance (or closer) counts as there
    arrive_center: float = 0.15  # and |cx - 0.5| at most this
    settle_s: float = 1.0  # GUESS: there and stable this long -> success
    lost_resume_s: float = 2.0  # person lost this long during approach -> search again (= follow's search_for_s)
    marker_hold_s: float = 0.3  # marker unseen up to this long: keep going (a dropped detection)
    marker_lost_s: float = 2.0  # GUESS: unseen this long -> search again; between the two: hold still
    marker_v_max: float = 0.3  # GUESS: m/s cap when driving up to furniture
    marker_turn_first: float = 0.2  # |cx - 0.5| above this: turn only, don't drive
    approach_timeout_s: float = 30.0  # GUESS

    # --- Loop and vision health (same as FollowSkill) ---
    hz: float = 20.0  # control rate; re-sends the drive request every 0.05 s (< 0.25 s)
    stale_after_s: float = 0.5  # perception older than this: hold position
    vision_timeout_s: float = 15.0  # no fresh perception this long: fail


class SkillFailed(Exception):
    """Raised inside a skill to end it with SkillResult(False, detail)."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


def direction_of(hint: str | None) -> int:
    """+1 (turn left, w > 0) or -1 (right) from a hint like "left" / "right" (default left)."""
    return -1 if hint is not None and hint.strip().lower().startswith("r") else 1


def side_of(cx: float) -> int:
    """The turn direction toward image column cx: left of center -> +1 (turn left)."""
    return 1 if cx < 0.5 else -1


def crop_jpeg(image: np.ndarray, box: Box, pad: float = 0.05, quality: int = 85) -> bytes:
    """JPEG bytes of `box` (normalized, padded by `pad` of the frame) cut from a BGR image."""
    h, w = image.shape[:2]
    x1 = max(0, int((box.x1 - pad) * w))
    x2 = min(w, int(math.ceil((box.x2 + pad) * w)))
    y1 = max(0, int((box.y1 - pad) * h))
    y2 = min(h, int(math.ceil((box.y2 + pad) * h)))
    crop = image[y1:y2, x1:x2] if x2 > x1 and y2 > y1 else image
    ok, buf = cv2.imencode(".jpg", crop, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if not ok:
        raise ValueError("JPEG encoding failed")
    return buf.tobytes()


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


class _Timing:
    """Clock, sleep and the control period shared by the search and the skills."""

    def __init__(self, config: SearchConfig, clock: Clock, sleep: Sleep) -> None:
        self.config = config
        self.clock = clock
        self.sleep = sleep
        self.period_s = 1.0 / config.hz

    async def fresh(self, ctx: SkillContext) -> Any:
        """The newest perception once it is fresh; holds position (withdraws the request) while
        vision is stale and raises SkillFailed if it stays stale for `vision_timeout_s`."""
        cfg = self.config
        start = self.clock()
        while True:
            p = ctx.perception
            now = self.clock()
            if p is not None and now - p.published_at <= cfg.stale_after_s:
                return p
            ctx.stop()
            if now - start > cfg.vision_timeout_s:
                raise SkillFailed(f"vision stopped (no frame for {cfg.vision_timeout_s:.0f} s)")
            await self.sleep(self.period_s)


@dataclass(frozen=True)
class SearchOutcome(Generic[T]):
    found: T | None  # what `found()` returned, or None after a full circle
    perception: Any  # the perception it was found in (None if not found)
    stops: int  # stops checked


def wrap_deg(a: float) -> float:
    """An angle in degrees, wrapped into [-180, 180)."""
    return (a + 180.0) % 360.0 - 180.0


def _finite(x: Any) -> float | None:
    if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x):
        return None
    return float(x)


class HeadingWatch:
    """The robot's heading from telemetry `yaw` (degrees, + left), and whether it is fresh.

    Sample it every control tick with `observe()`. Telemetry dicts carry no timestamp, but every
    link builds a new dict per message (UdpLink per packet, SerialLink per line), so a dict is
    fresh while a NEW one was seen within `fresh_s`. A dict seen for the first time, or first seen
    after not looking for longer than `fresh_s`, has an unknown age: it only counts once the next
    one arrives. `heading` sums the wrapped differences between yaw samples, so it keeps counting
    past +-180 / 360 whether or not the source wraps (the firmware's yaw doesn't).
    """

    def __init__(self, telemetry: Callable[[], dict | None], clock: Clock, fresh_s: float) -> None:
        self._telemetry = telemetry
        self._clock = clock
        self._fresh_s = fresh_s
        self._tel: Any = None  # the dict last seen
        self._obs_at: float | None = None  # when observe() last looked
        self._new_at: float | None = None  # when a new dict with yaw was seen (None: age unknown / no yaw)
        self._yaw: float | None = None  # the raw yaw last seen
        self.heading: float | None = None  # unwrapped heading, degrees (None until a yaw was seen)
        self.has_yaw = False  # the newest dict has a numeric yaw (fresh or not)

    def gap(self) -> float:
        """Seconds since observe() last looked (inf if never)."""
        return math.inf if self._obs_at is None else self._clock() - self._obs_at

    def observe(self) -> float | None:
        """Look at the telemetry now: the unwrapped heading if it is fresh, else None."""
        now = self._clock()
        try:
            tel = self._telemetry()
        except Exception:
            tel = None
        if tel is not self._tel:
            age_known = self._obs_at is not None and now - self._obs_at <= self._fresh_s
            self._tel = tel
            yaw = _finite(tel.get("yaw")) if isinstance(tel, dict) else None
            self.has_yaw = yaw is not None
            if yaw is None:
                self._new_at = None
            else:
                self.heading = yaw if self._yaw is None or self.heading is None else self.heading + wrap_deg(yaw - self._yaw)
                self._yaw = yaw
                self._new_at = now if age_known else None
        self._obs_at = now
        return self.heading if self.fresh(now) else None

    def fresh(self, now: float | None = None) -> bool:
        now = self._clock() if now is None else now
        return self.has_yaw and self._new_at is not None and now - self._new_at <= self._fresh_s


class Search(_Timing):
    """Turn in steps (by heading when telemetry has a fresh yaw, else by time); at each stop
    check the newest post-stop frame with `found`."""

    def __init__(self, config: SearchConfig = SearchConfig(), *, clock: Clock = time.monotonic,
                 sleep: Sleep = asyncio.sleep) -> None:
        super().__init__(config, clock, sleep)
        self.stops = 0  # stops checked in the current/last run
        self.modes: list[str] = []  # how each step turned: "heading" or "time"
        self.turned_deg = 0.0  # the circle so far: measured by heading, or step_deg per timed step
        self._watch: HeadingWatch | None = None

    async def run(
        self,
        ctx: SkillContext,
        found: Callable[[Any], Awaitable[T | None]],
        direction: int = 1,
    ) -> SearchOutcome[T]:
        cfg = self.config
        step_s = math.radians(cfg.step_deg) / cfg.turn_w
        sign = 1 if direction >= 0 else -1
        self.stops = 0
        self.modes = []
        self.turned_deg = 0.0
        watch = self._watch = HeadingWatch(getattr(ctx, "telemetry", lambda: None), self.clock, cfg.yaw_fresh_s)
        trust_yaw = True  # until a heading step shows yaw doesn't follow the turn
        by_heading = False  # some step of this search turned by heading: count the circle by degrees
        logged: str | None = None
        while True:
            pending: tuple[str, float, float] | None = None  # a heading step: (outcome, seconds, start heading)
            if self.stops > 0:
                if not self._another_step(by_heading):
                    break
                mode = "heading" if trust_yaw and await self._yaw_ready(ctx) else "time"
                if mode != logged:
                    log.info("search: turning by %s", "heading (telemetry yaw)" if mode == "heading"
                             else "time (no fresh yaw in the telemetry)")
                    logged = mode
                self.modes.append(mode)
                if mode == "heading":
                    by_heading = True
                    y0 = watch.heading
                    assert y0 is not None
                    outcome, took_s = await self._turn_by_heading(ctx, sign, step_s, y0)
                    pending = (outcome, took_s, y0)
                else:
                    await self._turn(ctx, sign * cfg.turn_w, step_s)
                    self.turned_deg += cfg.step_deg
            stopped_at = await self._hold(ctx, cfg.pause_s)
            p = await self._frame_after(ctx, stopped_at + cfg.frame_after_stop_s)
            if pending is not None:  # measured after the hold, so coasting after the stop counts
                outcome, took_s, y0 = pending
                now_h = watch.heading if watch.heading is not None else y0
                turned = cfg.step_deg if outcome == "lost" else sign * (now_h - y0)
                if outcome != "lost" and turned < cfg.min_turn_frac * cfg.step_deg:
                    log.warning("search: yaw changed only %.0f deg in a %.1f s turn (robot stuck? yaw sign wrong?); "
                                "turning by time for the rest of this search", turned, took_s)
                    trust_yaw = False
                    turned = cfg.step_deg
                self.turned_deg += turned
            self.stops += 1
            ctx.drive(0.0, 0.0)
            hit = await found(p)
            if hit is not None:
                log.info("search: found at stop %d", self.stops)
                return SearchOutcome(hit, p, self.stops)
        return SearchOutcome(None, None, self.stops)

    def _another_step(self, by_heading: bool) -> bool:
        """Turn once more? Timed: `max_stops` stops. By heading: until the next stop would land
        within half a step of the start heading (its view is already covered), capped."""
        cfg = self.config
        if not by_heading:
            return self.stops < cfg.max_stops
        if self.stops >= 2 * cfg.max_stops:
            log.warning("search: %d stops but only %.0f deg turned; giving up the circle", self.stops, self.turned_deg)
            return False
        return self.turned_deg + cfg.step_deg <= cfg.circle_deg - cfg.step_deg / 2 + 1e-6

    async def _yaw_ready(self, ctx: SkillContext) -> bool:
        """Fresh yaw now? If the telemetry has a yaw whose age is unknown (nobody looked during a
        long `found()` check), hold still up to `yaw_fresh_s` for the next telemetry dict."""
        watch = self._watch
        assert watch is not None
        gap = watch.gap()
        if watch.observe() is not None:
            return True
        if not watch.has_yaw or gap <= self.config.yaw_fresh_s:
            return False  # no yaw, or watched all along and it stopped updating
        start = self.clock()
        while self.clock() - start < self.config.yaw_fresh_s - 1e-9:
            ctx.drive(0.0, 0.0)
            await self.sleep(self.period_s)
            if watch.observe() is not None:
                return True
        return False

    async def _turn_by_heading(self, ctx: SkillContext, sign: int, step_s: float, y0: float) -> tuple[str, float]:
        """Turn until the heading is `step_deg` past `y0`. Returns (outcome, seconds turning):
        "done", "timeout", or "lost" (yaw went stale mid-turn: the step was finished by time)."""
        cfg = self.config
        watch = self._watch
        assert watch is not None
        timeout_s = cfg.turn_timeout_x * step_s
        w_min = min(cfg.turn_w_min, cfg.turn_w)
        start = self.clock()
        while True:
            elapsed = self.clock() - start
            heading = watch.observe()
            if heading is None:
                log.warning("search: yaw stopped updating mid-turn; finishing this step by time")
                await self._turn(ctx, sign * cfg.turn_w, step_s - elapsed)
                return "lost", max(elapsed, step_s)
            left_deg = cfg.step_deg - sign * (heading - y0)
            if left_deg <= cfg.turn_tol_deg:
                outcome = "done"
                break
            if elapsed >= timeout_s - 1e-9:
                log.info("search: heading step timed out after %.1f s (%.0f of %.0f deg)",
                         elapsed, cfg.step_deg - left_deg, cfg.step_deg)
                outcome = "timeout"
                break
            w = cfg.turn_w
            if cfg.turn_slow_deg > 0:
                w = _clamp(cfg.turn_w * left_deg / cfg.turn_slow_deg, w_min, cfg.turn_w)
            ctx.drive(0.0, sign * w)
            await self.sleep(min(self.period_s, timeout_s - elapsed))
        ctx.drive(0.0, 0.0)
        return outcome, self.clock() - start

    def _observe(self) -> None:
        if self._watch is not None:
            self._watch.observe()

    async def _turn(self, ctx: SkillContext, w: float, duration_s: float) -> None:
        start = self.clock()
        while (left := duration_s - (self.clock() - start)) > 1e-9:
            self._observe()
            ctx.drive(0.0, w)
            await self.sleep(min(self.period_s, left))
        ctx.drive(0.0, 0.0)

    async def _hold(self, ctx: SkillContext, duration_s: float) -> float:
        stopped_at = self.clock()
        while self.clock() - stopped_at < duration_s - 1e-9:
            self._observe()
            ctx.drive(0.0, 0.0)
            await self.sleep(self.period_s)
        return stopped_at

    async def _frame_after(self, ctx: SkillContext, t: float) -> Any:
        """The newest fresh perception whose frame was taken at or after `t` (holding still)."""
        start = self.clock()
        while True:
            self._observe()
            p = ctx.perception
            now = self.clock()
            if p is not None and now - p.published_at <= self.config.stale_after_s and p.frame_t >= t - 1e-9:
                return p
            ctx.drive(0.0, 0.0)
            if now - start > self.config.vision_timeout_s:
                raise SkillFailed(f"vision stopped (no frame for {self.config.vision_timeout_s:.0f} s)")
            await self.sleep(self.period_s)


# ---------------------------------------------------------------------------
# FindPerson
# ---------------------------------------------------------------------------


class FindPerson(_Timing):
    """Find a person (by saved look, description, or just the nearest) and stop in front of them."""

    name = "find_person"

    def __init__(
        self,
        name: str | None = None,
        description: str | None = None,
        registry: Registry | None = None,
        matcher: Matcher | None = None,
        config: SearchConfig = SearchConfig(),
        *,
        hint: str | None = None,
        follow_config: FollowConfig | None = None,
        lock_config: LockConfig = LockConfig(),
        clock: Clock = time.monotonic,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        super().__init__(config, clock, sleep)
        self.person = name.strip() if name and name.strip() else None  # NOT self.name: that's the skill's name
        self.description = description.strip() if description and description.strip() else None
        self.registry = registry
        self.matcher = matcher
        self.hint = hint
        self.follow_config = follow_config or replace(FollowConfig(), d_target_m=config.person_stop_m)
        self.lock_config = lock_config
        self.search = Search(config, clock=clock, sleep=sleep)
        # Debug / test view of the last run
        self.searches = 0  # search runs (1 + times it searched again after losing the person)
        self.stops_total = 0
        self.found_by: str | None = None  # "look", "description" or "nearest"
        self.matcher_calls = 0
        self.matcher_failures = 0
        self.saved_look = False
        self.last_command: DriveCommand | None = None
        self._seen = 0
        self._checks_ok = 0  # description checks that answered, in the current search
        self._checks_failed = 0  # ...and that raised
        self._last_p: Any = None

    @property
    def who(self) -> str:
        if self.person:
            return self.person
        if self.description:
            return f"the person ({self.description})"
        return "someone"

    async def run(self, ctx: SkillContext) -> SkillResult:
        vision = ctx.vision
        if vision is None:
            return SkillResult(False, "no vision: the server runs without a camera")
        problem = self._cannot_identify()
        if problem:
            return SkillResult(False, problem)
        cfg = self.config
        direction = direction_of(self.hint)
        self.searches = self.stops_total = self.matcher_calls = self.matcher_failures = self._seen = 0
        self.saved_look = False
        try:
            while self.searches < cfg.max_searches:
                self.searches += 1
                self._checks_ok = self._checks_failed = 0
                outcome = await self.search.run(ctx, self._check, direction)
                self.stops_total += outcome.stops
                if outcome.found is None:
                    if self._checks_failed and not self._checks_ok:
                        return SkillResult(False, "couldn't check descriptions (vision service unavailable)")
                    return SkillResult(
                        False, f"{self.who} not found after a full turn; saw {self._seen} people in {outcome.stops} stops"
                    )
                cand: Person = outcome.found
                direction = side_of(cand.box.cx)
                if not await self._lock_on(ctx, cand):
                    vision.disengage()
                    continue
                result, last_cx = await self._approach(ctx)
                if result is not None:
                    if result.ok:
                        self._maybe_save_look()
                    return result
                log.info("find_person: lost %s during approach, searching again", self.who)
                vision.disengage()
                direction = side_of(last_cx)
            return SkillResult(False, f"kept losing {self.who} ({cfg.max_searches} searches); giving up")
        except SkillFailed as e:
            return SkillResult(False, e.detail)
        finally:
            ctx.stop()
            vision.disengage()

    def _cannot_identify(self) -> str | None:
        """Why this request can't work at all (checked before moving), or None."""
        if self.description and self.matcher is None and not (self.person and self.registry is not None):
            return "can't check descriptions: no vision matcher is set up"
        if self.person and not self.description:
            if self.registry is None:
                return f"I don't know what {self.person} looks like: describe them or save their look first"
            try:
                known = self.person in self.registry  # type: ignore[operator]
            except TypeError:  # a registry without __contains__: just search
                known = True
            if not known:
                return f"I don't know what {self.person} looks like: describe them or save their look first"
        return None

    # --- picking a candidate at a stop ---

    async def _check(self, p: Any) -> Person | None:
        cfg = self.config
        people = [
            q for q in p.people if q.score >= self.lock_config.min_det_score and q.box.w >= cfg.min_person_w
        ]
        self._seen += len(people)
        if not people:
            return None
        widest_first = sorted(people, key=lambda q: -q.box.w)

        if self.person and self.registry is not None:
            for q in widest_first:
                parts = body_part_histograms(p.frame.image, q, p.people, self.lock_config)
                if parts is not None and self.registry.match(parts, self.person) is not None:
                    self.found_by = "look"
                    return q

        if self.description and self.matcher is not None:
            # One frame per stop, each candidate checked once: the verdicts are this stop's cache.
            failed_here = False
            for q in widest_first[: cfg.max_checks_per_stop]:
                self.matcher_calls += 1
                try:
                    ok, why = await self.matcher(crop_jpeg(p.frame.image, q.box), self.description)
                except Exception as e:  # network / API failure: treat as "no match", keep searching
                    self.matcher_failures += 1
                    self._checks_failed += 1
                    if not failed_here:  # log once per stop
                        log.warning("find_person: description check failed (%s: %s)", type(e).__name__, e)
                    failed_here = True
                    continue
                self._checks_ok += 1
                log.info("find_person: description check %s: %s", "yes" if ok else "no", why)
                if ok:
                    self.found_by = "description"
                    return q
            return None

        if self.person or self.description:
            return None
        near = [q for q in widest_first if abs(q.box.cx - 0.5) <= cfg.center_window]
        if near:
            self.found_by = "nearest"
            return near[0]
        return None

    # --- centering the candidate and locking onto them ---

    def _track(self, people: Iterable[Person], prev: Box) -> Person | None:
        """The person in this frame that continues `prev` (nearest cx, similar width)."""
        best: Person | None = None
        for q in people:
            ratio = q.box.w / max(prev.w, 1e-6)
            if abs(q.box.cx - prev.cx) > self.config.track_gate or not 0.5 <= ratio <= 2.0:
                continue
            if best is None or abs(q.box.cx - prev.cx) < abs(best.box.cx - prev.cx):
                best = q
        return best

    async def _lock_on(self, ctx: SkillContext, cand: Person) -> bool:
        """Track the candidate frame to frame, engage the lock on their box, check it locked THEM.

        The engage request carries the candidate's box (`request_engage(near=box)`), so the
        lock takes this person even with a wider one nearer the center. The robot turns first
        only while the candidate is within `edge_margin` of a frame edge. While the engage is
        pending it is re-sent with the newest tracked box, since the worker applies the box
        to later frames. The locked box must still overlap the candidate (`lock_min_iou`)."""
        cfg = self.config
        vision = ctx.vision
        assert vision is not None
        track = cand.box
        start = last_seen = self.clock()
        last_index: int | None = None
        seq: int | None = None
        while True:
            now = self.clock()
            if now - start > cfg.lock_timeout_s:
                log.info("find_person: couldn't lock onto %s in %.0f s", self.who, cfg.lock_timeout_s)
                return False
            p = await self.fresh(ctx)
            new_frame = p.frame_index != last_index
            if new_frame:
                last_index = p.frame_index
                q = self._track(p.people, track)
                if q is not None:
                    track, last_seen = q.box, now
                elif now - last_seen > cfg.track_lost_s:
                    return False
            if seq is not None:
                st = p.target
                if p.engaged_seq >= seq and st.status is TargetStatus.LOCKED and st.person is not None:
                    ctx.drive(0.0, 0.0)
                    if st.person.box.iou(track) >= cfg.lock_min_iou:
                        return True
                    log.info("find_person: the lock took someone else; searching again")
                    return False
            off = track.cx - 0.5
            if abs(off) > cfg.edge_margin:  # near the edge: turn toward them before engaging
                w = _clamp(-cfg.center_k_w * off, -cfg.center_w_max, cfg.center_w_max)
                ctx.drive(0.0, math.copysign(max(abs(w), cfg.center_w_min), w))
            else:
                ctx.drive(0.0, 0.0)
                if seq is None or (new_frame and p.engaged_seq < seq):
                    seq = vision.request_engage(near=track)  # (re)send with the newest box
            await self.sleep(self.period_s)

    # --- approach with the follow controller ---

    async def _approach(self, ctx: SkillContext) -> tuple[SkillResult | None, float]:
        """(result, last seen cx). result None = lost the person: search again."""
        cfg = self.config
        controller = FollowController(self.follow_config)
        start = self.clock()
        arrived_since: float | None = None
        last_index: int | None = None
        last_cx = 0.5
        cmd = DriveCommand(0.0, 0.0, "approaching")
        while True:
            now = self.clock()
            if now - start > cfg.approach_timeout_s:
                return SkillResult(False, f"couldn't reach {self.who} in {cfg.approach_timeout_s:.0f} s"), last_cx
            p = await self.fresh(ctx)
            st = p.target
            if st.status is TargetStatus.IDLE:
                return SkillResult(False, "the lock was released"), last_cx
            if p.frame_index != last_index:
                last_index = p.frame_index
                cmd = controller.update(st, p.frame_t)
                self.last_command = cmd
                if st.status is TargetStatus.LOCKED and st.person is not None:
                    self._last_p = p
                    box = st.person.box
                    last_cx = box.cx
                    cues, _ = controller.range_cues(st.person)
                    nearest = min(cues, key=lambda c: c.ratio)
                    there = nearest.ratio <= cfg.arrive_ratio and abs(box.cx - 0.5) <= cfg.arrive_center
                    arrived_since = (arrived_since if arrived_since is not None else now) if there else None
                    if arrived_since is not None and now - arrived_since >= cfg.settle_s:
                        d = nearest.distance_m
                        if d is None:  # the box cue: width ~ 1/distance
                            d = self.follow_config.d_target_m * (1.0 + nearest.ratio)
                        return SkillResult(True, f"found {self.who} at ~{d:.1f} m"), last_cx
                else:
                    arrived_since = None
                    last_cx = st.last_seen_cx
                    if st.lost_for_s >= cfg.lost_resume_s or "gave up" in cmd.reason:
                        return None, last_cx
            ctx.drive(cmd.v, cmd.w)  # every tick, so the arbiter never sees it as stale
            await self.sleep(self.period_s)

    def _maybe_save_look(self) -> None:
        """Found by description with a name: save the look so next time is instant."""
        if self.found_by != "description" or not self.person or self.registry is None:
            return
        save = getattr(self.registry, "save", None)
        p = self._last_p
        if save is None or p is None or p.target.person is None:
            return
        parts = body_part_histograms(p.frame.image, p.target.person, p.people, self.lock_config)
        if parts is None:
            return
        try:
            save(self.person, parts)
            self.saved_look = True
        except Exception:
            log.exception("find_person: saving %s's look failed", self.person)


# ---------------------------------------------------------------------------
# GoTo
# ---------------------------------------------------------------------------


def _default_places() -> tuple[Callable[[str], int | None], list[str]]:
    from app.vision import places

    return places.marker_for, sorted(places.places())


class GoTo(_Timing):
    """Go to a named place: find its printed marker, drive up to it and stop."""

    name = "go_to"

    def __init__(
        self,
        place: str,
        config: SearchConfig = SearchConfig(),
        *,
        hint: str | None = None,
        marker_for: Callable[[str], int | None] | None = None,
        known_places: Iterable[str] | None = None,
        follow_config: FollowConfig = FollowConfig(),
        clock: Clock = time.monotonic,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        super().__init__(config, clock, sleep)
        self.place = place
        self.hint = hint
        self._marker_for = marker_for
        self._known = None if known_places is None else list(known_places)
        self.follow_config = follow_config  # turn gains (k_w, dead_x, w_max) and speed law (k_v, dead_ratio)
        self.search = Search(config, clock=clock, sleep=sleep)
        self.marker_id: int | None = None
        self.searches = 0
        self._seen_ids: set[int] = set()

    async def run(self, ctx: SkillContext) -> SkillResult:
        lookup, known = self._marker_for, self._known
        if lookup is None or known is None:
            default_lookup, default_known = _default_places()
            lookup = lookup or default_lookup
            known = default_known if known is None else known
        self.marker_id = lookup(self.place)
        if self.marker_id is None:
            return SkillResult(False, f"I don't know a place called '{self.place}'; known places: {', '.join(known) or 'none'}")
        vision = ctx.vision
        if vision is None:
            return SkillResult(False, "no vision: the server runs without a camera")
        cfg = self.config
        direction = direction_of(self.hint)
        self.searches = 0
        self._seen_ids = set()
        try:
            while self.searches < cfg.max_searches:
                self.searches += 1
                outcome = await self.search.run(ctx, self._check, direction)
                if outcome.found is None:
                    seen = sorted(self._seen_ids)
                    return SkillResult(
                        False,
                        f"the {self.place} (marker {self.marker_id}) not found after a full turn; "
                        f"saw markers {seen if seen else 'none'}",
                    )
                result, last_cx = await self._approach(ctx, outcome.found)
                if result is not None:
                    return result
                direction = side_of(last_cx)
            return SkillResult(False, f"kept losing the {self.place} marker ({cfg.max_searches} searches); giving up")
        except SkillFailed as e:
            return SkillResult(False, e.detail)
        finally:
            ctx.stop()

    def _marker(self, p: Any) -> Marker | None:
        for m in getattr(p, "markers", ()):
            if m.id == self.marker_id:
                return m
        return None

    async def _check(self, p: Any) -> Marker | None:
        self._seen_ids.update(m.id for m in getattr(p, "markers", ()))
        return self._marker(p)

    def _ratio(self, m: Marker) -> float:
        """How many times too far: d / d_stop - 1 (< 0 = closer than the stop distance)."""
        cfg = self.config
        if m.distance_m is not None:
            return m.distance_m / cfg.marker_stop_m - 1.0
        return cfg.marker_stop_size / max(m.size, 1e-3) - 1.0  # size ~ 1/distance

    async def _approach(self, ctx: SkillContext, first: Marker) -> tuple[SkillResult | None, float]:
        cfg, fc = self.config, self.follow_config
        start = last_seen = self.clock()
        last_cx = first.cx
        arrived_since: float | None = None
        last_index: int | None = None
        last_t: float | None = None
        v = w = 0.0
        v_cmd = w_cmd = 0.0
        while True:
            now = self.clock()
            if now - start > cfg.approach_timeout_s:
                return SkillResult(False, f"couldn't reach the {self.place} in {cfg.approach_timeout_s:.0f} s"), last_cx
            p = await self.fresh(ctx)
            if p.frame_index != last_index:
                last_index = p.frame_index
                dt = fc.smooth_ref_dt_s if last_t is None or p.frame_t <= last_t else p.frame_t - last_t
                last_t = p.frame_t
                m = self._marker(p)
                if m is None:
                    arrived_since = None
                    unseen = now - last_seen
                    if unseen > cfg.marker_lost_s:
                        return None, last_cx
                    if unseen > cfg.marker_hold_s:
                        v_cmd = w_cmd = v = w = 0.0  # hold still (immediate, not smoothed)
                else:
                    last_seen, last_cx = now, m.cx
                    ratio = self._ratio(m)
                    off = m.cx - 0.5
                    w_cmd = 0.0 if abs(off) < fc.dead_x else _clamp(-fc.k_w * off, -fc.w_max, fc.w_max)
                    v_cmd = 0.0 if ratio < fc.dead_ratio else _clamp(fc.k_v * ratio, 0.0, cfg.marker_v_max)
                    if abs(off) > cfg.marker_turn_first:
                        v_cmd = 0.0
                    there = ratio <= cfg.arrive_ratio and abs(off) <= cfg.arrive_center
                    arrived_since = (arrived_since if arrived_since is not None else now) if there else None
                    if arrived_since is not None and now - arrived_since >= cfg.settle_s:
                        d = m.distance_m if m.distance_m is not None else cfg.marker_stop_m * (1.0 + ratio)
                        return SkillResult(True, f"at the {self.place} ({d:.1f} m)"), last_cx
                keep = fc.smooth_keep ** (dt / fc.smooth_ref_dt_s)
                v = keep * v + (1.0 - keep) * v_cmd
                w = keep * w + (1.0 - keep) * w_cmd
            ctx.drive(v, w)
            await self.sleep(self.period_s)
