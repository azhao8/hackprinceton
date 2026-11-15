"""#113: who is speaking comes from the camera, not from who the chat was with before.

The mic doesn't say who spoke, so every request ends with a "Camera now" note: who the camera
sees, who is most likely speaking, and who from earlier in the conversation is not in view now.
Fake camera views and the scripted fake client; the real-API check is evals/who_is_speaking.py."""

from __future__ import annotations

import asyncio
import logging

from app.brain.agent import Agent
from app.brain.tools import CameraView, Seen, ToolBox, ToolOutcome, speaker_note
from app.brain.types import Utterance
from tests.brain.test_agent import FakeClient, msg, text, tool

SARAH = Seen("Sarah", "center", "near")
STRANGER = Seen(None, "center", "near")


# --- who is most likely speaking -----------------------------------------------------------------


def test_the_speaker_is_the_closest_person_when_recognized_and_alone_that_close():
    assert CameraView(people=(SARAH,)).speaker == "Sarah"
    assert CameraView(people=(Seen("Sarah", "left", "middle distance"),)).speaker == "Sarah"
    assert CameraView(people=(SARAH, Seen(None, "left", "far"))).speaker == "Sarah"   # a stranger far behind


def test_no_speaker_for_a_stranger_nobody_a_far_person_two_close_people_or_no_picture():
    assert CameraView(people=(STRANGER,)).speaker is None
    assert CameraView(people=(STRANGER, Seen("Sarah", "left", "far"))).speaker is None
    assert CameraView().speaker is None                                         # nobody
    assert CameraView(people=(Seen("Sarah", "center", "far"),)).speaker is None
    assert CameraView(people=(SARAH, Seen("Alex", "left", "near"))).speaker is None
    assert CameraView(people=(SARAH, Seen(None, "right", "near"))).speaker is None
    assert CameraView(seeing=False).speaker is None


def test_view_text_matches_the_old_people_in_view_wording():
    view = CameraView(people=(Seen("Alex", "center", "near"), Seen(None, "left", "far")), more=2)
    assert view.text == "Alex (center, near); someone I don't recognize (left, far); and 2 more"
    assert view.names == ("Alex",)
    assert CameraView().text == "nobody"
    assert "isn't seeing" in CameraView(seeing=False).text


# --- the note -------------------------------------------------------------------------------------


def test_note_names_the_speaker_and_says_the_earlier_person_is_not_them():
    note = speaker_note(CameraView(people=(SARAH,)), ["Alex"])
    assert note.startswith("Camera now (your only clue to who is speaking): Sarah (center, near).")
    assert "most likely Sarah" in note
    assert "Earlier in this chat you talked with Alex, who is not in view now: the speaker is Sarah, not Alex." in note


def test_note_for_a_stranger_says_the_speaker_is_unknown_and_to_use_no_name():
    note = speaker_note(CameraView(people=(STRANGER,)), ["Alex"])
    assert "You don't recognize them, so you don't know who is speaking." in note
    assert "Earlier in this chat you talked with Alex, but that doesn't mean it is now" in note
    assert note.endswith("Use no name and no one's personal memories; if it matters, ask who they are.")
    assert "most likely" not in note


def test_note_for_nobody_or_no_picture():
    assert "Nobody is in view, so you can't tell who is speaking." in speaker_note(CameraView())
    no_picture = speaker_note(CameraView(seeing=False))
    assert "isn't seeing anything" in no_picture and "You can't tell who is speaking." in no_picture
    assert "Earlier" not in speaker_note(CameraView())                         # a new conversation


def test_note_leaves_out_people_still_in_view_and_lists_the_rest_newest_first_once():
    assert "Earlier" not in speaker_note(CameraView(people=(SARAH,)), ["sarah"])
    note = speaker_note(CameraView(people=(STRANGER,)), ["Alex", "Mom", "Alex", "Dad", "Grant"])
    assert "you talked with Grant, Dad and Alex, but" in note                   # three at most, newest first


# --- the agent ------------------------------------------------------------------------------------


