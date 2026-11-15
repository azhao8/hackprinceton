"""The API: the phone page's endpoints, the control page and the dashboard WebSocket.
The last test runs the whole path: phone page -> API -> arbiter -> UDP link -> mock robot."""

import asyncio
import socket
from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient, TestServer

from app.__main__ import drive_loop
from app.api import CONTROL_PAGE, PHONE_DIR, PHONE_LINES, STOCK_LINES, ApiState, create_app
from app.arbiter import Arbiter
from app.link import Health, UdpLink
from mock.__main__ import serve


class FakeLink:
    def __init__(self):
        self.telemetry = {"t": "tel", "state": "balance", "pitch": 5.6}

    def health(self):
        return Health(True, 0.01, 0.01, 12.0)


class FakeTTS:
    MEDIA_TYPE = "audio/mpeg"

    def __init__(self, fail: Exception | None = None):
        self.fail = fail
        self.asked: list[str] = []

    async def synth(self, text):
        self.asked.append(text)
        if self.fail:
            raise self.fail
        return b"ID3 fake mp3 " + text.encode()


def with_client(test, tts=None):
    async def go():
        state = ApiState(Arbiter(), FakeLink(), tts=tts)
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
        assert (await c.get("/face.js")).status == 200
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
        assert (cmd.v, cmd.w) == (1.0, 0.0)
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


def test_tts_serves_mp3_from_the_voice():
    tts = FakeTTS()

    async def t(c, s):
        r = await c.get("/tts", params={"text": "  Here is your water.  "})
        assert r.status == 200 and r.headers["Content-Type"] == "audio/mpeg"
        assert r.headers["Cache-Control"] == "no-store"
        assert await r.read() == b"ID3 fake mp3 Here is your water."
        assert tts.asked == ["Here is your water."]
        assert (await (await c.get("/tel")).json())["tts"] is True
    with_client(t, tts)


def test_tts_rejects_empty_or_long_text():
    tts = FakeTTS()

    async def t(c, s):
        assert (await c.get("/tts")).status == 400
        assert (await c.get("/tts", params={"text": "   "})).status == 400
        assert (await c.get("/tts", params={"text": "a" * 301})).status == 400
        assert (await c.get("/tts", params={"text": "a" * 300})).status == 200
        assert tts.asked == ["a" * 300]
    with_client(t, tts)


def test_tts_without_a_voice_is_503():
    async def t(c, s):
        r = await c.get("/tts", params={"text": "hello"})
        assert r.status == 503 and await r.json() == {"error": "tts not configured"}
        assert (await (await c.get("/tel")).json())["tts"] is False
    with_client(t)


def test_tts_failure_is_502():
    from app.speech.tts import TTSError

    async def t(c, s):
        r = await c.get("/tts", params={"text": "hello"})
        assert r.status == 502 and "error" in await r.json()
    with_client(t, FakeTTS(TTSError("cartesia said 401")))


def test_stock_lines_match_the_pages():
    page = (Path(PHONE_DIR) / "index.html").read_text()
    for line in PHONE_LINES:                     # the phone page's own lines, copied into the api module
        assert line in page, line
    assert "Hi, I'm Miguel!" in CONTROL_PAGE and "__PRESETS__" not in CONTROL_PAGE
    assert len(set(STOCK_LINES)) == len(STOCK_LINES) and all(0 < len(x) <= 300 for x in STOCK_LINES)


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


def test_stop_and_phone_follow_end_a_running_server_skill():
    from app.skills import SkillContext, SkillResult, SkillRunner

    class Forever:
        name = "follow"

        async def run(self, ctx):
            while True:
                ctx.drive(0.2, 0.0)
                await asyncio.sleep(0.01)

    async def go():
        arb = Arbiter()
        runner = SkillRunner(SkillContext(arb))
        state = ApiState(arb, FakeLink(), skills=runner)
        client = TestClient(TestServer(create_app(state)))
        await client.start_server()

        runner.start(Forever())
        await asyncio.sleep(0.03)
        await client.post("/auto", json={"v": 0.5, "w": 0.0})          # phone follow is off: ignored
        assert arb.decide().v == 0.2
        await client.post("/control/follow-on")                         # turning phone follow on ends the server skill
        await asyncio.sleep(0.03)
        assert runner.running is None
        await client.post("/auto", json={"v": 0.4, "w": 0.0})
        assert arb.decide().v == 0.4

        await client.post("/control/follow-off")
        runner.start(Forever())
        await asyncio.sleep(0.03)
        await client.post("/control/stop")                              # STOP ends the server skill too
        await asyncio.sleep(0.03)
        assert runner.running is None and arb.decide().source == "estop"
        await client.close()

    asyncio.run(go())


