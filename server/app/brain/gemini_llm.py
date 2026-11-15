"""Miguel's brain on Google Gemini (#99, the MLH "Best Use of Gemini API" challenge).

Switch: `MIGUEL_LLM=gemini` with `GEMINI_API_KEY` (from Google AI Studio). `MIGUEL_GEMINI_MODEL`
(default below) and `MIGUEL_GEMINI_EFFORT` (Gemini's `reasoning_effort`, default `low`; thinking
can't be turned off on Gemini 3 and 4).

`GeminiClient` looks like the part of `AsyncAnthropic` the brain uses (`client.beta.messages.create`
and `.stream`), like local_llm.py's `LocalClient`, so the agent's tool loop, the vision checks and
the fall check run unchanged. It calls Gemini's OpenAI-compatible endpoint
(`{base}/chat/completions`, streamed as server-sent events) with aiohttp, so no new package:

- tools: `{name, description, input_schema}` -> `{"type": "function", "function": {name,
  description, parameters}}`; `tool_choice: "auto"`.
- messages: `tool_use` blocks -> the assistant's `tool_calls` (arguments as a JSON string);
  `tool_result` blocks -> `role: tool` messages with `tool_call_id`, in the order of the calls;
  image blocks -> `image_url` data URLs; text blocks of one user turn are joined; consecutive user
  turns are merged.
- Thought signatures: Gemini 3 and 4 sign each step's function calls, and a call sent back without
  its signature is a 400. The signature comes in the tool call's `extra_content`; it is kept whole
  on the `tool_use` block (`extra_content`), so it rides along in the agent's history and goes
  back verbatim. A first call with no signature (none came) gets Google's documented placeholder.
- Anthropic-only parts are dropped: cache_control, betas, fallbacks, the per-message `role: system`
  effort note and thinking blocks. A `json_schema` output format becomes `response_format`
  `json_schema`. A `max_tokens=0` request (the agent's cache warm-up) answers at once without a
  call: Gemini's cache is implicit.
- Errors are `GeminiError`, a subclass of `anthropic.APIError`, so the agent's "my brain isn't
  connected" path handles a bad key or a network failure too. 429/5xx before the answer starts are
  retried once.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import AsyncIterator
from itertools import count
from types import SimpleNamespace
from typing import Any

import aiohttp
import anthropic
import httpx2   # anthropic's HTTP library (its errors carry a request)

from app.brain.local_llm import _get, _image_data, _result_text, system_text

log = logging.getLogger(__name__)

# Measured Nov 15 on a free-tier key: the only model that answered every call, and the fastest (first
# sentence 0.8 s for chat, 2.6 s for a task; 0.9 s for a picture question). gemini-4-hydrogen and
# gemini-3.8-flash gave 503 "high demand" after 20-50 s; gemini-4-argon has no free-tier quota.
DEFAULT_MODEL = "gemini-3.5-flash-lite"
DEFAULT_URL = "https://generativelanguage.googleapis.com/v1beta/openai"
DEFAULT_EFFORT = "low"
# For a call that has no signature of its own (Google's documented placeholder, for calls the API didn't make).
SKIP_SIGNATURE = "skip_thought_signature_validator"
RETRY_STATUSES = (429, 500, 502, 503, 504)


def gemini_model() -> str:
    return os.environ.get("MIGUEL_GEMINI_MODEL", "").strip() or DEFAULT_MODEL


def gemini_effort() -> str:
    return os.environ.get("MIGUEL_GEMINI_EFFORT", "").strip().lower() or DEFAULT_EFFORT


def gemini_url() -> str:
    return (os.environ.get("GEMINI_BASE_URL", "").strip() or DEFAULT_URL).rstrip("/")


class GeminiError(anthropic.APIError):
    """Gemini failed: no or bad key, unreachable, a bad request or a broken stream."""

    def __init__(self, message: str, url: str = DEFAULT_URL) -> None:
        super().__init__(message, httpx2.Request("POST", url), body=None)


# --- Anthropic -> OpenAI format -----------------------------------------------------------------


def tools_to_openai(tools: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Anthropic tool definitions -> OpenAI function tools (`strict` and cache_control dropped)."""
    return [{"type": "function", "function": {"name": t["name"], "description": t.get("description", ""),
                                              "parameters": t.get("input_schema") or {"type": "object", "properties": {}}}}
            for t in tools or []]


def _signed(extra: Any) -> bool:
    google = (extra or {}).get("google") if isinstance(extra, dict) else None
    return bool(isinstance(google, dict) and google.get("thought_signature"))


def _image_url(block: Any) -> str | None:
    data = _image_data(block)
    if not data:
        return None
    mime = _get(_get(block, "source") or {}, "media_type") or "image/jpeg"
    return f"data:{mime};base64,{data}"


