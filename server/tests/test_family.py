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
        self.working = False          # the agent's ApiState.agent_working

    def agent_working(self):
        return self.working

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


async def connect(h: FamilyHub, token: str = "secret", viewer: str = "m1"):
    app = web.Application()
    app.add_routes(h.routes())
    client = TestClient(TestServer(app))
    await client.start_server()
    ws = await client.ws_connect("/family/ws")
    await ws.send_json({"t": "hello", "v": 1, "token": token, "viewer": viewer})
    return client, ws


async def nothing(ws, t: str, seconds: float = 0.6) -> bool:
    """True if no message of type `t` arrives within `seconds`."""
    try:
        while True:
            m = await asyncio.wait_for(ws.receive_json(), seconds)
            if m.get("t") == t:
                return False
    except asyncio.TimeoutError:
        return True


async def go_live(h: FamilyHub, ws) -> None:
    await ws.send_json({"t": "check_in", "ref": "c", "action": "request"})
    await until(ws, "ack")
    h.on_agent_event({"kind": "check_in", "text": "yes", "data": {"answer": "yes"}})
    await until(ws, "frame")


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
        assert st.settings["camera"] == "back" and st.follow is True     # back to walking with her
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
        h.on_agent_event({"kind": "reply", "text": "Got it, I'm on it.", "data": {"ack": True}})   # not an answer
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


def test_listening_mode_follows_the_mic_hubs_listening_state(tmp_path):
    import asyncio as aio

    from app.speech.mic import MicHub

    h, st = hub(tmp_path)
    st.follow = False
    mic = MicHub(None, aio.Queue(), "Miguel")
    st.mic = types.SimpleNamespace(hub=mic)
    assert h.snapshot_state()["mode"] == "idle"
    mic.set_awaiting(True)                       # the agent waits for her answer
    assert h.snapshot_state()["mode"] == "listening"
    mic.set_awaiting(False)
    mic.open_once("tap")                         # she tapped his face
    assert h.snapshot_state()["mode"] == "listening"



def test_ending_a_check_in_while_he_asks_calls_it_off(tmp_path):
    async def go():
        h, st = hub(tmp_path)
        client, ws = await connect(h)
        await ws.send_json({"t": "check_in", "ref": "c", "action": "request"})
        await until(ws, "ack")
        await ws.send_json({"t": "check_in", "ref": "e", "action": "end"})
        await until(ws, "ack", lambda m: m["ref"] == "e")
        assert "cancelled the video check-in" in st.messages[-1][1] and h.check_in["phase"] == "idle"
        await ws.send_json({"t": "check_in", "ref": "c2", "action": "request"})   # a new one starts fresh
        await until(ws, "ack", lambda m: m["ref"] == "c2")
        assert h.check_in["phase"] == "asking" and "check_in_result" in st.messages[-1][1]
        await client.close()
    asyncio.run(go())


def nulls(v, path="") -> list[str]:
    """Every place a message carries null (the app's parser drops the whole message for one)."""
    if v is None:
        return [path or "."]
    if isinstance(v, dict):
        return [p for k, x in v.items() for p in nulls(x, f"{path}.{k}")]
    if isinstance(v, list):
        return [p for i, x in enumerate(v) for p in nulls(x, f"{path}[{i}]")]
    return []


def test_an_alert_before_the_first_camera_frame_has_no_null_photo(tmp_path):
    async def go():
        st = FakeState()
        h = FamilyHub(st, Memory(tmp_path / "m.db"), snapshot=lambda: None, token="secret")
        client, ws = await connect(h)
        await until(ws, "events")
        h.raise_alert("She may be on the floor.")
        s = await until(ws, "state", lambda m: m["alert"] is not None)
        assert "photo" not in s["alert"] and nulls({**s, "delivery": 0}) == []
        await client.close()
    asyncio.run(go())


def test_what_she_said_and_handled_reach_the_app_without_a_mode_change(tmp_path):
    async def go():
        h, st = hub(tmp_path)
        client, ws = await connect(h)
        await until(ws, "events")
        alert = h.raise_alert("She may be on the floor.")
        await until(ws, "state", lambda m: m["alert"] is not None)
        h.on_agent_event({"kind": "heard", "text": "I slipped. My hip hurts.", "data": {"source": "senior"}})
        s = await until(ws, "state", lambda m: (m["alert"] or {}).get("heard") == "I slipped. My hip hurts.")
        assert s["mode"] == "with_mom"
        h.on_agent_event({"kind": "reply", "text": "She fell; photo attached.", "data": {}})
        h.on_agent_event({"kind": "reply", "text": "She's sitting up now.", "data": {}})
        assert h.alert["did"].count("Told the family") == 1
        st.phone_frames = types.SimpleNamespace(age=lambda: None)   # link down: the mode stays offline
        await until(ws, "state", lambda m: m["mode"] == "offline")
        await ws.send_json({"t": "alert", "ref": "h", "id": alert["id"], "action": "handled"})
        s = await until(ws, "state", lambda m: (m["alert"] or {}).get("status") == "handled")
        assert s["alert"]["handled_by"] == "Sarah" and s["mode"] == "offline"
        await client.close()
    asyncio.run(go())


