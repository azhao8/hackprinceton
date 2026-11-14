"""The voice agent's channel (#54): /agent/message, /agent/events, /agent/photo, /ws agent messages,
/mic, and the wiring in `python -m app`. Fakes for the agent, speech-to-text and skills; no network."""

from __future__ import annotations

import asyncio
import json
import sys
import types
from pathlib import Path

import numpy as np
import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

import app.__main__ as server
from app import api
from app.api import ApiState, create_app
from app.arbiter import Arbiter
from app.brain.types import AgentEvent, Utterance
from app.link import Health

TOKEN = "s3cret-guardian"
WEB_CONTRACT = Path(__file__).resolve().parents[2] / "contract" / "web"


class FakeLink:
    telemetry = {"t": "tel", "state": "balance", "pitch": 1.0}

    def health(self):
        return Health(True, 0.01, 0.01, 12.0)


class FakeTTS:
    MEDIA_TYPE = "audio/mpeg"

    async def synth(self, text):
        return b"ID3" + text.encode()


def run_client(test, *, token=TOKEN, tts=None, inbox=True, mic=None):
    async def go():
        state = ApiState(Arbiter(), FakeLink(), tts=tts, guardian_token=token, mic=mic,
                         agent_inbox=asyncio.Queue() if inbox else None)
        client = TestClient(TestServer(create_app(state)))
        await client.start_server()
        try:
            await test(client, state)
        finally:
            await client.close()
    asyncio.run(go())


@pytest.fixture
def remote(monkeypatch):
    """Every request looks like it came from another machine."""
    monkeypatch.setattr(api, "LOCAL", ())


# --- POST /agent/message ---


def test_local_message_reaches_the_inbox():
    async def t(c, s):
        r = await c.post("/agent/message", json={"text": "  Bring Mom her pills  "})
        assert r.status == 200 and (await r.json()) == {"ok": True, "last": 0}
        u = s.agent_inbox.get_nowait()
        assert isinstance(u, Utterance) and (u.source, u.text, u.meta) == ("guardian", "Bring Mom her pills", {"channel": "api"})
        await c.post("/agent/message", json={"text": "stop", "from": "operator"})
        assert s.agent_inbox.get_nowait().source == "operator"
    run_client(t)


def test_message_text_is_checked_and_agent_off_is_503():
    async def t(c, s):
        assert (await c.post("/agent/message", json={"text": "  "})).status == 400
        assert (await c.post("/agent/message", json={"text": "x" * 1001})).status == 400
        assert (await c.post("/agent/message", data="junk")).status == 400
        assert s.agent_inbox.empty()
    run_client(t)

    async def off(c, s):
        r = await c.post("/agent/message", json={"text": "hi"})
        assert r.status == 503 and "ANTHROPIC_API_KEY" in (await r.json())["error"]
    run_client(off, inbox=False)


def test_remote_needs_the_guardian_token(remote):
    async def t(c, s):
        assert (await c.post("/agent/message", json={"text": "hi"})).status == 401
        bad = await c.post("/agent/message", json={"text": "hi"}, headers={"Authorization": "Bearer nope"})
        assert bad.status == 401 and bad.headers["WWW-Authenticate"] == "Bearer"
        ok = await c.post("/agent/message", json={"text": "hi", "from": "operator"},
                          headers={"Authorization": f"Bearer {TOKEN}"})
        assert ok.status == 200
        assert s.agent_inbox.get_nowait().source == "guardian"   # operator only from this laptop
        assert s.agent_inbox.empty()
    run_client(t)


def test_remote_without_a_token_configured_is_refused(remote):
    async def t(c, s):
        r = await c.post("/agent/message", json={"text": "hi"}, headers={"Authorization": "Bearer "})
        assert r.status == 403 and s.agent_inbox.empty()
        assert (await c.get("/agent/events")).status == 403
    run_client(t, token=None)


def test_a_tunnel_on_this_laptop_is_not_local():
    async def t(c, s):
        fwd = {"X-Forwarded-For": "203.0.113.9"}
        assert (await c.post("/agent/message", json={"text": "hi"}, headers=fwd)).status == 401
        assert (await c.post("/agent/message", json={"text": "hi"},
                             headers={**fwd, "Authorization": f"Bearer {TOKEN}"})).status == 200
        assert (await c.get("/agent/events", headers={"CF-Connecting-IP": "203.0.113.9"})).status == 401
    run_client(t)


