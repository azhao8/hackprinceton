"""FindPerson / GoTo against a simulated room: the robot turns and drives by what the arbiter
decides, the fake camera sees people and markers from the robot's pose, and a fake lock engages
like TargetLock (the person overlapping the requested box, else the widest person near the
center). Time is simulated: `World.sleep` advances it."""

from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass

import cv2
import numpy as np
import pytest

from app.arbiter import Arbiter
from app.skills import SkillContext
from app.skills.search import FindPerson, GoTo
from app.vision.tracking import BodyParts, LockConfig, body_part_histograms, parts_distance
from app.vision.types import Box, Detections, Frame, Marker, Person, TargetState, TargetStatus

HFOV_DEG = 67.0
TAN_HALF = math.tan(math.radians(HFOV_DEG / 2))
FPS = 20.0
IMG_H, IMG_W = 90, 160
BOX_W_AT_1M = 0.45  # = FollowConfig.target_box_w, so the box cue reads the true distance
MARKER_SIDE_M = 0.1
COLORS = {"red": (0, 0, 220), "blue": (220, 60, 0), "green": (0, 170, 0), "yellow": (0, 210, 230)}


@dataclass
class Body:
    name: str
    x: float
    y: float
    color: str


@dataclass
class Tag:
    id: int
    x: float
    y: float


def at(bearing_deg: float, dist: float) -> tuple[float, float]:
    a = math.radians(bearing_deg)
    return dist * math.cos(a), dist * math.sin(a)


@dataclass
class FakePerception:
    """Duck-types app.vision.worker.Perception (plus `markers`)."""

    frame: Frame
    detections: Detections
    target: TargetState
    engage_pending: bool
    engaged_seq: int
    published_at: float
    markers: tuple[Marker, ...] = ()

    @property
    def frame_t(self) -> float:
        return self.frame.t

    @property
    def frame_index(self) -> int:
        return self.frame.index

    @property
    def people(self) -> list[Person]:
        return self.detections.people


@dataclass
class Sample:
    t: float
    v: float
    w: float
    source: str


class World:
    """The room, the robot's pose (driven by the arbiter's decisions) and simulated time."""

    def __init__(self, bodies: list[Body] = (), tags: list[Tag] = ()) -> None:  # type: ignore[assignment]
        self.t = 0.0
        self.arb = Arbiter(clock=self.now)
        self.bodies = list(bodies)
        self.tags = list(tags)
        self.rx = self.ry = self.th = 0.0
        self.samples: list[Sample] = []
        self.on_advance = None  # optional hook(world), called every simulation step

    def now(self) -> float:
        return self.t

    async def sleep(self, dt: float) -> None:
        self.advance(max(0.0, dt))
        await asyncio.sleep(0)

    def advance(self, dt: float) -> None:
        steps = max(1, math.ceil(dt / 0.01 - 1e-9))
        h = dt / steps
        for _ in range(steps):
            cmd = self.arb.decide()
            self.th += cmd.w * h
            self.rx += cmd.v * h * math.cos(self.th)
            self.ry += cmd.v * h * math.sin(self.th)
            self.t += h
            self.samples.append(Sample(self.t, cmd.v, cmd.w, cmd.source))
            if self.on_advance is not None:
                self.on_advance(self)

    def dist(self, x: float, y: float) -> float:
        return math.hypot(x - self.rx, y - self.ry)

    def heading_deg(self) -> float:
        return math.degrees(self.th)

    def view(self, x: float, y: float) -> tuple[float, float] | None:
        """(image cx, distance) of a world point, or None if it is out of view."""
        dx, dy = x - self.rx, y - self.ry
        fwd = dx * math.cos(self.th) + dy * math.sin(self.th)
        left = -dx * math.sin(self.th) + dy * math.cos(self.th)
        if fwd <= 0.05:
            return None
        u = (left / fwd) / TAN_HALF  # -1..1, + left
        if abs(u) > 1.0:
            return None
        return 0.5 - u / 2, math.hypot(dx, dy)


def person_box(cx: float, dist: float) -> Box:
    w = BOX_W_AT_1M / dist
    return Box(max(0.0, cx - w / 2), 0.05, min(1.0, cx + w / 2), 0.95)