def messages_to_openai(system: Any, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """An Anthropic `system` + `messages` -> chat-completions messages."""
    out: list[dict[str, Any]] = []
    sys_text = system_text(system)
    if sys_text:
        out.append({"role": "system", "content": sys_text})
    for m in messages:
        role, content = m["role"], m.get("content")
        if role == "system":     # the per-message effort note (Anthropic only)
            continue
        blocks = [{"type": "text", "text": content}] if isinstance(content, str) else list(content or [])
        if role == "assistant":
            text = "".join(_get(b, "text", "") for b in blocks if _get(b, "type") == "text")
            calls = []
            for b in blocks:
                if _get(b, "type") != "tool_use":
                    continue
                call: dict[str, Any] = {"id": _get(b, "id"), "type": "function",
                                        "function": {"name": _get(b, "name"),
                                                     "arguments": json.dumps(dict(_get(b, "input") or {}))}}
                extra = _get(b, "extra_content")
                if extra:
                    call["extra_content"] = extra
                calls.append(call)
            if calls and not any(_signed(c.get("extra_content")) for c in calls):
                # Gemini 3/4 want a signature on a step's first call; none came (or it's a replayed call)
                calls[0]["extra_content"] = {"google": {"thought_signature": SKIP_SIGNATURE}}
            if not text and not calls:   # a turn that was only thinking
                continue
            msg: dict[str, Any] = {"role": "assistant", "content": text or None}
            if calls:
                msg["tool_calls"] = calls
            out.append(msg)
            continue
        parts: list[dict[str, Any]] = []
        texts: list[str] = []
        for b in blocks:
            kind = _get(b, "type")
            if kind == "tool_result":
                body = _result_text(_get(b, "content"))
                if _get(b, "is_error"):
                    body = f"Error: {body}"
                out.append({"role": "tool", "tool_call_id": _get(b, "tool_use_id"), "content": body or "(no output)"})
            elif kind == "text" and _get(b, "text"):
                texts.append(_get(b, "text"))
            elif kind == "image" and _image_url(b):
                parts.append({"type": "image_url", "image_url": {"url": _image_url(b)}})
        if not texts and not parts:
            continue
        if out and out[-1]["role"] == "user":   # two user turns in a row (a stop note, then a request)
            prev = out[-1]
            prev_parts = prev["content"] if isinstance(prev["content"], list) else [{"type": "text", "text": prev["content"]}]
            merged = "\n\n".join([*(p["text"] for p in prev_parts if p["type"] == "text"), *texts])
            prev["content"] = _user_content(merged, [*(p for p in prev_parts if p["type"] != "text"), *parts])
            continue
        out.append({"role": "user", "content": _user_content("\n\n".join(texts), parts)})
    return out


def _user_content(text: str, images: list[dict[str, Any]]) -> Any:
    """A plain string when there are no images; otherwise the images, then the text."""
    if not images:
        return text
    return [*images, *([{"type": "text", "text": text}] if text else [])]


def chat_body(params: dict[str, Any], *, model: str, effort: str | None = None, stream: bool = True) -> dict[str, Any]:
    """The /chat/completions request for an Anthropic-style `messages.create` call."""
    body: dict[str, Any] = {
        "model": model,
        "messages": messages_to_openai(params.get("system"), params.get("messages") or []),
        "stream": stream,
        "reasoning_effort": effort or gemini_effort(),
    }
    if params.get("max_tokens"):
        body["max_tokens"] = int(params["max_tokens"])
    if stream:
        body["stream_options"] = {"include_usage": True}
    tools = tools_to_openai(params.get("tools"))
    if tools:
        body["tools"] = tools
        body["tool_choice"] = "auto"
    fmt = (params.get("output_config") or {}).get("format") or {}
    if fmt.get("type") == "json_schema" and fmt.get("schema"):
        body["response_format"] = {"type": "json_schema",
                                   "json_schema": {"name": fmt.get("name") or "answer", "schema": fmt["schema"]}}
    return body


# --- OpenAI format -> Anthropic -----------------------------------------------------------------

_ids = count(1)


def _parse_args(args: Any) -> dict[str, Any]:
    if isinstance(args, str):
        try:
            args = json.loads(args) if args.strip() else {}
        except ValueError:
            args = {}
    return args if isinstance(args, dict) else {}


def message_from_openai(text: str, calls: list[dict[str, Any]], finish: str | None, usage: dict[str, Any] | None,
                        model: str) -> Any:
    """What Gemini sent -> an Anthropic-shaped message (content blocks, stop_reason, usage)."""
    content: list[Any] = []
    if text:
        content.append(SimpleNamespace(type="text", text=text))
    for c in calls:
        fn = c.get("function") or {}
        block = SimpleNamespace(type="tool_use", id=c.get("id") or f"toolu_gemini_{next(_ids)}",
                                name=fn.get("name", ""), input=_parse_args(fn.get("arguments")))
        if c.get("extra_content"):
            block.extra_content = c["extra_content"]   # the thought signature: goes back as it came
        content.append(block)
    if finish == "length":
        stop = "max_tokens"
    elif calls:
        stop = "tool_use"
    elif finish == "content_filter":
        stop = "refusal"
    else:
        stop = "end_turn"
    u = usage or {}
    cached = ((u.get("prompt_tokens_details") or {}).get("cached_tokens")) or 0
    prompt = u.get("prompt_tokens") or 0
    usage_ns = SimpleNamespace(input_tokens=max(0, prompt - cached), output_tokens=u.get("completion_tokens") or 0,
                               cache_read_input_tokens=cached, cache_creation_input_tokens=0)
    return SimpleNamespace(content=content, stop_reason=stop, stop_details=None, model=model, usage=usage_ns)


def _merge_call(calls: dict[int, dict[str, Any]], i: int, delta: dict[str, Any]) -> None:
    """Fold one streamed tool_call delta into the call at index i (OpenAI streams the arguments in
    pieces; Gemini usually sends a call whole)."""
    c = calls.setdefault(i, {"id": None, "function": {"name": "", "arguments": ""}})
    if delta.get("id"):
        c["id"] = delta["id"]
    fn = delta.get("function") or {}
    if fn.get("name"):
        c["function"]["name"] = fn["name"]
    args = fn.get("arguments")
    if isinstance(args, dict):
        c["function"]["arguments"] = json.dumps(args)
    elif args:
        c["function"]["arguments"] += args
    if delta.get("extra_content"):
        c["extra_content"] = delta["extra_content"]


def _error_detail(text: str) -> str:
    """Gemini's error message from an error body (a JSON object, or a one-element list of one),
    with the quota line when there is one; else the start of the body."""
    try:
        data = json.loads(text)
        err = (data[0] if isinstance(data, list) and data else data).get("error") or {}
        msg = str(err.get("message") or "").strip()
    except (ValueError, AttributeError):
        msg = ""
    if not msg:
        return text[:300]
    first, _, rest = msg.partition("\n")
    quota = next((ln.strip(" *") for ln in rest.splitlines() if "Quota exceeded" in ln), "")
    return f"{first[:200]}{' ' + quota[:200] if quota else ''}"


# --- the client ---------------------------------------------------------------------------------


class _Stream:
    """`async with client.beta.messages.stream(**kw) as s: async for ev in s: ...; await s.get_final_message()`.
    Events: content_block_start (text), text deltas, content_block_stop, like the Anthropic SDK's."""

    def __init__(self, client: GeminiClient, body: dict[str, Any]) -> None:
        self.client, self.body = client, body
        self._session: aiohttp.ClientSession | None = None
        self._resp: aiohttp.ClientResponse | None = None
        self._text = ""
        self._calls: dict[int, dict[str, Any]] = {}
        self._finish: str | None = None
        self._usage: dict[str, Any] | None = None
        self._consumed = False

    async def __aenter__(self) -> _Stream:
        url = f"{self.client.url}/chat/completions"
        if not self.client.api_key:
            raise GeminiError("GEMINI_API_KEY is not set", url)
        headers = {"Authorization": f"Bearer {self.client.api_key}"}
        self._session = aiohttp.ClientSession(timeout=self.client.timeout)
        for attempt in range(self.client.retries + 1):
            try:
                self._resp = await self._session.post(url, json=self.body, headers=headers)
            except (aiohttp.ClientError, TimeoutError) as e:
                if attempt < self.client.retries:
                    await asyncio.sleep(0.5)
                    continue
                await self._session.close()
                raise GeminiError(f"Gemini unreachable: {type(e).__name__}: {e}", url) from e
            if self._resp.status == 200:
                return self
            detail = _error_detail(await self._resp.text())
            self._resp.release()
            if self._resp.status in RETRY_STATUSES and attempt < self.client.retries:
                log.info("gemini %s, retrying: %s", self._resp.status, detail[:120])
                await asyncio.sleep(0.5)
                continue
            await self._close()
            raise GeminiError(f"Gemini {self._resp.status} for {self.body['model']}: {detail}", url)
        raise AssertionError("unreachable")

    async def __aexit__(self, *exc: Any) -> None:
        await self._close()

    async def _close(self) -> None:
        if self._resp is not None:
            self._resp.release()
        if self._session is not None:
            await self._session.close()

    def __aiter__(self) -> AsyncIterator[Any]:
        return self._events()

    def _chunks_of(self, raw: bytes) -> dict[str, Any] | None:
        """One SSE line (or a whole JSON body) -> a chunk; None for blank lines, comments and [DONE]."""
        line = raw.strip()
        if not line or line.startswith(b":"):
            return None
        if line.startswith(b"data:"):
            line = line[5:].strip()
        if line == b"[DONE]":
            return None
        try:
            chunk = json.loads(line)
        except ValueError as e:
            raise GeminiError(f"Gemini sent a line that isn't JSON: {line[:120]!r}", self.client.url) from e
        if isinstance(chunk, list):   # an error can come as a one-element list
            chunk = chunk[0] if chunk else {}
        if chunk.get("error"):
            err = chunk["error"]
            raise GeminiError(f"Gemini: {err.get('message', err) if isinstance(err, dict) else err}", self.client.url)
        return chunk

    async def _chunks(self) -> AsyncIterator[dict[str, Any]]:
        assert self._resp is not None
        if not self.body.get("stream"):   # one JSON answer: its "message" is the whole "delta"
            whole = self._chunks_of(await self._resp.read()) or {}
            for ch in whole.get("choices") or []:
                ch["delta"] = ch.pop("message", None) or {}
            yield whole
            return
        async for raw in self._resp.content:
            chunk = self._chunks_of(raw)
            if chunk is not None:
                yield chunk

    def _call_index(self, tc: dict[str, Any]) -> int:
        """Which call a tool_call delta belongs to: its `index`, else a new call for a new id, else the last."""
        if isinstance(tc.get("index"), int):
            return tc["index"]
        if tc.get("id") and all(c["id"] != tc["id"] for c in self._calls.values()) or not self._calls:
            return max(self._calls, default=-1) + 1
        return max(self._calls)

    async def _events(self) -> AsyncIterator[Any]:
        self._consumed = True
        text_open = False
        try:
            async for chunk in self._chunks():
                if chunk.get("usage"):
                    self._usage = chunk["usage"]
                for choice in chunk.get("choices") or []:
                    d = choice.get("delta") or {}
                    delta = d.get("content") or ""
                    if delta:
                        if not text_open:
                            text_open = True
                            yield SimpleNamespace(type="content_block_start", content_block=SimpleNamespace(type="text"))
                        self._text += delta
                        yield SimpleNamespace(type="text", text=delta)
                    for tc in d.get("tool_calls") or []:
                        _merge_call(self._calls, self._call_index(tc), tc)
                    if choice.get("finish_reason"):
                        self._finish = choice["finish_reason"]
        except (aiohttp.ClientError, TimeoutError) as e:
            raise GeminiError(f"Gemini stream broke: {type(e).__name__}: {e}", self.client.url) from e
        if text_open:
            yield SimpleNamespace(type="content_block_stop")

    async def get_final_message(self) -> Any:
        if not self._consumed:
            async for _ in self:
                pass
        calls = [self._calls[i] for i in sorted(self._calls)]
        return message_from_openai(self._text.strip(), calls, self._finish, self._usage, self.body["model"])


class _Messages:
    def __init__(self, client: GeminiClient) -> None:
        self.client = client

    def stream(self, **params: Any) -> _Stream:
        return _Stream(self.client, chat_body(params, model=self.client.model, effort=self.client.effort,
                                              stream=self.client.stream))

    async def create(self, **params: Any) -> Any:
        if params.get("max_tokens") == 0:   # the agent's cache warm-up: Gemini caches implicitly, nothing to do
            return message_from_openai("", [], "stop", None, self.client.model)
        async with self.stream(**params) as s:
            return await s.get_final_message()


class GeminiClient:
    """An AsyncAnthropic stand-in backed by Gemini (see the module docstring). It ignores the
    requested model name and always uses its own `model`."""

    is_local = False
    label = "Gemini"   # in the agent's error events

    def __init__(self, model: str | None = None, api_key: str | None = None, url: str | None = None, *,
                 effort: str | None = None, stream: bool | None = None, timeout_s: float = 20.0,
                 retries: int = 1) -> None:
        self.model = model or gemini_model()
        self.api_key = api_key if api_key is not None else os.environ.get("GEMINI_API_KEY", "").strip()
        self.url = (url or gemini_url()).rstrip("/")
        self.effort = effort or gemini_effort()
        self.retries = retries
        # MIGUEL_GEMINI_STREAM=0: one whole answer per call (if streamed tool calls misbehave)
        self.stream = stream if stream is not None else \
            os.environ.get("MIGUEL_GEMINI_STREAM", "1").strip().lower() not in ("0", "false", "no", "off")
        # no total limit (a long answer streams for a while); a silent socket for timeout_s is a failure
        self.timeout = aiohttp.ClientTimeout(total=None, sock_connect=10.0, sock_read=timeout_s)
        self.beta = SimpleNamespace(messages=_Messages(self))
        self.messages = self.beta.messages
