"""Start the server: `uv run python -m app --robot mock`.

For now it runs the arbiter in one asyncio loop (open question T-7) and prints what it would send
to the robot once a second. The robot link (UDP to the mock or the real robot) comes with the
contract; the API, vision and agent plug into the same loop as their lanes land.
"""

from __future__ import annotations

import argparse
import asyncio
import logging

from app.arbiter import Arbiter
from app.skills import SkillContext, SkillRunner

SEND_HZ = 20
log = logging.getLogger("app")


async def run(robot: str) -> None:
    arbiter = Arbiter()
    skills = SkillRunner(SkillContext(arbiter))  # noqa: F841  (the agent will start skills here)
    log.info("server up, robot=%s; the robot link isn't built yet, so commands are only logged", robot)
    tick = 0
    while True:
        cmd = arbiter.decide()
        if tick % SEND_HZ == 0:
            log.info("would send v=%.2f w=%.2f (from %s)", cmd.v, cmd.w, cmd.source)
        tick += 1
        await asyncio.sleep(1 / SEND_HZ)


def main() -> None:
    ap = argparse.ArgumentParser(prog="python -m app", description="Miguel.exe server")
    ap.add_argument("--robot", choices=["mock", "real"], default="mock",
                    help="mock: the mock robot on this laptop (default); real: the robot over Wi-Fi")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s", datefmt="%H:%M:%S")
    if args.robot == "real":
        raise SystemExit("--robot real needs the robot link, which isn't built yet (it comes with the contract).")
    try:
        asyncio.run(run(args.robot))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