# --- events, photos, audio ---


def test_events_poll_after_n():
    async def t(c, s):
        assert (await (await c.get("/agent/events")).json()) == {"events": [], "last": 0}
        for i, kind in enumerate(["heard", "plan", "say"], start=1):
            s.publish_agent_event(AgentEvent(i, kind, f"e{i}", data={"steps": []} if kind == "plan" else {}))
        d = await (await c.get("/agent/events?after=1")).json()
        assert d["last"] == 3 and [e["id"] for e in d["events"]] == [2, 3]
        assert d["events"][0] == {"id": 2, "kind": "plan", "text": "e2", "to": None, "data": {"steps": []}}
        assert len((await (await c.get("/agent/events?after=junk")).json())["events"]) == 3
    run_client(t)


def test_event_ids_keep_increasing_and_old_events_drop():
    s = ApiState(Arbiter(), FakeLink())
    s.publish_agent_event(AgentEvent(5, "say", "a"))
    assert s.publish_agent_event(AgentEvent(5, "say", "b"))["id"] == 6       # a repeated id is bumped
    assert s.publish_agent_event({"kind": "error", "text": "c"})["id"] == 7   # a dict without one too
    for i in range(300):
        s.publish_agent_event(AgentEvent(100 + i, "step", ""))
    assert len(s.agent_events) == api.AGENT_EVENTS_KEPT and s.last_agent_event == 399


def test_reply_keeps_the_agents_photo_and_gets_audio():
    async def t(c, s):
        url = s.save_photo(b"\xff\xd8jpeg")                     # the ToolBox's save_photo
        assert url == "/agent/photo/1.jpg"
        d = s.publish_agent_event(AgentEvent(1, "reply", "Done: Mom has her pills.", to="guardian",
                                             data={"photo_id": 1, "photo_url": url}))
        assert d["data"] == {"photo_id": 1, "photo_url": url,
                             "audio_url": "/tts?text=Done%3A%20Mom%20has%20her%20pills."}
        r = await c.get("/agent/photo/1.jpg")
        assert r.status == 200 and r.content_type == "image/jpeg" and await r.read() == b"\xff\xd8jpeg"
        assert (await c.get("/agent/photo/2.jpg")).status == 404
        tts = await c.get(d["data"]["audio_url"])
        assert tts.status == 200 and await tts.read() == b"ID3Done: Mom has her pills."
        assert s.publish_agent_event(AgentEvent(2, "say", "hi"))["data"] == {}   # only replies get audio
    run_client(t, tts=FakeTTS())


def test_reply_without_voice_has_no_audio():
    s = ApiState(Arbiter(), FakeLink())
    assert s.publish_agent_event(AgentEvent(1, "reply", "ok"))["data"] == {}


def test_only_the_last_photos_are_kept():
    s = ApiState(Arbiter(), FakeLink())
    urls = [s.save_photo(b"\xff\xd8") for _ in range(25)]
    assert urls[-1] == "/agent/photo/25.jpg" and list(s.agent_photos) == list(range(6, 26))


def test_photos_need_the_token_from_afar(remote):
    async def t(c, s):
        s.save_photo(b"\xff\xd8")
        assert (await c.get("/agent/photo/1.jpg")).status == 401
        assert (await c.get("/agent/photo/1.jpg", headers={"Authorization": f"bearer {TOKEN}"})).status == 200
    run_client(t)


def test_tray_loaded_releases_the_bring_skill():
    async def t(c, s):
        assert (await (await c.post("/control/loaded")).json()) == {"ok": False}   # nothing waiting
        waiting = asyncio.create_task(s.wait_loaded())
        await asyncio.sleep(0)
        assert (await (await c.post("/control/loaded")).json()) == {"ok": True}
        assert await asyncio.wait_for(waiting, 1) is True
        assert "$('loaded').onclick" in api.CONTROL_PAGE
    run_client(t)


def test_tray_loaded_is_local_only(remote):
    async def t(c, s):
        assert (await c.post("/control/loaded", headers={"Authorization": f"Bearer {TOKEN}"})).status == 403
    run_client(t)


# --- the dashboard WebSocket ---


async def next_agent(ws):
    while True:
        m = await asyncio.wait_for(ws.receive_json(), 1)
        if m["t"] == "agent":
            return m


