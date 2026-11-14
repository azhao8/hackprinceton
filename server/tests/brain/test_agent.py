"""Agent + ToolBox tests with a scripted fake Anthropic client (no network)."""

import asyncio
import copy
from types import SimpleNamespace

from app.arbiter import Arbiter
from app.brain.agent import Agent, stop_requested
from app.brain.tools import ToolBox
from app.brain.types import Utterance
from app.skills import SkillContext, SkillResult, SkillRunner

# --- fakes ------------------------------------------------------------------------------------


def tool(tool_name, tool_id, **input):
    return SimpleNamespace(type="tool_use", id=tool_id, name=tool_name, input=input)


def text(t):
    return SimpleNamespace(type="text", text=t)


def thinking(t="hmm"):
    return SimpleNamespace(type="thinking", thinking=t, signature="sig")


def msg(*blocks, stop="tool_use", details=None):
    return SimpleNamespace(content=list(blocks), stop_reason=stop, stop_details=details, model="claude-opus-5-5")


class FakeMessages:
    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    async def create(self, **kw):
        self.calls.append(copy.deepcopy(kw))
        assert self.script, "unexpected LLM call"
        item = self.script.pop(0)
        if callable(item):
            item = item(kw)
        await asyncio.sleep(0)
        return item


class FakeClient:
    def __init__(self, script):
        self.beta = SimpleNamespace(messages=FakeMessages(script))

    @property
    def calls(self):
        return self.beta.messages.calls


class Quick:
    def __init__(self, name, ok=True, detail="done"):
        self.name, self.ok, self.detail = name, ok, detail

    async def run(self, ctx):
        await asyncio.sleep(0.01)
        return SkillResult(self.ok, self.detail)


class Forever:
    def __init__(self, name):
        self.name = name

    async def run(self, ctx):
        while True:
            ctx.drive(0.2, 0.0)
            await asyncio.sleep(0.01)


def make(script, factories=None, **toolbox_kw):
    arb = Arbiter()
    runner = SkillRunner(SkillContext(arb))
    tools = ToolBox(runner, factories or {}, **toolbox_kw)
    client = FakeClient(script)
    agent = Agent(tools, client=client)
    return agent, client, arb, runner


def kinds(agent, skip=("heard",)):
    return [e.kind for e in agent.events if e.kind not in skip]


async def until(cond, timeout=2.0):
    end = asyncio.get_running_loop().time() + timeout
    while not cond():
        assert asyncio.get_running_loop().time() < end, "timed out"
        await asyncio.sleep(0.005)


def last_user(call):
    return call["messages"][-1]["content"]


# --- tests ------------------------------------------------------------------------------------


def test_stop_words():
    for s in ["stop", "Stop!", "Miguel, stop", "no no wait", "hold on", "Stop, bring me water instead", "freeze"]:
        assert stop_requested(s), s
    for s in ["bring me water", "can you wait for me in the kitchen please", "don't go anywhere", "hello"]:
        assert not stop_requested(s), s


def test_multi_step_request_emits_plan_steps_say_and_reply_in_order():
    built = []

    def factory(name):
        def f(**kw):
            built.append((name, kw))
            return Quick(name)
        return f

    script = [
        msg(thinking(), tool("set_plan", "t1", steps=["Go to the kitchen", "Bring Mom her pills", "Tell you"])),
        msg(tool("say", "t2", text="I'm going to the kitchen now.", step=0), tool("go_to", "t3", place="kitchen", step=0)),
        msg(tool("bring", "t4", item="pills", person="Mom", step=1)),
        msg(tool("reply_to_guardian", "t5", text="Mom has her pills.", attach_photo=True, step=2)),
        msg(text("Done."), stop="end_turn"),
    ]
    agent, client, _, _ = make(
        script, {"go_to": factory("go_to"), "bring": factory("bring")}, snapshot=lambda: b"JPEG")

    async def scenario():
        await agent.handle(Utterance("guardian", "Bring Mom her pills and send me a photo"))
        await agent.idle()

    asyncio.run(scenario())

    assert kinds(agent) == [
        "task", "plan", "step", "say", "step", "step", "step", "step", "reply", "step", "task"]
    steps = [(e.data["index"], e.data["status"]) for e in agent.events if e.kind == "step"]
    assert steps == [(0, "running"), (0, "done"), (1, "running"), (1, "done"), (2, "running"), (2, "done")]
    plan = next(e for e in agent.events if e.kind == "plan")
    assert plan.data["steps"][1] == "Bring Mom her pills"
    tasks = [e.data["status"] for e in agent.events if e.kind == "task"]
    assert tasks == ["started", "done"]
    assert built == [("go_to", {"place": "kitchen"}), ("bring", {"item": "pills", "person": "Mom"})]

    reply = next(e for e in agent.events if e.kind == "reply")
    assert reply.to == "guardian" and reply.text == "Mom has her pills."
    assert agent.tools.photos[reply.data["photo_id"]] == b"JPEG"
    assert sum(e.kind == "reply" for e in agent.events) == 1   # final text not re-sent: already replied

    first = client.calls[0]
    assert first["model"] == "claude-opus-5-5"
    assert first["output_config"] == {"effort": "medium"}
    assert first["fallbacks"] == "default" and first["betas"] == ["server-side-fallback-2026-07-01"]
    assert all(t["strict"] and t["input_schema"]["additionalProperties"] is False for t in first["tools"])
    assert "thinking" not in first and "tool_choice" not in first
    content = first["messages"][0]["content"]
    assert content[0]["text"].startswith("[guardian via app] Bring Mom")
    assert content[-1]["text"].startswith("World memory:")
    # parallel tool results come back in ONE user message
    assert [b["tool_use_id"] for b in last_user(client.calls[2])] == ["t2", "t3"]


