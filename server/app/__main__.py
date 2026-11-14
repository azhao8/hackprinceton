"""Start the server: `uv run python -m app --robot mock` (or `--robot real`).

One asyncio loop (open question T-7). About 20 times a second the arbiter's decision goes to the
robot link. The API, vision and agent plug into the same loop as their lanes land.

`--test-drive` runs a short pattern through the arbiter (forward, turn left, stop) so you can
see the server move the robot without a dashboard. The server never starts balancing by itself:
someone presses g (on the real robot, while holding it upright), then the commands take effect.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os

from app.arbiter import Arbiter, Source
from app.link import PORT, RobotLink, UdpLink
from app.skills import SkillContext, SkillResult, SkillRunner

SEND_HZ = 20
log = logging.getLogger("app")


class TestDrive:
    """Forward 2 s, turn left 2 s, stop. Uses the skill path, so e-stop and joystick win."""

    name = "test_drive"

    async def run(self, ctx: SkillContext) -> SkillResult:
        for v, w, seconds in ((0.15, 0.0, 2.0), (0.0, 0.6, 2.0)):
            for _ in range(int(seconds * SEND_HZ)):
                ctx.drive(v, w)
                await asyncio.sleep(1 / SEND_HZ)
        return SkillResult(True, "test drive done")


async def drive_loop(arbiter: Arbiter, link: RobotLink, stop: asyncio.Event | None = None) -> None:
    """Send the arbiter's decision to the robot, SEND_HZ times a second."""
    was_estopped = False
    tick = 0
    while not (stop and stop.is_set()):
        cmd = arbiter.decide()
        if arbiter.estopped and not was_estopped:
            link.send_letter("5")          # cancel any 90-degree turn or 50 cm move in progress
        was_estopped = arbiter.estopped
        link.send_cmd(cmd.v, cmd.w, "drive")   # drive 0,0 holds position without cancelling L/R/F/B
        if tick % SEND_HZ == 0:
            h = link.health()
            tel = link.telemetry or {}
            log.info("send v=%.2f w=%.2f (%s) | robot %s pitch=%s x=%s yaw=%s | link %s%s",
                     cmd.v, cmd.w, cmd.source, tel.get("state", "?"), tel.get("pitch", "?"),
                     tel.get("x", "?"), tel.get("yaw", "?"), "ok" if h.ok else "DOWN",
                     f" lag {h.lag_ms:.0f} ms" if h.lag_ms is not None else "")
        tick += 1
        await asyncio.sleep(1 / SEND_HZ)


async def run(robot: str, host: str | None, test_drive: bool) -> None:
    arbiter = Arbiter()
    skills = SkillRunner(SkillContext(arbiter))
    default = "127.0.0.1" if robot == "mock" else os.environ.get("ROBOT_HOST", "balancebot.local")
    link = UdpLink(host or default, PORT)
    await link.start()
    if test_drive:
        log.info("test drive in 3 s (forward 2 s, turn left 2 s). The robot only moves if it's balancing (g).")

        async def later():
            await asyncio.sleep(3)
            result = await skills.start(TestDrive())
            log.info("test drive: %s", result.detail)

        asyncio.create_task(later())
    try:
        await drive_loop(arbiter, link)
    finally:
        await link.close()


def main() -> None:
    ap = argparse.ArgumentParser(prog="python -m app", description="Miguel.exe server")
    ap.add_argument("--robot", choices=["mock", "real"], default="mock",
                    help="mock: the mock robot on this laptop (default); real: the robot over Wi-Fi")
    ap.add_argument("--host", help="robot address (default: 127.0.0.1 for mock; $ROBOT_HOST or balancebot.local for real)")
    ap.add_argument("--test-drive", action="store_true", help="drive forward, then turn, through the arbiter")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    if args.robot == "real":
        log.warning("REAL ROBOT: only run this with someone at the robot (CLAUDE.md).")
    try:
        asyncio.run(run(args.robot, args.host, args.test_drive))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
