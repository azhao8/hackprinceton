"""The agent's tools (owner: Grant): what Claude can call, and the code behind each call.

`ToolBox` maps tool names to async handlers that return a `ToolOutcome`, and produces the
Claude tool definitions (strict JSON schema, `additionalProperties: false`). The list of
definitions is fixed at construction (all built-in tools are always declared, so the prompt
prefix stays cacheable); a tool whose backing piece is missing (no skill factory, no camera)
answers with an error that says it's unavailable.

Physical tools (`follow`, `find_person`, `go_to`, `bring`) build a skill with an injected
factory and run it through the `SkillRunner` (one body: starting one cancels the other).
Factories are called with keyword arguments:

    skill_factories = {
        "follow": lambda: FollowSkill(),
        "find_person": lambda name, description: ...,   # name / description may be None
        "go_to": lambda place: ...,
        "bring": lambda item, person: ...,
    }

The agent binds itself as the `ToolHost` (events, waiting for the senior's reply, the
"someone spoke while you were working" signal) with `ToolBox.bind(agent)`.
"""

from __future__ import annotations

import asyncio
import inspect
import itertools
import logging
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.brain.types import AgentEvent, EventKind, Source, Utterance
from app.skills import Skill, SkillResult, SkillRunner

log = logging.getLogger(__name__)

PHYSICAL_TOOLS = ("follow", "find_person", "go_to", "bring")
MAX_PHOTOS = 20


@dataclass(frozen=True)
class ToolOutcome:
    ok: bool
    text: str
    data: dict[str, Any] = field(default_factory=dict)


Handler = Callable[[dict[str, Any]], Awaitable[ToolOutcome]]
Snapshot = Callable[[], "bytes | None | Awaitable[bytes | None]"]


class ToolHost(Protocol):
    """What the tools need from the agent."""

    def emit(self, kind: EventKind, text: str = "", *, to: Source | None = None,
             data: dict[str, Any] | None = None) -> AgentEvent: ...

    async def wait_for_senior(self, seconds: float) -> Utterance | None: ...

    async def wait_interjection(self) -> None: ...


@dataclass
class _Tool:
    name: str
    description: str
    properties: dict[str, Any]
    handler: Handler
    stepped: bool = True   # gets the optional "step" (plan step index) field

    def definition(self) -> dict[str, Any]:
        props = dict(self.properties)
        if self.stepped:
            props["step"] = {
                "anyOf": [{"type": "integer"}, {"type": "null"}],
                "description": "Index (0-based) of the set_plan step this call belongs to, or null.",
            }
        return {
            "name": self.name,
            "description": self.description,
            "strict": True,
            "input_schema": {
                "type": "object",
                "properties": props,
                "required": list(props),
                "additionalProperties": False,
            },
        }


def _str(desc: str) -> dict[str, Any]:
    return {"type": "string", "description": desc}


def _nullable_str(desc: str) -> dict[str, Any]:
    return {"anyOf": [{"type": "string"}, {"type": "null"}], "description": desc}


