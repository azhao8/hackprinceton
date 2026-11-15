"""Miguel's agent (owner: Grant): Claude turns what people say into tool calls (issue #54).

    tools = ToolBox(runner, skill_factories, snapshot=latest_jpeg)
    agent = Agent(tools, events_cb=print)
    asyncio.create_task(agent.run())            # consumes agent.inbox forever
    await agent.inbox.put(Utterance("guardian", "Bring Mom her pills", meta={"channel": "app"}))

How it works (docs/03-software.md, "How an instruction becomes motion"):
- One shared conversation for everyone. Each user message starts with who spoke
  ("[senior via mic]", "[guardian via app]") and ends with a short world-memory summary.
- A request runs as one task: a tool-use loop where Claude plans (`set_plan`), acts through
  tools (skills via the SkillRunner, `say`, `reply_to_guardian`...) and stops when it has no
  more tool calls. The agent emits `plan`, `step`, `say`, `reply` and `task` events.
- One task at a time (one body). Messages that arrive while a task runs are handed to that
  task's loop (Claude decides: answer, queue, replace or ask); a physical tool that is waiting
  on its skill returns early so Claude sees the new message quickly.
- "stop" (and "wait", "halt"...) is checked first, without the LLM: it cancels the skill and
  the task immediately.
- The LLM never sends speeds: tools start skills, skills drive through the arbiter.

Conversation memory keeps the last `history_exchanges` tasks. Thinking blocks are dropped from
a task once it finishes (they are only needed inside its own tool loop), so trimming old tasks
off the front never edits the prefix a live thinking block was produced with.

Voice latency (Sat Nov 14):
- Responses are streamed. Plain text for the senior is spoken sentence by sentence as Claude
  writes it (a `say` event per sentence), so the first sentence plays while the rest is written.
- Prompt caching: the tools and system prompt are one cached block (a breakpoint on the system
  prompt), the conversation so far a second (a breakpoint on the last block of the history), and
  automatic caching covers the growing tail. Effort changes go in a per-message system message,
  and the history is trimmed in chunks, so the cached prefix stays byte-identical between tasks.
  Every call logs its token usage (cache reads included).
- `stay_silent`: when a mic message was not meant for Miguel, the task ends with nothing said
  and is left out of the history.
- The first `say` of a task carries `data.timing` (monotonic stage times: speech end, transcript,
  Claude's first text, the say) for the server's per-turn timing log.
"""

from __future__ import annotations

import asyncio
import copy
import itertools
import logging
import re
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import anthropic

from app.brain.prompt import (
    EFFORT_BETA,
    EFFORT_CHAT,
    EFFORT_PER_MESSAGE,
    EFFORT_TASK,
    FALL_CHANNEL,
    KEEPALIVE_S,
    MODEL,
    SYSTEM_PROMPT,
    create_message,
    effort_for,
    ACK_GUARDIAN,
    ACK_SPOKEN,
    get_client,
    stream_message,
)
from app.brain.tools import ToolBox
from app.brain.types import AgentEvent, EventKind, Source, Utterance

log = logging.getLogger(__name__)

DEFAULT_CHANNEL = {"senior": "mic", "guardian": "app", "operator": "control page"}

_STOP_WORDS = {"stop", "halt", "freeze", "wait", "whoa", "woah"}
_FILLER = {"miguel", "please", "ok", "okay", "hey", "oh", "no", "now", "robot"}


def stop_requested(text: str) -> bool:
    """True when an utterance means "stop now": a stop word leading the sentence (after filler
    like "Miguel," or "no,"), "hold on", or a stop word anywhere in a short (<= 4 word) phrase."""
    words = re.findall(r"[a-z']+", text.lower())
    core = [w for w in words if w not in _FILLER]
    if not core:
        return False
    if core[0] in _STOP_WORDS or core[:2] == ["hold", "on"]:
        return True
    return len(words) <= 4 and any(w in _STOP_WORDS for w in core)


# How a mic message without Miguel's name got through (app/speech/mic.py meta "via")
_VIA_NOTES = {"question": "right after your question", "reply": "answering you", "tap": "tapped your face"}


def _label(u: Utterance, working: bool = False) -> str:
    channel = u.meta.get("channel") or DEFAULT_CHANNEL.get(u.source, "?")
    notes = [n for n in (_VIA_NOTES.get(u.meta.get("via")), "while you were working" if working else None) if n]
    return f"[{u.source} via {channel}{''.join(', ' + n for n in notes)}] {u.text}"