def test_websocket_pushes_agent_events_and_takes_agent_message():
    async def t(c, s):
        s.publish_agent_event(AgentEvent(1, "say", "old"))   # before connecting: not replayed
        ws = await c.ws_connect("/ws")
        s.publish_agent_event(AgentEvent(2, "task", "Bring water", data={"id": "t1", "status": "started", "summary": ""}))
        m = await next_agent(ws)
        assert m == {"t": "agent", "id": 2, "kind": "task", "text": "Bring water", "to": None,
                     "data": {"id": "t1", "status": "started", "summary": ""}}
        await ws.send_json({"t": "agent_message", "text": "go to the kitchen"})
        u = await asyncio.wait_for(s.agent_inbox.get(), 1)
        assert (u.source, u.text, u.meta["channel"]) == ("operator", "go to the kitchen", "ws")
        await ws.close()
    run_client(t)


def test_remote_websocket_agent_message_needs_the_token(remote):
    async def t(c, s):
        ws = await c.ws_connect("/ws")
        await ws.send_json({"t": "agent_message", "text": "hi"})
        await asyncio.sleep(0.05)
        assert s.agent_inbox.empty()
        await ws.close()
        ws = await c.ws_connect("/ws", headers={"Authorization": f"Bearer {TOKEN}"})
        await ws.send_json({"t": "agent_message", "text": "hi"})
        assert (await asyncio.wait_for(s.agent_inbox.get(), 1)).source == "guardian"
        await ws.close()
    run_client(t)


# --- /mic ---


class FakeHub:
    def __init__(self):
        self.ptt, self.spoke = [], 0

    def push_to_talk(self, text, source="operator"):
        self.ptt.append((text, source))

    def note_miguel_spoke(self):
        self.spoke += 1


def test_operator_messages_go_through_the_mics_push_to_talk():
    async def mic(request):
        return web.Response()
    mic.hub = FakeHub()

    async def t(c, s):
        await c.post("/agent/message", json={"text": "come here", "from": "operator"})
        await c.post("/agent/message", json={"text": "from the family"})
        assert mic.hub.ptt == [("come here", "operator")]
        assert s.agent_inbox.get_nowait().text == "from the family" and s.agent_inbox.empty()
    run_client(t, mic=mic)


def test_say_events_open_the_mics_answer_window():
    async def mic(request):
        return web.Response()
    mic.hub = FakeHub()
    s = ApiState(Arbiter(), FakeLink(), mic=mic)
    server.on_agent_event(s, AgentEvent(1, "say", "Do you want water?"))
    server.on_agent_event(s, AgentEvent(2, "reply", "ok"))
    assert mic.hub.spoke == 1 and s.say[-1]["text"] == "Do you want water?"


def test_mic_is_mounted_only_when_given():
    async def mic(request):
        sock = web.WebSocketResponse()
        await sock.prepare(request)
        await sock.send_str("listening")
        await sock.close()
        return sock

    async def t(c, s):
        ws = await c.ws_connect("/mic")
        assert (await ws.receive()).data == "listening"
    run_client(t, mic=mic)

    async def off(c, s):
        assert (await c.get("/mic")).status == 404
    run_client(off)


# --- contract samples ---


def test_agent_samples_match_what_the_server_sends():
    samples = WEB_CONTRACT / "samples"
    msg = json.loads((samples / "agent-message.json").read_text())
    assert set(msg) == {"text", "from"} and msg["from"] in ("guardian", "operator")
    ws_msg = json.loads((samples / "agent-message-ws.json").read_text())
    assert ws_msg["t"] == "agent_message" and ws_msg["text"]
    kinds = set()
    for path in sorted(samples.glob("agent-event-*.json")):
        ev = json.loads(path.read_text())
        assert ev["t"] == "agent" and set(ev) == {"t", "id", "kind", "text", "to", "data"}, path.name
        kinds.add(ev["kind"])
    assert {"reply", "say", "task", "plan", "step"} <= kinds
    reply = json.loads((samples / "agent-event-reply.json").read_text())
    assert reply["data"]["photo_url"].startswith("/agent/photo/") and reply["data"]["audio_url"].startswith("/tts?text=")


# --- wiring in python -m app ---


