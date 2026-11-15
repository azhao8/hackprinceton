"""The Gemini brain (#99): Anthropic <-> OpenAI-format conversion, and the agent's tool loop,
streaming, thought signatures, errors and vision against a fake Gemini (an aiohttp test server
speaking the OpenAI-compatible chat/completions API; no key or network needed)."""

import asyncio
import base64
import json
from types import SimpleNamespace

from aiohttp import web
from aiohttp.test_utils import TestServer

from app.arbiter import Arbiter
from app.brain.agent import Agent
from app.brain.gemini_llm import (SKIP_SIGNATURE, GeminiClient, GeminiError, chat_body, message_from_openai,
                                  messages_to_openai, tools_to_openai)
from app.brain.prompt import SYSTEM_PROMPT, get_client
from app.brain.tools import ToolBox
from app.brain.types import Utterance
from app.brain.vision_check import MATCH_SCHEMA, describe_scene, matches_description
from app.skills import SkillContext, SkillResult, SkillRunner

SIG = "CsYBAXLI2nyFake/Signature=="

# --- a fake Gemini ------------------------------------------------------------------------------


def call(name, args, id_="call_1", sig=SIG, index=None):
    c = {"id": id_, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}
    if index is not None:
        c["index"] = index
    if sig:
        c["extra_content"] = {"google": {"thought_signature": sig}}
    return c


def reply(*texts, calls=(), finish=None, usage=None):
    """One streamed answer as chunks: text deltas, then the tool calls whole, then a usage chunk."""
    chunks = [{"choices": [{"index": 0, "delta": {"role": "assistant", "content": t}}]} for t in texts]
    if calls:
        chunks.append({"choices": [{"index": 0, "delta": {"role": "assistant", "tool_calls": list(calls)}}]})
    chunks.append({"choices": [{"index": 0, "delta": {}, "finish_reason": finish or ("tool_calls" if calls else "stop")}]})
    chunks.append({"choices": [], "usage": usage or {"prompt_tokens": 5000, "completion_tokens": 30,
                                                     "prompt_tokens_details": {"cached_tokens": 4000}}})
    return chunks


class FakeGemini:
    def __init__(self, script=()):
        self.script = list(script)
        self.requests = []
        self.headers = []
        self.server = None

    async def _chat(self, request):
        body = await request.json()
        self.requests.append(body)
        self.headers.append(dict(request.headers))
        assert self.script, "unexpected chat/completions call"
        chunks = self.script.pop(0)
        if isinstance(chunks, int):   # an HTTP error status, Gemini's error shape
            return web.json_response([{"error": {"code": chunks, "message": "API key not valid", "status": "X"}}],
                                     status=chunks)
        if not body.get("stream"):   # one JSON answer: the deltas folded into a message
            msg = {"role": "assistant", "content": "".join(c["choices"][0]["delta"].get("content") or ""
                                                           for c in chunks if c["choices"]) or None}
            calls = [tc for c in chunks if c["choices"] for tc in c["choices"][0]["delta"].get("tool_calls") or []]
            if calls:
                msg["tool_calls"] = calls
            finish = next(c["choices"][0]["finish_reason"] for c in chunks if c["choices"] and c["choices"][0].get("finish_reason"))
            return web.json_response({"choices": [{"index": 0, "message": msg, "finish_reason": finish}],
                                      "usage": chunks[-1]["usage"]})
        resp = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
        await resp.prepare(request)
        for ch in chunks:
            await resp.write(f"data: {json.dumps(ch)}\n\n".encode())
        await resp.write(b"data: [DONE]\n\n")
        await resp.write_eof()
        return resp

    async def __aenter__(self):
        app = web.Application()
        app.router.add_post("/v1beta/openai/chat/completions", self._chat)
        self.server = TestServer(app)
        await self.server.start_server()
        return self

    async def __aexit__(self, *exc):
        await self.server.close()

    @property
    def url(self):
        return str(self.server.make_url("/v1beta/openai"))

    def client(self, **kw):
        return GeminiClient(model="gemini-test", api_key="test-key", url=self.url, **kw)


class Quick:
    def __init__(self, name, detail="done"):
        self.name, self.detail = name, detail

    async def run(self, ctx):
        await asyncio.sleep(0.01)
        return SkillResult(True, self.detail)


def make_agent(client, factories=None, **kw):
    runner = SkillRunner(SkillContext(Arbiter()))
    return Agent(ToolBox(runner, factories or {}, **kw), client=client, keepalive_s=0)


def says(agent):
    return [e.text for e in agent.events if e.kind == "say"]