def test_another_task_ending_does_not_fail_a_delivery_still_queued(tmp_path):
    async def go():
        h, st = hub(tmp_path)
        client, ws = await connect(h)
        await ws.send_json({"t": "send", "ref": "r1", "item": "water", "label": "Water"})
        await until(ws, "ack")
        st.working = True    # Mom's chat ends; the family's request is next in line
        h.on_agent_event({"kind": "task", "text": "chatted", "data": {"id": "task-1", "status": "done"}})
        await asyncio.sleep(0.5)
        assert h.delivery["stage"] == "sent"
        st.working = False   # he finished everything without calling bring
        h.on_agent_event({"kind": "reply", "text": "I couldn't find the tray.", "data": {}})
        h.on_agent_event({"kind": "task", "text": "done", "data": {"id": "task-2", "status": "done"}})
        s = await until(ws, "state", lambda m: (m["delivery"] or {}).get("stage") == "failed")
        assert s["delivery"]["detail"] == "I couldn't find the tray."
        await client.close()
    asyncio.run(go())


def test_a_check_in_he_never_answers_is_declined(tmp_path):
    async def go():
        h, st = hub(tmp_path)
        client, ws = await connect(h)
        await ws.send_json({"t": "check_in", "ref": "c", "action": "request"})
        await until(ws, "ack")
        h.on_agent_event({"kind": "error", "text": "Claude API error", "data": {}})   # no check_in_result
        s = await until(ws, "state", lambda m: m["check_in"]["phase"] == "declined")
        assert s["mode"] != "listening"
        await client.close()
    asyncio.run(go())


def test_a_check_in_times_out_while_he_is_busy(tmp_path, monkeypatch):
    import app.family as family

    monkeypatch.setattr(family, "ASK_TIMEOUT_S", 0.2)

    async def go():
        h, st = hub(tmp_path)
        st.working = True    # busy with something else: the request waits behind it
        client, ws = await connect(h)
        await ws.send_json({"t": "check_in", "ref": "c", "action": "request"})
        await until(ws, "ack")
        ev = await until(ws, "event", lambda m: m["kind"] == "check_in")     # sent just before the state
        assert ev["note"] == "Miguel was busy and couldn't ask her."
        await until(ws, "state", lambda m: m["check_in"]["phase"] == "declined")
        assert "Nobody answered" in st.messages[-1][1]
        await client.close()
    asyncio.run(go())


def test_an_error_without_a_ref_has_no_null_ref(tmp_path):
    async def go():
        h, _ = hub(tmp_path)
        client, ws = await connect(h)
        await ws.send_json({"t": "dance"})
        m = await until(ws, "error")
        assert "ref" not in m and m["code"] == "bad_request"
        await client.close()
    asyncio.run(go())


def test_frames_and_the_check_in_belong_to_whoever_asked(tmp_path):
    async def go():
        h, st = hub(tmp_path)
        c1, sarah = await connect(h)
        c2, david = await connect(h, viewer="m2")
        await until(david, "events")
        await go_live(h, sarah)
        s = await until(david, "state", lambda m: m["mode_note"].startswith("On a call"))
        assert s["check_in"] == {"phase": "idle"}            # David sees Mom's on a call, not Sarah's call
        assert await nothing(david, "frame")
        await david.send_json({"t": "check_in", "ref": "d", "action": "request"})
        assert (await until(david, "error"))["code"] == "busy"
        await c1.close()
        await c2.close()
    asyncio.run(go())


def test_the_call_ends_when_the_caller_leaves(tmp_path):
    async def go():
        h, st = hub(tmp_path)
        client, ws = await connect(h)
        await go_live(h, ws)
        await ws.close()
        for _ in range(50):
            if h.check_in["phase"] == "idle":
                break
            await asyncio.sleep(0.02)
        assert h.check_in["phase"] == "idle" and st.settings["camera"] == "back" and h._call_task is None
        await client.close()
    asyncio.run(go())


