"""The agent's voice-latency and turn-taking behavior, with a fake streaming client (no network):
sentence-by-sentence speech, stay_silent, mic labels, timing marks, prompt caching shape."""

import asyncio
import copy
import logging
import re
from types import SimpleNamespace

from app.brain.agent import Agent, _Sentences, _with_breakpoint
from app.brain.prompt import stream_message
from app.brain.tools import ToolBox
from app.brain.types import Utterance

from .test_agent import FakeClient, msg, text, thinking, tool


class FakeStream:
    """Plays a scripted message as stream events, word by word; `probe()` runs after each word."""

    def __init__(self, message, probe=None):
        self.message = message
        self.probe = probe

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def __aiter__(self):
        return self._events()

    async def _events(self):
        for i, b in enumerate(self.message.content):
            yield SimpleNamespace(type="content_block_start", index=i, content_block=SimpleNamespace(type=b.type))
            if b.type == "text":
                for piece in re.findall(r"\S+\s*", b.text):
                    yield SimpleNamespace(type="text", text=piece, snapshot="")
                    await asyncio.sleep(0)
                    if self.probe is not None:
                        self.probe()
            yield SimpleNamespace(type="content_block_stop", index=i, content_block=b)   # the SDK's snapshot

    async def get_final_message(self):
        return self.message


class StreamMessages:
    def __init__(self, script):
        self.script = list(script)
        self.calls = []
        self.probe = None

    def stream(self, **kw):
        self.calls.append(copy.deepcopy(kw))
        assert self.script, "unexpected LLM call"
        item = self.script.pop(0)
        if callable(item):
            item = item(kw)
        return FakeStream(item, self.probe)

    async def create(self, **kw):   # pragma: no cover - the agent streams
        raise AssertionError("the agent should stream")


class StreamClient:
    def __init__(self, script):
        self.beta = SimpleNamespace(messages=StreamMessages(script))

    @property
    def calls(self):
        return self.beta.messages.calls


def says(agent):
    return [e.text for e in agent.events if e.kind == "say"]


def run(agent, *utterances):
    async def scenario():
        for u in utterances:
            await agent.handle(u)
            await agent.idle()

    asyncio.run(scenario())


def strip_cache(messages):
    """Messages as plain data without cache markers (the moving marker is not part of the prefix)."""
    def block(b):
        d = dict(b) if isinstance(b, dict) else dict(vars(b))
        d.pop("cache_control", None)
        return d
    return [{**m, "content": [block(b) for b in m["content"]]} for m in messages]


# --- sentence by sentence -----------------------------------------------------------------------


def test_sentences_cut_at_sentence_ends_but_not_abbreviations():
    out = []
    s = _Sentences(out.append, max_chars=60)
    for piece in ["Sure! ", "Dr. Lee ", "called. ", "Is it 3.5", " pills? ", "Okay"]:
        s.feed(piece)
    assert out == ["Sure!", "Dr. Lee called.", "Is it 3.5 pills?"]
    s.flush()
    assert out[-1] == "Okay" and s.used
    s.feed("first line\nsecond ")
    assert out[-1] == "first line"
    s.feed("word " * 20)                       # no sentence end: cut near max_chars at a space
    assert len(out[-1]) <= 60 and out[-1].startswith("second word")


def test_a_sentence_at_the_end_of_a_burst_is_said_without_waiting_for_the_next_burst():
    out = []
    s = _Sentences(out.append)
    s.feed("Two plus two is four!")
    assert out == ["Two plus two is four!"]
    s.feed(" It costs 3.")                     # maybe "3.50": wait for more
    assert out == ["Two plus two is four!"]
    s.feed("50 dollars. Well..")
    assert out[1:] == ["It costs 3.50 dollars.", "Well.."]
    s.feed(".")                                 # the rest of an ellipsis is not a line of its own
    s.flush()
    assert out == ["Two plus two is four!", "It costs 3.50 dollars.", "Well.."]


def test_first_sentence_is_said_before_claude_finishes_and_nothing_is_said_twice():
    client = StreamClient([msg(thinking(), text("Sure thing! The kitchen is to your left. I can show you."),
                               stop="end_turn")])
    agent = Agent(ToolBox(), client=client, ack=False)
    seen_while_streaming = []
    client.beta.messages.probe = lambda: seen_while_streaming.append(list(says(agent)))
    run(agent, Utterance("senior", "Where is the kitchen?"))
    assert says(agent) == ["Sure thing!", "The kitchen is to your left.", "I can show you."]
    assert ["Sure thing!"] in seen_while_streaming          # spoken while Claude was still writing
    assert sum(e.kind == "say" for e in agent.events) == 3   # the final text is not repeated


