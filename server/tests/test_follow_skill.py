"""FollowSkill against a fake vision worker: drives through the arbiter, cancels, fails cleanly."""

from __future__ import annotations

import asyncio
import time

import numpy as np

from app.arbiter import Arbiter, Command
from app.skills import SkillContext, SkillResult, SkillRunner
from app.skills.follow import FollowSkill
from app.vision.follow import WAITING_REASON, FollowConfig
from app.vision.tracking import TargetLock
from app.vision.types import Box, Detections, DriveCommand, Frame, Person, TargetState, TargetStatus
from app.vision.worker import Perception
from tests.vision.test_tracking import BLUE, RED, Walker, render

RIGHT_OF_CENTER = Person(box=Box(0.6, 0.2, 0.9, 0.95), score=0.9)  # w < 0 to face them
IMAGE = np.zeros((4, 4, 3), np.uint8)


class FakeVision:
    """Every latest() is a fresh frame. `mode`: "ok" locks on request, "nobody" never does,
    "lost" locks then reports the target lost for `lost_for` seconds, "frozen" stops publishing."""

    def __init__(self, mode: str = "ok", lost_for: float = 0.0) -> None:
        self.mode = mode
        self.lost_for = lost_for
        self.seq = 0
        self.engaged_seq = 0
        self.disengaged = 0
        self.index = 0
        self._frozen: Perception | None = None

    def request_engage(self) -> int:
        self.seq += 1
        if self.mode != "nobody":
            self.engaged_seq = self.seq
        return self.seq

    def disengage(self) -> None:
        self.disengaged += 1
        self.engaged_seq = 0

    def latest(self) -> Perception | None:
        if self.mode == "frozen" and self._frozen is not None:
            return self._frozen
        now = time.monotonic()
        self.index += 1
        if self.engaged_seq == 0:
            state = TargetState(TargetStatus.IDLE)
        elif self.mode == "lost":
            state = TargetState(TargetStatus.LOST, lost_for_s=self.lost_for, last_seen_cx=0.8)
        else:
            state = TargetState(TargetStatus.LOCKED, person=RIGHT_OF_CENTER)
        frame = Frame(t=now, index=self.index, image=IMAGE)
        dets = Detections(now, self.index, 4, 4, [RIGHT_OF_CENTER])
        p = Perception(frame, dets, state, self.seq > self.engaged_seq, self.engaged_seq, 0.0, 20.0, now)
        if self.mode == "frozen":
            self._frozen = p
        return p


def test_follow_drives_through_the_arbiter_and_cancels_cleanly():
    async def scenario():
        arb, vision = Arbiter(), FakeVision()
        runner = SkillRunner(SkillContext(arb, vision))
        skill = FollowSkill(FollowConfig(turn_only=True))
        task = runner.start(skill)
        await asyncio.sleep(0.3)
        cmd = arb.decide()
        assert cmd.source == "skill"
        assert cmd.w < 0 and cmd.v == 0.0  # turns right toward the person; turn-only never drives
        assert skill.last_command is not None and skill.last_command.reason == "following"

        runner.cancel()
        assert await task == SkillResult(False, "cancelled")
        assert arb.decide().source == "none"  # the robot request is gone
        assert vision.disengaged == 1

    asyncio.run(scenario())


def test_estop_wins_over_follow():
    async def scenario():
        arb = Arbiter()
        runner = SkillRunner(SkillContext(arb, FakeVision()))
        runner.start(FollowSkill())
        await asyncio.sleep(0.2)
        arb.estop(True)
        assert arb.decide().source == "estop"
        runner.cancel()

    asyncio.run(scenario())


def test_fails_when_nobody_is_locked():
    async def scenario():
        arb, vision = Arbiter(), FakeVision("nobody")
        runner = SkillRunner(SkillContext(arb, vision))
        result = await runner.start(FollowSkill(engage_timeout_s=0.2))
        assert not result.ok and "nobody" in result.detail
        assert arb.decide().source == "none"
        assert vision.disengaged == 1  # the pending engage is withdrawn

    asyncio.run(scenario())


# Fast timings for the wait tests: coast 0.05 s, search until 0.3 s, then wait.
FAST = FollowConfig(coast_s=0.05, search_for_s=0.3)


