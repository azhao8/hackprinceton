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
        assert (cmd.v, cmd.w) == (3.2, 0.0)
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


class FakeStreamTTS(FakeTTS):
    """Like CartesiaTTS: a cache, and stream() that yields chunks as they come."""

    def __init__(self, fail: Exception | None = None):
        super().__init__(fail)
        self.cache: dict[str, bytes] = {}
        self.streamed: list[str] = []

    def cached(self, text):
        return self.cache.get(text)

    async def stream(self, text):
        self.streamed.append(text)
        if self.fail:
            raise self.fail
        for chunk in (b"ID3", b" chunk1", b" chunk2"):
            await asyncio.sleep(0)
            yield chunk


def test_tts_streams_lines_not_in_the_cache_and_serves_cached_ones_whole():
    from app.speech.tts import TTSError

    tts = FakeStreamTTS()

    async def t(c, s):
        r = await c.get("/tts", params={"text": "Hello there."})
        assert r.status == 200 and r.headers["Content-Type"] == "audio/mpeg"
        assert await r.read() == b"ID3 chunk1 chunk2" and tts.streamed == ["Hello there."]
        tts.cache["Hi."] = b"ID3 whole"
        r = await c.get("/tts", params={"text": "Hi."})
        assert await r.read() == b"ID3 whole" and r.headers["Content-Length"] == "9"
        assert tts.streamed == ["Hello there."] and tts.asked == []
        tts.fail = TTSError("401")
        assert (await c.get("/tts", params={"text": "Nope."})).status == 502   # before any audio: still a 502
    with_client(t, tts)


def test_say_lines_are_prefetched_and_tel_says_listening_and_tts_stream():
    tts = FakeTTS()

    async def t(c, s):
        s.add_say("On my way to the kitchen.")
        await asyncio.sleep(0.01)
        assert tts.asked == ["On my way to the kitchen."]     # the audio is being made before the phone asks
        s.set_settings({"voice": False})
        s.add_say("Quiet line.")
        await asyncio.sleep(0.01)
        assert tts.asked == ["On my way to the kitchen."]     # voice off: no prefetch
        d = await (await c.get("/tel")).json()
        assert d["listening"] is False and d["tts_stream"] is False
        s.tts_stream = True
        assert (await (await c.get("/tel")).json())["tts_stream"] is True
    with_client(t, tts)


def test_one_timing_line_per_turn_from_end_of_speech_to_playback(caplog):
    import logging

    from app.speech.mic import make_mic_handler

    caplog.set_level(logging.INFO, logger="app.speech.timing")
    tts = FakeStreamTTS()
    mic = make_mic_handler(None, asyncio.Queue(), "Miguel")

    async def go():
        state = ApiState(Arbiter(), FakeLink(), tts=tts, mic=mic)
        client = TestClient(TestServer(create_app(state)))
        await client.start_server()
        try:
            import time

            now = time.monotonic()
            timing = {"t_speech_end": now - 1.0, "t_final": now - 0.6, "heard": now - 0.6,
                      "llm_start": now - 0.6, "first_text": now - 0.1, "say": now - 0.1}
            state.publish_agent_event({"id": 1, "kind": "say", "text": "Sure thing!", "to": "senior",
                                       "data": {"timing": timing}})
            assert "timing" not in state.agent_events[-1]["data"]          # server-side only
            state.add_say("Sure thing!")
            await (await client.get("/tts", params={"text": "Sure thing!"})).read()
            mic.hub._voice(True, "Sure thing!", state.say[-1]["id"])        # the phone starts playing it
        finally:
            await client.close()
        return state.timer.last

    last = asyncio.run(go())
    assert last["text"] == "Sure thing!"
    ms = last["ms"]
    assert list(ms) == ["transcript", "Claude asked", "first text", "say", "audio asked", "audio first byte",
                        "playback"]
    assert 350 <= ms["transcript"] <= 450 and 850 <= ms["first text"] <= 950
    assert ms["audio asked"] <= ms["audio first byte"] <= ms["playback"]
    assert caplog.text.count("turn timing (ms after the end of speech)") == 1


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
        assert d["settings"] == {"mode": "person", "speed": 0.8, "distance": 0.8, "voice": True, "camera": "back", "mirror": False, "drive_speed": 1.1, "turn_rate": 1.0}
        d = await (await c.post("/control/settings", json={"speed": 0.15, "distance": 9, "voice": False, "drive_speed": 9})).json()
        assert d["settings"] == {"mode": "person", "speed": 0.15, "distance": 1.0, "voice": False, "camera": "back", "mirror": False,
                                 "drive_speed": 3.2, "turn_rate": 1.0}   # clamped
        d = await (await c.post("/control/settings", json={"mode": "yellow"})).json()
        assert d["settings"] == {"mode": "yellow", "speed": 0.4, "distance": 0.35, "voice": False, "camera": "back", "mirror": False,
                                 "drive_speed": 3.2, "turn_rate": 1.0}    # new mode: its follow defaults; drive kept
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
        link.telemetry = {"t": "tel", "state": "idle", "pitch": 11.2, "rate": 0.0}   # lying down
        await ws.send_json({"t": "key", "letter": "P"})
        await ws.send_json({"t": "key", "letter": "g"})          # refused: g only through arm
        await ws.send_json({"t": "arm"})                           # the test client is local: Start waits
        await asyncio.sleep(0.1)
        assert link.sent == ["P"] and state.autostart.waiting
        for i in range(25):                                        # held upright and steady for 1.25 s
            link.telemetry = {"t": "tel", "state": "idle", "pitch": -3.65 + 0.3, "rate": 1.0}
            state.watch(100.0 + i * 0.05)
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