def paint(image: np.ndarray, box: Box, color: str) -> None:
    x1, x2 = int(box.x1 * IMG_W), int(math.ceil(box.x2 * IMG_W))
    y1, y2 = int(box.y1 * IMG_H), int(math.ceil(box.y2 * IMG_H))
    image[y1:y2, x1:x2] = COLORS[color]


class FakeVision:
    """The camera + detector + lock. One frame every 1/FPS of simulated time."""

    def __init__(self, world: World, lock_config: LockConfig = LockConfig()) -> None:
        self.world = world
        self.cfg = lock_config
        self.seq = 0
        self.pending: int | None = None
        self.pending_near: Box | None = None
        self.engage_requests: list[Box | None] = []
        self.engaged_seq = 0
        self.locked: Body | None = None
        self.last_seen_t = 0.0
        self.last_seen_cx = 0.5
        self.disengaged = 0
        self.frames = 0
        self._index = -1
        self._p: FakePerception | None = None

    def request_engage(self, near: Box | None = None) -> int:
        self.seq += 1
        self.pending, self.pending_near = self.seq, near
        self.engage_requests.append(near)
        return self.seq

    def disengage(self) -> None:
        self.disengaged += 1
        self.seq += 1
        self.pending = None
        self.locked = None

    def latest(self) -> FakePerception:
        index = int(self.world.t * FPS + 1e-9)
        if index != self._index:
            self._index = index
            self._p = self._render(index, index / FPS)
        assert self._p is not None
        return self._p

    def _render(self, index: int, t: float) -> FakePerception:
        self.frames += 1
        w = self.world
        image = np.full((IMG_H, IMG_W, 3), 128, np.uint8)
        seen: list[tuple[float, Body, Person]] = []
        for b in w.bodies:
            v = w.view(b.x, b.y)
            if v is not None:
                seen.append((v[1], b, Person(person_box(v[0], v[1]), 0.9)))
        seen.sort(key=lambda s: -s[0])  # far first, so near people paint over them
        for _, b, q in seen:
            paint(image, q.box, b.color)
        people = [q for _, _, q in seen]

        markers = []
        for tag in w.tags:
            v = w.view(tag.x, tag.y)
            if v is not None:
                markers.append(Marker(tag.id, v[0], 0.5, MARKER_SIDE_M / (2 * v[1] * TAN_HALF), v[1]))

        if self.pending is not None:
            if self.pending_near is not None:  # like TargetLock.engage(near=...): best IoU
                box = self.pending_near
                near = [s for s in seen if s[2].box.iou(box) >= self.cfg.engage_min_iou]
                pick = max(near, key=lambda s: s[2].box.iou(box)) if near else None
            else:
                near = [s for s in seen if abs(s[2].box.cx - 0.5) <= self.cfg.engage_max_offset
                        and s[2].box.w >= self.cfg.engage_min_w]
                pick = max(near, key=lambda s: s[2].box.w) if near else None
            if pick is not None:
                self.locked = pick[1]
                self.engaged_seq, self.pending = self.pending, None

        if self.locked is None:
            target = TargetState(TargetStatus.IDLE)
        else:
            mine = [q for _, b, q in seen if b is self.locked]
            if mine:
                self.last_seen_t, self.last_seen_cx = t, mine[0].box.cx
                target = TargetState(TargetStatus.LOCKED, person=mine[0], last_seen_cx=mine[0].box.cx)
            else:
                target = TargetState(TargetStatus.LOST, lost_for_s=t - self.last_seen_t, last_seen_cx=self.last_seen_cx)

        frame = Frame(t=t, index=index, image=image)
        dets = Detections(t, index, IMG_W, IMG_H, people)
        return FakePerception(frame, dets, target, self.pending is not None, self.engaged_seq, t, tuple(markers))


def look_of(color: str) -> BodyParts:
    image = np.full((IMG_H, IMG_W, 3), 128, np.uint8)
    q = Person(person_box(0.5, 1.5), 0.9)
    paint(image, q.box, color)
    parts = body_part_histograms(image, q)
    assert parts is not None
    return parts


