"""The move and set_follow_settings tools, and the agent's reset_conversation / clear_events."""

import asyncio

from app.brain.agent import Agent
from app.brain.tools import PHYSICAL_TOOLS, ToolBox
from app.brain.types import Utterance
from tests.brain.test_agent import FakeClient, Forever, Quick, make, msg, text, tool, until

MOVE_ARGS = {"seconds": None, "meters": None, "degrees": None, "speed": None}


def run(coro):
    return asyncio.run(coro)


# --- move --------------------------------------------------------------------------------------


def test_move_is_physical_and_passes_every_kwarg():
    built = []

    def factory(**kw):
        built.append(kw)
        return Quick("move", detail="moved backward 2.00 m")

    agent, client, _, runner = make([], {"move": factory})
    tools = agent.tools
    assert "move" in PHYSICAL_TOOLS and tools.is_physical("move")
    out = run(tools.call("move", {"direction": "backward", **MOVE_ARGS, "meters": 2}))
    assert out.ok and out.text == "move: moved backward 2.00 m"
    assert built == [{"direction": "backward", "seconds": None, "meters": 2, "degrees": None, "speed": None}]

    d = next(t for t in tools.definitions() if t["name"] == "move")
    props = d["input_schema"]["properties"]
    assert set(d["input_schema"]["required"]) == {"direction", "seconds", "meters", "degrees", "speed", "step"}
    assert props["direction"]["enum"] == ["forward", "backward", "left", "right"]
    assert {"type": "null"} in props["speed"]["anyOf"]


def test_move_rejects_mixed_amounts_before_stopping_anything():
    built = []
    agent, _, _, runner = make([], {"move": lambda **kw: built.append(kw) or Quick("move")})
    tools = agent.tools
    for args in ({"direction": "forward", **MOVE_ARGS, "seconds": 2, "meters": 1},
                 {"direction": "left", **MOVE_ARGS, "meters": 1},
                 {"direction": "forward", **MOVE_ARGS, "degrees": 90}):
        out = run(tools.call("move", args))
        assert not out.ok, args
    assert built == []


def test_move_unavailable_without_a_factory():
    agent, *_ = make([])
    out = run(agent.tools.call("move", {"direction": "forward", **MOVE_ARGS}))
    assert not out.ok and "unavailable" in out.text


def test_agent_runs_a_move_from_the_llm():
    built = []
    script = [msg(tool("move", "t1", direction="left", seconds=None, meters=None, degrees=90, speed=None, step=None)),
              msg(text("Turned."), stop="end_turn")]
    agent, client, _, _ = make(script, {"move": lambda **kw: built.append(kw) or Quick("move", detail="turned left 90°")})

    async def scenario():
        await agent.handle(Utterance("senior", "turn left 90 degrees"))
        await agent.idle()

    run(scenario())
    assert built == [{"direction": "left", "seconds": None, "meters": None, "degrees": 90, "speed": None}]
    assert client.calls[1]["messages"][-1]["content"][0]["content"] == "move: turned left 90°"
    assert [e.data["status"] for e in agent.events if e.kind == "task"] == ["started", "done"]


# --- set_follow_settings -----------------------------------------------------------------------


class Settings:
    def __init__(self):
        self.now = {"speed": 0.8, "distance": 0.8, "other": 1}
        self.calls = []

    def set(self, changes):
        self.calls.append(dict(changes))
        self.now.update(changes)
        return dict(self.now)


def test_follow_setting_words_map_in_code():
    s = Settings()
    tools = ToolBox(set_settings=s.set, settings=lambda: dict(s.now))
    assert not tools.is_physical("set_follow_settings")
    d = next(t for t in tools.definitions() if t["name"] == "set_follow_settings")
    assert set(d["input_schema"]["required"]) == {"speed", "closeness"}   # not stepped

    out = run(tools.call("set_follow_settings", {"speed": "Slower", "closeness": None}))
    assert out.ok and s.calls[-1] == {"speed": 0.5}
    assert out.text == "Follow speed 0.50 m/s, closeness 0.80. It applies right away if I'm following."
    assert out.data == {"speed": 0.5, "distance": 0.8}

    run(tools.call("set_follow_settings", {"speed": None, "closeness": "closer"}))
    assert s.calls[-1] == {"distance": 1.0}
    run(tools.call("set_follow_settings", {"speed": "fast", "closeness": "further"}))
    assert s.calls[-1] == {"speed": 1.0, "distance": 0.6}
    run(tools.call("set_follow_settings", {"speed": "normal", "closeness": "default"}))
    assert s.calls[-1] == {"speed": 0.8, "distance": 0.8}


def test_follow_setting_numbers_pass_through():
    s = Settings()
    tools = ToolBox(set_settings=s.set)
    out = run(tools.call("set_follow_settings", {"speed": 0.6, "closeness": "0.9"}))
    assert out.ok and s.calls == [{"speed": 0.6, "distance": 0.9}]
    run(tools.call("set_follow_settings", {"speed": 9, "closeness": None}))   # the server clamps, not the tool
    assert s.calls[-1] == {"speed": 9.0}