class Camera(ToolBox):
    """A ToolBox whose camera sees what the test says; this_is always succeeds."""

    def __init__(self) -> None:
        super().__init__()
        self.view: CameraView | None = CameraView(people=(STRANGER,))

    def camera_view(self, *a, **kw) -> CameraView | None:
        return self.view

    def this_is(self, name: str) -> ToolOutcome:
        return ToolOutcome(True, f"Saved what {name} looks like.")


def camera_note(call) -> str:
    """The Camera now note of the newest request in this call."""
    for m in reversed(call["messages"]):
        if m["role"] == "user" and isinstance(m["content"], list):
            notes = [b["text"] for b in m["content"] if b.get("type") == "text" and b["text"].startswith("Camera now")]
            if notes:
                return notes[-1]
    raise AssertionError("no Camera now note")


def test_after_this_is_alex_a_different_person_in_view_is_told_apart_from_alex(caplog):
    caplog.set_level(logging.INFO, logger="app.brain.agent")
    tools = Camera()
    client = FakeClient([
        msg(tool("this_is", "t1", name="Alex", step=None)),
        msg(text("Nice to meet you, Alex!"), stop="end_turn"),
        msg(text("You're Sarah!"), stop="end_turn"),
        msg(text("Who am I talking to?"), stop="end_turn"),
    ])
    agent = Agent(tools, client=client, ack=False)

    async def scenario():
        await agent.handle(Utterance("senior", "Miguel, this is Alex"))
        await agent.idle()
        tools.view = CameraView(people=(SARAH,))
        await agent.handle(Utterance("senior", "Miguel, who am I?"))
        await agent.idle()
        agent.reset_conversation()   # a new conversation: nobody from before
        tools.view = CameraView(people=(STRANGER,))
        await agent.handle(Utterance("senior", "Miguel, who am I?"))
        await agent.idle()

    asyncio.run(scenario())
    first, _, second, third = client.calls
    assert "Earlier" not in camera_note(first)
    assert "the speaker is Sarah, not Alex" in camera_note(second)   # Alex came from this_is
    assert "Earlier" not in camera_note(third)
    assert any("Camera now" in r.getMessage() and "Sarah" in r.getMessage() for r in caplog.records)


def test_a_person_the_camera_recognized_counts_as_someone_the_chat_was_with():
    tools = Camera()
    tools.view = CameraView(people=(Seen("Mom", "center", "near"),))
    client = FakeClient([msg(text("Hi Mom!"), stop="end_turn"), msg(text("Who am I talking to?"), stop="end_turn")])
    agent = Agent(tools, client=client, ack=False)

    async def scenario():
        await agent.handle(Utterance("senior", "Miguel, hello"))
        await agent.idle()
        tools.view = CameraView()
        await agent.handle(Utterance("senior", "Miguel, what's my name?"))
        await agent.idle()

    asyncio.run(scenario())
    note = camera_note(client.calls[1])
    assert "Nobody is in view" in note and "Earlier in this chat you talked with Mom" in note


def test_a_message_from_the_app_gets_who_is_in_view_without_the_speaker_rules():
    """A guardian's message says who sent it: "use no name and no one's memories" would stop
    Miguel telling the family about Mom."""
    tools = Camera()
    client = FakeClient([msg(text("She's fine."), stop="end_turn")])
    agent = Agent(tools, client=client, ack=False)

    async def scenario():
        await agent.handle(Utterance("guardian", "How is Mom doing?"))
        await agent.idle()

    asyncio.run(scenario())
    texts = [b["text"] for m in client.calls[0]["messages"] if isinstance(m["content"], list)
             for b in m["content"] if b.get("type") == "text"]
    assert "People in view now: someone I don't recognize (center, near)." in texts
    assert not any(t.startswith("Camera now") for t in texts)


def test_no_camera_no_note():
    client = FakeClient([msg(text("Hi!"), stop="end_turn")])
    agent = Agent(ToolBox(), client=client, ack=False)

    async def scenario():
        await agent.handle(Utterance("senior", "Miguel, hello"))
        await agent.idle()

    asyncio.run(scenario())
    texts = [b["text"] for m in client.calls[0]["messages"] if isinstance(m["content"], list)
             for b in m["content"] if b.get("type") == "text"]
    assert not any(t.startswith("Camera now") for t in texts)
