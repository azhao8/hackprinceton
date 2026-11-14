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
"""

from __future__ import annotations

import asyncio
import itertools
import logging
import re
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import anthropic

from app.brain.prompt import (
    EFFORT_CHAT,
    EFFORT_TASK,
    MODEL,
    SYSTEM_PROMPT,
    create_message,
    effort_for,
    ACK_GUARDIAN,
    ACK_SPOKEN,
    get_client,
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


def _label(u: Utterance, working: bool = False) -> str:
    channel = u.meta.get("channel") or DEFAULT_CHANNEL.get(u.source, "?")
    return f"[{u.source} via {channel}{', while you were working' if working else ''}] {u.text}"


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
        out.append({"role": m["role"], "content": content})
    return out


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
        max_rounds: int = 16,
        max_tokens: int = 8000,
        max_events: int = 300,
        ack: bool = True,
    ):
        """
        tools: the ToolBox (the agent binds itself as its host).
        events_cb: called with every AgentEvent (sync; keep it quick).
        client: an AsyncAnthropic (default: the shared one, created on first call).
        fallbacks: server-side refusal fallbacks (None = env MIGUEL_LLM_FALLBACKS, default on).
        history_exchanges: how many past tasks the conversation keeps.
        max_rounds: LLM calls per task before giving up.
        """
        self.tools = tools
        self.events_cb = events_cb
        self.ack = ack   # say "On it!" / reply "Got it" at once for task-like requests
        self.model = model
        self.fallbacks = fallbacks
        self.history_exchanges = history_exchanges
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

    async def run(self) -> None:
        """Consume the inbox forever."""
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
        ev = AgentEvent(next(self._event_ids), kind, text, to, dict(data or {}))
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
        try:
            return await asyncio.wait_for(fut, seconds)
        except TimeoutError:
            return None
        finally:
            if self._reply_waiter is fut:
                self._reply_waiter = None

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
        self._state = st
        efforts = {effort_for(u.text, u.source) for u in utterances}
        effort = EFFORT_TASK if EFFORT_TASK in efforts else EFFORT_CHAT
        content: list[dict[str, Any]] = [{"type": "text", "text": _label(u)} for u in utterances]
        content.append({"type": "text", "text": f"World memory: {self.tools.memory_summary()}"})
        ex: list[dict[str, Any]] = [{"role": "user", "content": content}]
        if self.ack and effort == EFFORT_TASK:   # acknowledge at once; the plan follows when Claude answers
            if last.source == "guardian":
                self.emit("reply", ACK_GUARDIAN, to="guardian", data={"ack": True})
            else:
                self.emit("say", ACK_SPOKEN, to="senior", data={"ack": True})
        status, summary, keep = "done", "", True
        try:
            for _ in range(self.max_rounds):
                resp = await self._call(ex, effort)
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
                    self._final_text(st, summary)
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

    async def _call(self, ex: list[dict[str, Any]], effort: str) -> Any:
        messages = [m for exchange in self._history for m in exchange] + ex
        return await create_message(
            self.client,
            fallbacks=self.fallbacks,
            model=self.model,
            max_tokens=self.max_tokens,
            system=SYSTEM_PROMPT,
            tools=self.tools.definitions(),
            messages=messages,
            output_config={"effort": effort},
            cache_control={"type": "ephemeral"},
        )

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
        if keep:
            exchange = _strip_thinking(ex)
            if self._stop_note:
                exchange.append({"role": "user", "content": [{"type": "text", "text": self._stop_note}]})
            self._history.append(exchange)
        self._stop_note = None
        del self._history[: max(0, len(self._history) - self.history_exchanges)]
        if self._state is st:
            self._state = None
