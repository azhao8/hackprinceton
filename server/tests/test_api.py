"""The API: the phone page's endpoints, the control page and the dashboard WebSocket.
The last test runs the whole path: phone page -> API -> arbiter -> UDP link -> mock robot."""

import asyncio
import socket

from aiohttp.test_utils import TestClient, TestServer

from app.__main__ import drive_loop
from app.api import ApiState, create_app
from app.arbiter import Arbiter
from app.link import Health, UdpLink
from mock.__main__ import serve


class FakeLink:
    def __init__(self):
        self.telemetry = {"t": "tel", "state": "balance", "pitch": 5.6}

    def health(self):
        return Health(True, 0.01, 0.01, 12.0)


def with_client(test):
    async def go():
        state = ApiState(Arbiter(), FakeLink())
        client = TestClient(TestServer(create_app(state, ca_page="trust me")))
        await client.start_server()
        try:
            await test(client, state)
        finally:
            await client.close()
    asyncio.run(go())


def test_phone_page_and_cert_page_are_served():
    async def t(c, s):
        assert (await (await c.get("/")).text()) == "trust me"          # plain HTTP: the certificate page
        page = await c.get("/index.html")
        assert page.status == 200 and "Miguel" in await page.text()
        assert (await c.get("/track.js")).status == 200
    with_client(t)


def test_auto_is_ignored_until_follow_is_on():
    async def t(c, s):
        r = await c.post("/auto", json={"v": 0.3, "w": 0.1, "found": True})
        assert (await r.json())["follow"] is False and s.arbiter.decide().source == "none"
        await c.post("/control/follow-on")
        await c.post("/auto", json={"v": 0.3, "w": 0.1, "found": True})
        cmd = s.arbiter.decide()
        assert cmd.source == "skill" and (cmd.v, cmd.w) == (0.3, 0.1)
        await c.post("/control/follow-off")
        assert s.arbiter.decide().source == "none"
    with_client(t)


def test_auto_clamps_and_survives_junk():
    async def t(c, s):
        await c.post("/control/follow-on")
        await c.post("/auto", json={"v": 9, "w": "nan"})
        cmd = s.arbiter.decide()
        assert (cmd.v, cmd.w) == (0.6, 0.0)
        assert (await c.post("/auto", data=b"not json")).status == 200
    with_client(t)


def test_stop_and_release():
    async def t(c, s):
        await c.post("/control/follow-on")
        status = await (await c.post("/control/stop")).json()
        assert status["estop"] is True and status["follow"] is False and s.arbiter.estopped
        await c.post("/control/release")
        assert not s.arbiter.estopped
    with_client(t)


def test_tel_and_say():
    async def t(c, s):
        d = await (await c.get("/tel")).json()
        assert d["tel"]["state"] == "balance" and d["link"] is True
        first = await (await c.get("/say?after=-1")).json()
        assert first == {"msgs": [], "last": 0}
        assert (await c.post("/say", json={"text": "Time for your medicine."})).status == 200
        d = await (await c.get("/say?after=0")).json()
        assert d["msgs"] == [{"id": 1, "text": "Time for your medicine."}]
        assert (await c.post("/say", json={"text": "  "})).status == 400
        assert (await c.get("/control")).status == 200
    with_client(t)


def test_websocket_sends_telemetry_and_takes_commands():
    async def t(c, s):
        ws = await c.ws_connect("/ws")
        msg = await asyncio.wait_for(ws.receive_json(), 1)
        assert msg["t"] == "tel"
        await ws.send_json({"t": "joystick", "v": -0.2, "w": 0.0})
        await asyncio.sleep(0.05)
        assert s.arbiter.decide().source == "joystick"
        await ws.send_json({"t": "estop", "on": True})
        await asyncio.sleep(0.05)
        assert s.arbiter.estopped
        await ws.send_json({"t": "say", "text": "hello"})
        await asyncio.sleep(0.05)
        assert s.say[-1]["text"] == "hello"
        await ws.close()
    with_client(t)


def test_phone_follow_drives_the_mock_end_to_end():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]

    async def go():
        ready = asyncio.Event()
        mock = asyncio.create_task(serve("127.0.0.1", port, verbose=False, ready=ready, armed=True))
        await ready.wait()
        arb, link = Arbiter(), UdpLink("127.0.0.1", port)
        await link.start()
        state = ApiState(arb, link)
        client = TestClient(TestServer(create_app(state)))
        await client.start_server()
        stop = asyncio.Event()
        loop_task = asyncio.create_task(drive_loop(arb, link, stop))

        await client.post("/control/follow-on")
        for _ in range(25):                               # the phone page posts ~15 times a second
            await client.post("/auto", json={"v": 0.3, "w": 0.0, "found": True})
            await asyncio.sleep(0.066)
        tel = (await (await client.get("/tel")).json())["tel"]
        assert tel["state"] == "drive" and tel["x"] > 0.1

        await client.post("/control/stop")
        await asyncio.sleep(1.5)
        tel = (await (await client.get("/tel")).json())["tel"]
        assert tel["state"] == "balance" and abs(tel["vl"]) < 0.01

        stop.set()
        await loop_task
        await client.close()
        await link.close()
        mock.cancel()

    asyncio.run(go())