class FakeRegistry:
    def __init__(self, looks: dict[str, BodyParts] | None = None) -> None:
        self.looks = {k.lower(): v for k, v in (looks or {}).items()}
        self.match_calls = 0
        self.saved: list[str] = []

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and name.lower() in self.looks

    def match(self, parts: BodyParts, name: str | None = None) -> tuple[str, float] | None:
        self.match_calls += 1
        look = self.looks.get((name or "").lower())
        d = None if look is None else parts_distance(look, parts)
        return (name or "", d) if d is not None and d <= 0.4 else None

    def save(self, name: str, parts: BodyParts) -> None:
        self.saved.append(name)
        self.looks[name.lower()] = parts


class FakeMatcher:
    """'Claude vision': says yes when the crop's dominant color is named in the description."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def __call__(self, jpeg: bytes, description: str) -> tuple[bool, str]:
        crop = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
        h, w = crop.shape[:2]
        mean = crop[h // 4: 3 * h // 4, w // 4: 3 * w // 4].reshape(-1, 3).mean(axis=0)
        color = min(COLORS, key=lambda c: float(np.linalg.norm(mean - np.array(COLORS[c]))))
        self.calls.append(color)
        await asyncio.sleep(0)
        return color in description, f"wearing {color}"


def setup(bodies=(), tags=()) -> tuple[World, FakeVision, SkillContext]:
    world = World(list(bodies), list(tags))
    vision = FakeVision(world)
    return world, vision, SkillContext(world.arb, vision)


def sim(world: World) -> dict:
    return {"clock": world.now, "sleep": world.sleep}


def run(coro, timeout: float = 30.0):
    async def main():
        return await asyncio.wait_for(coro, timeout)

    return asyncio.run(main())


def turn_segments(world: World) -> list[float]:
    """Angles (deg) turned in each run of consecutive non-zero-w samples."""
    segments, current, prev_t = [], 0.0, 0.0
    for s in world.samples:
        if s.w != 0.0:
            current += math.degrees(s.w * (s.t - prev_t))
        elif current:
            segments.append(current)
            current = 0.0
        prev_t = s.t
    if current:
        segments.append(current)
    return segments


# ---------------------------------------------------------------------------


def test_search_turns_in_steps_and_gives_up_after_one_circle():
    world, vision, ctx = setup()
    skill = FindPerson(**sim(world))
    result = run(skill.run(ctx))

    assert not result.ok
    assert "not found after a full turn" in result.detail and "9 stops" in result.detail
    segments = turn_segments(world)
    assert len(segments) == 8  # 9 stops: the start heading + 8 steps
    assert all(s == pytest.approx(40.0, abs=1.0) for s in segments)
    assert world.heading_deg() == pytest.approx(320.0, abs=3.0)
    # The request never went stale while searching (re-sent every tick), and it's withdrawn at the end.
    assert all(s.source == "skill" for s in world.samples)
    assert world.arb.decide().source == "none"


def test_finds_a_person_by_saved_look_on_the_third_stop_and_stops_at_1m():
    alice = Body("Alice", *at(0, 2.0), "red")
    bob = Body("Bob", *at(80, 3.0), "blue")
    world, vision, ctx = setup([alice, bob])
    registry = FakeRegistry({"bob": look_of("blue")})
    skill = FindPerson("Bob", registry=registry, **sim(world))

    result = run(skill.run(ctx))

    assert result.ok, result.detail
    assert skill.search.stops == 3 and skill.found_by == "look"
    assert result.detail.startswith("found Bob at ~1.")
    assert world.dist(bob.x, bob.y) == pytest.approx(1.05, abs=0.1)
    assert vision.locked is None and vision.disengaged >= 1  # released at the end
    assert world.arb.decide().source == "none"


def test_finds_by_description_checking_only_candidates_and_saves_the_look():
    alice = Body("Alice", *at(0, 2.0), "red")
    bob = Body("Bob", *at(80, 3.0), "blue")
    world, vision, ctx = setup([alice, bob])
    registry, matcher = FakeRegistry(), FakeMatcher()
    skill = FindPerson("Bob", "a man in a blue shirt", registry=registry, matcher=matcher, **sim(world))

    result = run(skill.run(ctx))

    assert result.ok, result.detail
    assert skill.found_by == "description"
    assert matcher.calls == ["red", "blue"]  # Alice at stop 1, Bob at stop 3: once per candidate
    assert vision.frames > 50  # ...out of many frames
    assert registry.saved == ["Bob"] and skill.saved_look  # next time is instant


def test_without_criteria_picks_the_closest_centered_person():
    alice = Body("Alice", *at(0, 2.5), "red")
    carl = Body("Carl", *at(10, 1.6), "green")
    dan = Body("Dan", *at(-28, 1.2), "yellow")  # closest, but at the picture's edge
    world, vision, ctx = setup([alice, carl, dan])
    skill = FindPerson(**sim(world))

    result = run(skill.run(ctx))

    assert result.ok, result.detail
    assert skill.found_by == "nearest" and skill.search.stops == 1
    assert world.dist(carl.x, carl.y) == pytest.approx(1.05, abs=0.1)


def test_closer_bystander_next_to_the_target_does_not_steal_the_lock():
    # Bob is picked by his look; Carl stands beside him, closer (wider) and also near the
    # center, partly in front of him. An engage without a box would take Carl.
    bob = Body("Bob", *at(-5, 2.0), "blue")
    carl = Body("Carl", *at(12, 1.5), "red")
    world, vision, ctx = setup([bob, carl])
    skill = FindPerson("Bob", registry=FakeRegistry({"bob": look_of("blue")}), **sim(world))
    locked: list[str] = []
    world.on_advance = lambda w: vision.locked is not None and locked.append(vision.locked.name)

    result = run(skill.run(ctx))

    assert result.ok, result.detail
    assert skill.found_by == "look" and skill.searches == 1 and skill.search.stops == 1
    assert set(locked) == {"Bob"}  # never locked Carl, not even for a moment
    assert vision.engage_requests and all(b is not None for b in vision.engage_requests)
    assert world.dist(bob.x, bob.y) == pytest.approx(1.05, abs=0.1)


def test_candidate_at_the_frame_edge_gets_a_short_turn_before_the_lock():
    bob = Body("Bob", *at(30, 2.0), "blue")  # cx ~0.07: too close to the edge to engage at once
    world, vision, ctx = setup([bob])
    skill = FindPerson("Bob", registry=FakeRegistry({"bob": look_of("blue")}), **sim(world))
    heading_at_engage: list[float] = []
    world.on_advance = lambda w: (
        not heading_at_engage and vision.engage_requests and heading_at_engage.append(w.heading_deg())
    )

    result = run(skill.run(ctx))

    assert result.ok, result.detail
    assert skill.search.stops == 1
    # Turned left only until Bob was inside the edge margin (|cx - 0.5| <= 0.35), not to the center.
    assert 0.0 < heading_at_engage[0] < 15.0
    assert world.dist(bob.x, bob.y) == pytest.approx(1.05, abs=0.1)


class FailingMatcher:
    """'Claude vision' that is down: every check raises."""

    def __init__(self) -> None:
        self.calls = 0

    async def __call__(self, jpeg: bytes, description: str) -> tuple[bool, str]:
        self.calls += 1
        await asyncio.sleep(0)
        raise ConnectionError("API unreachable")


def test_failing_description_checks_report_the_vision_service_not_not_found():
    world, vision, ctx = setup([Body("Alice", *at(0, 2.0), "red"), Body("Bob", *at(80, 3.0), "blue")])
    matcher = FailingMatcher()
    skill = FindPerson(description="a man in a blue shirt", matcher=matcher, **sim(world))

    result = run(skill.run(ctx))

    assert not result.ok
    assert result.detail == "couldn't check descriptions (vision service unavailable)"
    assert matcher.calls == skill.matcher_failures >= 2  # kept searching after the first failure
    assert world.arb.decide().source == "none"


def test_a_failed_description_check_is_a_no_match_and_the_search_goes_on():
    alice = Body("Alice", *at(0, 2.0), "red")
    bob = Body("Bob", *at(80, 3.0), "blue")
    world, vision, ctx = setup([alice, bob])
    inner = FakeMatcher()

    async def flaky(jpeg: bytes, description: str) -> tuple[bool, str]:
        if not inner.calls:  # the first check (Alice, stop 1) fails
            inner.calls.append("error")
            raise ConnectionError("timeout")
        return await inner(jpeg, description)

    skill = FindPerson(description="a man in a blue shirt", matcher=flaky, **sim(world))

    result = run(skill.run(ctx))

    assert result.ok, result.detail
    assert skill.found_by == "description" and skill.matcher_failures == 1
    assert inner.calls == ["error", "blue"]


def test_approach_stops_at_the_stop_distance_without_overshooting():
    bob = Body("Bob", *at(0, 3.0), "blue")
    world, vision, ctx = setup([bob])
    closest = [99.0]
    world.on_advance = lambda w: closest.__setitem__(0, min(closest[0], w.dist(bob.x, bob.y)))
    skill = FindPerson(**sim(world))

    result = run(skill.run(ctx))

    assert result.ok and result.detail.startswith("found someone at ~1.")
    assert world.dist(bob.x, bob.y) == pytest.approx(1.05, abs=0.1)
    assert closest[0] > 0.9


def test_lost_during_approach_searches_again_from_there():
    bob = Body("Bob", *at(0, 3.5), "blue")
    world, vision, ctx = setup([bob])
    moved = [False]

    def walk_away(w: World) -> None:
        # When the robot gets within 2.5 m, Bob steps out of view to the robot's right.
        if not moved[0] and w.dist(bob.x, bob.y) < 2.5:
            moved[0] = True
            a = w.th - math.radians(80)
            bob.x, bob.y = w.rx + 2.5 * math.cos(a), w.ry + 2.5 * math.sin(a)

    world.on_advance = walk_away
    skill = FindPerson("Bob", registry=FakeRegistry({"bob": look_of("blue")}), **sim(world))

    result = run(skill.run(ctx))

    assert moved[0]
    assert result.ok, result.detail
    assert skill.searches == 2  # searched again after losing him
    assert skill.search.stops == 3  # lost near the center -> searched right: -40, -80 deg
    assert world.dist(bob.x, bob.y) == pytest.approx(1.05, abs=0.1)


def test_go_to_unknown_place_fails_fast():
    world, vision, ctx = setup()
    skill = GoTo("garage", marker_for={"station": 1, "couch": 2}.get, known_places=["station", "couch"], **sim(world))

    result = run(skill.run(ctx))

    assert not result.ok
    assert "garage" in result.detail and "station, couch" in result.detail
    assert world.samples == [] and vision.frames == 0  # never moved or looked


def test_go_to_finds_the_marker_and_stops_at_its_distance():
    station = Tag(1, *at(-100, 3.0))
    couch = Tag(2, *at(0, 2.0))  # another marker in view first: not the one we want
    world, vision, ctx = setup(tags=[station, couch])
    skill = GoTo("station", hint="right", marker_for={"station": 1, "couch": 2}.get, known_places=["station", "couch"],
                 **sim(world))

    result = run(skill.run(ctx))

    assert result.ok, result.detail
    assert skill.search.stops == 3  # 0, -40, -80 deg: the station is at -100 deg, in view from -80
    assert result.detail.startswith("at the station (0.5")
    assert world.dist(station.x, station.y) == pytest.approx(0.53, abs=0.05)
    assert world.arb.decide().source == "none"


def test_go_to_reports_the_markers_it_saw_when_the_place_isnt_there():
    world, vision, ctx = setup(tags=[Tag(2, *at(0, 2.0))])
    skill = GoTo("station", marker_for={"station": 1}.get, known_places=["station"], **sim(world))

    result = run(skill.run(ctx))

    assert not result.ok and "not found after a full turn" in result.detail and "[2]" in result.detail


def test_cancelling_stops_the_robot_and_releases_vision():
    async def scenario():
        world, vision, ctx = setup()
        task = asyncio.create_task(FindPerson(**sim(world)).run(ctx))
        while world.t < 1.0:  # the first stop takes 0.5 s, then it turns for ~1.4 s
            await asyncio.sleep(0)
        assert world.arb.decide().w > 0  # mid-turn
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert world.arb.decide().source == "none"
        assert vision.disengaged >= 1

    asyncio.run(scenario())


def test_without_vision_fails_at_once():
    world = World()
    result = run(FindPerson().run(SkillContext(world.arb)))
    assert not result.ok and "no vision" in result.detail


def test_unknown_name_without_description_fails_before_moving():
    world, vision, ctx = setup([Body("Bob", *at(0, 2.0), "blue")])
    result = run(FindPerson("Zed", registry=FakeRegistry({"bob": look_of("blue")}), **sim(world)).run(ctx))
    assert not result.ok and "Zed" in result.detail and world.samples == []