class ScriptedVision(FakeVision):
    """Locked on the person (right of center) until `leave_at` seconds after the engage, then
    LOST (last seen on the right) until `back_at` (None = never), then LOCKED again, with
    `reacquired=True` on the first frame back. Times are wall-clock seconds."""

    def __init__(self, leave_at: float, back_at: float | None = None) -> None:
        super().__init__("ok")
        self.leave_at, self.back_at = leave_at, back_at
        self.engaged_at: float | None = None
        self._was_lost = False

    def request_engage(self) -> int:
        self.engaged_at = time.monotonic()
        return super().request_engage()

    def latest(self) -> Perception | None:
        now = time.monotonic()
        self.index += 1
        el = now - (self.engaged_at or now)
        if self.engaged_seq == 0:
            state = TargetState(TargetStatus.IDLE)
        elif self.leave_at <= el and (self.back_at is None or el < self.back_at):
            state = TargetState(TargetStatus.LOST, lost_for_s=el - self.leave_at, last_seen_cx=0.75)
            self._was_lost = True
        else:
            state = TargetState(TargetStatus.LOCKED, person=RIGHT_OF_CENTER, last_seen_cx=0.75,
                                reacquired=self._was_lost)
            self._was_lost = False
        frame = Frame(t=now, index=self.index, image=IMAGE)
        dets = Detections(now, self.index, 4, 4, [])
        return Perception(frame, dets, state, False, self.engaged_seq, 0.0, 20.0, now)


async def _watch(arb: Arbiter, skill: FollowSkill, seconds: float) -> list:
    """(arbiter command, follow reason) every 20 ms for `seconds`."""
    out = []
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        reason = skill.last_command.reason if skill.last_command is not None else None
        out.append((arb.decide(), reason))
        await asyncio.sleep(0.02)
    return out


def test_losing_the_person_never_ends_follow_it_searches_then_waits_in_place():
    async def scenario():
        arb, vision = Arbiter(), ScriptedVision(leave_at=0.2)
        runner = SkillRunner(SkillContext(arb, vision))
        skill = FollowSkill(FAST)
        task = runner.start(skill)
        await asyncio.sleep(0.2 + 0.1)
        searching = await _watch(arb, skill, 0.12)  # lost 0.1-0.22 s: past the coast, searching right
        assert any(r == "lost: searching right" for _, r in searching)
        for cmd, r in searching:
            if r == "lost: searching right":
                assert cmd.source == "skill" and cmd.v == 0.0 and cmd.w < 0
        await asyncio.sleep(0.2)
        waiting = await _watch(arb, skill, 1.5)  # many times longer than the old give-up
        assert not task.done()
        assert runner.running == "follow"
        for cmd, r in waiting:
            assert r == WAITING_REASON
            assert (cmd.source, cmd.v, cmd.w) == ("skill", 0.0, 0.0)  # holds position, request kept
        assert vision.disengaged == 0  # vision stays engaged on the same look
        runner.cancel()
        assert await task == SkillResult(False, "cancelled")

    asyncio.run(scenario())


def test_follow_resumes_when_the_same_person_is_reacquired():
    async def scenario():
        arb, vision = Arbiter(), ScriptedVision(leave_at=0.1, back_at=1.0)
        runner = SkillRunner(SkillContext(arb, vision))
        skill = FollowSkill(FAST)
        task = runner.start(skill)
        await asyncio.sleep(0.8)
        assert skill.last_command.reason == WAITING_REASON
        await asyncio.sleep(0.5)  # back since ~0.3 s
        cmd = arb.decide()
        assert skill.last_command.reason == "following"
        assert cmd.source == "skill" and cmd.w < 0  # turning toward them again (right of center)
        assert not task.done() and vision.disengaged == 0
        runner.cancel()
        assert (await task).detail == "cancelled"

    asyncio.run(scenario())


def test_follow_off_ends_it_while_waiting():
    async def scenario():
        arb, vision = Arbiter(), ScriptedVision(leave_at=0.05)
        runner = SkillRunner(SkillContext(arb, vision))
        skill = FollowSkill(FAST)
        task = runner.start(skill)
        await asyncio.sleep(0.6)
        assert skill.last_command.reason == WAITING_REASON
        runner.cancel()  # Follow off, "stop", the F key: all cancel the task
        assert await task == SkillResult(False, "cancelled")
        assert arb.decide().source == "none"
        assert vision.disengaged == 1

    asyncio.run(scenario())


def test_estop_wins_while_waiting_and_after_the_person_comes_back():
    async def scenario():
        arb = Arbiter()
        runner = SkillRunner(SkillContext(arb, ScriptedVision(leave_at=0.05, back_at=0.6)))
        skill = FollowSkill(FAST)
        task = runner.start(skill)
        await asyncio.sleep(0.45)
        assert skill.last_command.reason == WAITING_REASON
        arb.estop(True)
        assert arb.decide() == Command(0.0, 0.0, "estop")
        await asyncio.sleep(0.4)  # they came back: the skill follows, the e-stop still wins
        assert skill.last_command.reason == "following"
        assert arb.decide() == Command(0.0, 0.0, "estop")
        runner.cancel()
        await task

    asyncio.run(scenario())