class FakeAgent:
    instances: list[FakeAgent] = []

    def __init__(self, tools, events_cb=None, client=None, model="claude-opus-5-5"):
        self.tools, self.events_cb = tools, events_cb
        self.inbox: asyncio.Queue = asyncio.Queue()
        self.ran = self.cancelled = self.closed = False
        FakeAgent.instances.append(self)

    async def run(self):
        self.ran = True
        self.events_cb(AgentEvent(1, "say", "Hi, I'm listening."))
        self.events_cb(AgentEvent(2, "reply", "On it.", to="guardian"))
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise

    async def aclose(self):
        self.closed = True


class FakeToolBox:
    def __init__(self, runner=None, skill_factories=None, *, snapshot=None, describe=None, save_photo=None):
        self.runner, self.skill_factories, self.snapshot = runner, skill_factories, snapshot
        self.save_photo = save_photo


class FakeSTT:
    closed = False

    @classmethod
    def from_env(cls):
        return cls()

    async def close(self):
        self.closed = True


@pytest.fixture
def brain(monkeypatch):
    """Fake app.brain.agent / tools / app.speech.stt / mic / the search skills, as importable modules."""
    FakeAgent.instances = []
    mic_calls: list = []

    def make_mic_handler(stt, inbox, wake_word=None):
        mic_calls.append((stt, inbox, wake_word))

        async def handler(request):
            return web.Response(text="mic")
        return handler

    class Made:
        def __init__(self, *args, **kw):
            self.args, self.kw = args, kw

    class FindPerson(Made):
        name = "find_person"

    class GoTo(Made):
        name = "go_to"

    class Bring(Made):
        name = "bring"

    async def matches_description(jpeg, description):
        return True, "fake"

    mods = {"app.brain.agent": {"Agent": FakeAgent}, "app.brain.tools": {"ToolBox": FakeToolBox},
            "app.speech.stt": {"CartesiaSTT": FakeSTT}, "app.speech.mic": {"make_mic_handler": make_mic_handler},
            "app.skills.search": {"FindPerson": FindPerson, "GoTo": GoTo}, "app.skills.bring": {"Bring": Bring},
            "app.vision.people": {"PeopleRegistry": lambda: "registry"},
            "app.brain.vision_check": {"matches_description": matches_description}}
    for name, attrs in mods.items():
        m = types.ModuleType(name)
        m.__dict__.update(attrs)
        monkeypatch.setitem(sys.modules, name, m)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("GUARDIAN_TOKEN", TOKEN)
    return mic_calls


def serve_with_fakes(monkeypatch, argv, ticks=6):
    from tests.test_main import TEL, FakeUdpLink, FakeWindow, fake_api_start

    seen = fake_api_start(monkeypatch)
    monkeypatch.setattr(server, "make_tts", lambda: None)
    link = FakeUdpLink(dict(TEL))
    app = asyncio.run(server.serve(server.parse_args(argv), link, window=FakeWindow([-1] * ticks + ["q"]),
                                   render=lambda p, h: h))
    return app, seen["state"], link


def test_serve_runs_the_agent_and_its_say_events_reach_the_phone(monkeypatch, brain):
    app, state, link = serve_with_fakes(monkeypatch, ["--no-vision"])
    agent = FakeAgent.instances[-1]
    assert agent.ran and agent.cancelled and agent.closed
    assert state.agent_inbox is agent.inbox and state.guardian_token == TOKEN
    assert [m["text"] for m in state.say] == ["Hi, I'm listening."]             # say -> the phone's say queue
    assert [e["kind"] for e in state.agent_events] == ["say", "reply"]
    assert isinstance(agent.tools, FakeToolBox) and agent.tools.runner is app.skills
    assert agent.tools.skill_factories == {} and agent.tools.snapshot is None   # no camera: no physical skills
    assert agent.tools.save_photo == state.save_photo
    stt, inbox, wake = brain[0]
    assert inbox is agent.inbox and wake == "Miguel" and state.mic is not None and stt.closed
    assert link.events[-2:] == ["x", "close"]                                    # shutdown unchanged


def test_wake_word_can_be_turned_off(monkeypatch, brain):
    serve_with_fakes(monkeypatch, ["--no-vision", "--wake-word", ""])
    assert brain[0][2] is None