def test_follow_setting_unknown_word_fails_and_lists_the_words():
    s = Settings()
    tools = ToolBox(set_settings=s.set)
    out = run(tools.call("set_follow_settings", {"speed": "zippy", "closeness": "closer"}))
    assert not out.ok and "zippy" in out.text and "slower" in out.text and "faster" in out.text
    out = run(tools.call("set_follow_settings", {"speed": None, "closeness": "nearer"}))
    assert not out.ok and "farther" in out.text
    assert s.calls == []   # nothing applied


def test_follow_settings_nothing_to_change_and_unavailable():
    s = Settings()
    tools = ToolBox(set_settings=s.set, settings=lambda: dict(s.now))
    out = run(tools.call("set_follow_settings", {"speed": None, "closeness": None}))
    assert not out.ok and "Follow speed 0.80 m/s" in out.text and s.calls == []
    out = run(ToolBox().call("set_follow_settings", {"speed": "slower", "closeness": None}))
    assert not out.ok and "unavailable" in out.text


# --- reset_conversation / clear_events ---------------------------------------------------------


def test_reset_conversation_forgets_history_but_not_world_memory():
    script = [msg(text("Hi Mom!"), stop="end_turn"), msg(text("Hello!"), stop="end_turn")]
    agent, client, _, _ = make(script)
    agent.tools.memory["pills"] = "kitchen counter"

    async def scenario():
        await agent.handle(Utterance("senior", "hello, I'm Mom"))
        await agent.idle()
        assert len(agent._history) == 1
        agent.reset_conversation()
        await agent.handle(Utterance("senior", "hello"))
        await agent.idle()

    run(scenario())
    msgs = client.calls[1]["messages"]
    assert [m["role"] for m in msgs] == ["user", "system"]   # nothing from before the reset
    assert any("pills: kitchen counter" in b["text"] for b in msgs[0]["content"])   # world memory note
    assert agent.tools.memory == {"pills": "kitchen counter"}


def test_reset_stops_the_running_task_and_it_does_not_write_history_back():
    script = [msg(tool("go_to", "t1", place="kitchen", step=None))]
    agent, client, arb, runner = make(script, {"go_to": lambda place: Forever("go_to")})

    async def scenario():
        await agent.handle(Utterance("guardian", "Go to the kitchen"))
        await until(lambda: runner.running == "go_to" and arb.decide().source == "skill")
        await agent.handle(Utterance("guardian", "and then the bedroom"))   # queued for the task
        await agent.inbox.put(Utterance("senior", "hi"))                  # waiting in the inbox
        says_before = sum(e.kind == "say" for e in agent.events)
        agent.reset_conversation()
        assert arb.decide().source == "none"   # stopped synchronously
        assert agent.inbox.empty() and agent._pending == []
        await agent.idle()
        assert runner.running is None and not agent.busy
        assert agent._history == []            # the cancelled task didn't append its exchange
        assert sum(e.kind == "say" for e in agent.events) == says_before   # nothing said to the senior
        assert not agent.working

    run(scenario())
    assert len(client.calls) == 1
    assert [e.data["status"] for e in agent.events if e.kind == "task"] == ["started", "cancelled"]


def test_reset_after_stop_drops_the_stop_note():
    agent = Agent(ToolBox(), client=FakeClient([]))
    agent.stop("test")   # no task: the stop note goes straight into the history
    assert len(agent._history) == 1
    agent.reset_conversation()
    assert agent._history == []


def test_clear_events_keeps_ids_increasing():
    agent = Agent(ToolBox(), client=FakeClient([]))
    first = agent.emit("say", "one")
    agent.emit("say", "two")
    agent.clear_events()
    assert agent.events == [] and agent.events_after(0) == []
    third = agent.emit("say", "three")
    assert third.id > first.id + 1 and [e.text for e in agent.events] == ["three"]


def test_never_more_strict_tools_than_the_api_allows():
    """Sun 3:40 am: 21 strict tools and the API refused every request (#79)."""
    from app.brain.tools import MAX_STRICT_TOOLS, ToolBox

    box = ToolBox()
    def unions(defs):
        return sum("anyOf" in p for d in defs if d["strict"] for p in d["input_schema"]["properties"].values())
    assert sum(d["strict"] for d in box.definitions()) <= MAX_STRICT_TOOLS - 2   # headroom for the next tools
    assert unions(box.definitions()) <= 16 and [d for d in box.definitions() if d["name"] == "move"][0]["strict"] is False
    assert box.definitions()[0]["strict"] is True                                # the first tools stay strict

    async def noop(a):
        return None
    for i in range(10):
        box.register(f"extra_{i}", "x", {}, noop, stepped=False)
    assert sum(d["strict"] for d in box.definitions()) == MAX_STRICT_TOOLS
    for i in range(10):
        box.register(f"nullable_{i}", "x", {"a": {"anyOf": [{"type": "string"}, {"type": "null"}]}}, noop, stepped=False)
    assert unions(box.definitions()) <= 16