# --- conversion ---------------------------------------------------------------------------------


def test_tools_convert():
    out = tools_to_openai([{"name": "bring", "description": "Bring a thing", "strict": True,
                            "input_schema": {"type": "object", "properties": {"item": {"type": "string"}}},
                            "cache_control": {"type": "ephemeral"}}, {"name": "stop"}])
    assert out[0] == {"type": "function", "function": {"name": "bring", "description": "Bring a thing",
                                                       "parameters": {"type": "object", "properties": {"item": {"type": "string"}}}}}
    assert out[1]["function"]["parameters"] == {"type": "object", "properties": {}}


def test_messages_convert_and_signatures_round_trip():
    signed = SimpleNamespace(type="tool_use", id="call_a", name="bring", input={"item": "water"},
                             extra_content={"google": {"thought_signature": SIG}})
    second = SimpleNamespace(type="tool_use", id="call_b", name="say", input={"text": "hi"})
    img = {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": "QUJD"}}
    msgs = messages_to_openai([{"type": "text", "text": "SYS", "cache_control": {"type": "ephemeral"}}], [
        {"role": "user", "content": [{"type": "text", "text": "[senior via mic] water"}, {"type": "text", "text": "World memory: x"}]},
        {"role": "system", "content": [], "output_config": {"effort": "medium"}},
        {"role": "assistant", "content": [{"type": "thinking", "thinking": "hm"},
                                          SimpleNamespace(type="text", text="On my way."), signed, second]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "call_a", "content": "brought"},
                                     {"type": "tool_result", "tool_use_id": "call_b", "is_error": True,
                                      "content": [{"type": "text", "text": "no"}]}]},
        {"role": "user", "content": "stopped"},
        {"role": "user", "content": [img, {"type": "text", "text": "what is this?"}]},
        {"role": "assistant", "content": [{"type": "tool_use", "id": "call_c", "name": "look", "input": {}}]},
    ])
    assert msgs[0] == {"role": "system", "content": "SYS"}
    assert msgs[1] == {"role": "user", "content": "[senior via mic] water\n\nWorld memory: x"}
    a = msgs[2]
    assert a["role"] == "assistant" and a["content"] == "On my way."
    assert a["tool_calls"][0] == {"id": "call_a", "type": "function",
                                  "function": {"name": "bring", "arguments": '{"item": "water"}'},
                                  "extra_content": {"google": {"thought_signature": SIG}}}
    assert "extra_content" not in a["tool_calls"][1]   # only a step's first call carries one
    assert msgs[3] == {"role": "tool", "tool_call_id": "call_a", "content": "brought"}
    assert msgs[4] == {"role": "tool", "tool_call_id": "call_b", "content": "Error: no"}
    # a stop note and the next request run together; the image comes before the text
    assert msgs[5] == {"role": "user", "content": [{"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,QUJD"}},
                                                   {"type": "text", "text": "stopped\n\nwhat is this?"}]}
    # a call that came without a signature gets Google's placeholder (or Gemini 3/4 answer 400)
    assert msgs[6]["content"] is None
    assert msgs[6]["tool_calls"][0]["extra_content"] == {"google": {"thought_signature": SKIP_SIGNATURE}}
    assert len(msgs) == 7


def test_answer_converts_to_anthropic_blocks():
    m = message_from_openai("Hi.", [call("bring", {"item": "water"})], "tool_calls",
                            {"prompt_tokens": 100, "completion_tokens": 5, "prompt_tokens_details": {"cached_tokens": 60}}, "g")
    text, use = m.content
    assert (text.type, text.text) == ("text", "Hi.")
    assert (use.type, use.id, use.name, use.input) == ("tool_use", "call_1", "bring", {"item": "water"})
    assert use.extra_content == {"google": {"thought_signature": SIG}}
    assert m.stop_reason == "tool_use"
    assert (m.usage.input_tokens, m.usage.cache_read_input_tokens, m.usage.output_tokens) == (40, 60, 5)
    assert message_from_openai("", [], "length", None, "g").stop_reason == "max_tokens"
    assert message_from_openai("", [], "content_filter", None, "g").stop_reason == "refusal"
    # a call with no id gets one; arguments that aren't JSON become {}
    odd = message_from_openai("", [{"function": {"name": "x", "arguments": "{not json"}}], "stop", None, "g")
    assert odd.content[0].id.startswith("toolu_gemini_") and odd.content[0].input == {}


