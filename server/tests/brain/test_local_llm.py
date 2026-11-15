"""The local brain (#81): Anthropic <-> Ollama conversion, and the agent's tool loop, warm-up,
streaming and vision against a fake Ollama (an aiohttp test server; no real model needed)."""

import asyncio
import base64
import json
import logging
from types import SimpleNamespace

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from app.arbiter import Arbiter
from app.brain import local_llm
from app.brain.agent import Agent
from app.brain.local_llm import (LocalClient, LocalLLMError, chat_body, message_from_ollama, messages_to_ollama,
                                 tools_to_ollama)
from app.brain.prompt import SYSTEM_PROMPT, get_client
from app.brain.tools import ToolBox
from app.brain.types import Utterance
from app.brain.vision_check import describe_scene, matches_description
from app.skills import SkillContext, SkillResult, SkillRunner

# --- a fake Ollama ------------------------------------------------------------------------------


def reply(*texts, calls=(), done_reason="stop", prompt_tokens=4400, out_tokens=20):
    """One /api/chat answer as NDJSON chunks: text deltas, then the tool calls whole, then done."""
    chunks = [{"message": {"role": "assistant", "content": t}, "done": False} for t in texts]
    if calls:
        chunks.append({"message": {"role": "assistant", "content": "",
                                   "tool_calls": [{"function": {"name": n, "arguments": a}} for n, a in calls]},
                       "done": False})
    chunks.append({"message": {"role": "assistant", "content": ""}, "done": True, "done_reason": done_reason,
                   "prompt_eval_count": prompt_tokens, "prompt_eval_duration": 180_000_000,
                   "eval_count": out_tokens, "eval_duration": 400_000_000, "load_duration": 1_000_000})
    return chunks


class FakeOllama:
    def __init__(self, script=(), delay=0.0):
        self.script = list(script)
        self.requests = []      # /api/chat bodies
        self.generates = []     # /api/generate bodies
        self.delay = delay      # between chunks
        self.server = None

    async def _chat(self, request):
        body = await request.json()
        self.requests.append(body)
        assert self.script, "unexpected /api/chat call"
        chunks = self.script.pop(0)
        if isinstance(chunks, int):   # an HTTP error status
            return web.Response(status=chunks, text='{"error":"model not found"}')
        resp = web.StreamResponse(headers={"Content-Type": "application/x-ndjson"})
        await resp.prepare(request)
        for ch in chunks:
            await resp.write((json.dumps(ch) + "\n").encode())
            await asyncio.sleep(self.delay)
        await resp.write_eof()
        return resp

    async def _generate(self, request):
        self.generates.append(await request.json())
        return web.json_response({"model": "m", "done": True})

    async def __aenter__(self):
        app = web.Application()
        app.router.add_post("/api/chat", self._chat)
        app.router.add_post("/api/generate", self._generate)
        self.server = TestServer(app)   # a free port on 127.0.0.1
        await self.server.start_server()
        return self

    async def __aexit__(self, *exc):
        await self.server.close()

    @property
    def url(self):
        return str(self.server.make_url("")).rstrip("/")

    def client(self, **kw):
        return LocalClient(model="test-model", url=self.url, **kw)


class Quick:
    def __init__(self, name, detail="done"):
        self.name, self.detail = name, detail

    async def run(self, ctx):
        await asyncio.sleep(0.01)
        return SkillResult(True, self.detail)


def make_agent(client, factories=None, **kw):
    runner = SkillRunner(SkillContext(Arbiter()))
    tools = ToolBox(runner, factories or {}, **kw)
    return Agent(tools, client=client, keepalive_s=0)


def says(agent):
    return [e.text for e in agent.events if e.kind == "say"]


# --- conversion ---------------------------------------------------------------------------------


def test_tools_convert_strict_and_non_strict():
    defs = ToolBox().definitions()
    non_strict = {"name": "move", "description": "Drive a bit.",
                  "input_schema": {"type": "object", "properties": {"m": {"type": "number"}}}}
    out = tools_to_ollama([*defs, non_strict])
    assert len(out) == len(defs) + 1
    for d, o in zip(defs, out):
        assert o == {"type": "function", "function": {"name": d["name"], "description": d["description"],
                                                      "parameters": d["input_schema"]}}
    assert out[-1]["function"]["parameters"] == non_strict["input_schema"]
    assert not any("strict" in json.dumps(o["function"]).split('"parameters"')[0] for o in out)
    assert tools_to_ollama([{"name": "stop", "description": "x"}])[0]["function"]["parameters"]["type"] == "object"


