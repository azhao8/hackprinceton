"""The tools added in Alex's redesign (Sat night): describe_scene(question), wait_for_tray,
check_in_result, learn_place, forget; and the SQLite memory behind remember / recall / forget."""

from __future__ import annotations

import asyncio
import types

from app.brain.tools import ToolBox
from app.memory import Memory
from app.vision.types import Marker


class Host:
    def __init__(self):
        self.events = []

    def emit(self, kind, text="", *, to=None, data=None):
        self.events.append((kind, text, data or {}))

    async def wait_for_senior(self, seconds):
        return None

    async def wait_interjection(self):
        await asyncio.sleep(3600)


def call(tools: ToolBox, name: str, args: dict):
    return asyncio.run(tools.call(name, args))


def test_describe_scene_passes_the_question():
    seen = []

    async def describe(jpeg, question=None):
        seen.append(question)
        return "an orange pill bottle" if question else "a living room"

    tools = ToolBox(snapshot=lambda: b"jpeg", describe=describe)
    assert call(tools, "describe_scene", {"question": "what is she holding?"}).text == "an orange pill bottle"
    assert call(tools, "describe_scene", {"question": None}).text == "a living room"
    assert seen == ["what is she holding?", None]


def test_describe_scene_works_with_an_old_describe_without_questions():
    async def describe(jpeg):
        return "a kitchen"

    tools = ToolBox(snapshot=lambda: b"jpeg", describe=describe)
    assert call(tools, "describe_scene", {"question": "is the stove on?"}).text == "a kitchen"


def test_wait_for_tray():
    async def loaded():
        return True

    async def never():
        await asyncio.sleep(3600)
        return True

    out = call(ToolBox(wait_tray=loaded), "wait_for_tray", {"seconds": 10})
    assert out.ok and out.data == {"loaded": True}
    assert not call(ToolBox(), "wait_for_tray", {"seconds": 10}).ok          # no button: unavailable


def test_wait_for_tray_times_out(monkeypatch):
    async def never():
        await asyncio.sleep(3600)
        return True

    real_wait_for = asyncio.wait_for

    async def quick(aw, timeout):   # 5 s minimum in the tool; don't wait that long in a test
        return await real_wait_for(aw, 0.01)

    monkeypatch.setattr(asyncio, "wait_for", quick)
    out = call(ToolBox(wait_tray=never), "wait_for_tray", {"seconds": 5})
    assert out.ok and out.data == {"loaded": False}


def test_check_in_result_emits_the_answer():
    tools, host = ToolBox(), Host()
    tools.bind(host)
    assert call(tools, "check_in_result", {"answer": "yes"}).ok
    assert not call(tools, "check_in_result", {"answer": "maybe"}).ok
    assert host.events == [("check_in", "yes", {"answer": "yes"})]


def test_learn_place_saves_the_marker_in_view(tmp_path):
    mem = Memory(tmp_path / "m.db")
    near, far = Marker(id=7, cx=0.5, cy=0.5, size=0.2), Marker(id=3, cx=0.2, cy=0.5, size=0.05)
    tools, host = ToolBox(places=mem, perception=lambda: types.SimpleNamespace(markers=(far, near))), Host()
    tools.bind(host)
    out = call(tools, "learn_place", {"name": "Water station"})
    assert out.ok and mem.marker_for("water") == 7 and mem.place_for(7) == "water station"
    assert host.events[-1][0] == "place"


def test_learn_place_reads_the_sign_when_no_name_is_given(tmp_path):
    mem = Memory(tmp_path / "m.db")

    async def describe(jpeg, question=None):
        return "MEDICATION STATION | a shelf with a pill organizer"

    tools = ToolBox(places=mem, snapshot=lambda: b"jpeg", describe=describe,
                    perception=lambda: types.SimpleNamespace(markers=(Marker(id=2, cx=0.5, cy=0.5, size=0.1),)))
    out = call(tools, "learn_place", {"name": None})
    assert out.ok and mem.find_place("medication")["marker"] == 2
    assert mem.find_place("medication station")["description"] == "a shelf with a pill organizer"


def test_learn_place_without_a_card_or_a_name_asks(tmp_path):
    async def describe(jpeg, question=None):
        return "none | a wall"

    tools = ToolBox(places=Memory(tmp_path / "m.db"), snapshot=lambda: b"jpeg", describe=describe,
                    perception=lambda: types.SimpleNamespace(markers=()))
    assert not call(tools, "learn_place", {"name": None}).ok


def test_remember_recall_forget_survive_a_restart(tmp_path):
    path = tmp_path / "m.db"
    tools = ToolBox(memory=Memory(path).facts)
    call(tools, "remember", {"key": "evening pills", "value": "blue bottle, 8 pm"})
    again = ToolBox(memory=Memory(path).facts)                         # a new server process
    assert "blue bottle" in call(again, "recall", {"key": "evening pills"}).text
    assert call(again, "forget", {"key": "evening pills"}).text == "Forgot evening pills."
    assert "Nothing remembered" in call(again, "recall", {"key": "evening pills"}).text


def test_memory_places_events_and_summary(tmp_path):
    mem = Memory(tmp_path / "m.db", seed_places={"station": 1, "couch": 2}, seed_aliases={"meds": "station"})
    assert mem.marker_for("the meds") == 1 and mem.marker_for("sofa") is None
    mem.set_place("water station", marker=1)                      # one marker marks one place
    assert mem.place_for(1) == "water station" and mem.marker_for("station") == 1   # "station" in "water station"
    assert mem.find_place("station")["name"] in ("station", "water station")
    mem.add_event("water", "Water, from Sarah", data={"quote": "Love you"})
    assert [e["title"] for e in mem.today()] == ["Water, from Sarah"]
    assert "water station (marker 1)" in mem.summary() and "Water, from Sarah" in mem.summary()
    assert Memory(tmp_path / "m.db", seed_places={"other": 9}).marker_for("other") is None   # seeds only once
