"""Follow skill: lock onto the person in front and keep them at a set distance.

On start it asks vision to engage (lock onto the close person nearest the center), then runs
the follow controller (app/vision/follow.py) on each new frame and requests the result from
the arbiter with `ctx.drive(v, w)` about 20 times a second. E-stop and the joystick win in
the arbiter; cancelling the task (the F key, the stop gesture, the agent, the e-stop) stops it.

It fails (returns `SkillResult(False, ...)`) when:
- nobody is locked within `engage_timeout_s` of the first frame;
- the person stays lost until the controller gives up searching;
- vision stops delivering frames for `vision_timeout_s`;
- someone else disengaged the lock.

While vision is stale (no new result for `stale_after_s`) it withdraws its request, so the
robot holds position instead of acting on an old picture.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable

from app.skills import SkillContext, SkillResult
from app.vision.follow import FollowConfig, FollowController
from app.vision.types import DriveCommand, TargetState, TargetStatus

log = logging.getLogger(__name__)


class FollowSkill:
    name = "follow"

    def __init__(
        self,
        config: FollowConfig = FollowConfig(),
        *,
        hz: float = 20.0,
        engage_timeout_s: float = 4.0,
        stale_after_s: float = 0.5,
        vision_timeout_s: float = 15.0,  # covers opening the camera and the ~7.5 s detector warm-up
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.config = config
        self.controller = FollowController(config)
        self.period_s = 1.0 / hz
        self.engage_timeout_s = engage_timeout_s
        self.stale_after_s = stale_after_s
        self.vision_timeout_s = vision_timeout_s
        self._clock = clock
        self.last_command: DriveCommand | None = None  # what the controller last asked for (debug view)

    async def run(self, ctx: SkillContext) -> SkillResult:
        vision = ctx.vision
        if vision is None:
            return SkillResult(False, "no vision: the server runs without a camera")
        self.controller.reset()
        self.last_command = None
        seq = vision.request_engage()
        started = self._clock()
        first_fresh: float | None = None  # when vision first delivered after the request
        last_fresh = started
        engaged = False
        last_index: int | None = None
        cmd = DriveCommand(0.0, 0.0, "waiting for vision")
        try:
            while True:
                now = self._clock()
                p = ctx.perception
                fresh = p is not None and now - p.published_at <= self.stale_after_s

                if not fresh:
                    ctx.stop()
                    self.last_command = DriveCommand(0.0, 0.0, "vision stale: holding")
                    if now - last_fresh > self.vision_timeout_s:
                        return SkillResult(False, f"vision stopped (no frame for {self.vision_timeout_s:.0f} s)")
                    await asyncio.sleep(self.period_s)
                    continue

                assert p is not None
                last_fresh = now
                first_fresh = now if first_fresh is None else first_fresh
                state = p.target

                if not engaged:
                    if p.engaged_seq >= seq and state.status is not TargetStatus.IDLE:
                        engaged = True
                        log.info("follow: locked on")
                    elif now - first_fresh > self.engage_timeout_s:
                        return SkillResult(False, "nobody to follow: stand 1-2 m in front of the robot, centered")
                    else:
                        ctx.stop()
                        self.last_command = DriveCommand(0.0, 0.0, "engaging")

                if engaged:
                    if state.status is TargetStatus.IDLE:
                        return SkillResult(False, "the lock was released")
                    if p.frame_index != last_index:  # the controller runs once per frame
                        last_index = p.frame_index
                        cmd = self.controller.update(state, p.frame_t)
                        self.last_command = cmd
                        if self._gave_up(cmd, state):
                            return SkillResult(False, "lost the person and gave up searching")
                    ctx.drive(cmd.v, cmd.w)  # every tick, so the arbiter never sees it as stale

                await asyncio.sleep(self.period_s)
        finally:
            # The runner withdraws our arbiter request (and only if no newer skill replaced us).
            vision.disengage()

    def _gave_up(self, cmd: DriveCommand, state: TargetState) -> bool:
        if "gave up" in cmd.reason:
            return True
        cfg = self.config
        # Backstop in case the controller's wording changes: lost longer than its search lasts.
        limit = getattr(cfg, "lost_hold_s", 0.0) + getattr(cfg, "search_for_s", 5.0)
        return state.status is TargetStatus.LOST and state.lost_for_s >= limit
