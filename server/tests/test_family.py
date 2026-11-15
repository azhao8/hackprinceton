"""The family app's server side (app/family.py, contract/web/family.md): sign-in, Send with the bring
stages and the word-for-word note, the check-in consent lock, Ask Miguel, and the fall alert."""

from __future__ import annotations

import asyncio
import types

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from app.family import FamilyHub
from app.link import Health
from app.memory import Memory


class FakeState:
    def __init__(self):
        self.link = types.SimpleNamespace(health=lambda: Health(True, 0.01, 0.01, 10.0))
        self.phone_frames = None
        self.mic = None
        self.skills = types.SimpleNamespace(running=None)
        self.settings = {"camera": "back"}
        self.said, self.messages, self.follow = [], [], True
        self.agent_photos = {3: b"proof"}

    def agent_message(self, text, source, channel):
        self.messages.append((source, text))
        return 200, ""

    def add_say(self, text):
        self.said.append(text)

    def set_settings(self, new):
        self.settings.update(new)

    def set_follow(self, on):
        self.follow = on

    def follow_running(self):
        return self.follow


def hub(tmp_path, **kw) -> tuple[FamilyHub, FakeState]:
    st = FakeState()
    return FamilyHub(st, Memory(tmp_path / "m.db"), snapshot=lambda: b"\xff\xd8jpeg", token="secret", **kw), st


async def connect(h: FamilyHub, token: str = "secret"):
    app = web.Application()
    app.add_routes(h.routes())
    client = TestClient(TestServer(app))
    await client.start_server()
    ws = await client.ws_connect("/family/ws")
    await ws.send_json({"t": "hello", "v": 1, "token": token, "viewer": "m1"})
    return client, ws


async def until(ws, t: str, pred=lambda m: True):
    for _ in range(50):
        m = await asyncio.wait_for(ws.receive_json(), 2)
        if m.get("t") == t and pred(m):
            return m
    raise AssertionError(f"no {t}")


def test_wrong_token_is_refused(tmp_path):
    async def go():
        h, _ = hub(tmp_path)
        client, ws = await connect(h, token="nope")
        m = await ws.receive_json()
        assert m["t"] == "error" and m["code"] == "unauthorized"
        await client.close()
    asyncio.run(go())


def test_send_runs_bring_and_reads_the_note_word_for_word(tmp_path):
    async def go():
        h, st = hub(tmp_path)
        client, ws = await connect(h)
        welcome = await until(ws, "welcome")
        assert welcome["viewer"]["name"] == "Sarah" and welcome["resident"]["short"] == "Mom"
        await until(ws, "events")
        await ws.send_json({"t": "send", "ref": "r1", "item": "water", "label": "Water", "message": "Love you, Mom"})
        ack = await until(ws, "ack")
        assert ack["ref"] == "r1" and ack["id"].startswith("d")
        source, text = st.messages[-1]
        assert source == "guardian" and "bring(item='water', person='Mom')" in text and "Love you" not in text
        await ws.send_json({"t": "send", "ref": "r2", "item": "water", "label": "Water"})
        assert (await until(ws, "error"))["code"] == "busy"                      # one at a time
        for stage in ("sent", "loading", "on_the_way"):
            h.on_bring_step(stage, "...")
        s = await until(ws, "state", lambda m: (m["delivery"] or {}).get("stage") == "on_the_way")
        assert s["mode"] == "delivering"
        h.on_bring_step("delivered", "delivered")
        ev = await until(ws, "event")
        assert ev["kind"] == "water" and ev["quote"] == "Love you, Mom" and ev["photo"].startswith("/family/media/")
        assert st.said == ["Love you, Mom"]                                       # word for word, not by Claude
        photo = await client.get(ev["photo"])
        assert photo.status == 200 and await photo.read() == b"\xff\xd8jpeg"
        await client.close()
    asyncio.run(go())


def test_a_failed_bring_shows_the_reason(tmp_path):
    async def go():
        h, st = hub(tmp_path)
        client, ws = await connect(h)
        await ws.send_json({"t": "send", "ref": "r1", "item": "medication", "label": "Evening pills"})
        await until(ws, "ack")
        h.on_bring_step("failed", "I have the medication but couldn't find Mom: not found")
        s = await until(ws, "state", lambda m: (m["delivery"] or {}).get("stage") == "failed")
        assert s["delivery"]["detail"].startswith("I have the medication")
        await client.close()
    asyncio.run(go())