_ABBREVIATIONS = {"mr", "mrs", "ms", "dr", "st", "vs", "etc", "jr", "sr", "e.g", "i.e", "approx"}
# A sentence ends at . ! ? (and closing quotes) followed by a space, or at the end of what has
# arrived so far: text comes in bursts, and waiting for the next burst to see the space can cost
# a few hundred ms on the first sentence.
_SENTENCE_END = re.compile(r"[.!?]+[\"'”’)\]]*(?=\s|$)")


class _Sentences:
    """Cuts streamed text into spoken lines: each finished sentence goes to `emit` at once."""

    def __init__(self, emit: Callable[[str], None], max_chars: int = 240) -> None:
        self.emit = emit
        self.max_chars = max_chars
        self.buf = ""
        self.used = False      # any text arrived

    def feed(self, delta: str) -> None:
        self.used = True
        self.buf += delta
        while True:
            cut = self._cut()
            if cut is None:
                return
            line, self.buf = self.buf[:cut].strip(), self.buf[cut:]
            if re.search(r"\w", line):   # not a stray "." (the end of an ellipsis split across bursts)
                self.emit(line)

    def flush(self) -> None:
        line, self.buf = self.buf.strip(), ""
        if re.search(r"\w", line):
            self.emit(line)

    def _cut(self) -> int | None:
        for m in _SENTENCE_END.finditer(self.buf):
            before = self.buf[: m.start()].split()
            if m.group().startswith(".") and before and before[-1].lower().strip("(\"'") in _ABBREVIATIONS:
                continue           # "Dr. Lee": not the end of a sentence
            if m.end() == len(self.buf) and m.group() == "." and m.start() > 0 and self.buf[m.start() - 1].isdigit():
                continue           # "3." may be "3.5" once the next burst arrives
            return m.end()
        nl = self.buf.find("\n")
        if nl > 0 and self.buf[:nl].strip():
            return nl + 1
        if len(self.buf) > self.max_chars:   # no sentence end in sight: break at a comma or a space
            head = self.buf[: self.max_chars]
            at = max(head.rfind(", "), head.rfind(" "))
            return (at + 1) if at > 0 else self.max_chars
        return None


def _btype(block: Any) -> str | None:
    return block.get("type") if isinstance(block, dict) else getattr(block, "type", None)


def _text_of(content: list[Any]) -> str:
    parts = []
    for b in content:
        if _btype(b) == "text":
            parts.append(b["text"] if isinstance(b, dict) else b.text)
    return "\n".join(p for p in parts if p).strip()


