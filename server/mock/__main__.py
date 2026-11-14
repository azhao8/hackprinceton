"""Run the mock robot on UDP, like the real one: `uv run python -m mock`.

It listens on 127.0.0.1:4210 (the robot's port), takes the same messages as the firmware, and
sends 20 Hz telemetry to whoever sent the last packet. Point the server or
`firmware/balance/linktest.py --udp 127.0.0.1` at it.
"""

from __future__ import annotations

import argparse
import asyncio
import json
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


async def serve(host: str, port: int, verbose: bool = True, ready: asyncio.Event | None = None) -> None:
    robot = MockRobot()
    loop = asyncio.get_running_loop()
    transport, server = await loop.create_datagram_endpoint(lambda: MockServer(robot, verbose), local_addr=(host, port))
    if verbose:
        print(f"[mock] robot listening on {host}:{port} (UDP). Send g to start balancing.", flush=True)
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


def main() -> None:
    ap = argparse.ArgumentParser(prog="python -m mock", description="Mock robot (contract v1, UDP)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=4210)
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()
    try:
        asyncio.run(serve(args.host, args.port, verbose=not args.quiet))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