def test_serve_without_the_key_runs_as_before(monkeypatch, brain, caplog):
    caplog.set_level("INFO")
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    app, state, link = serve_with_fakes(monkeypatch, ["--no-vision"])
    assert "agent: off (ANTHROPIC_API_KEY not set)" in caplog.text
    assert not FakeAgent.instances and state.agent_inbox is None and state.mic is None and not brain
    assert app.background == [] and link.events[-2:] == ["x", "close"]


def test_a_missing_brain_module_leaves_the_agent_off(monkeypatch, brain, caplog):
    caplog.set_level("INFO")
    monkeypatch.setitem(sys.modules, "app.brain.agent", None)
    _, state, _ = serve_with_fakes(monkeypatch, ["--no-vision"])
    assert "agent: off" in caplog.text and state.agent_inbox is None


def test_without_an_stt_key_mic_is_still_mounted_and_drops_audio(monkeypatch, brain):
    monkeypatch.setattr(FakeSTT, "from_env", classmethod(lambda cls: None))
    _, state, _ = serve_with_fakes(monkeypatch, ["--no-vision"])
    assert state.agent_inbox is not None and state.mic is not None and brain[0][0] is None


def test_skill_factories_build_skills_from_the_tools_arguments(brain):
    vision_check = sys.modules["app.brain.vision_check"]
    say, wait_loaded = (lambda text: None), (lambda: None)
    f = server.make_skill_factories(lambda: "follow-skill", say=say, wait_loaded=wait_loaded)
    assert set(f) == {"follow", "find_person", "go_to", "bring"}
    assert f["follow"]() == "follow-skill"
    fp = f["find_person"](name="Mom", description=None)
    assert fp.name == "find_person" and fp.args == ("Mom", None, "registry", vision_check.matches_description)
    assert f["go_to"](place="kitchen").args == ("kitchen",)
    b = f["bring"](item="water", person="Mom")
    assert b.args == ("water", "Mom", wait_loaded, say)
    assert b.kw == {"registry": "registry", "matcher": vision_check.matches_description}
    assert server.make_skill_factories(None) == {}                        # no camera: none
    assert "bring" not in server.make_skill_factories(lambda: 1)          # no say / wait_loaded: no bring


def test_follow_only_when_the_search_skills_are_missing(monkeypatch):
    monkeypatch.setitem(sys.modules, "app.skills.search", None)
    made = []
    f = server.make_skill_factories(lambda: made.append(1) or "follow-skill", say=print, wait_loaded=print)
    assert set(f) == {"follow"} and f["follow"]() == "follow-skill" and made == [1]


def test_with_a_camera_the_agent_gets_snapshots_and_skills(monkeypatch, brain):
    from tests.test_main import TEL, FakeUdpLink, FakeVision, FakeWindow, fake_api_start

    seen = fake_api_start(monkeypatch)
    monkeypatch.setattr(server, "make_tts", lambda: None)
    asyncio.run(server.serve(server.parse_args([]), FakeUdpLink(dict(TEL)), vision=FakeVision(),
                             follow_factory=lambda: "follow-skill", window=FakeWindow([-1, -1, "q"]),
                             render=lambda p, h: h))
    tools = FakeAgent.instances[-1].tools
    assert set(tools.skill_factories) == {"follow", "find_person", "go_to", "bring"}
    assert tools.snapshot() is None   # FakeVision has no frame yet
    b = tools.skill_factories["bring"](item="pills", person=None)
    assert b.args[2] == seen["state"].wait_loaded and b.args[3] == seen["state"].add_say


def test_snapshot_is_a_small_jpeg_of_the_newest_frame():
    class Vision:
        p = None

        def latest(self):
            return self.p

    v = Vision()
    snap = server.make_snapshot(v)
    assert snap() is None
    v.p = types.SimpleNamespace(frame=types.SimpleNamespace(image=np.zeros((1080, 1920, 3), np.uint8)))
    jpeg = snap()
    assert jpeg[:2] == b"\xff\xd8"
    import cv2

    img = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
    assert img.shape == (540, 960, 3)


def test_a_crashing_agent_does_not_stop_the_server(monkeypatch, brain, caplog):
    async def boom(self):
        raise RuntimeError("model said no")

    monkeypatch.setattr(FakeAgent, "run", boom)
    _, _, link = serve_with_fakes(monkeypatch, ["--no-vision"])
    assert "agent stopped" in caplog.text and link.events[-2:] == ["x", "close"]