def test_recalibrate_only_when_not_balancing():
    link = TrimLink()
    state = ApiState(Arbiter(), link)
    link.telemetry = {"t": "tel", "state": "balance"}
    assert not state.recalibrate() and link.sent == []
    link.telemetry = {"t": "tel", "state": "idle"}
    assert state.recalibrate() and link.sent == ["c"]


def test_a_tunnel_on_this_laptop_is_not_this_laptop():
    """#69 review #1/#3: a proxy on the laptop connects from 127.0.0.1 but adds forwarding headers."""
    async def go():
        link = TrimLink()
        link.telemetry = {"t": "tel", "state": "idle"}
        arb = Arbiter()
        state = ApiState(arb, link, view_jpeg=lambda: b"\xff\xd8x")
        client = TestClient(TestServer(create_app(state)))
        await client.start_server()
        tunnel = {"CF-Connecting-IP": "203.0.113.9"}
        assert (await client.get("/video.mjpg", headers=tunnel)).status == 403
        assert (await client.post("/frame", data=b"x", headers=tunnel)).status == 403
        assert (await client.post("/auto", json={"v": 0.3}, headers=tunnel)).status == 403
        assert (await client.post("/control/stop", headers=tunnel)).status == 403
        ws = await client.ws_connect("/ws", headers=tunnel)
        for m in ({"t": "arm"}, {"t": "joystick", "v": 0.5, "w": 0}, {"t": "key", "letter": "F"},
                  {"t": "settings", "speed": 3.0}, {"t": "trim", "steps": -4}, {"t": "estop", "on": False}):
            await ws.send_json(m)
        await ws.send_json({"t": "estop", "on": True})      # stopping is always allowed
        await asyncio.sleep(0.1)
        assert link.sent == [] and state.settings["speed"] != 3.0 and arb.estopped
        await ws.close()
        ws = await client.ws_connect("/ws")                  # this laptop, directly
        await ws.send_json({"t": "estop", "on": False})
        await asyncio.sleep(0.1)
        assert not arb.estopped
        await ws.close()
        await client.close()
    asyncio.run(go())


# --- #79: auto-start, drift, the phone's controls, the resets ---------------------------------------


def held(state, link, t0, seconds, pitch=-3.65, rate=0.5, state_name="idle"):
    """Feed `seconds` of 20 Hz telemetry to the API's watchers."""
    n = int(seconds * 20)
    for i in range(n):
        link.telemetry = {"t": "tel", "state": state_name, "pitch": pitch, "rate": rate}
        state.watch(t0 + i * 0.05)
    return t0 + n * 0.05


def test_start_waits_for_upright_and_steady_then_sends_g():
    link = LetterLink()
    state = ApiState(Arbiter(), link)
    link.telemetry = {"t": "tel", "state": "idle", "pitch": 11.0, "rate": 0.0}
    assert state.arm() and state.autostart.waiting and link.sent == []
    t = held(state, link, 0.0, 2.0, pitch=11.0)                   # lying down: nothing
    t = held(state, link, t, 2.0, pitch=-3.65, rate=25.0)        # upright but swinging: nothing
    assert link.sent == []
    held(state, link, t, 1.2, pitch=-2.0, rate=2.0)              # upright and steady
    assert link.sent == ["g"]
    held(state, link, 50.0, 0.2, state_name="balance")
    assert not state.autostart.waiting and state.status()["autostart"] == {"waiting": False, "note": ""}


def test_stop_park_and_cancel_end_the_wait():
    link = LetterLink()
    state = ApiState(Arbiter(), link)
    link.telemetry = {"t": "tel", "state": "idle", "pitch": 11.0, "rate": 0.0}
    for end in (lambda: state.estop(True), lambda: state.key("P"), state.cancel_start):
        state.arm()
        end()
        assert not state.autostart.waiting
    held(state, link, 0.0, 2.0)
    assert "g" not in link.sent