def test_tool_failure_is_marked_error_and_the_loop_continues():
    script = [
        msg(tool("go_to", "t1", place="bedroom", step=None)),
        msg(tool("find_person", "t2", name=None, description="woman in a blue sweater", step=None)),
        msg(tool("fly", "t3")),
        msg(tool("say", "t4", text="I couldn't get to the bedroom. Can you help me?", step=None)),
        msg(text("Told her."), stop="end_turn"),
    ]
    factories = {"go_to": lambda place: Quick("go_to", ok=False, detail="the hallway is blocked")}
    agent, client, _, _ = make(script, factories)

    async def scenario():
        await agent.handle(Utterance("senior", "Go to the bedroom and find my glasses"))
        await agent.idle()

    asyncio.run(scenario())

    r1 = last_user(client.calls[1])[0]
    assert r1["is_error"] is True and "hallway is blocked" in r1["content"]
    r2 = last_user(client.calls[2])[0]
    assert r2["is_error"] is True and "unavailable" in r2["content"]   # no find_person skill injected
    r3 = last_user(client.calls[3])[0]
    assert r3["is_error"] is True and "'fly' is unavailable" in r3["content"]
    assert len(client.calls) == 5
    says = [e.text for e in agent.events if e.kind == "say"]
    assert says == ["I couldn't get to the bedroom. Can you help me?"]   # final text not spoken twice


def test_senior_stop_cancels_the_skill_without_an_llm_call():
    script = [
        msg(tool("say", "t1", text="Going to the kitchen.", step=None), tool("go_to", "t2", place="kitchen", step=None)),
        msg(text("Hi!"), stop="end_turn"),
    ]
    agent, client, arb, runner = make(script, {"go_to": lambda place: Forever("go_to")})

    async def scenario():
        await agent.handle(Utterance("guardian", "Go to the kitchen"))
        await until(lambda: runner.running == "go_to" and arb.decide().source == "skill")
        await agent.handle(Utterance("senior", "Stop!"))
        assert arb.decide().source == "none"        # stopped synchronously, before any await
        assert len(client.calls) == 1               # no LLM call for the stop
        await agent.idle()
        assert runner.running is None
        # The next request sees a valid history: the cut-off tool call got a result, plus a stop note.
        await agent.handle(Utterance("senior", "hello"))
        await agent.idle()

    asyncio.run(scenario())

    tasks = [e.data["status"] for e in agent.events if e.kind == "task"]
    assert tasks == ["started", "cancelled"]
    assert any(e.kind == "say" and e.text == "Okay, stopping." for e in agent.events)
    msgs = client.calls[1]["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant", "user", "user", "user"]
    results = msgs[2]["content"]
    assert [r["tool_use_id"] for r in results] == ["t1", "t2"] and all(r["is_error"] for r in results)
    assert msgs[3]["content"][0]["text"].startswith("[stop]")
    assert client.calls[1]["output_config"] == {"effort": "low"}   # small talk


def test_one_physical_task_new_request_is_handed_to_the_running_task():
    built = []
    skills = {}

    def go_to(place):
        skills["go_to"] = s = Forever("go_to")
        built.append("go_to")
        return s

    def bring(item, person):
        built.append("bring")
        return Quick("bring")

    def second(kw):
        content = kw["messages"][-1]["content"]
        assert content[0]["tool_use_id"] == "t1" and "still running" in content[0]["content"]
        assert content[1]["text"] == "[guardian via app, while you were working] Actually, bring Dad some water first"
        return msg(tool("say", "t2", text="Okay, water for Dad first.", step=None),
                   tool("bring", "t3", item="water", person="Dad", step=None))

    script = [
        msg(tool("go_to", "t1", place="kitchen", step=None)),
        second,
        msg(text("Brought Dad water."), stop="end_turn"),
    ]
    agent, client, arb, runner = make(script, {"go_to": go_to, "bring": bring})
    go_to_tasks = []

    async def scenario():
        await agent.handle(Utterance("guardian", "Go to the kitchen"))
        await until(lambda: runner.running == "go_to")
        go_to_tasks.append(runner.task)
        await agent.handle(Utterance("guardian", "Actually, bring Dad some water first"))
        await agent.idle()

    asyncio.run(scenario())

    assert built == ["go_to", "bring"]
    assert go_to_tasks[0].result() == SkillResult(False, "cancelled")   # replaced, not run side by side
    assert [e.data["status"] for e in agent.events if e.kind == "task"] == ["started", "done"]   # one task
    assert len(client.calls) == 3
    assert runner.running is None