def test_messages_convert_tool_use_results_images_and_drop_anthropic_parts():
    jpeg = base64.standard_b64encode(b"jpg").decode()
    system = [{"type": "text", "text": "You are Miguel.", "cache_control": {"type": "ephemeral"}}]
    msgs = [
        {"role": "user", "content": [{"type": "text", "text": "[stop] earlier note"}]},
        {"role": "user", "content": [{"type": "text", "text": "[senior via mic] bring water"},
                                     {"type": "text", "text": "World memory: x", "cache_control": {"type": "ephemeral"}}]},
        {"role": "system", "content": [], "output_config": {"effort": "medium"}},   # per-message effort: dropped
        {"role": "assistant", "content": [
            SimpleNamespace(type="thinking", thinking="hmm", signature="s"),
            SimpleNamespace(type="text", text="On my way."),
            SimpleNamespace(type="tool_use", id="t1", name="bring", input={"item": "water", "person": "Mom", "step": None}),
            {"type": "tool_use", "id": "t2", "name": "say", "input": {"text": "Hi"}}]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": "bring: done"},
            {"type": "tool_result", "tool_use_id": "t2", "is_error": True,
             "content": [{"type": "text", "text": "no speaker"}]},
            {"type": "text", "text": "[guardian via app, while you were working] thanks"}]},
        {"role": "user", "content": [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                                  "data": jpeg}},
                                     {"type": "text", "text": "what is this?"}]},
    ]
    out = messages_to_ollama(system, msgs)
    assert out == [
        {"role": "system", "content": "You are Miguel."},
        {"role": "user", "content": "[stop] earlier note\n\n[senior via mic] bring water\n\nWorld memory: x"},
        {"role": "assistant", "content": "On my way.", "tool_calls": [
            {"function": {"name": "bring", "arguments": {"item": "water", "person": "Mom", "step": None}}},
            {"function": {"name": "say", "arguments": {"text": "Hi"}}}]},
        {"role": "tool", "tool_name": "bring", "content": "bring: done"},
        {"role": "tool", "tool_name": "say", "content": "Error: no speaker"},
        {"role": "user", "content": "[guardian via app, while you were working] thanks\n\nwhat is this?",
         "images": [jpeg]},
    ]
    assert messages_to_ollama(system, msgs) == out   # deterministic: the same prefix every time


def test_answer_converts_to_anthropic_blocks():
    m = message_from_ollama("On it.", [{"function": {"name": "bring", "arguments": {"item": "water"}}},
                                       {"function": {"name": "say", "arguments": '{"text": "hi"}'}}],
                            {"done_reason": "stop", "prompt_eval_count": 10, "eval_count": 3}, "test-model")
    assert m.stop_reason == "tool_use"
    assert [b.type for b in m.content] == ["text", "tool_use", "tool_use"]
    assert m.content[1].name == "bring" and m.content[1].input == {"item": "water"}
    assert m.content[2].input == {"text": "hi"}                    # JSON-string arguments parsed
    assert m.content[1].id != m.content[2].id and m.content[1].id.startswith("toolu_")
    assert (m.usage.input_tokens, m.usage.output_tokens, m.usage.local) == (10, 3, True)
    assert message_from_ollama("hi", [], {"done_reason": "stop"}, "m").stop_reason == "end_turn"
    assert message_from_ollama("hi", [], {"done_reason": "length"}, "m").stop_reason == "max_tokens"


def test_chat_body_settings():
    schema = {"type": "object", "properties": {"match": {"type": "boolean"}}}
    body = chat_body({"model": "claude-sonnet-5-5", "max_tokens": 8000, "betas": ["x"], "fallbacks": "default",
                      "cache_control": {"type": "ephemeral"},
                      "output_config": {"effort": "low", "format": {"type": "json_schema", "schema": schema}},
                      "messages": [{"role": "user", "content": "hi"}]}, model="test-model")
    assert body["model"] == "test-model" and body["think"] is False and body["stream"] is True
    assert body["options"]["num_ctx"] == local_llm.NUM_CTX
    assert body["options"]["num_predict"] == local_llm.MAX_PREDICT
    assert body["format"] == schema and "tools" not in body
    assert set(body) == {"model", "messages", "stream", "think", "keep_alive", "options", "format"}