def test_control_page_does_not_use_bare_element_ids():
    # Bare ids like `stop.onclick` silently bind to window.stop() in browsers, so STOP did nothing (#35).
    from app.api import CONTROL_PAGE
    for name in ("stop", "release", "fon", "foff"):
        assert f"\n{name}.onclick" not in CONTROL_PAGE and f";{name}.onclick" not in CONTROL_PAGE
    assert "$('stop').onclick" in CONTROL_PAGE


def test_follow_settings_are_set_on_the_control_page_and_read_by_the_phone():
    async def t(c, s):
        d = await (await c.get("/tel")).json()
        assert d["settings"] == {"mode": "person", "speed": 0.25, "distance": 0.7, "voice": True, "camera": "back", "mirror": False}
        d = await (await c.post("/control/settings", json={"speed": 0.15, "distance": 9, "voice": False})).json()
        assert d["settings"] == {"mode": "person", "speed": 0.15, "distance": 1.0, "voice": False, "camera": "back", "mirror": False}   # clamped
        d = await (await c.post("/control/settings", json={"mode": "yellow"})).json()
        assert d["settings"] == {"mode": "yellow", "speed": 0.4, "distance": 0.35, "voice": False, "camera": "back", "mirror": False}    # new mode: its defaults
        await c.post("/control/settings", json={"mode": "nonsense", "speed": "fast"})
        assert (await (await c.get("/tel")).json())["settings"]["mode"] == "yellow"
        ws = await c.ws_connect("/ws")
        await ws.send_json({"t": "settings", "speed": 0.2})
        await asyncio.sleep(0.05)
        assert s.settings["speed"] == 0.2
        await ws.close()
    with_client(t)


class LetterLink(FakeLink):
    def __init__(self):
        super().__init__()
        self.sent = []

    def send_letter(self, letter):
        self.sent.append(letter)

    def arm(self):
        self.sent.append("g")


def test_websocket_keys_arm_and_status():
    async def go():
        link = LetterLink()
        state = ApiState(Arbiter(), link)
        client = TestClient(TestServer(create_app(state)))
        await client.start_server()
        ws = await client.ws_connect("/ws")
        got_status = False
        for _ in range(10):
            m = await asyncio.wait_for(ws.receive_json(), 1)
            if m["t"] == "status":
                got_status = True
                assert m["link"] is True and "settings" in m and "tel" not in m
                break
        assert got_status
        state.follow = True
        await ws.send_json({"t": "key", "letter": "P"})
        await ws.send_json({"t": "key", "letter": "g"})          # refused: g only through arm
        await ws.send_json({"t": "arm"})                           # the test client is local
        await asyncio.sleep(0.1)
        assert link.sent == ["P", "g"] and state.follow is False
        await ws.close()
        await client.close()
    asyncio.run(go())


def test_phone_frames_feed_vision_and_follow_runs_on_the_server():
    import cv2
    import numpy as np

    from app.vision.phone_source import PhoneFrameSource

    async def go():
        src = PhoneFrameSource()
        running = {"follow": False}
        state = ApiState(Arbiter(), FakeLink(), phone_frames=src,
                         follow_start=lambda: running.update(follow=True),
                         follow_stop=lambda: running.update(follow=False),
                         follow_running=lambda: running["follow"],
                         view_jpeg=lambda: b"\xff\xd8fakejpeg", vision_status=lambda: "running")
        client = TestClient(TestServer(create_app(state)))
        await client.start_server()

        ok, jpg = cv2.imencode(".jpg", np.zeros((64, 36, 3), dtype=np.uint8))
        assert (await client.post("/frame", data=jpg.tobytes())).status == 204
        assert (await client.post("/frame", data=b"not an image")).status == 400
        frame = src.read_next(timeout=1)
        assert frame is not None and frame.image.shape == (64, 36, 3)

        st = await (await client.get("/tel")).json()
        assert st["vision"]["mode"] == "server" and st["vision"]["camera"]["frames"] == 1

        await client.post("/control/follow-on")
        assert running["follow"] and (await (await client.get("/tel")).json())["follow"] is True
        await client.post("/auto", json={"v": 0.3, "w": 0})            # the phone no longer drives
        assert state.arbiter.decide().source == "none"
        await client.post("/control/stop")                             # STOP ends the follow skill (skills=None here: flag cleared)
        await client.post("/control/follow-off")
        assert not running["follow"]

        resp = await client.get("/video.mjpg")
        chunk = await resp.content.read(64)
        assert resp.headers["Content-Type"].startswith("multipart/x-mixed-replace") and b"--frame" in chunk
        resp.close()
        await client.close()

    asyncio.run(go())