def _strip_thinking(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for m in messages:
        content = m["content"]
        if m["role"] == "assistant" and isinstance(content, list):
            content = [b for b in content if _btype(b) not in ("thinking", "redacted_thinking")]
            if not content:   # a turn that was only thinking: drop it (user turns may run together)
                continue
        out.append({**m, "content": content})   # keeps a system message's output_config
    return out


_CACHEABLE = ("text", "tool_use", "tool_result", "image", "document")
CACHE = {"type": "ephemeral"}


def _as_dict(block: Any) -> dict[str, Any]:
    if isinstance(block, dict):
        return copy.deepcopy(block)
    dump = getattr(block, "model_dump", None)
    if callable(dump):   # exactly as the SDK sends a response block back (anthropic/_utils/_json.py)
        return dump(mode="json", exclude_unset=True, by_alias=True, exclude=getattr(block, "__api_exclude__", None))
    return dict(vars(block))


def _with_breakpoint(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The history with a cache breakpoint on its last cacheable block (copies only that message),
    so the conversation so far is read from the cache by every call of the next task too."""
    for i in range(len(history) - 1, -1, -1):
        content = history[i]["content"]
        if not isinstance(content, list):
            continue
        for j in range(len(content) - 1, -1, -1):
            if _btype(content[j]) in _CACHEABLE:
                block = {**_as_dict(content[j]), "cache_control": CACHE}
                msg = {**history[i], "content": [*content[:j], block, *content[j + 1:]]}
                return [*history[:i], msg, *history[i + 1:]]
    return history


@dataclass
class _TaskState:
    id: str
    request: str
    requester: Source
    started: bool = False
    said: bool = False
    replied: bool = False
    plan: list[str] = field(default_factory=list)
    steps: dict[int, str] = field(default_factory=dict)   # index -> "running" | "done" | "failed"
    marks: dict[str, float] = field(default_factory=dict) # timing: speech_end, final, llm_start, first_text
    timed: bool = False                                   # the first say already carried the timing


class Agent:
    def __init__(
        self,
        tools: ToolBox,
        events_cb: Callable[[AgentEvent], None] | None = None,
        client: Any = None,
        model: str = MODEL,
        *,
        fallbacks: bool | None = None,
        history_exchanges: int = 20,
        history_trim: int = 6,
        max_rounds: int = 16,
        max_tokens: int = 8000,
        max_events: int = 300,
        ack: bool = True,
        per_message_effort: bool | None = None,
        keepalive_s: float | None = None,
    ):
        """
        tools: the ToolBox (the agent binds itself as its host).
        events_cb: called with every AgentEvent (sync; keep it quick).
        client: an AsyncAnthropic (default: the shared one, created on first call).
        fallbacks: server-side refusal fallbacks (None = env MIGUEL_LLM_FALLBACKS, default on).
        history_exchanges: how many past tasks the conversation keeps at most.
        history_trim: past the limit, drop this many more at once, so the cached prefix changes
            once every few tasks instead of on every task.
        max_rounds: LLM calls per task before giving up.
        per_message_effort: say each task's effort in a system message (keeps the cache);
            None = env MIGUEL_EFFORT_PER_MESSAGE (default on). Off: top-level effort per task.
        keepalive_s: while `run()` runs, warm the prompt cache at start and refresh it after this
            many idle seconds (the cache lives 5 minutes); None = env MIGUEL_LLM_KEEPALIVE_S
            (default 240), 0 = off.
        """
        self.tools = tools
        self.events_cb = events_cb
        self.ack = ack   # say "On it!" / reply "Got it" at once for task-like requests
        self.model = model
        self.fallbacks = fallbacks
        self.per_message_effort = EFFORT_PER_MESSAGE if per_message_effort is None else per_message_effort
        self.history_exchanges = history_exchanges
        self.history_trim = max(0, min(history_trim, history_exchanges - 1))
        self.last_usage: dict[str, Any] = {}   # the last call's token usage (for the log and tests)
        self.keepalive_s = KEEPALIVE_S if keepalive_s is None else max(0.0, keepalive_s)
        self._last_call = float("-inf")
        self._warm_task: asyncio.Task[None] | None = None
        self.max_rounds = max_rounds
        self.max_tokens = max_tokens
        self.inbox: asyncio.Queue[Utterance] = asyncio.Queue()
        self._client = client
        self._events: deque[AgentEvent] = deque(maxlen=max_events)
        self._event_ids = itertools.count(1)
        self._subs: list[asyncio.Queue[AgentEvent]] = []
        self._history: list[list[dict[str, Any]]] = []   # finished tasks, thinking stripped
        self._task: asyncio.Task[None] | None = None
        self._task_ids = itertools.count(1)
        self._state: _TaskState | None = None
        self._pending: list[Utterance] = []               # arrived while a task runs
        self._interject = asyncio.Event()
        self._reply_waiter: asyncio.Future[Utterance | None] | None = None
        self._stop_note: str | None = None
        tools.bind(self)

    # --- public API -----------------------------------------------------------------------------

    @property
    def client(self) -> Any:
        if self._client is None:
            self._client = get_client()
        return self._client

    @property
    def events(self) -> list[AgentEvent]:
        """Recent events, oldest first."""
        return list(self._events)

    def events_after(self, after_id: int) -> list[AgentEvent]:
        return [e for e in self._events if e.id > after_id]

    def subscribe(self, maxsize: int = 500) -> asyncio.Queue[AgentEvent]:
        """A queue that receives every new event (drop it with unsubscribe)."""
        q: asyncio.Queue[AgentEvent] = asyncio.Queue(maxsize=maxsize)
        self._subs.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[AgentEvent]) -> None:
        if q in self._subs:
            self._subs.remove(q)

    @property
    def busy(self) -> bool:
        return self._task is not None and not self._task.done()

    @property
    def working(self) -> bool:
        """A task is running, or messages are waiting for one (in the inbox, or queued for the next
        task). False means every request so far has been handled (app/family.py uses it)."""
        return self.busy or bool(self._pending) or not self.inbox.empty()

    async def run(self) -> None:
        """Consume the inbox forever (and keep the prompt cache warm, see keepalive_s)."""
        if self.keepalive_s > 0 and self._warm_task is None:
            self._warm_task = asyncio.create_task(self._keep_warm(), name="agent-cache-warm")
        while True:
            u = await self.inbox.get()
            try:
                await self.handle(u)
            except Exception:  # noqa: BLE001 - one bad message must not kill the brain
                log.exception("agent: handling %r failed", u)
                self.emit("error", "the agent hit a bug handling that message")

    async def handle(self, u: Utterance) -> None:
        """Route one utterance. Returns quickly: tasks run in the background (see `idle()`)."""
        self.emit("heard", u.text, data={"source": u.source, **u.meta})
        if stop_requested(u.text):
            self.stop(f"{u.source} said {u.text!r}")
            if len(u.text.split()) <= 4:
                return
            # "Stop, bring me water instead": stopped already; let Claude handle the rest.
            self._start([u])
            return
        if u.source == "senior" and self._reply_waiter is not None and not self._reply_waiter.done():
            self._reply_waiter.set_result(u)
            return
        if self.busy:
            self._pending.append(u)
            self._interject.set()
            return
        self._start([u])

    def stop(self, reason: str = "stop") -> None:
        """Stop now, without the LLM: cancel the skill (the arbiter request clears at once) and
        the running task. Sync, so the stop gesture can call it too."""
        moving = self.tools.running is not None
        self.tools.cancel_physical()
        if self._reply_waiter is not None and not self._reply_waiter.done():
            self._reply_waiter.set_result(None)
        self._pending.clear()
        self._interject.clear()
        note = f"[stop] {reason}. Miguel stopped right away and cancelled what it was doing."
        had_task = self.busy
        if had_task:
            self._stop_note = note
            assert self._task is not None
            self._task.cancel()
        else:
            self._history.append([{"role": "user", "content": [{"type": "text", "text": note}]}])
        if moving or had_task:
            self.emit("say", "Okay, stopping.", to="senior")

    async def idle(self) -> None:
        """Wait until no task is running (including tasks started for queued messages)."""
        while self._task is not None and not self._task.done():
            await asyncio.wait({self._task})

    # --- ToolHost -------------------------------------------------------------------------------

    def emit(self, kind: EventKind, text: str = "", *, to: Source | None = None,
             data: dict[str, Any] | None = None) -> AgentEvent:
        data = dict(data or {})
        st = self._state
        if kind == "say" and st is not None and not st.timed and not data.get("ack"):
            st.timed = True   # the task's first real line: carries the stage times for the timing log
            data["timing"] = {**st.marks, "say": time.monotonic()}
        ev = AgentEvent(next(self._event_ids), kind, text, to, data)
        self._events.append(ev)
        if self.events_cb is not None:
            try:
                self.events_cb(ev)
            except Exception:  # noqa: BLE001
                log.exception("agent: events_cb failed")
        for q in self._subs:
            try:
                q.put_nowait(ev)
            except asyncio.QueueFull:
                log.warning("agent: an event subscriber is full; dropping event %d", ev.id)
        return ev

    async def wait_for_senior(self, seconds: float) -> Utterance | None:
        for i, u in enumerate(self._pending):   # they may have answered before we started waiting
            if u.source == "senior":
                del self._pending[i]
                if not self._pending:
                    self._interject.clear()
                return u
        fut: asyncio.Future[Utterance | None] = asyncio.get_running_loop().create_future()
        self._reply_waiter = fut
        # the mic listens without the wake word while we wait (app/speech/mic.py, via the API)
        self.emit("listen", f"waiting up to {seconds:g} s for the senior's answer",
                  data={"on": True, "seconds": seconds})
        try:
            return await asyncio.wait_for(fut, seconds)
        except TimeoutError:
            return None
        finally:
            if self._reply_waiter is fut:
                self._reply_waiter = None
            self.emit("listen", "stopped waiting for an answer", data={"on": False})

    async def wait_interjection(self) -> None:
        await self._interject.wait()

    # --- the task loop --------------------------------------------------------------------------

    def _start(self, utterances: list[Utterance]) -> None:
        prev = self._task if self.busy else None   # e.g. still unwinding from a stop
        self._task = asyncio.create_task(self._run_task(utterances, prev), name="agent-task")

    async def _run_task(self, utterances: list[Utterance], after: asyncio.Task[None] | None = None) -> None:
        if after is not None:
            await asyncio.wait({after})   # let it finish and write its history first
        last = utterances[-1]
        st = _TaskState(f"task-{next(self._task_ids)}", " / ".join(u.text for u in utterances), last.source)
        st.marks = {"heard": last.t, **{k: last.meta[k] for k in ("t_speech_end", "t_final")
                                        if isinstance(last.meta.get(k), (int, float))}}
        self._state = st
        efforts = {effort_for(u.text, u.source) for u in utterances}
        effort = EFFORT_TASK if EFFORT_TASK in efforts else EFFORT_CHAT
        content: list[dict[str, Any]] = [{"type": "text", "text": _label(u)} for u in utterances]
        content.append({"type": "text", "text": f"World memory: {self.tools.memory_summary()}"})
        ex: list[dict[str, Any]] = [{"role": "user", "content": content}]
        if self.per_message_effort:   # this task's effort, without touching the cached prefix
            ex.append({"role": "system", "content": [], "output_config": {"effort": effort}})
        # acknowledge at once; the plan follows when Claude answers. Not for mic speech without his
        # name (an answer window, no wake word set): it may not be meant for Miguel at all.
        # Nor for a fall alert (#71): a cheerful "On it!" is wrong there; the prompt has Miguel speak calmly.
        if self.ack and effort == EFFORT_TASK and last.meta.get("addressed", True) is not False \
                and last.meta.get("channel") != FALL_CHANNEL:
            if last.source == "guardian":
                self.emit("reply", ACK_GUARDIAN, to="guardian", data={"ack": True})
            else:
                self.emit("say", ACK_SPOKEN, to="senior", data={"ack": True})
        status, summary, keep = "done", "", True
        try:
            for rounds in range(self.max_rounds):
                speech = _Sentences(lambda line: self._speak_streamed(st, line))
                resp = await self._call(ex, effort, st, speech)
                stop_reason = resp.stop_reason
                if stop_reason == "refusal":
                    details = getattr(resp, "stop_details", None)
                    category = getattr(details, "category", None)
                    self.emit("error", f"Claude declined this request ({category or 'no category'})",
                              data={"category": category})
                    self._tell(st, "Sorry, I can't help with that one.")
                    status, summary, keep = "failed", "declined", False
                    break
                ex.append({"role": "assistant", "content": list(resp.content)})
                uses = [b for b in resp.content if _btype(b) == "tool_use"]
                if stop_reason == "max_tokens":
                    if uses:   # a cut-off turn: never run its tools
                        ex.append({"role": "user", "content": [
                            {"type": "tool_result", "tool_use_id": b.id, "is_error": True,
                             "content": "Not run: your response was cut off."} for b in uses]})
                    self.emit("error", "the agent's answer was cut off (max_tokens)")
                    status, summary = "failed", "answer cut off"
                    break
                if stop_reason == "pause_turn":
                    continue
                if not uses:
                    summary = _text_of(resp.content)
                    if not speech.used or st.requester == "guardian":   # streamed text was spoken already
                        self._final_text(st, summary)
                    break
                if rounds == 0 and [b.name for b in uses] == ["stay_silent"]:
                    # not meant for Miguel: nothing said, no follow-up call, and not kept in the history
                    reason = str((uses[0].input or {}).get("reason", "")).strip()
                    log.info("agent: stayed silent on %r (%s)", st.request[:80], reason or "no reason")
                    status, summary, keep = "done", "stayed silent", False
                    break
                results = [await self._exec(st, b) for b in uses]
                ex.append({"role": "user", "content": results + self._drain_pending(st)})
            else:
                status, summary = "failed", f"gave up after {self.max_rounds} steps"
                self.emit("error", f"task {st.id}: {summary}")
        except asyncio.CancelledError:
            status, summary = "cancelled", "stopped"
            self._close_dangling(ex, "Cancelled: Miguel was told to stop.")
            raise
        except anthropic.APIError as e:
            status, summary = "failed", f"LLM call failed: {type(e).__name__}"
            log.warning("agent: %s", e)
            self.emit("error", f"Claude API error: {type(e).__name__}: {getattr(e, 'message', e)}")
            self._tell(st, "Sorry, my brain isn't connected right now.")
            self._close_dangling(ex, "Not run: the API call failed.")
        except Exception as e:  # noqa: BLE001
            status, summary = "failed", f"agent bug: {type(e).__name__}"
            log.exception("agent: task crashed")
            self.emit("error", f"the agent crashed: {type(e).__name__}: {e}")
            self._close_dangling(ex, "Not run: the agent crashed.")
        finally:
            self._finish(st, ex, status, summary, keep)
        if self._pending:   # arrived after Claude's last look: run them as the next task
            pending, self._pending = self._pending, []
            self._interject.clear()
            self._start(pending)

    def _speak_streamed(self, st: _TaskState, line: str) -> None:
        """A finished sentence of Claude's plain text: say it now (the senior or operator asked).
        Not when Claude already used say() in this task: then its text is only a log note."""
        if st.requester != "guardian" and not st.said:
            self.emit("say", line, to="senior", data={"streamed": True})

    def _params(self, effort: str) -> dict[str, Any]:
        """What every call shares, byte for byte: model, tools, system prompt (cached), effort."""
        params: dict[str, Any] = {
            "model": self.model,
            # the tools and the system prompt: one cached block, the same on every call
            "system": [{"type": "text", "text": SYSTEM_PROMPT, "cache_control": CACHE}],
            "tools": self.tools.definitions(),
        }
        if self.per_message_effort:
            params["betas"] = [EFFORT_BETA]
            # pinned: a top-level effort change would invalidate the cached conversation
            params["output_config"] = {"effort": EFFORT_CHAT}
        else:
            params["output_config"] = {"effort": effort}
        return params

    async def prewarm(self) -> bool:
        """Write or refresh the cached prefix (tools, system prompt, the conversation so far) with a
        max_tokens=0 request: nothing is generated, it bills a cache write or read. True if it ran."""
        if self.busy:
            return False
        history = [m for exchange in self._history for m in exchange]
        self._last_call = time.monotonic()
        try:
            resp = await create_message(
                self.client,
                fallbacks=self.fallbacks,   # the same betas as the real calls
                **self._params(EFFORT_CHAT),
                max_tokens=0,
                # the breakpoint on the last block the next real request shares; the placeholder is never answered
                messages=_with_breakpoint(history) + [{"role": "user", "content": [{"type": "text", "text": "."}]}],
            )
        except Exception as e:  # noqa: BLE001 - warming is an optimization; never break the brain for it
            log.info("llm cache warm-up failed: %s: %s", type(e).__name__, getattr(e, "message", e))
            return False
        self._log_usage(resp, self._last_call, None, "cache warm-up")
        return True

    async def _keep_warm(self) -> None:
        await self.prewarm()
        while True:
            await asyncio.sleep(min(5.0, self.keepalive_s))
            if not self.busy and time.monotonic() - self._last_call >= self.keepalive_s:
                await self.prewarm()

    async def _call(self, ex: list[dict[str, Any]], effort: str, st: _TaskState | None = None,
                    speech: _Sentences | None = None) -> Any:
        history = [m for exchange in self._history for m in exchange]

        def on_event(kind: str, value: Any) -> None:
            if kind == "text" and value:
                if st is not None and "first_text" not in st.marks:
                    st.marks["first_text"] = time.monotonic()
                if speech is not None:
                    speech.feed(value)
            elif kind == "block_stop" and speech is not None:
                speech.flush()           # the end of a text block ends its last sentence

        t0 = self._last_call = time.monotonic()
        if st is not None:
            st.marks.setdefault("llm_start", t0)
        resp = await stream_message(
            self.client,
            fallbacks=self.fallbacks,
            on_event=on_event,
            max_tokens=self.max_tokens,
            # the conversation so far: a second cached block, shared by every call of this task and the next
            messages=_with_breakpoint(history) + ex,
            cache_control=CACHE,   # automatic caching for the growing tail of this task
            **self._params(effort),
        )
        if speech is not None:
            speech.flush()
        self._last_call = time.monotonic()
        self._log_usage(resp, t0, st)
        return resp

    def _log_usage(self, resp: Any, t0: float, st: _TaskState | None, what: str = "llm") -> None:
        usage = getattr(resp, "usage", None)
        if usage is None:
            return
        u = {k: getattr(usage, k, None) or 0 for k in
             ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens", "output_tokens")}
        self.last_usage = u
        first = st.marks.get("first_text") if st is not None else None
        log.info("%s: %d ms%s; tokens: %d new + %d cache read + %d cache write in, %d out; stop %s",
                 what, 1000 * (time.monotonic() - t0),
                 f" (first text at {1000 * (first - t0):.0f} ms)" if first is not None and first >= t0 else "",
                 u["input_tokens"], u["cache_read_input_tokens"], u["cache_creation_input_tokens"],
                 u["output_tokens"], getattr(resp, "stop_reason", "?"))

    async def _exec(self, st: _TaskState, block: Any) -> dict[str, Any]:
        name = block.name
        args = dict(block.input or {})
        step = args.pop("step", None)
        if name == "set_plan" or self.tools.is_physical(name):
            self._task_started(st)
        if isinstance(step, int) and 0 <= step < len(st.plan):
            self._step_running(st, step, name)
        else:
            step = None
        out = await self.tools.call(name, args)
        if name == "set_plan" and out.ok:
            st.plan, st.steps = list(out.data.get("steps", [])), {}
        elif name == "say" and out.ok:
            st.said = True
        elif name == "reply_to_guardian" and out.ok:
            st.replied = True
        if step is not None and not out.ok:
            self._set_step(st, step, "failed", out.text)
        result: dict[str, Any] = {"type": "tool_result", "tool_use_id": block.id, "content": out.text}
        if not out.ok:
            result["is_error"] = True
        return result

    def _drain_pending(self, st: _TaskState) -> list[dict[str, Any]]:
        pending, self._pending = self._pending, []
        self._interject.clear()
        if pending:
            st.requester = pending[-1].source
        return [{"type": "text", "text": _label(u, working=True)} for u in pending]

    # --- events and bookkeeping -----------------------------------------------------------------

    def _task_started(self, st: _TaskState) -> None:
        if not st.started:
            st.started = True
            self.emit("task", st.request, data={"id": st.id, "status": "started", "summary": st.request})

    def _step_running(self, st: _TaskState, index: int, detail: str) -> None:
        for i, s in list(st.steps.items()):   # moving on means the earlier steps are done
            if i < index and s == "running":
                self._set_step(st, i, "done", "")
        if st.steps.get(index) != "running":
            self._set_step(st, index, "running", detail)

    def _set_step(self, st: _TaskState, index: int, status: str, detail: str) -> None:
        st.steps[index] = status
        text = st.plan[index] if index < len(st.plan) else ""
        self.emit("step", text, data={"index": index, "status": status, "detail": detail})

    def _tell(self, st: _TaskState, text: str) -> None:
        """Say something to whoever asked (reply for guardians, out loud otherwise)."""
        if st.requester == "guardian":
            self.emit("reply", text, to="guardian")
        else:
            self.emit("say", text, to="senior")

    def _final_text(self, st: _TaskState, text: str) -> None:
        """Plain text at the end of a task reaches the requester unless Claude already did."""
        if not text:
            return
        if st.requester == "guardian":
            if not st.replied:
                self.emit("reply", text, to="guardian")
        elif not st.said:
            self.emit("say", text, to="senior")

    @staticmethod
    def _close_dangling(ex: list[dict[str, Any]], why: str) -> None:
        """Give every unanswered tool_use a result, so the history stays valid."""
        if not ex or ex[-1]["role"] != "assistant":
            return
        uses = [b for b in ex[-1]["content"] if _btype(b) == "tool_use"]
        if uses:
            ex.append({"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": b.id, "is_error": True, "content": why} for b in uses]})

    def _finish(self, st: _TaskState, ex: list[dict[str, Any]], status: str, summary: str, keep: bool) -> None:
        final = "done" if status == "done" else "failed"
        for i, s in sorted(st.steps.items()):
            if s == "running":
                self._set_step(st, i, final, "" if final == "done" else summary)
        if st.started:
            self.emit("task", summary or status, data={"id": st.id, "status": status, "summary": summary})
        elif status != "done":
            # #71: it failed before any action (API error, refusal, cut off, stop). Say so anyway: the
            # family layer ends a waiting delivery on this, or it would stay "sent" and block every Send.
            self.emit("task", summary or status,
                      data={"id": st.id, "status": status, "summary": summary, "started": False})
        if keep:
            exchange = _strip_thinking(ex)
            if self._stop_note:
                exchange.append({"role": "user", "content": [{"type": "text", "text": self._stop_note}]})
            self._history.append(exchange)
        self._stop_note = None
        if len(self._history) > self.history_exchanges:   # trim in a chunk: the cached prefix moves rarely
            del self._history[: len(self._history) - (self.history_exchanges - self.history_trim)]
        if self._state is st:
            self._state = None
