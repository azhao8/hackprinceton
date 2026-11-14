"""FollowSkill against a fake vision worker: drives through the arbiter, cancels, fails cleanly."""

from __future__ import annotations

import asyncio
import time

import numpy as np

from app.arbiter import Arbiter
from app.skills import SkillContext, SkillResult, SkillRunner
from app.skills.follow import FollowSkill
from app.vision.follow import FollowConfig
from app.vision.types import Box, Detections, Frame, Person, TargetState, TargetStatus
from app.vision.worker import Perception

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


def test_fails_when_the_person_is_lost_for_good():
    async def scenario():
        arb = Arbiter()
        cfg = FollowConfig(search_for_s=2.0)
        runner = SkillRunner(SkillContext(arb, FakeVision("lost", lost_for=3.0)))
        result = await asyncio.wait_for(runner.start(FollowSkill(cfg)), 2.0)
        assert not result.ok and "lost" in result.detail
        assert arb.decide().source == "none"

    asyncio.run(scenario())


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