def test_guardian_gets_one_reply_not_streamed_speech():
    client = StreamClient([msg(text("All good. She is resting."), stop="end_turn")])
    agent = Agent(ToolBox(), client=client, ack=False)
    run(agent, Utterance("guardian", "How is Mom?"))
    assert says(agent) == []
    assert [(e.kind, e.text) for e in agent.events if e.kind == "reply"] == [("reply", "All good. She is resting.")]


def test_tools_still_work_while_streaming_and_a_log_note_after_say_is_not_spoken():
    built = []

    class Quick:
        name = "go_to"

        async def run(self, ctx):
            return SimpleNamespace(ok=True, detail="arrived")

    from app.arbiter import Arbiter
    from app.skills import SkillContext, SkillRunner

    def go_to(place):
        built.append(place)
        return Quick()

    script = [
        msg(text("Okay."), tool("say", "t1", text="Going to the kitchen now.", step=None),
            tool("go_to", "t2", place="kitchen", step=None)),
        msg(text("Arrived."), stop="end_turn"),               # a log note: say() was used
    ]
    client = StreamClient(script)
    agent = Agent(ToolBox(SkillRunner(SkillContext(Arbiter())), {"go_to": go_to}), client=client, ack=False)
    run(agent, Utterance("senior", "Go to the kitchen"))
    assert built == ["kitchen"]
    assert says(agent) == ["Okay.", "Going to the kitchen now."]
    assert len(client.calls) == 2


# --- turn-taking ------------------------------------------------------------------------------


def test_stay_silent_says_nothing_makes_one_call_and_leaves_no_history():
    client = StreamClient([
        msg(tool("stay_silent", "t1", reason="two people talking"), stop="tool_use"),
        msg(text("Hello!"), stop="end_turn"),
    ])
    agent = Agent(ToolBox(), client=client, ack=True)
    run(agent,
        Utterance("senior", "so then I told him to bring the car",
                  meta={"channel": "mic", "via": "question", "addressed": False}),
        Utterance("senior", "hello", meta={"channel": "mic", "via": "wake", "addressed": True}))
    assert says(agent) == ["Hello!"]                          # nothing (not even "On it!") for the first
    first, second = client.calls
    assert first["messages"][0]["content"][0]["text"] == \
        "[senior via mic, right after your question] so then I told him to bring the car"
    assert "stay_silent" in [t["name"] for t in first["tools"]]
    assert len(second["messages"]) == 2                       # the silent exchange was left out
    assert second["messages"][0]["content"][0]["text"] == "[senior via mic] hello"


def test_mic_labels_say_how_unaddressed_speech_got_through():
    client = FakeClient([msg(text("Yes."), stop="end_turn"), msg(text("Hi."), stop="end_turn")])
    agent = Agent(ToolBox(), client=client, ack=False)
    run(agent, Utterance("senior", "what's that", meta={"channel": "mic", "via": "tap", "addressed": True}),
        Utterance("senior", "no thanks", meta={"channel": "mic", "via": "reply"}))
    assert client.calls[0]["messages"][0]["content"][0]["text"] == "[senior via mic, tapped your face] what's that"
    assert client.calls[1]["messages"][-2]["content"][0]["text"] == "[senior via mic, answering you] no thanks"


def test_no_instant_ack_for_mic_speech_without_his_name():
    class Never:
        class beta:
            class messages:
                @staticmethod
                async def create(**kw):
                    await asyncio.sleep(3600)

    async def scenario():
        agent = Agent(ToolBox(), client=Never())
        await agent.handle(Utterance("senior", "go get the car keys",
                                     meta={"channel": "mic", "via": "open", "addressed": False}))
        await asyncio.sleep(0.02)
        acks = [e for e in agent.events if e.data.get("ack")]
        agent.stop("test over")
        return acks

    assert asyncio.run(scenario()) == []


# --- timing ----------------------------------------------------------------------------------