def test_drift_is_said_out_loud_and_blocks_start():
    from app.api import DRIFT_LINE
    link = LetterLink()
    state = ApiState(Arbiter(), link)
    held(state, link, 0.0, 2.5, pitch=12.0, rate=27.0)           # lying still, gyro reads 27 deg/s
    assert state.drift.on and state.status()["drift"] is True
    assert [m["text"] for m in state.say] == [DRIFT_LINE]
    assert not state.arm() and not state.autostart.waiting       # refused, and said again
    assert [m["text"] for m in state.say] == [DRIFT_LINE, DRIFT_LINE]
    assert state.recalibrate() and link.sent == ["c"] and not state.drift.on
    assert state.status()["calibrating"] is True
    held(state, link, 10.0, 3.0, pitch=12.0, rate=0.1)
    assert not state.drift.on and state.arm()


def test_drift_mid_wait_cancels_the_start():
    link = LetterLink()
    state = ApiState(Arbiter(), link)
    link.telemetry = {"t": "tel", "state": "idle", "pitch": 12.0, "rate": 0.0}
    state.arm()
    held(state, link, 0.0, 2.5, pitch=12.0, rate=-8.0)
    assert state.drift.on and not state.autostart.waiting and "drifting" in state.autostart.note
    assert "g" not in link.sent


def test_phone_actions_from_the_hotspot_only():
    async def go():
        link = LetterLink()
        link.telemetry = {"t": "tel", "state": "idle", "pitch": 11.0, "rate": 0.0}
        state = ApiState(Arbiter(), link)
        client = TestClient(TestServer(create_app(state)))
        await client.start_server()
        try:
            r = await (await client.post("/phone/action", json={"action": "start"})).json()
            assert r["ok"] and state.autostart.waiting
            r = await (await client.post("/phone/action", json={"action": "cancel_start"})).json()
            assert r["ok"] and not state.autostart.waiting
            assert (await (await client.post("/phone/action", json={"action": "park"})).json())["ok"]
            assert (await (await client.post("/phone/action", json={"action": "recalibrate"})).json())["ok"]
            assert link.sent == ["P", "c"]
            assert (await client.post("/phone/action", json={"action": "g"})).status == 400
            tunnel = {"X-Forwarded-For": "203.0.113.9"}
            assert (await client.post("/phone/action", json={"action": "start"}, headers=tunnel)).status == 403
            assert (await (await client.get("/tel")).json())["phone"] is True   # it just polled
        finally:
            await client.close()
    asyncio.run(go())


def test_status_says_who_is_connected():
    state = ApiState(Arbiter(), FakeLink())
    st = state.status()
    assert st["phone"] is False and st["family"] == 0 and st["agent"] is False and st["drift"] is False

    class Family:
        clients = {"a": 1, "b": 2}
    state.family = Family()
    assert state.status()["family"] == 2


class FakeAgent:
    def __init__(self):
        self.calls = []

    def reset_conversation(self):
        self.calls.append("reset")

    def clear_events(self):
        self.calls.append("clear")


def test_resets_from_the_control_page(tmp_path):
    from app.memory import Memory

    async def go():
        state = ApiState(Arbiter(), FakeLink())
        state.agent = FakeAgent()
        state.memory = Memory(tmp_path / "m.db", seed_places={"water station": 3})
        state.memory.facts["pills"] = "blue bottle"
        state.memory.set_place("kitchen", marker=7)
        state.memory.add_event("delivery", "Brought water")
        for i in (1, 2):
            state.publish_agent_event({"id": i, "kind": "say", "text": "hi", "to": None, "data": {}})
        client = TestClient(TestServer(create_app(state)))
        await client.start_server()
        try:
            ws = await client.ws_connect("/ws")
            await ws.send_json({"t": "reset_chat"})
            await ws.send_json({"t": "clear_log"})
            got = None
            for _ in range(20):
                m = await asyncio.wait_for(ws.receive_json(), 1)
                if m["t"] == "agent_clear":
                    got = m
                    break
            assert got is not None and state.agent_events == [] and state.agent.calls == ["reset", "clear"]
            d = state.publish_agent_event({"id": 1, "kind": "say", "text": "new", "to": None, "data": {}})
            assert d["id"] == 3                                    # ids keep increasing after a clear
            await ws.send_json({"t": "reset_memory"})
            for _ in range(20):
                m = await asyncio.wait_for(ws.receive_json(), 1)
                if m["t"] == "memory":
                    break
            assert m["facts"] == [] and [p["name"] for p in m["places"]] == ["water station"]
            assert state.memory.today() == [] and state.agent.calls[-1] == "reset"
            await ws.close()
        finally:
            await client.close()
    asyncio.run(go())
