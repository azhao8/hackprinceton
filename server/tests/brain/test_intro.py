"""introduce_yourself: Miguel's prepared introduction for judges and visitors."""

from __future__ import annotations

import asyncio

from app.api import STOCK_LINES, TTS_MAX_CHARS
from app.brain.prompt import EFFORT_CHAT, INTRO_LINE, effort_for
from app.brain.spoken import clean_spoken
from app.brain.tools import ToolBox
from app.brain.types import Utterance

from tests.brain.test_agent import make, msg, text, tool


class Host:
    def __init__(self):
        self.events = []

    def emit(self, kind, text="", *, to=None, data=None):
        self.events.append((kind, text, to))

    async def wait_for_senior(self, seconds):
        return None

    async def wait_interjection(self):
        await asyncio.sleep(3600)


def test_introduce_yourself_says_the_prepared_line():
    tools, host = ToolBox(), Host()
    tools.bind(host)
    out = asyncio.run(tools.call("introduce_yourself", {}))
    assert out.ok and out.data["text"] == INTRO_LINE
    assert host.events == [("say", INTRO_LINE, "senior")]


def test_the_intro_opens_the_answer_window_though_it_ends_with_a_period():
    seen = []
    host = Host()
    host.emit = lambda kind, text="", *, to=None, data=None: seen.append((kind, data))
    tools = ToolBox()
    tools.bind(host)
    asyncio.run(tools.call("introduce_yourself", {}))
    assert seen == [("say", {"asks": True})]          # mic.py opens the window after a line that asks
    assert not INTRO_LINE.rstrip('"').endswith("?")   # ...which a "?" check alone would miss


def test_introduce_yourself_takes_no_arguments_and_leaves_the_strict_slots():
    d = {t["name"]: t for t in ToolBox().definitions()}["introduce_yourself"]
    assert d["input_schema"]["properties"] == {} and d["strict"] is False


def test_the_intro_plays_at_once_and_stays_short():
    assert INTRO_LINE in STOCK_LINES                 # made at startup: no wait for Cartesia
    assert clean_spoken(INTRO_LINE) == INTRO_LINE    # what's said is exactly what was made
    assert len(INTRO_LINE) <= TTS_MAX_CHARS
    assert len(INTRO_LINE.split()) <= 45             # about 15 seconds out loud
    assert INTRO_LINE.endswith('Just say "Miguel" first.')


def test_asking_for_the_intro_gets_no_on_it_first():
    assert effort_for("Miguel, introduce yourself", "senior") == EFFORT_CHAT
    assert effort_for("Who are you?", "senior") == EFFORT_CHAT


def test_the_agent_says_the_intro_once_and_keeps_its_log_note_quiet():
    script = [msg(tool("introduce_yourself", "t1")), msg(text("Introduced myself."), stop="end_turn")]
    agent, _, _, _ = make(script)

    async def scenario():
        await agent.handle(Utterance("senior", "Miguel, introduce yourself to the judges"))
        await agent.idle()

    asyncio.run(scenario())
    assert [e.text for e in agent.events if e.kind == "say"] == [INTRO_LINE]