class ToolBox:
    """Tools for the agent. Inject what exists; the rest reports itself unavailable."""

    def __init__(
        self,
        runner: SkillRunner | None = None,
        skill_factories: dict[str, Callable[..., Skill]] | None = None,
        *,
        snapshot: Snapshot | None = None,
        describe: Callable[[bytes], Awaitable[str]] | None = None,
        save_photo: Callable[[bytes], str] | None = None,
        memory: dict[str, str] | None = None,
        skill_wait_s: float = 120.0,
        follow_check_s: float = 1.0,
    ):
        """
        runner: the SkillRunner shared with the rest of the server (None = no body).
        skill_factories: tool name -> factory returning a Skill (see module docstring).
        snapshot: returns the latest camera frame as JPEG bytes (or None); sync or async.
        describe: JPEG -> scene text (default: vision_check.describe_scene).
        save_photo: stores a photo, returns a URL for the app (default: kept in self.photos).
        memory: the world memory dict (shared, in-memory; wiped on restart).
        skill_wait_s: how long a physical tool waits for its skill before reporting "still running".
        follow_check_s: follow returns after this long if it hasn't failed straight away.
        """
        self.runner = runner
        self.skill_factories: dict[str, Callable[..., Skill]] = dict(skill_factories or {})
        self.snapshot = snapshot
        self.describe = describe
        self.save_photo = save_photo
        self.memory: dict[str, str] = memory if memory is not None else {}
        self.photos: OrderedDict[int, bytes] = OrderedDict()
        self.skill_wait_s = skill_wait_s
        self.follow_check_s = follow_check_s
        self.host: ToolHost | None = None
        self._photo_ids = itertools.count(1)
        self._skill_task: asyncio.Task[SkillResult] | None = None   # the physical action we started
        self._skill_label = ""
        self._tools: dict[str, _Tool] = {}
        self._register_builtins()

    # --- wiring ---------------------------------------------------------------------------------

    def bind(self, host: ToolHost) -> None:
        self.host = host

    def register(self, name: str, description: str, properties: dict[str, Any], handler: Handler,
                 *, stepped: bool = True) -> None:
        """Add (or replace) a tool. Do it before the agent's first call: the tool list is part of
        the cached prompt prefix. `properties` are JSON-schema properties; all become required
        (use anyOf with null for optional ones)."""
        self._tools[name] = _Tool(name, description, properties, handler, stepped)

    def definitions(self) -> list[dict[str, Any]]:
        return [t.definition() for t in self._tools.values()]

    @property
    def names(self) -> list[str]:
        return list(self._tools)

    def is_physical(self, name: str) -> bool:
        return name in PHYSICAL_TOOLS

    @property
    def running(self) -> str | None:
        """The physical action running now, or None."""
        if self.runner is None:
            return None
        return self.runner.running

    def cancel_physical(self) -> None:
        """Stop the body right away (the senior's stop). Safe to call from sync code."""
        if self.runner is not None:
            self.runner.cancel()

    def memory_summary(self, max_items: int = 12, max_chars: int = 600) -> str:
        parts = [f"{k}: {v}" for k, v in list(self.memory.items())[-max_items:]]
        text = "; ".join(parts) if parts else "nothing yet"
        if len(text) > max_chars:
            text = text[: max_chars - 3] + "..."
        doing = self.running
        return f"Known facts: {text}. Doing now: {self._skill_label if doing else 'nothing physical'}."

    async def call(self, name: str, args: dict[str, Any]) -> ToolOutcome:
        """Run one tool. Unknown tools and handler crashes come back as failed outcomes."""
        tool = self._tools.get(name)
        if tool is None:
            return ToolOutcome(False, f"The tool {name!r} is unavailable. Use one of: {', '.join(self._tools)}.")
        try:
            return await tool.handler(args)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 - a broken tool must not kill the agent
            log.exception("tool %s crashed", name)
            return ToolOutcome(False, f"{name} failed: {type(e).__name__}: {e}")

    # --- built-in tools -------------------------------------------------------------------------

    def _register_builtins(self) -> None:
        r = self.register
        r("set_plan",
          "Call this first for any request with more than one step: lay out the plan as short steps "
          "(a few words each) so the family can follow along. Call again to replace the plan.",
          {"steps": {"type": "array", "items": {"type": "string"}, "description": "The steps, in order."}},
          self._set_plan, stepped=False)
        r("say",
          "Say something out loud through the phone's speaker, to the senior and anyone in the room. "
          "Use it to greet, to announce what you are about to do before moving, to ask, and to report.",
          {"text": _str("What to say: short, simple spoken sentences.")},
          self._say)
        r("reply_to_guardian",
          "Send a message to the guardian (family member) in their app. Use it to answer them, report a "
          "finished or failed task, or alert them. attach_photo adds the current camera frame: only when "
          "they asked for a photo or the task needs proof.",
          {"text": _str("The message, short like a text message."),
           "attach_photo": {"type": "boolean", "description": "Attach the latest camera frame."}},
          self._reply)
        r("wait_for_reply",
          "Wait for the senior to answer out loud (after you asked them something with say). Returns what "
          "they said, or 'no answer'.",
          {"seconds": {"type": "integer", "description": "How long to wait, 5 to 60 seconds."}},
          self._wait_for_reply)
        r("follow",
          "Start (on=true) or stop (on=false) following the person standing in front of you. It keeps "
          "running after this call returns, until stopped, replaced by another action, or the person is lost.",
          {"on": {"type": "boolean", "description": "true to start following, false to stop."}},
          self._follow)
        r("find_person",
          "Look around for a person and drive up to them. Give a name if you know it (from memory), "
          "a visual description (clothes, hair), or both; null for 'anyone'.",
          {"name": _nullable_str("Who, by name, or null."),
           "description": _nullable_str("What they look like, or null.")},
          self._physical("find_person", lambda a: {"name": a.get("name"), "description": a.get("description")}))
        r("go_to",
          "Drive to a place or object in the home (for example 'kitchen', 'the armchair', 'front door').",
          {"place": _str("Where to go.")},
          self._physical("go_to", lambda a: {"place": a["place"]}))
        r("bring",
          "Bring an item to a person: fetch it and deliver it (for example item 'medication', person 'Mom').",
          {"item": _str("What to bring."), "person": _str("Who it is for.")},
          self._physical("bring", lambda a: {"item": a["item"], "person": a["person"]}))
        r("wait_for_action",
          "Keep waiting for the physical action that is still running (after a tool said it is still "
          "running, or after you were interrupted). Returns its result, or 'still running'.",
          {"seconds": {"type": "integer", "description": "How long to wait, up to 120 seconds."}},
          self._wait_for_action)
        r("stop",
          "Stop moving right away and cancel the running physical action.",
          {}, self._stop, stepped=False)
        r("describe_scene",
          "Look through the camera and get a one or two sentence description of what you see now.",
          {}, self._describe_scene)
        r("remember",
          "Store a fact in world memory (for example key 'pills', value 'on the kitchen counter'). "
          "Overwrites the old value for that key.",
          {"key": _str("Short name for the fact."), "value": _str("The fact.")},
          self._remember, stepped=False)
        r("recall",
          "Look up a fact in world memory by key. Returns the value, or the known keys if it's missing.",
          {"key": _str("The key to look up.")},
          self._recall, stepped=False)

    def _emit(self, kind: EventKind, text: str = "", *, to: Source | None = None,
              data: dict[str, Any] | None = None) -> None:
        if self.host is not None:
            self.host.emit(kind, text, to=to, data=data)

    async def _set_plan(self, a: dict[str, Any]) -> ToolOutcome:
        steps = [str(s).strip() for s in a.get("steps", []) if str(s).strip()]
        if not steps:
            return ToolOutcome(False, "The plan needs at least one step.")
        self._emit("plan", "; ".join(steps), data={"steps": steps})
        return ToolOutcome(True, f"Plan set with {len(steps)} steps.", {"steps": steps})

    async def _say(self, a: dict[str, Any]) -> ToolOutcome:
        text = str(a.get("text", "")).strip()
        if not text:
            return ToolOutcome(False, "Nothing to say.")
        self._emit("say", text, to="senior")
        return ToolOutcome(True, "Said it out loud.", {"text": text})

    async def _reply(self, a: dict[str, Any]) -> ToolOutcome:
        text = str(a.get("text", "")).strip()
        if not text:
            return ToolOutcome(False, "The message is empty.")
        data: dict[str, Any] = {}
        note = "Sent to the guardian."
        if a.get("attach_photo"):
            jpeg = await self._snap()
            if jpeg is None:
                note = "Sent to the guardian, but without a photo: no camera frame was available."
            else:
                data.update(self._store_photo(jpeg))
                note = "Sent to the guardian with a photo."
        self._emit("reply", text, to="guardian", data=data)
        return ToolOutcome(True, note, data)

    async def _wait_for_reply(self, a: dict[str, Any]) -> ToolOutcome:
        if self.host is None:
            return ToolOutcome(False, "wait_for_reply is unavailable (no microphone).")
        seconds = min(max(int(10 if a.get("seconds") is None else a["seconds"]), 1), 60)
        u = await self.host.wait_for_senior(seconds)
        if u is None:
            return ToolOutcome(True, f"no answer (waited {seconds} s)", {"answer": None})
        return ToolOutcome(True, f'The senior said: "{u.text}"', {"answer": u.text})

    async def _follow(self, a: dict[str, Any]) -> ToolOutcome:
        if not a.get("on"):
            was = self.running
            self.cancel_physical()
            return ToolOutcome(True, "Stopped following." if was == "follow" else "Wasn't following; holding still.")
        task = self._start_skill("follow", {})
        if isinstance(task, ToolOutcome):
            return task
        done, _ = await asyncio.wait({task}, timeout=self.follow_check_s)
        if done:
            return _from_result("follow", task.result())
        return ToolOutcome(True, "Following now. It keeps running until stopped or replaced.", {"skill": "follow"})

    def _physical(self, name: str, kwargs_of: Callable[[dict[str, Any]], dict[str, Any]]) -> Handler:
        async def handler(a: dict[str, Any]) -> ToolOutcome:
            task = self._start_skill(name, kwargs_of(a))
            if isinstance(task, ToolOutcome):
                return task
            return await self._await_skill(task, self.skill_wait_s)
        return handler

    def _start_skill(self, name: str, kwargs: dict[str, Any]) -> asyncio.Task[SkillResult] | ToolOutcome:
        factory = self.skill_factories.get(name)
        if self.runner is None or factory is None:
            return ToolOutcome(False, f"{name} is unavailable right now (that skill isn't running on this robot).")
        skill = factory(**kwargs)
        self._skill_label = name + (f"({', '.join(str(v) for v in kwargs.values() if v)})" if kwargs else "")
        self._skill_task = self.runner.start(skill)
        return self._skill_task

    async def _await_skill(self, task: asyncio.Task[SkillResult], timeout: float) -> ToolOutcome:
        """Wait for the skill, but come back early if someone speaks (so the agent can decide)."""
        name = task.get_name()
        waiter = asyncio.ensure_future(self.host.wait_interjection()) if self.host is not None else None
        try:
            done, _ = await asyncio.wait({task} | ({waiter} if waiter else set()), timeout=timeout,
                                         return_when=asyncio.FIRST_COMPLETED)
        except asyncio.CancelledError:
            if not task.done():
                self.cancel_physical()   # the agent's task was cancelled (stop): stop the body too
            raise
        finally:
            if waiter is not None:
                waiter.cancel()
        if task in done:
            return _from_result(name, task.result())
        why = "Someone spoke while you were working (see below)" if waiter in done else f"Still going after {timeout:.0f} s"
        return ToolOutcome(True, f"{why}. {name} is still running. Call wait_for_action to keep waiting, start "
                                 f"another action to replace it, or stop().", {"skill": name, "running": True})

    async def _wait_for_action(self, a: dict[str, Any]) -> ToolOutcome:
        task = self._skill_task
        if task is None or (self.runner is not None and self.runner.task is not task):
            return ToolOutcome(True, "No physical action of yours is running.")
        if task.done():
            return _from_result(task.get_name(), task.result())
        seconds = min(max(int(30 if a.get("seconds") is None else a["seconds"]), 1), 120)
        return await self._await_skill(task, seconds)

    async def _stop(self, a: dict[str, Any]) -> ToolOutcome:
        was = self.running
        self.cancel_physical()
        return ToolOutcome(True, f"Stopped {was}." if was else "Nothing was moving; holding still.")

    async def _describe_scene(self, a: dict[str, Any]) -> ToolOutcome:
        jpeg = await self._snap()
        if jpeg is None:
            return ToolOutcome(False, "describe_scene is unavailable: no camera frame right now.")
        describe = self.describe
        if describe is None:
            from app.brain.vision_check import describe_scene
            describe = describe_scene
        return ToolOutcome(True, await describe(jpeg))

    async def _remember(self, a: dict[str, Any]) -> ToolOutcome:
        key, value = str(a.get("key", "")).strip(), str(a.get("value", "")).strip()
        if not key:
            return ToolOutcome(False, "remember needs a key.")
        self.memory.pop(key, None)   # re-insert so the newest facts come last in the summary
        self.memory[key] = value
        return ToolOutcome(True, f"Remembered {key}.")

    async def _recall(self, a: dict[str, Any]) -> ToolOutcome:
        key = str(a.get("key", "")).strip()
        if key in self.memory:
            return ToolOutcome(True, f"{key}: {self.memory[key]}", {"value": self.memory[key]})
        keys = ", ".join(self.memory) or "none"
        return ToolOutcome(True, f"Nothing remembered for {key!r}. Known keys: {keys}.", {"value": None})

    # --- helpers --------------------------------------------------------------------------------

    async def _snap(self) -> bytes | None:
        if self.snapshot is None:
            return None
        jpeg = self.snapshot()
        if inspect.isawaitable(jpeg):
            jpeg = await jpeg
        return jpeg or None

    def _store_photo(self, jpeg: bytes) -> dict[str, Any]:
        pid = next(self._photo_ids)
        self.photos[pid] = jpeg
        while len(self.photos) > MAX_PHOTOS:
            self.photos.popitem(last=False)
        url = self.save_photo(jpeg) if self.save_photo is not None else None
        return {"photo_id": pid, "photo_url": url}


def _from_result(name: str, r: SkillResult) -> ToolOutcome:
    text = r.detail or ("done" if r.ok else "failed")
    return ToolOutcome(r.ok, f"{name}: {text}", {"skill": name})