def test_lost_guard_never_drives_while_lost_whatever_the_controller_says():
    skill = FollowSkill(FAST)
    drive = DriveCommand(0.3, -0.5, "lost: something new")
    coasting = TargetState(TargetStatus.LOST, lost_for_s=0.01, last_seen_cx=0.8)
    searching = TargetState(TargetStatus.LOST, lost_for_s=0.1, last_seen_cx=0.8)
    waiting = TargetState(TargetStatus.LOST, lost_for_s=10.0, last_seen_cx=0.8)
    assert skill._lost_guard(drive, coasting) == drive  # the short coast lets the speed die out
    assert (skill._lost_guard(drive, searching).v, skill._lost_guard(drive, searching).w) == (0.0, -0.5)
    assert skill._lost_guard(drive, waiting) == DriveCommand(0.0, 0.0, WAITING_REASON)
    locked = TargetState(TargetStatus.LOCKED, person=RIGHT_OF_CENTER)
    assert skill._lost_guard(drive, locked) == drive


def test_stale_vision_holds_then_fails():
    async def scenario():
        arb = Arbiter()
        runner = SkillRunner(SkillContext(arb, FakeVision("frozen")))
        task = runner.start(FollowSkill(stale_after_s=0.1, vision_timeout_s=0.4))
        await asyncio.sleep(0.25)
        assert arb.decide().source == "none"  # no new frames: withdraw, the robot holds position
        result = await asyncio.wait_for(task, 2.0)
        assert not result.ok and "vision" in result.detail

    asyncio.run(scenario())


def test_without_vision_it_fails_at_once():
    async def scenario():
        runner = SkillRunner(SkillContext(Arbiter()))
        result = await runner.start(FollowSkill())
        assert not result.ok

    asyncio.run(scenario())


class LockVision(FakeVision):
    """The real target lock (app/vision/tracking.py) on synthetic frames (tests/vision/test_tracking.py):
    each latest() is the next frame of `scene(index) -> walkers` at 30 fps of frame time. It logs, per
    frame, the lock's state and what the skill and the arbiter were doing just before that frame."""

    def __init__(self, scene, skill: FollowSkill, arb: Arbiter) -> None:
        super().__init__("ok")
        self.scene, self.skill, self.arb = scene, skill, arb
        self.lock = TargetLock()
        self.engage_pending = False
        self.log: list[tuple[int, TargetState, str | None, Command]] = []

    def request_engage(self) -> int:
        self.seq += 1
        self.engage_pending = True
        return self.seq

    def latest(self) -> Perception | None:
        self.index += 1
        dets, image = render(self.index, self.scene(self.index))
        if self.engage_pending:
            state = self.lock.engage(dets, image)
            if state.status is not TargetStatus.IDLE:
                self.engage_pending, self.engaged_seq = False, self.seq
        else:
            state = self.lock.update(dets, image)
        prev = self.skill.last_command.reason if self.skill.last_command is not None else None
        self.log.append((self.index, state, prev, self.arb.decide()))
        frame = Frame(t=dets.frame_t, index=self.index, image=image)
        return Perception(frame, dets, state, self.engage_pending, self.engaged_seq, 0.0, 30.0, time.monotonic())


def test_only_the_same_clothes_bring_follow_back_with_the_real_lock():
    me = Walker(0.5, BLUE)
    stranger = Walker(0.5, RED)  # same shirt, red trousers, right where I left
    back = Walker(0.7, BLUE)  # me again, off to the right

    def scene(i: int) -> list:
        if i <= 20:
            return [me]
        if i <= 110:
            return []  # 3 s gone: search, then wait
        if i <= 200:
            return [stranger]  # 3 s of a stranger in front
        return [back]

    async def scenario():
        arb = Arbiter()
        skill = FollowSkill(hz=200)  # default timings; one frame per tick keeps the test quick
        vision = LockVision(scene, skill, arb)
        runner = SkillRunner(SkillContext(arb, vision))
        task = runner.start(skill)
        while vision.index < 240 and not task.done():
            await asyncio.sleep(0.01)
        assert not task.done(), task.result()
        runner.cancel()
        await task

        by = {i: (st, reason, cmd) for i, st, reason, cmd in vision.log}
        assert by[20][0].status is TargetStatus.LOCKED
        assert by[110][1] == WAITING_REASON  # waiting before the stranger shows up
        for i in range(111, 202):  # the stranger: never locked, never driven toward
            st, reason, cmd = by[i]
            assert st.status is TargetStatus.LOST, i
            assert reason == WAITING_REASON, i
            assert (cmd.v, cmd.w) == (0.0, 0.0), i
        first = next(i for i in range(201, 240) if by[i][0].status is TargetStatus.LOCKED)
        assert by[first][0].reacquired and by[first][0].person.box == back.box
        assert all(by[i][0].status is TargetStatus.LOCKED for i in range(first, 240))
        _, reason, cmd = by[239]
        assert reason == "following" and cmd.source == "skill" and cmd.w < 0  # turning toward me again

    asyncio.run(scenario())