def test_chat_body_settings():
    body = chat_body({"system": "S", "max_tokens": 8000, "fallbacks": "default", "betas": ["x"],
                      "cache_control": {"type": "ephemeral"}, "output_config": {"effort": "medium"},
                      "tools": [{"name": "t", "input_schema": {"type": "object"}}],
                      "messages": [{"role": "user", "content": "hi"}]}, model="gemini-test", effort="low")
    assert body["model"] == "gemini-test" and body["reasoning_effort"] == "low" and body["max_tokens"] == 8000
    assert body["stream"] is True and body["stream_options"] == {"include_usage": True}
    assert body["tool_choice"] == "auto" and body["tools"][0]["function"]["name"] == "t"
    assert not {"fallbacks", "betas", "cache_control", "output_config", "system"} & set(body)
    js = chat_body({"output_config": {"format": {"type": "json_schema", "schema": MATCH_SCHEMA}},
                    "messages": [{"role": "user", "content": "x"}]}, model="g", stream=False)
    assert js["response_format"] == {"type": "json_schema", "json_schema": {"name": "answer", "schema": MATCH_SCHEMA}}
    assert "stream_options" not in js and "tools" not in js


def test_switch(monkeypatch):
    import app.brain.prompt as prompt
    from app.__main__ import brain_available

    monkeypatch.setattr(prompt, "_client", None)
    monkeypatch.setenv("MIGUEL_LLM", "gemini")
    monkeypatch.setenv("MIGUEL_GEMINI_MODEL", "gemini-4-argon")
    monkeypatch.setenv("MIGUEL_GEMINI_EFFORT", "medium")
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    c = get_client()
    assert isinstance(c, GeminiClient) and c.model == "gemini-4-argon" and c.effort == "medium" and c.api_key == "k"
    assert c.url == "https://generativelanguage.googleapis.com/v1beta/openai"
    assert brain_available()
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "a")
    assert not brain_available()   # gemini needs its own key
    assert not make_agent(GeminiClient(api_key="k")).local   # the Claude path: no Ollama warm-up or trimming
    monkeypatch.setattr(prompt, "_client", None)


# --- the agent on the fake Gemini ---------------------------------------------------------------


def test_full_tool_loop_round_trips_the_thought_signature():
    async def go():
        async with FakeGemini([
            reply("I'll get you some water.", calls=[call("bring", {"item": "water", "person": "Mom", "step": None})]),
            reply("Here you go, Mom. ", "Anything else?"),
        ]) as gem:
            built = []
            agent = make_agent(gem.client(),
                               {"bring": lambda **kw: built.append(kw) or Quick("bring", "brought water to Mom")})
            await agent.handle(Utterance("senior", "Miguel, bring me some water"))
            await agent.idle()
            return agent, gem, built

    agent, gem, built = asyncio.run(go())
    assert built == [{"item": "water", "person": "Mom"}]
    assert says(agent) == ["On it!", "I'll get you some water.", "Here you go, Mom.", "Anything else?"]
    assert [e.data["status"] for e in agent.events if e.kind == "task"] == ["started", "done"]
    first, second = gem.requests
    assert gem.headers[0]["Authorization"] == "Bearer test-key"
    assert first["model"] == "gemini-test" and first["reasoning_effort"] == "low"
    assert first["messages"][0] == {"role": "system", "content": SYSTEM_PROMPT}
    assert first["messages"][1]["content"].startswith("[senior via mic] Miguel, bring me some water\n\nWorld memory: ")
    assert {t["function"]["name"] for t in first["tools"]} == set(agent.tools.names)
    asked = second["messages"][2]
    assert asked["tool_calls"][0]["id"] == "call_1"
    assert asked["tool_calls"][0]["extra_content"] == {"google": {"thought_signature": SIG}}   # back as it came
    assert second["messages"][3] == {"role": "tool", "tool_call_id": "call_1", "content": "bring: brought water to Mom"}


def test_next_task_keeps_the_signed_history():
    async def go():
        async with FakeGemini([reply(calls=[call("say", {"text": "Hello Mom."}, sig="S1")]), reply("Done."),
                               reply("Hi again.")]) as gem:
            agent = make_agent(gem.client())
            await agent.handle(Utterance("senior", "Miguel, say hello"))
            await agent.idle()
            await agent.handle(Utterance("senior", "Miguel, hi"))
            await agent.idle()
            return agent, gem

    agent, gem = asyncio.run(go())
    assert says(agent)[-1] == "Hi again."
    later = gem.requests[2]["messages"]
    calls = [m for m in later if m.get("tool_calls")]
    assert calls[0]["tool_calls"][0]["extra_content"]["google"]["thought_signature"] == "S1"