def test_first_real_say_carries_the_stage_times():
    client = StreamClient([msg(text("Of course. Here I come."), stop="end_turn")])
    agent = Agent(ToolBox(), client=client, ack=True)
    u = Utterance("senior", "Miguel, please come here and bring the water", t=100.0,
                  meta={"channel": "mic", "via": "wake", "t_speech_end": 99.5, "t_final": 100.0})
    run(agent, u)
    ack, first, second = [e for e in agent.events if e.kind == "say"]
    assert ack.data.get("ack") and "timing" not in ack.data
    t = first.data["timing"]
    assert t["t_speech_end"] == 99.5 and t["t_final"] == 100.0 and t["heard"] == 100.0
    assert t["llm_start"] <= t["first_text"] <= t["say"]
    assert "timing" not in second.data


# --- prompt caching ---------------------------------------------------------------------------


def test_cached_prefix_is_byte_stable_between_tasks_and_marked_at_the_end_of_the_history():
    client = FakeClient([msg(thinking(), text(f"Answer {i}."), stop="end_turn") for i in range(3)])
    agent = Agent(ToolBox(), client=client, ack=False)
    run(agent, Utterance("senior", "hi"), Utterance("guardian", "please bring Mom her pills"),
        Utterance("senior", "thanks"))
    a, b, c = client.calls
    assert a["system"] == b["system"] == c["system"] and a["tools"] == b["tools"] == c["tools"]
    assert a["output_config"] == b["output_config"] == c["output_config"] == {"effort": "low"}
    # each request starts with the one before it (minus thinking blocks of finished tasks)
    assert strip_cache(c["messages"])[: len(b["messages"])] == strip_cache(b["messages"])
    assert strip_cache(b["messages"])[:2] == strip_cache(a["messages"])
    # the breakpoint sits on the last block of the history, and only there
    marked = [(i, j) for i, m in enumerate(c["messages"]) for j, blk in enumerate(m["content"])
              if isinstance(blk, dict) and "cache_control" in blk]
    assert marked == [(5, 0)] and c["messages"][5]["role"] == "assistant"
    assert [m["role"] for m in c["messages"]] == ["user", "system", "assistant"] * 2 + ["user", "system"]
    assert c["messages"][4]["output_config"] == {"effort": "medium"}   # the pills task's effort


def test_breakpoint_copy_does_not_touch_the_stored_history():
    history = [{"role": "user", "content": [{"type": "text", "text": "hi"}]},
               {"role": "assistant", "content": [SimpleNamespace(type="text", text="hello")]}]
    before = copy.deepcopy(history)
    out = _with_breakpoint(history)
    assert out[1]["content"][0] == {"type": "text", "text": "hello", "cache_control": {"type": "ephemeral"}}
    assert vars(history[1]["content"][0]) == vars(before[1]["content"][0]) and history[0] == before[0]
    assert _with_breakpoint([]) == []


def test_history_is_trimmed_in_chunks():
    client = FakeClient([msg(text("ok"), stop="end_turn") for _ in range(8)])
    agent = Agent(ToolBox(), client=client, ack=False, history_exchanges=4, history_trim=2)
    sizes = []

    async def scenario():
        for i in range(8):
            await agent.handle(Utterance("senior", f"hello number {i}"))
            await agent.idle()
            sizes.append(len(agent._history))

    asyncio.run(scenario())
    assert sizes == [1, 2, 3, 4, 2, 3, 4, 2]


def test_top_level_effort_when_per_message_effort_is_off():
    client = FakeClient([msg(text("ok"), stop="end_turn")])
    agent = Agent(ToolBox(), client=client, ack=False, fallbacks=False, per_message_effort=False)
    run(agent, Utterance("guardian", "bring Mom her pills"))
    call = client.calls[0]
    assert call["output_config"] == {"effort": "medium"} and "betas" not in call
    assert [m["role"] for m in call["messages"]] == ["user"]


def test_usage_is_logged_with_cache_reads(caplog):
    caplog.set_level(logging.INFO, logger="app.brain.agent")
    usage = SimpleNamespace(input_tokens=40, cache_read_input_tokens=5200, cache_creation_input_tokens=0,
                            output_tokens=12)
    reply = msg(text("Hi!"), stop="end_turn")
    reply.usage = usage
    agent = Agent(ToolBox(), client=StreamClient([reply]), ack=False)
    run(agent, Utterance("senior", "hello"))
    assert agent.last_usage["cache_read_input_tokens"] == 5200
    assert "5200 cache read" in caplog.text


