"""Miguel's brain on a local model through Ollama, for when the venue internet is bad (issue #81).

Switch: `MIGUEL_LLM=local` (default `claude`). `MIGUEL_LOCAL_MODEL` (default `qwen3.8:27b`, the
benchmark's pick; fallback `qwen3.6:latest`) and `OLLAMA_URL` (default http://localhost:11434).

`LocalClient` looks like the part of `AsyncAnthropic` the brain uses (`client.beta.messages.create`
and `.stream`), so the agent's tool loop, the vision checks and the fall check run unchanged on
either backend. It turns each Anthropic-format request into one call to Ollama's native
`/api/chat`, and the answer back into an Anthropic-shaped message:

- tools: `{name, description, input_schema}` -> `{"type": "function", "function": {name,
  description, parameters}}`; Ollama's `tool_calls` -> `tool_use` blocks with made-up ids.
- messages: `tool_use` blocks -> the assistant's `tool_calls`; `tool_result` blocks -> `role: tool`
  messages (named by the matching tool_use); text blocks of one user turn are joined; image blocks
  -> the message's `images` (base64 JPEG). Consecutive user turns are merged.
- Anthropic-only parts are dropped: cache_control, betas, fallbacks, effort (top-level and the
  per-message `role: system` message), thinking blocks. A `json_schema` output format becomes
  Ollama's `format`.
- Text streams; Ollama sends a tool call whole, at the end. Thinking is off (`think: false`).
- Errors are `LocalLLMError`, a subclass of `anthropic.APIError`, so the agent's "my brain isn't
  connected" path handles a stopped Ollama too.

Benchmark notes (M5 Pro, qwen3.8:27b): the first one or two prompts after a load take 4 to 10 s; after
two warm-up requests with the real system prompt and tools (different user messages), the runner
keeps a checkpoint at the end of the tools, and a new user turn costs about 0.2 s of prompt time.
Appending to the conversation reuses the cache; cutting its front forces a full re-read (the agent
keeps the history append-only on this backend and trims rarely, in one big chunk).
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import AsyncIterator
from itertools import count
from types import SimpleNamespace
from typing import Any

import aiohttp
import anthropic
import httpx2   # anthropic's HTTP library (its errors carry a request)

log = logging.getLogger(__name__)

DEFAULT_MODEL = "qwen3.8:27b"
DEFAULT_URL = "http://localhost:11434"
NUM_CTX = 16384          # the context Ollama allocates; the agent trims its history near it
KEEP_ALIVE = "30m"       # how long Ollama keeps the model loaded after a call (the agent refreshes it while idle)
MAX_PREDICT = 1024       # a cap on generated tokens (Claude's max_tokens includes thinking; ours is off)
TEMPERATURE = 0.2


def backend() -> str:
    """'local', 'gemini' or 'claude' (env MIGUEL_LLM; anything else means Claude)."""
    name = os.environ.get("MIGUEL_LLM", "").strip().lower()
    return name if name in ("local", "gemini") else "claude"


def local_model() -> str:
    return os.environ.get("MIGUEL_LOCAL_MODEL", "").strip() or DEFAULT_MODEL


def ollama_url() -> str:
    return (os.environ.get("OLLAMA_URL", "").strip() or DEFAULT_URL).rstrip("/")


class LocalLLMError(anthropic.APIError):
    """Ollama failed: not running, the model is missing, a bad request or a broken stream."""

    def __init__(self, message: str, url: str = DEFAULT_URL) -> None:
        super().__init__(message, httpx2.Request("POST", url), body=None)


# --- Anthropic -> Ollama ------------------------------------------------------------------------


def _get(block: Any, key: str, default: Any = None) -> Any:
    return block.get(key, default) if isinstance(block, dict) else getattr(block, key, default)


def tools_to_ollama(tools: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Anthropic tool definitions -> Ollama function tools (`strict` and cache_control dropped)."""
    return [{"type": "function", "function": {"name": t["name"], "description": t.get("description", ""),
                                              "parameters": t.get("input_schema") or {"type": "object", "properties": {}}}}
            for t in tools or []]


def system_text(system: Any) -> str:
    """The system prompt as text: a string, or a list of text blocks (with cache_control)."""
    if not system:
        return ""
    if isinstance(system, str):
        return system
    return "\n\n".join(_get(b, "text", "") for b in system if _get(b, "type") == "text")


def _result_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    return "\n".join(_get(b, "text", "") for b in content or [] if _get(b, "type") == "text")


def _image_data(block: Any) -> str | None:
    src = _get(block, "source") or {}
    return _get(src, "data") if _get(src, "type") == "base64" else None