def test_check_in_sends_video_only_after_she_says_yes(tmp_path):
    async def go():
        h, st = hub(tmp_path)
        client, ws = await connect(h)
        await ws.send_json({"t": "check_in", "ref": "c", "action": "request"})
        await until(ws, "ack")
        assert "check_in_result" in st.messages[-1][1]
        assert h.check_in["phase"] == "asking"
        await ws.send_json({"t": "rtc", "call": "x", "sdp": {"type": "offer", "sdp": ""}})
        assert (await until(ws, "error"))["code"] == "no_consent"
        h.on_agent_event({"kind": "check_in", "text": "yes", "data": {"answer": "yes"}})
        frame = await until(ws, "frame")
        assert frame["call"] == h.check_in["id"] and st.settings["camera"] == "front" and st.follow is False
        await ws.send_json({"t": "check_in", "ref": "e", "action": "end"})
        await until(ws, "state", lambda m: m["check_in"]["phase"] == "idle")
        assert st.settings["camera"] == "back"
        await client.close()
    asyncio.run(go())


def test_a_no_declines(tmp_path):
    h, _ = hub(tmp_path)
    h.check_in = {"phase": "asking", "id": "c1", "by": "Sarah"}
    h.on_agent_event({"kind": "check_in", "text": "no", "data": {"answer": "no"}})
    assert h.check_in["phase"] == "declined" and h._call_task is None


def test_ask_miguel_and_his_replies(tmp_path):
    async def go():
        h, st = hub(tmp_path)
        client, ws = await connect(h)
        await ws.send_json({"t": "ask", "ref": "a", "text": "Ask Mom if she wants a walk"})
        await until(ws, "ack")
        assert st.messages[-1] == ("guardian", "[family app, from Sarah] Ask Mom if she wants a walk")
        h.on_agent_event({"kind": "reply", "text": "She said yes!", "data": {"photo_url": "/agent/photo/3.jpg"}})
        ev = await until(ws, "event")
        assert ev["kind"] == "message" and ev["note"] == "She said yes!" and ev["photo"].startswith("/family/media/")
        await client.close()
    asyncio.run(go())


def test_fall_alert_goes_to_the_agent_and_anyone_can_handle_it(tmp_path):
    async def go():
        h, st = hub(tmp_path)
        client, ws = await connect(h)
        await until(ws, "events")
        alert = h.raise_alert("She may be on the floor.")
        assert st.messages[-1][0] == "operator" and "fall alert" in st.messages[-1][1]
        s = await until(ws, "state", lambda m: m["alert"] is not None)
        assert s["alert"]["status"] == "active" and s["mode"] == "with_mom"
        h.on_agent_event({"kind": "heard", "text": "I slipped", "data": {"source": "senior"}})
        h.on_agent_event({"kind": "reply", "text": "Possible fall", "data": {}})
        assert h.alert["heard"] == "I slipped" and "Told the family" in h.alert["did"]
        await ws.send_json({"t": "alert", "ref": "h", "id": alert["id"], "action": "handled"})
        await until(ws, "ack")
        assert h.alert["status"] == "handled" and h.alert["handled_by"] == "Sarah"
        await client.close()
    asyncio.run(go())


def test_without_a_token_only_this_laptop_may_sign_in(tmp_path):
    async def go():
        st = FakeState()
        h = FamilyHub(st, None, token="")
        client, ws = await connect(h, token="")
        assert (await ws.receive_json())["t"] == "welcome"      # the test client is local
        await client.close()
    asyncio.run(go())


def test_control_page_memory_page(tmp_path):
    from app.api import ApiState
    from app.arbiter import Arbiter

    mem = Memory(tmp_path / "c.db", seed_places={"station": 1})
    forgotten = []
    reg = types.SimpleNamespace(names=lambda: ["Mom"], forget=forgotten.append)
    state = ApiState(Arbiter(), FakeState().link, memory=mem, registry=reg)
    view = state.control_message({"t": "memory_get"})
    assert view["people"] == ["Mom"] and view["places"][0]["name"] == "station"
    view = state.control_message({"t": "memory_set", "what": "fact", "key": "evening pills", "value": "blue bottle"})
    assert view["facts"] == [{"key": "evening pills", "value": "blue bottle", "source": "control page"}]
    view = state.control_message({"t": "memory_set", "what": "place", "name": "Water station", "marker": "4",
                                  "aliases": "water, drinks"})
    assert {"name": "water station", "marker": 4, "aliases": ["drinks", "water"], "description": ""} in view["places"]
    state.control_message({"t": "memory_set", "what": "person", "action": "delete", "name": "Mom"})
    assert forgotten == ["Mom"]
    view = state.control_message({"t": "memory_set", "what": "fact", "action": "delete", "key": "evening pills"})
    assert view["facts"] == []
