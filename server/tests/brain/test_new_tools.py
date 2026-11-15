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

    real_wait = asyncio.wait

    async def quick(fs, *, timeout=None, return_when=asyncio.ALL_COMPLETED):   # 5 s minimum in the tool
        return await real_wait(fs, timeout=0.01, return_when=return_when)

    monkeypatch.setattr(asyncio, "wait", quick)
    tools = ToolBox(wait_tray=never)
    tools.bind(Host())                                                       # nobody speaks either
    out = call(tools, "wait_for_tray", {"seconds": 5})
    assert out.ok and out.data == {"loaded": False}


class SpeakingHost(Host):
    """A host whose wait_interjection ends when `speak()` is called; records cancelled waits."""

    def __init__(self):
        super().__init__()
        self.spoke = asyncio.Event()
        self.cancelled = []

    async def wait_interjection(self):
        try:
            await self.spoke.wait()
        except asyncio.CancelledError:
            self.cancelled.append("interjection")
            raise


def test_wait_for_tray_comes_back_when_someone_speaks():
    """'It's in your tray' is queued for Claude: the tool returns at once instead of waiting 300 s."""
    host, cancelled = SpeakingHost(), []

    async def button():
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            cancelled.append("button")
            raise
        return True

    async def scenario():
        tools = ToolBox(wait_tray=button)
        tools.bind(host)
        task = asyncio.create_task(tools.call("wait_for_tray", {"seconds": 300}))
        await asyncio.sleep(0.01)
        host.spoke.set()
        out = await asyncio.wait_for(task, 1)
        await asyncio.sleep(0)   # let the cancelled button wait unwind
        return out

    out = asyncio.run(scenario())
    assert out.ok and out.data == {"loaded": None, "spoke": True}
    assert "Someone spoke" in out.text and "wait_for_tray again" in out.text
    assert cancelled == ["button"]                    # the Tray loaded waiter doesn't linger


def test_wait_for_tray_still_ends_on_the_button():
    host = SpeakingHost()

    async def button():
        await asyncio.sleep(0.01)
        return True

    async def scenario():
        tools = ToolBox(wait_tray=button)
        tools.bind(host)
        out = await tools.call("wait_for_tray", {"seconds": 300})
        await asyncio.sleep(0)
        return out

    out = asyncio.run(scenario())
    assert out.ok and out.data == {"loaded": True}
    assert host.cancelled == ["interjection"]


def test_stop_cancels_both_tray_waits():
    host, cancelled = SpeakingHost(), []

    async def button():
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            cancelled.append("button")
            raise
        return True

    async def scenario():
        tools = ToolBox(wait_tray=button)
        tools.bind(host)
        task = asyncio.create_task(tools.call("wait_for_tray", {"seconds": 300}))
        await asyncio.sleep(0.01)
        task.cancel()                                  # the senior's stop cancels the agent's task
        try:
            await task
        except asyncio.CancelledError:
            pass
        else:
            raise AssertionError("the cancel was swallowed")
        await asyncio.sleep(0)

    asyncio.run(scenario())
    assert cancelled == ["button"] and host.cancelled == ["interjection"]


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


def test_learn_place_refuses_a_place_without_a_marker(tmp_path):
    """'This is the kitchen' with no card in view: go_to couldn't reach it, so nothing is saved."""
    mem, asked = Memory(tmp_path / "m.db"), []

    async def describe(jpeg, question=None):
        asked.append(question)
        return "KITCHEN | a counter with a kettle"

    no_card = types.SimpleNamespace(markers=())
    tools = ToolBox(places=mem, snapshot=lambda: b"jpeg", describe=describe, perception=lambda: no_card)
    out = call(tools, "learn_place", {"name": "kitchen"})
    assert not out.ok and out.text == "No marker card in view for 'kitchen'. Ask them to hold the card in front of you."
    assert asked == []                                           # no slow camera question first
    out = call(tools, "learn_place", {"name": None})            # name read off the sign, still no card
    assert not out.ok and "No marker card in view for 'KITCHEN'" in out.text
    assert mem.places() == []


def test_learn_place_without_a_card_keeps_the_marker_it_had(tmp_path):
    mem = Memory(tmp_path / "m.db", seed_places={"kitchen": 4})

    async def describe(jpeg, question=None):
        return "none | a counter with a kettle"

    tools = ToolBox(places=mem, snapshot=lambda: b"jpeg", describe=describe,
                    perception=lambda: types.SimpleNamespace(markers=()))
    out = call(tools, "learn_place", {"name": "Kitchen"})
    assert out.ok and "marker 4" in out.text
    assert mem.marker_for("kitchen") == 4 and mem.find_place("kitchen")["description"] == "a counter with a kettle"


def test_learn_place_by_an_alias_updates_that_place(tmp_path):
    """'This is the medication station' (an alias of station) moves station's marker, keeps its names."""
    mem = Memory(tmp_path / "m.db", seed_places={"station": 1},
                 seed_aliases={"medication station": "station", "pills": "station"})
    tools = ToolBox(places=mem, perception=lambda: types.SimpleNamespace(markers=(Marker(id=6, cx=0.5, cy=0.5, size=0.1),)))
    assert call(tools, "learn_place", {"name": "Medication station"}).ok
    assert mem.known_places() == ["station"] and mem.marker_for("pills") == 6


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


def test_set_place_keeps_the_marker_aliases_and_description(tmp_path):
    mem = Memory(tmp_path / "m.db", seed_places={"station": 1, "kitchen": 4}, seed_aliases={"pills": "station"})
    mem.set_place("Station", aliases=["water"])                  # re-learnt with no card, a new alias
    assert mem.marker_for("pills") == 1 and mem.marker_for("water") == 1   # seeded alias and marker kept
    mem.set_place("kitchen", description="by the fridge")
    mem.set_place("kitchen", description="  ")                    # empty keeps the description
    assert mem.find_place("kitchen") == {"name": "kitchen", "marker": 4, "aliases": [], "description": "by the fridge"}
    mem.set_place("couch", marker=4)                              # one marker marks one place
    assert mem.place_for(4) == "couch" and mem.find_place("kitchen")["marker"] is None


def test_find_place_matches_whole_words(tmp_path):
    mem = Memory(tmp_path / "m.db", seed_places={"station": 1, "couch": 2, "door": 3, "water station": 5},
                 seed_aliases={"pills": "station", "meds": "station", "front door": "door", "sofa": "couch"})
    assert mem.find_place("door key") is None and mem.marker_for("door key") is None   # a key, not the door
    assert mem.find_place("outdoor shoes") is None                # 'door' is only part of a word
    assert all(mem.find_place(s) is None for s in ("", "   ", "the", "?!"))
    assert mem.find_place("Pills!")["name"] == "station"          # alias, any case and punctuation
    assert mem.marker_for("the front door") == 3
    assert mem.find_place("water")["name"] == "water station"     # every word said is in the name
    assert mem.find_place("my evening pills")["name"] == "station"   # the alias ends what was said
    assert mem.find_place("Mom's sofa")["name"] == "couch"
    assert mem.find_place("station")["name"] == "station"         # exact beats 'water station'
    assert mem.find_place("pills", exact=True)["name"] == "station" and mem.find_place("water", exact=True) is None


def test_find_place_doesnt_guess_between_two_places(tmp_path):
    mem = Memory(tmp_path / "m.db", seed_places={"water station": 5, "charging station": 6})
    assert mem.find_place("station") is None
    assert mem.find_place("charging")["marker"] == 6