def messages_to_ollama(system: Any, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """An Anthropic `system` + `messages` -> Ollama chat messages. Deterministic, so the same
    history always gives the same prefix (Ollama's prompt cache depends on it)."""
    out: list[dict[str, Any]] = []
    sys_text = system_text(system)
    if sys_text:
        out.append({"role": "system", "content": sys_text})
    names: dict[str, str] = {}   # tool_use id -> tool name, for the tool messages
    for m in messages:
        role, content = m["role"], m.get("content")
        if role == "system":     # the per-message effort note (Anthropic only)
            continue
        blocks = [{"type": "text", "text": content}] if isinstance(content, str) else list(content or [])
        if role == "assistant":
            text = "".join(_get(b, "text", "") for b in blocks if _get(b, "type") == "text")
            calls = []
            for b in blocks:
                if _get(b, "type") == "tool_use":
                    names[_get(b, "id")] = _get(b, "name")
                    calls.append({"function": {"name": _get(b, "name"), "arguments": dict(_get(b, "input") or {})}})
            if not text and not calls:   # a turn that was only thinking
                continue
            msg: dict[str, Any] = {"role": "assistant", "content": text}
            if calls:
                msg["tool_calls"] = calls
            out.append(msg)
            continue
        texts: list[str] = []
        images: list[str] = []
        for b in blocks:
            kind = _get(b, "type")
            if kind == "tool_result":
                body = _result_text(_get(b, "content"))
                if _get(b, "is_error"):
                    body = f"Error: {body}"
                out.append({"role": "tool", "tool_name": names.get(_get(b, "tool_use_id"), "tool"), "content": body})
            elif kind == "text" and _get(b, "text"):
                texts.append(_get(b, "text"))
            elif kind == "image" and _image_data(b):
                images.append(_image_data(b))
        if not texts and not images:
            continue
        if out and out[-1]["role"] == "user":   # two user turns in a row (a stop note, then a request)
            prev = out[-1]
            prev["content"] = "\n\n".join(p for p in (prev["content"], *texts) if p)
            if images:
                prev["images"] = [*prev.get("images", []), *images]
            continue
        msg = {"role": "user", "content": "\n\n".join(texts)}
        if images:
            msg["images"] = images
        out.append(msg)
    return out


def chat_body(params: dict[str, Any], *, model: str, stream: bool = True) -> dict[str, Any]:
    """The /api/chat request for an Anthropic-style `messages.create` call."""
    max_tokens = int(params.get("max_tokens") or MAX_PREDICT)
    body: dict[str, Any] = {
        "model": model,
        "messages": messages_to_ollama(params.get("system"), params.get("messages") or []),
        "stream": stream,
        "think": False,
        "keep_alive": KEEP_ALIVE,
        "options": {"num_ctx": NUM_CTX, "temperature": TEMPERATURE, "num_predict": max(1, min(max_tokens, MAX_PREDICT))},
    }
    tools = tools_to_ollama(params.get("tools"))
    if tools:
        body["tools"] = tools
    fmt = (params.get("output_config") or {}).get("format") or {}
    if fmt.get("type") == "json_schema" and fmt.get("schema"):
        body["format"] = fmt["schema"]
    return body


# --- Ollama -> Anthropic ------------------------------------------------------------------------

_ids = count(1)


def message_from_ollama(text: str, calls: list[dict[str, Any]], final: dict[str, Any], model: str) -> Any:
    """What Ollama sent -> an Anthropic-shaped message (content blocks, stop_reason, usage)."""
    content: list[Any] = []
    if text:
        content.append(SimpleNamespace(type="text", text=text))
    for c in calls:
        fn = c.get("function") or {}
        args = fn.get("arguments")
        if isinstance(args, str):   # some models send the arguments as a JSON string
            try:
                args = json.loads(args)
            except ValueError:
                args = {}
        content.append(SimpleNamespace(type="tool_use", id=c.get("id") or f"toolu_local_{next(_ids)}",
                                       name=fn.get("name", ""), input=args if isinstance(args, dict) else {}))
    if final.get("done_reason") == "length":
        stop = "max_tokens"
    elif calls:
        stop = "tool_use"
    else:
        stop = "end_turn"
    ns = 1e6
    usage = SimpleNamespace(
        input_tokens=final.get("prompt_eval_count") or 0, output_tokens=final.get("eval_count") or 0,
        cache_read_input_tokens=0, cache_creation_input_tokens=0,
        prompt_ms=(final.get("prompt_eval_duration") or 0) / ns, eval_ms=(final.get("eval_duration") or 0) / ns,
        load_ms=(final.get("load_duration") or 0) / ns, local=True)
    return SimpleNamespace(content=content, stop_reason=stop, stop_details=None, model=model, usage=usage)


# --- the client ---------------------------------------------------------------------------------


class _Stream:
    """`async with client.beta.messages.stream(**kw) as s: async for ev in s: ...; await s.get_final_message()`.
    Events: content_block_start (text), text deltas, content_block_stop, like the Anthropic SDK's."""

    def __init__(self, client: LocalClient, body: dict[str, Any]) -> None:
        self.client, self.body = client, body
        self._session: aiohttp.ClientSession | None = None
        self._resp: aiohttp.ClientResponse | None = None
        self._text = ""
        self._calls: list[dict[str, Any]] = []
        self._final: dict[str, Any] = {}
        self._consumed = False

    async def __aenter__(self) -> _Stream:
        url = f"{self.client.url}/api/chat"
        self._session = aiohttp.ClientSession(timeout=self.client.timeout)
        try:
            self._resp = await self._session.post(url, json=self.body)
        except (aiohttp.ClientError, TimeoutError) as e:
            await self._session.close()
            raise LocalLLMError(f"Ollama unreachable at {self.client.url}: {type(e).__name__}: {e}", url) from e
        if self._resp.status != 200:
            detail = (await self._resp.text())[:300]
            await self._close()
            raise LocalLLMError(f"Ollama {self._resp.status} for {self.body['model']}: {detail}", url)
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self._close()

    async def _close(self) -> None:
        if self._resp is not None:
            self._resp.release()
        if self._session is not None:
            await self._session.close()

    def __aiter__(self) -> AsyncIterator[Any]:
        return self._events()

    async def _events(self) -> AsyncIterator[Any]:
        assert self._resp is not None
        self._consumed = True
        text_open = False
        try:
            async for raw in self._resp.content:
                line = raw.strip()
                if not line:
                    continue
                try:
                    chunk = json.loads(line)
                except ValueError as e:
                    raise LocalLLMError(f"Ollama sent a line that isn't JSON: {line[:120]!r}", self.client.url) from e
                if chunk.get("error"):
                    raise LocalLLMError(f"Ollama: {chunk['error']}", self.client.url)
                m = chunk.get("message") or {}
                delta = m.get("content") or ""
                if delta:
                    if not text_open:
                        text_open = True
                        yield SimpleNamespace(type="content_block_start", content_block=SimpleNamespace(type="text"))
                    self._text += delta
                    yield SimpleNamespace(type="text", text=delta)
                self._calls.extend(m.get("tool_calls") or [])
                if chunk.get("done"):
                    self._final = chunk
        except (aiohttp.ClientError, TimeoutError) as e:
            raise LocalLLMError(f"Ollama stream broke: {type(e).__name__}: {e}", self.client.url) from e
        if text_open:
            yield SimpleNamespace(type="content_block_stop")

    async def get_final_message(self) -> Any:
        if not self._consumed:
            async for _ in self:
                pass
        return message_from_ollama(self._text.strip(), self._calls, self._final, self.body["model"])


class _Messages:
    def __init__(self, client: LocalClient) -> None:
        self.client = client

    def stream(self, **params: Any) -> _Stream:
        return _Stream(self.client, chat_body(params, model=self.client.model))

    async def create(self, **params: Any) -> Any:
        async with self.stream(**params) as s:
            return await s.get_final_message()


class LocalClient:
    """An AsyncAnthropic stand-in backed by Ollama (see the module docstring). It ignores the
    requested model name and always uses its own `model`."""

    is_local = True

    def __init__(self, model: str | None = None, url: str | None = None, *, timeout_s: float = 120.0) -> None:
        self.model = model or local_model()
        self.url = (url or ollama_url()).rstrip("/")
        # no total limit (a long answer streams for a while); a silent socket for timeout_s is a failure
        self.timeout = aiohttp.ClientTimeout(total=None, sock_connect=5.0, sock_read=timeout_s)
        self.beta = SimpleNamespace(messages=_Messages(self))
        self.messages = self.beta.messages
        self.warmed = False

    async def warm_up(self, system: Any, tools: list[dict[str, Any]], users: list[str]) -> list[float]:
        """Load the model and teach its prompt cache the system prompt + tools: one 1-token request
        per user message (give two different ones: the runner keeps a checkpoint at the branch
        point once it has seen two). Returns each request's seconds."""
        times = []
        for text in users:
            t0 = time.monotonic()
            await self.messages.create(system=system, tools=tools, max_tokens=1,
                                       messages=[{"role": "user", "content": [{"type": "text", "text": text}]}])
            times.append(time.monotonic() - t0)
        self.warmed = True
        return times

    async def keep_loaded(self) -> None:
        """Reset Ollama's unload timer without running the model (an empty /api/generate)."""
        url = f"{self.url}/api/generate"
        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as s, \
                    s.post(url, json={"model": self.model, "keep_alive": KEEP_ALIVE}) as r:
                if r.status != 200:
                    raise LocalLLMError(f"Ollama {r.status}: {(await r.text())[:200]}", url)
                await r.read()
        except (aiohttp.ClientError, TimeoutError) as e:
            raise LocalLLMError(f"Ollama unreachable at {self.url}: {type(e).__name__}: {e}", url) from e


def is_local(client: Any) -> bool:
    return bool(getattr(client, "is_local", False))
