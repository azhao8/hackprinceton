"""Run the mock robot on UDP, like the real one: `uv run python -m mock`.

It listens on 127.0.0.1:4210 (the robot's port), takes the same messages as the firmware, and
sends 20 Hz telemetry to whoever sent the last packet. Point the server or
`firmware/balance/linktest.py --udp 127.0.0.1` at it.

Type into its terminal to act out the robot's surroundings (#79), then Enter:
`u` someone holds it upright, `d` lay it down, `b 27` its gyro zero is off by 27 deg/s (`b 0` fixes it;
so does the firmware's recalibrate, c), `f` it falls over while balancing (#88: motors cut, lying down).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time

from mock.robot import MockRobot

STEP_HZ = 100
TEL_HZ = 20


class MockServer(asyncio.DatagramProtocol):
    def __init__(self, robot: MockRobot, verbose: bool = True):
        self.robot = robot
        self.verbose = verbose
        self.peer: tuple[str, int] | None = None
        self.transport: asyncio.DatagramTransport | None = None

    def connection_made(self, transport):  # type: ignore[override]
        self.transport = transport

    def datagram_received(self, data: bytes, addr):  # type: ignore[override]
        self.peer = addr
        self.robot.handle_packet(data, time.monotonic())

    def send_telemetry(self) -> None:
        if self.transport and self.peer:
            self.transport.sendto(json.dumps(self.robot.telemetry(), separators=(",", ":")).encode(), self.peer)

    def flush_log(self) -> None:
        while self.robot.log:
            line = self.robot.log.pop(0)
            if self.verbose:
                print(f"[mock] {line}", flush=True)


async def serve(host: str, port: int, verbose: bool = True, ready: asyncio.Event | None = None,
                armed: bool = False, held: bool = False, gyro_bias: float = 0.0) -> None:
    robot = MockRobot(held=held, gyro_bias=gyro_bias)
    if armed:
        robot.handle_char("g", time.monotonic())   # as if someone pressed g while holding it
    loop = asyncio.get_running_loop()
    transport, server = await loop.create_datagram_endpoint(lambda: MockServer(robot, verbose), local_addr=(host, port))
    if verbose:
        print(f"[mock] robot listening on {host}:{port} (UDP). Send g to start balancing.", flush=True)
        print("[mock] type u (held upright), d (laid down), f (falls over) or b 27 (gyro bias, deg/s), then Enter", flush=True)
    try:
        fd = sys.stdin.fileno()

        def typed() -> None:   # every line that arrived, not just the first (no buffered reads)
            data = os.read(fd, 4096)
            if not data:
                loop.remove_reader(fd)   # stdin closed
                return
            for line in data.decode(errors="ignore").splitlines():
                act(robot, line)

        loop.add_reader(fd, typed)
    except (NotImplementedError, OSError, ValueError):
        pass   # no terminal (tests, a pipe): the hooks just aren't there
    if ready:
        ready.set()
    try:
        tick, last = 0, time.monotonic()
        while True:
            await asyncio.sleep(1 / STEP_HZ)
            now = time.monotonic()
            robot.step(now - last, now)
            last = now
            tick += 1
            if tick % (STEP_HZ // TEL_HZ) == 0:
                server.send_telemetry()
            server.flush_log()
    finally:
        transport.close()


def act(robot: MockRobot, line: str) -> None:
    """A line typed into the mock's terminal (see the module docstring)."""
    words = line.split()
    if not words:
        return
    if words[0] == "u":
        robot.held = True
        print("[mock] someone holds it upright", flush=True)
    elif words[0] == "d":
        robot.held = False
        print("[mock] laid down", flush=True)
    elif words[0] == "f":
        robot.fall()
        print("[mock] fell over", flush=True)
    elif words[0] == "b":
        try:
            robot.gyro_bias = float(words[1]) if len(words) > 1 else 0.0
        except ValueError:
            return
        print(f"[mock] gyro bias {robot.gyro_bias:+.1f} deg/s", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser(prog="python -m mock", description="Mock robot (contract v1, UDP)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=4210)
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--armed", action="store_true", help="start already balancing, as if someone pressed g")
    ap.add_argument("--held", action="store_true", help="someone holds it upright (Start balances at once)")
    ap.add_argument("--gyro-bias", type=float, default=0.0, help="deg/s: a drifting tilt sensor (c clears it)")
    args = ap.parse_args()
    try:
        asyncio.run(serve(args.host, args.port, verbose=not args.quiet, armed=args.armed, held=args.held,
                          gyro_bias=args.gyro_bias))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