def test_she_can_end_the_call(tmp_path):
    async def go():
        h, st = hub(tmp_path)
        client, ws = await connect(h)
        await go_live(h, ws)
        h.on_agent_event({"kind": "check_in", "text": "no", "data": {"answer": "no"}})   # "that's enough"
        await until(ws, "state", lambda m: m["check_in"]["phase"] == "idle")
        await go_live(h, ws)
        h.on_agent_event({"kind": "heard", "text": "Miguel, stop", "data": {"source": "senior"}})
        await until(ws, "state", lambda m: m["check_in"]["phase"] == "idle")
        await client.close()
    asyncio.run(go())


def test_a_new_check_in_waits_while_he_may_still_answer_the_called_off_one(tmp_path):
    async def go():
        h, st = hub(tmp_path)
        client, ws = await connect(h)
        await ws.send_json({"t": "check_in", "ref": "c1", "action": "request"})
        await until(ws, "ack")
        st.working = True                                        # still asking her about c1
        await ws.send_json({"t": "check_in", "ref": "e", "action": "end"})
        await until(ws, "ack", lambda m: m["ref"] == "e")
        await ws.send_json({"t": "check_in", "ref": "c2", "action": "request"})
        assert (await until(ws, "error"))["code"] == "busy"
        st.working = False                                       # done: no late answer can come now
        await ws.send_json({"t": "check_in", "ref": "c3", "action": "request"})
        await until(ws, "ack", lambda m: m["ref"] == "c3")
        assert h.check_in["phase"] == "asking"
        await client.close()
    asyncio.run(go())


def test_a_bring_mom_asked_for_doesnt_move_the_familys_delivery(tmp_path):
    async def go():
        h, st = hub(tmp_path)
        client, ws = await connect(h)
        await ws.send_json({"t": "send", "ref": "r1", "item": "water", "label": "Water", "message": "Love you"})
        await until(ws, "ack")
        h.on_bring_step("delivered", "here are your pills", item="pills")    # her own request, by voice
        assert h.delivery["stage"] == "sent" and st.said == []
        h.on_bring_step("loading", "waiting for the glass of water", item="glass of water")
        assert h.delivery["stage"] == "loading"
        await client.close()
    asyncio.run(go())


def test_a_hello_that_isnt_an_object_is_refused(tmp_path):
    async def go():
        h, _ = hub(tmp_path)
        app = web.Application()
        app.add_routes(h.routes())
        client = TestClient(TestServer(app))
        await client.start_server()
        ws = await client.ws_connect("/family/ws")
        await ws.send_json(["hello"])
        m = await ws.receive_json()
        assert m["code"] == "unauthorized"
        await client.close()
    asyncio.run(go())


def test_a_camera_error_doesnt_stop_the_calls_video(tmp_path):
    async def go():
        st = FakeState()
        shots = iter([RuntimeError("camera hiccup"), b"\xff\xd8ok"])

        def snapshot():
            shot = next(shots, b"\xff\xd8ok")
            if isinstance(shot, Exception):
                raise shot
            return shot

        h = FamilyHub(st, Memory(tmp_path / "m.db"), snapshot=snapshot, token="secret")
        client, ws = await connect(h)
        await ws.send_json({"t": "check_in", "ref": "c", "action": "request"})
        await until(ws, "ack")
        h.on_agent_event({"kind": "check_in", "text": "yes", "data": {"answer": "yes"}})
        assert (await until(ws, "frame"))["jpeg"]
        await client.close()
    asyncio.run(go())


def test_through_a_tunnel_on_this_laptop_the_app_needs_the_token(tmp_path):
    from unittest import mock

    from aiohttp.test_utils import make_mocked_request

    laptop = mock.Mock()
    laptop.get_extra_info.return_value = ("127.0.0.1", 5555)   # cloudflared connects from this laptop
    h = FamilyHub(FakeState(), None, token="")
    direct = make_mocked_request("GET", "/family/ws", transport=laptop)
    tunneled = make_mocked_request("GET", "/family/ws", headers={"CF-Connecting-IP": "203.0.113.9"}, transport=laptop)
    assert h._token_ok("", direct) is True and h._token_ok("", tunneled) is False


def test_alert_did_keeps_the_latest_lines(tmp_path):
    h, _ = hub(tmp_path)
    h.alert = {"id": "a1", "did": [], "status": "active"}
    for i in range(20):
        h._did(f"Said: line {i}")
    h._did("Said: line 19")
    assert h.alert["did"] == [f"Said: line {i}" for i in range(12, 20)]