def test_switch(monkeypatch):
    import app.brain.prompt as prompt

    monkeypatch.setattr(prompt, "_client", None)
    monkeypatch.setenv("MIGUEL_LLM", "local")
    monkeypatch.setenv("MIGUEL_LOCAL_MODEL", "qwen3.6:latest")
    monkeypatch.setenv("OLLAMA_URL", "http://127.0.0.1:9/")
    c = get_client()
    assert isinstance(c, LocalClient) and c.model == "qwen3.6:latest" and c.url == "http://127.0.0.1:9"
    monkeypatch.setattr(prompt, "_client", None)
    monkeypatch.setenv("MIGUEL_LLM", "claude")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    assert not isinstance(get_client(), LocalClient)
    monkeypatch.setattr(prompt, "_client", None)


# --- the agent on the fake Ollama ---------------------------------------------------------------


def test_full_tool_loop(caplog):
    caplog.set_level(logging.INFO, logger="app.brain.agent")

    async def go():
        async with FakeOllama([
            reply("I'll get you some water.", calls=[("bring", {"item": "water", "person": "Mom", "step": None})]),
            reply("Here you go, Mom. ", "Anything else?"),
        ]) as ollama:
            built = []
            agent = make_agent(ollama.client(),
                               {"bring": lambda **kw: built.append(kw) or Quick("bring", "brought water to Mom")})
            await agent.handle(Utterance("senior", "Miguel, bring me some water"))
            await agent.idle()
            return agent, ollama, built

    agent, ollama, built = asyncio.run(go())
    assert built == [{"item": "water", "person": "Mom"}]
    assert says(agent) == ["On it!", "I'll get you some water.", "Here you go, Mom.", "Anything else?"]
    tasks = [e.data["status"] for e in agent.events if e.kind == "task"]
    assert tasks == ["started", "done"]
    first, second = ollama.requests
    assert first["model"] == "test-model" and first["think"] is False
    assert first["messages"][0] == {"role": "system", "content": SYSTEM_PROMPT}
    assert first["messages"][1]["content"].startswith("[senior via mic] Miguel, bring me some water\n\nWorld memory: ")
    assert {t["function"]["name"] for t in first["tools"]} == set(agent.tools.names)
    # the second call is the first one plus the answer and the tool's result: append-only
    assert second["messages"][: len(first["messages"])] == first["messages"]
    assert second["messages"][2]["tool_calls"][0]["function"]["name"] == "bring"
    assert second["messages"][3] == {"role": "tool", "tool_name": "bring", "content": "bring: brought water to Mom"}
    assert any("local test-model" in r.message and "tok/s" in r.message for r in caplog.records)


def test_next_task_appends_to_the_history_and_trims_by_half_near_num_ctx():
    async def go():
        async with FakeOllama([reply("Hello Mom."), reply("Hi again.", prompt_tokens=int(0.8 * local_llm.NUM_CTX)),
                               reply("Third.")]) as ollama:
            agent = make_agent(ollama.client())
            for text in ("hello", "hi", "hey"):
                await agent.handle(Utterance("senior", text))
                await agent.idle()
            return agent, ollama

    agent, ollama = asyncio.run(go())
    a, b, c = ollama.requests
    assert b["messages"][: len(a["messages"])] == a["messages"]   # task 2 extends task 1
    assert len(agent._history) == 2                                 # after task 2: 2 tasks, then cut to 1 (+ task 3)
    assert "[senior via mic] hi" in c["messages"][1]["content"]     # the oldest task went, the newer stayed


def test_sentences_stream_as_they_arrive_and_a_repeated_say_is_not_said_twice():
    async def go():
        async with FakeOllama([
            reply("Here's your water! ", "I hope it's ", "nice and cool. 💧",
                  calls=[("say", {"text": "Here's your water! I hope it's nice and cool.", "step": None})]),
            reply("."),
        ], delay=0.2) as ollama:
            agent = make_agent(ollama.client())
            await agent.handle(Utterance("senior", "hello there"))
            for _ in range(200):
                if says(agent):
                    break
                await asyncio.sleep(0.005)
            early = says(agent), len(ollama.requests)   # the first sentence is out while the rest streams
            await agent.idle()
            return agent, early

    agent, early = asyncio.run(go())
    assert early == (["Here's your water!"], 1)
    assert says(agent) == ["Here's your water!", "I hope it's nice and cool."]   # emoji gone, say not repeated


def test_say_tool_and_final_text_lose_emojis_and_markdown():
    async def go():
        async with FakeOllama([reply(calls=[("say", {"text": "**Good morning**, Mom! 🌞", "step": None})]),
                               reply("💧")]) as ollama:
            agent = make_agent(ollama.client())
            await agent.handle(Utterance("senior", "morning"))
            await agent.idle()
            return agent

    assert says(asyncio.run(go())) == ["Good morning, Mom!"]