def test_camera_and_mirror_settings_reach_the_phone_and_the_frame_source():
    import cv2
    import numpy as np

    from app.vision.phone_source import PhoneFrameSource

    async def go():
        src = PhoneFrameSource()
        state = ApiState(Arbiter(), FakeLink(), phone_frames=src)
        client = TestClient(TestServer(create_app(state)))
        await client.start_server()
        d = await (await client.post("/control/settings", json={"camera": "front", "mirror": True})).json()
        assert d["settings"]["camera"] == "front" and d["settings"]["mirror"] is True and src.mirror
        await client.post("/control/settings", json={"camera": "sideways", "mirror": "yes"})   # ignored
        assert state.settings["camera"] == "front" and state.settings["mirror"] is True
        img = np.zeros((10, 20, 3), dtype=np.uint8)
        img[:, :5] = 255                                    # white on the left
        ok, jpg = cv2.imencode(".png", img)
        src.push_jpeg(jpg.tobytes())
        assert src.read_next(timeout=1).image[:, -5:].mean() > 200   # mirrored: white on the right now
        await client.close()

    asyncio.run(go())


def test_tel_has_the_face_with_server_vision_and_null_without():
    async def phone_mode(c, s):
        assert (await (await c.get("/tel")).json())["face"] is None
    with_client(phone_mode)

    face = {"status": "locked", "target": {"cx": 0.4, "cy": 0.3, "w": 0.2}, "event": {"id": 1, "kind": "found"}}

    async def go():
        state = ApiState(Arbiter(), FakeLink(), follow_start=lambda: None, follow_stop=lambda: None,
                         follow_running=lambda: True, vision_status=lambda: "running", face=lambda: face)
        client = TestClient(TestServer(create_app(state)))
        await client.start_server()
        try:
            st = await (await client.get("/tel")).json()
            assert st["face"] == face and set(st["face"]) == {"status", "target", "event"}
            ws = await client.ws_connect("/ws")
            msg = await ws.receive_json(timeout=2)
            while msg.get("t") != "status":
                msg = await ws.receive_json(timeout=2)
            assert msg["face"] == face
            await ws.close()
        finally:
            await client.close()
    asyncio.run(go())


class TrimLink(LetterLink):
    def send_trim(self, steps):
        self.sent.append(steps)


def test_trim_shifts_the_balance_angle_one_step_at_a_time_while_balancing():
    link = TrimLink()
    state = ApiState(Arbiter(), link)
    link.telemetry = {"t": "tel", "state": "idle"}
    assert state.trim(-35) and state.trim_shift == -8.75
    assert state.trim(999) and link.sent[-1] == 60                 # clamped to 15 deg
    assert not state.trim(0) and not state.trim(1.5) and not state.trim(True) and not state.trim("3")
    link.telemetry = {"t": "tel", "state": "balance"}
    assert not state.trim(-4)                                       # a big jump while balancing: refused
    assert state.trim(-1)
    assert link.sent == [-35, 60, -1] and state.trim_shift == pytest.approx(-8.75 + 15 - 0.25)
    assert state.status()["trim_shift"] == state.trim_shift


def test_websocket_trim_from_this_laptop():
    async def go():
        link = TrimLink()
        link.telemetry = {"t": "tel", "state": "idle"}
        state = ApiState(Arbiter(), link)
        client = TestClient(TestServer(create_app(state)))
        await client.start_server()
        ws = await client.ws_connect("/ws")
        await ws.send_json({"t": "trim", "steps": -2})
        await asyncio.sleep(0.1)
        assert link.sent == [-2] and state.trim_shift == -0.5
        await ws.close()
        await client.close()
    asyncio.run(go())