def test_streamed_tool_call_pieces_are_joined():
    pieces = [{"index": 0, "id": "c1", "type": "function", "function": {"name": "bring", "arguments": '{"item": '},
               "extra_content": {"google": {"thought_signature": SIG}}},
              {"index": 0, "function": {"arguments": '"water"}'}},
              {"index": 1, "id": "c2", "type": "function", "function": {"name": "say", "arguments": '{"text": "ok"}'}}]
    chunks = [{"choices": [{"index": 0, "delta": {"tool_calls": [p]}}]} for p in pieces]
    chunks.append({"choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]})

    async def go():
        async with FakeGemini([chunks]) as gem:
            return await gem.client().messages.create(max_tokens=100, messages=[{"role": "user", "content": "x"}])

    m = asyncio.run(go())
    a, b = m.content
    assert (a.id, a.name, a.input, a.extra_content["google"]["thought_signature"]) == ("c1", "bring", {"item": "water"}, SIG)
    assert (b.id, b.name, b.input) == ("c2", "say", {"text": "ok"}) and not hasattr(b, "extra_content")
    assert m.stop_reason == "tool_use" and m.usage.input_tokens == 0


def test_non_streaming_mode():
    async def go():
        async with FakeGemini([reply("Hello there.", calls=[call("say", {"text": "x"})])]) as gem:
            m = await gem.client(stream=False).messages.create(max_tokens=100, messages=[{"role": "user", "content": "x"}])
            return gem, m

    gem, m = asyncio.run(go())
    assert gem.requests[0]["stream"] is False
    assert m.content[0].text == "Hello there." and m.content[1].extra_content["google"]["thought_signature"] == SIG
    assert m.usage.cache_read_input_tokens == 4000


def test_warm_up_request_makes_no_call():
    async def go():
        async with FakeGemini([]) as gem:
            agent = make_agent(gem.client())
            ran = await agent.prewarm()
            return gem, ran

    gem, ran = asyncio.run(go())
    assert ran and gem.requests == []


def test_errors_are_api_errors_and_busy_is_retried_once():
    async def go():
        async with FakeGemini([401, 503, reply("Back.")]) as gem:
            bad = make_agent(gem.client())
            await bad.handle(Utterance("senior", "hello"))
            await bad.idle()
            retried = make_agent(gem.client())
            await retried.handle(Utterance("senior", "hello"))
            await retried.idle()
            down = make_agent(GeminiClient(api_key="k", url="http://127.0.0.1:9", retries=0))   # nothing listens there
            await down.handle(Utterance("senior", "hello"))
            await down.idle()
            nokey = make_agent(GeminiClient(api_key="", url=gem.url))
            await nokey.handle(Utterance("senior", "hello"))
            await nokey.idle()
            return bad, retried, down, nokey, gem

    bad, retried, down, nokey, gem = asyncio.run(go())
    for a in (bad, down, nokey):
        assert says(a)[-1] == "Sorry, my brain isn't connected right now."
        assert any(e.kind == "error" and e.text.startswith("Gemini error: GeminiError") for e in a.events)
    assert any("API key not valid" in e.text for e in bad.events if e.kind == "error")
    assert any("GEMINI_API_KEY is not set" in e.text for e in nokey.events if e.kind == "error")
    assert says(retried) == ["Back."]
    assert len(gem.requests) == 3
    assert issubclass(GeminiError, Exception)


# --- vision on the fake Gemini ------------------------------------------------------------------


def test_describe_scene_sends_every_frame_of_a_clip():
    async def go():
        async with FakeGemini([reply("She is standing up.")]) as gem:
            return gem, await describe_scene([b"f1", b"f2", b"f3"], gem.client(), question="What is she doing?")

    gem, answer = asyncio.run(go())
    assert answer == "She is standing up."
    parts = gem.requests[0]["messages"][0]["content"]
    assert [p["image_url"]["url"] for p in parts[:3]] == \
        [f"data:image/jpeg;base64,{base64.b64encode(f).decode()}" for f in (b"f1", b"f2", b"f3")]
    assert "3 camera frames" in parts[3]["text"] and "What is she doing?" in parts[3]["text"]


def test_matches_description_asks_for_json_schema():
    async def go():
        async with FakeGemini([reply('{"match": true, "reason": "red shirt"}')]) as gem:
            return gem, await matches_description(b"crop", "the man in the red shirt", gem.client())

    gem, answer = asyncio.run(go())
    assert answer == (True, "red shirt")
    rf = gem.requests[0]["response_format"]
    assert rf["type"] == "json_schema" and rf["json_schema"]["schema"]["required"] == ["match", "reason"]