def test_warm_up_then_keep_loaded():
    async def go():
        async with FakeOllama([reply("x"), reply("y")]) as ollama:
            agent = make_agent(ollama.client())
            assert await agent.prewarm()
            assert await agent.prewarm()   # warmed: only a keep-alive this time
            return ollama

    ollama = asyncio.run(go())
    a, b = ollama.requests
    for r in (a, b):
        assert r["messages"][0] == {"role": "system", "content": SYSTEM_PROMPT}
        assert r["options"]["num_predict"] == 1 and len(r["tools"]) == len(ToolBox().definitions())
        assert "\n\nWorld memory: " in r["messages"][1]["content"]
    assert a["messages"][1]["content"] != b["messages"][1]["content"]   # two different user turns
    assert a["tools"] == b["tools"]
    assert ollama.generates == [{"model": "test-model", "keep_alive": local_llm.KEEP_ALIVE}]


def test_run_warms_up_in_the_background_even_with_keepalive_off():
    async def go():
        async with FakeOllama([reply("x"), reply("y")]) as ollama:
            agent = make_agent(ollama.client())
            runner = asyncio.create_task(agent.run())
            for _ in range(100):
                if len(ollama.requests) == 2:
                    break
                await asyncio.sleep(0.02)
            runner.cancel()
            return ollama

    assert len(asyncio.run(go()).requests) == 2


def test_ollama_down_or_missing_model_is_an_api_error():
    async def go():
        async with FakeOllama([404]) as ollama:
            agent = make_agent(ollama.client())
            await agent.handle(Utterance("senior", "hello"))
            await agent.idle()
            down = make_agent(LocalClient(model="m", url="http://127.0.0.1:9"))   # nothing listens there
            await down.handle(Utterance("senior", "hello"))
            await down.idle()
            return agent, down

    agent, down = asyncio.run(go())
    for a in (agent, down):
        assert says(a)[-1] == "Sorry, my brain isn't connected right now."
        assert any(e.kind == "error" and e.text.startswith("Local model error: LocalLLMError") for e in a.events)
    with pytest.raises(LocalLLMError):
        asyncio.run(LocalClient(model="m", url="http://127.0.0.1:9").keep_loaded())


# --- vision on the fake Ollama ------------------------------------------------------------------


def test_describe_scene_sends_every_frame_of_a_clip():
    async def go():
        async with FakeOllama([reply("She is standing up."), reply("A mug.")]) as ollama:
            c = ollama.client()
            clip = await describe_scene([b"f1", b"f2", b"f3"], c, question="What is she doing?")
            one = await describe_scene(b"f1", c)
            return ollama, clip, one

    ollama, clip, one = asyncio.run(go())
    assert (clip, one) == ("She is standing up.", "A mug.")
    a, b = ollama.requests
    assert a["messages"][0]["images"] == [base64.b64encode(f).decode() for f in (b"f1", b"f2", b"f3")]
    assert "3 camera frames" in a["messages"][0]["content"] and "What is she doing?" in a["messages"][0]["content"]
    assert len(b["messages"][0]["images"]) == 1 and "short clip" not in b["messages"][0]["content"]


def test_matches_description_uses_ollama_json_format():
    async def go():
        async with FakeOllama([reply('{"match": true, "reason": "red shirt"}')]) as ollama:
            return ollama, await matches_description(b"crop", "the man in the red shirt", ollama.client())

    ollama, answer = asyncio.run(go())
    assert answer == (True, "red shirt")
    assert ollama.requests[0]["format"]["required"] == ["match", "reason"]


def test_describe_scene_tool_takes_a_clip_when_asked():
    frames = iter([b"a", b"a", b"b", b"c"])   # the camera repeats a frame once: skipped
    got = []

    async def describe(jpeg, question=None):
        got.append((jpeg, question))
        return "someone is getting up"

    async def go():
        tb = ToolBox(snapshot=lambda: next(frames), describe=describe, clip_gap_s=0, clip_frames=4)
        clip = await tb.call("describe_scene", {"question": "is she getting up?", "clip": True})
        tb.snapshot = lambda: b"z"
        one = await tb.call("describe_scene", {"question": None, "clip": False})
        return clip, one

    clip, one = asyncio.run(go())
    assert clip.ok and one.ok
    assert got == [([b"a", b"b", b"c"], "is she getting up?"), (b"z", None)]
    schema = next(d for d in ToolBox().definitions() if d["name"] == "describe_scene")["input_schema"]
    assert schema["properties"]["clip"]["type"] == "boolean"