def test_wait_for_reply_gets_the_next_senior_utterance():
    def second(kw):
        assert last_user(kw)[1]["content"] == 'The senior said: "juice please"'
        return msg(text("Juice it is!"), stop="end_turn")

    script = [msg(tool("say", "t1", text="Water or juice?", step=None), tool("wait_for_reply", "t2", seconds=10, step=None)),
              second]
    agent, client, _, _ = make(script)

    async def scenario():
        await agent.handle(Utterance("senior", "I'm thirsty"))
        await until(lambda: agent._reply_waiter is not None)
        await agent.handle(Utterance("senior", "juice please"))
        await agent.idle()

    asyncio.run(scenario())
    assert len(client.calls) == 2   # the answer went to the waiting tool, not a new task
    # said "Water or juice?" during the task, so the final text is a log note, not spoken
    assert [e.text for e in agent.events if e.kind == "say"] == ["Water or juice?"]


def test_wait_for_reply_times_out_with_no_answer():
    tools = ToolBox()
    agent = Agent(tools, client=FakeClient([]))

    async def scenario():
        out = await tools.call("wait_for_reply", {"seconds": 1})
        return out

    tools_out = asyncio.run(asyncio.wait_for(scenario(), 10))
    assert tools_out.ok and tools_out.text.startswith("no answer")
    assert agent.events == []


def test_reply_without_camera_still_sends():
    tools = ToolBox(snapshot=lambda: None)
    agent = Agent(tools, client=FakeClient([]))
    out = asyncio.run(tools.call("reply_to_guardian", {"text": "All good", "attach_photo": True}))
    assert out.ok and "without a photo" in out.text
    assert agent.events[-1].kind == "reply" and agent.events[-1].data == {}


def test_refusal_is_reported_without_crashing_and_left_out_of_history():
    script = [
        msg(stop="refusal", details=SimpleNamespace(category="cyber", explanation=None)),
        msg(text("Hello!"), stop="end_turn"),
    ]
    agent, client, _, _ = make(script)

    async def scenario():
        await agent.handle(Utterance("senior", "something odd"))
        await agent.idle()
        await agent.handle(Utterance("senior", "hi"))
        await agent.idle()

    asyncio.run(scenario())
    err = next(e for e in agent.events if e.kind == "error")
    assert "cyber" in err.text
    assert any(e.kind == "say" and e.text.startswith("Sorry") for e in agent.events)
    assert len(client.calls[1]["messages"]) == 1   # the refused exchange was dropped


def test_small_talk_is_one_call_and_spoken_and_fallbacks_can_be_switched_off():
    tools = ToolBox()
    client = FakeClient([msg(thinking(), text("I'm great, thank you!"), stop="end_turn"),
                         msg(text("Sure."), stop="end_turn")])
    agent = Agent(tools, client=client, fallbacks=False)
    seen = []
    agent.events_cb = seen.append

    async def scenario():
        q = agent.subscribe()
        await agent.handle(Utterance("senior", "How are you?"))
        await agent.idle()
        await agent.handle(Utterance("guardian", "Thanks Miguel"))
        await agent.idle()
        return q

    q = asyncio.run(scenario())
    assert kinds(agent) == ["say", "reply"]   # no task events for chat
    assert agent.events[1].text == "I'm great, thank you!" and agent.events[1].to == "senior"
    assert "betas" not in client.calls[0] and "fallbacks" not in client.calls[0]
    assert client.calls[0]["output_config"] == {"effort": "low"}
    assert len(seen) == len(agent.events) == q.qsize()
    # finished tasks keep no thinking blocks in the history
    history = client.calls[1]["messages"]
    assert [b.type for b in history[1]["content"]] == ["text"]


def test_memory_tools_and_summary():
    tools = ToolBox()

    async def scenario():
        await tools.call("remember", {"key": "pills", "value": "kitchen counter"})
        return await tools.call("recall", {"key": "pills"}), await tools.call("recall", {"key": "keys"})

    hit, miss = asyncio.run(scenario())
    assert hit.text == "pills: kitchen counter"
    assert miss.ok and "Known keys: pills" in miss.text
    assert "pills: kitchen counter" in tools.memory_summary()