def test_prewarm_writes_the_same_prefix_with_max_tokens_zero_and_keeps_it_warm():
    client = FakeClient([msg(text("Hi."), stop="end_turn"),
                         msg(stop="max_tokens"), msg(stop="max_tokens"), msg(stop="max_tokens")])
    agent = Agent(ToolBox(), client=client, ack=False, keepalive_s=0.05)

    async def scenario():
        await agent.handle(Utterance("senior", "hello"))
        await agent.idle()
        assert await agent.prewarm()
        runner = asyncio.create_task(agent.run())
        await asyncio.sleep(0.3)                # warm at start, then again after 0.05 s idle
        runner.cancel()
        agent._warm_task.cancel()

    asyncio.run(scenario())
    real, warm = client.calls[0], client.calls[1]
    assert warm["max_tokens"] == 0 and "cache_control" not in warm
    for key in ("system", "tools", "output_config", "betas", "fallbacks", "model"):
        assert warm[key] == real[key], key
    # the history (the real call's exchange, answered) with the breakpoint on its last block, then a placeholder
    assert strip_cache(warm["messages"][:2]) == strip_cache(real["messages"])
    assert warm["messages"][2]["content"][-1]["cache_control"] == {"type": "ephemeral"}
    assert warm["messages"][-1] == {"role": "user", "content": [{"type": "text", "text": "."}]}
    # one direct, the warm-up at start, then refreshes while idle (the fake errors once its script
    # runs out: harmless)
    assert len(client.calls) >= 4 and all(c["max_tokens"] == 0 for c in client.calls[1:])


def test_prewarm_failure_is_harmless():
    agent = Agent(ToolBox(), client=FakeClient([]), ack=False)   # the fake raises: no script left
    assert asyncio.run(agent.prewarm()) is False


def test_stream_message_falls_back_to_create_and_merges_betas():
    events = []
    client = StreamClient([msg(text("One. Two."), stop="end_turn")])
    out = asyncio.run(stream_message(client, fallbacks=True, on_event=lambda k, v: events.append((k, v)),
                                     model="m", max_tokens=5, messages=[], betas=["x"]))
    assert out.stop_reason == "end_turn"
    assert client.calls[0]["betas"] == ["server-side-fallback-2026-07-01", "x"]
    assert ("text", "One. ") in events and events[0] == ("block_start", "text") and events[-1] == ("block_stop", None)
    plain = FakeClient([msg(text("hi"), stop="end_turn")])
    assert asyncio.run(stream_message(plain, fallbacks=False, on_event=print, model="m", max_tokens=5,
                                      messages=[])).content[0].text == "hi"


# --- early say: a say() call is spoken when its block finishes, not after the whole response ------


def test_say_is_spoken_as_soon_as_its_block_finishes_streaming():
    seen = []
    client = StreamClient([
        msg(tool("say", "s1", text="Okay, backing up a little."), text("Backing up now, as asked."),
            tool("move", "m1", distance_m=-0.2)),
        msg(text("Backed up."), stop="end_turn"),
    ])
    agent = Agent(ToolBox(), client=client, ack=False)
    client.beta.messages.probe = lambda: seen.append(list(says(agent)))
    run(agent, Utterance("senior", "back up a bit", meta={"channel": "mic"}))
    assert seen and seen[0] == ["Okay, backing up a little."]     # said while the response still streamed
    assert says(agent) == ["Okay, backing up a little."]          # once; the text after it is only a log note
    results = client.calls[1]["messages"][-1]["content"]
    assert results[0]["tool_use_id"] == "s1" and results[0]["content"] == "Said it out loud."


def test_early_say_can_be_switched_off():
    seen = []
    client = StreamClient([
        msg(tool("say", "s1", text="Okay, backing up a little."), text("Note."), tool("move", "m1")),
        msg(text("Backed up."), stop="end_turn"),
    ])
    agent = Agent(ToolBox(), client=client, ack=False)
    agent.early_say = False
    client.beta.messages.probe = lambda: seen.append(list(says(agent)))
    run(agent, Utterance("senior", "back up a bit", meta={"channel": "mic"}))
    assert seen and "Okay, backing up a little." not in seen[0]
    assert "Okay, backing up a little." in says(agent)


def test_early_say_skips_a_repeat_of_the_streamed_text():
    client = StreamClient([
        msg(text("On my way to you. "), tool("say", "s1", text="On my way to you!")),
        msg(text("Done."), stop="end_turn"),
    ])
    agent = Agent(ToolBox(), client=client, ack=False)
    run(agent, Utterance("senior", "come here", meta={"channel": "mic"}))
    assert says(agent) == ["On my way to you."]
