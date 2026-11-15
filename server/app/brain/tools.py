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

`this_is(name)` (#62, "Miguel, this is Mom") saves the clothes of the person in front under a
name in the PeopleRegistry (app/vision/people.py), so `find_person(name)` can find them later.
It needs `registry=` and `perception=` (a function returning the vision worker's newest
`Perception`); `save_look()` is the same save path for the control page's "This is" box.
"""

from __future__ import annotations

import asyncio
import inspect
import itertools
import logging
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.brain.types import AgentEvent, EventKind, Source, Utterance
from app.skills import Skill, SkillResult, SkillRunner

log = logging.getLogger(__name__)

PHYSICAL_TOOLS = ("follow", "find_person", "go_to", "bring")
MAX_PHOTOS = 20

# this_is (#62)
NAME_MAX = 40            # characters in a person's name
LOOK_MAX_AGE_S = 2.0     # a camera result older than this is stale: the person may have walked off (guess)
SIMILAR_WIDTH = 0.8      # a 2nd centered person at least this wide (vs the widest) = "who do you mean?" (guess)


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
        registry: Any = None,
        perception: Callable[[], Any] | None = None,
        wait_tray: Callable[[], Awaitable[bool]] | None = None,
        places: Any = None,
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
        registry: the PeopleRegistry (saved looks) find_person uses; this_is saves into it.
        perception: returns the vision worker's newest Perception (or None); this_is reads it.
        skill_wait_s: how long a physical tool waits for its skill before reporting "still running".
        follow_check_s: follow returns after this long if it hasn't failed straight away.
        wait_tray: waits until someone confirms the tray (Tray loaded button or voice); True if confirmed.
        places: the Memory (SQLite) that learn_place saves into (set_place, place_for).
        """
        self.runner = runner
        self.skill_factories: dict[str, Callable[..., Skill]] = dict(skill_factories or {})
        self.snapshot = snapshot
        self.describe = describe
        self.save_photo = save_photo
        self.memory: dict[str, str] = memory if memory is not None else {}
        self.registry = registry
        self.perception = perception
        self.wait_tray = wait_tray
        self.places = places
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
        people = ""
        if self.registry is not None:   # who find_person can find by name (saved with this_is)
            try:
                names = list(self.registry.names())
            except Exception:  # noqa: BLE001 - a broken registry must not break every request
                names = []
            people = f" People you know by sight: {', '.join(names[-max_items:]) or 'nobody yet'}."
        places = ""
        if self.places is not None:   # places (learn_place) and today's events, from SQLite
            try:
                places = " " + self.places.summary()
            except Exception:  # noqa: BLE001 - a broken store must not break every request
                places = ""
        return (f"Known facts: {text}.{people}{places} "
                f"Doing now: {self._skill_label if doing else 'nothing physical'}.")

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
        r("stay_silent",
          "Say nothing and do nothing: the mic message was not meant for you (people talking to each "
          "other, the TV, a stray fragment). Call it alone, with no text.",
          {"reason": _str("A few words on why, for the log.")},
          self._stay_silent, stepped=False)
        r("follow",
          "Start (on=true) or stop (on=false) following the person standing in front of you. It keeps "
          "running after this call returns, until stopped or replaced by another action. If the person "
          "steps out of view, you stop and wait for them, and follow again when they come back.",
          {"on": {"type": "boolean", "description": "true to start following, false to stop."}},
          self._follow)
        r("this_is",
          "Remember what the person standing in front of you looks like, under their name, so "
          "find_person(name) can find them later. Call it when someone in front of you says who they "
          "are ('this is Mom', 'I'm Dad'). Saving a name again replaces the old look. It knows people "
          "by their clothes, not their face, so it lasts until they change clothes. The World memory "
          "note lists who you know by sight. Returns what was saved, or why not (for example nobody "
          "or two people in front of you): then ask them to fix it and call it again.",
          {"name": _str("Their name, as the family calls them (for example 'Mom').")},
          self._this_is)
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
          "Look through the camera. With a question ('what is she holding?', 'what does the label say?', "
          "'is the stove on?') you get the answer; with null, a one or two sentence description of the scene.",
          {"question": _nullable_str("What to find out from the picture, or null for a general description.")},
          self._describe_scene)
        r("wait_for_tray",
          "Wait until someone confirms they put something in your tray or took it out (the Tray loaded "
          "button, or they tell you). Ask them out loud first with say. Returns loaded or timed out.",
          {"seconds": {"type": "integer", "description": "How long to wait, 5 to 300 seconds."}},
          self._wait_for_tray)
        r("check_in_result",
          "After asking the senior whether a guardian may check in on video now: record their answer. "
          "yes starts the video, no or no_answer declines it.",
          {"answer": {"type": "string", "enum": ["yes", "no", "no_answer"], "description": "Their answer."}},
          self._check_in_result, stepped=False)
        r("learn_place",
          "Save the place in front of you: the printed sign card with a marker (for example the water or "
          "medication station). Give the name if someone said it ('this is the kitchen'); null to read it "
          "off the sign. Saving a name again replaces it.",
          {"name": _nullable_str("The place's name, or null to read the sign.")},
          self._learn_place, stepped=False)
        r("remember",
          "Store a fact in world memory (for example key 'pills', value 'on the kitchen counter'). "
          "Overwrites the old value for that key.",
          {"key": _str("Short name for the fact."), "value": _str("The fact.")},
          self._remember, stepped=False)
        r("recall",
          "Look up a fact in world memory by key. Returns the value, or the known keys if it's missing.",
          {"key": _str("The key to look up.")},
          self._recall, stepped=False)
        r("forget",
          "Delete a fact from world memory (when someone says it's wrong or asks you to forget it).",
          {"key": _str("The key to delete.")},
          self._forget, stepped=False)

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

    async def _stay_silent(self, a: dict[str, Any]) -> ToolOutcome:
        reason = str(a.get("reason", "")).strip()
        log.info("agent stays silent: %s", reason or "not meant for Miguel")
        return ToolOutcome(True, "Staying silent.", {"silent": True, "reason": reason})

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
        return ToolOutcome(True, "Following now. If they step out of view I wait for them to come back. "
                                 "It keeps running until stopped or replaced.", {"skill": "follow"})

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
        question = str(a.get("question") or "").strip() or None
        if self.describe is None:
            from app.brain.vision_check import describe_scene
            return ToolOutcome(True, await describe_scene(jpeg, question=question))
        if question is None:
            return ToolOutcome(True, await self.describe(jpeg))
        try:
            return ToolOutcome(True, await self.describe(jpeg, question=question))   # type: ignore[call-arg]
        except TypeError:   # an injected describe without questions (tests)
            return ToolOutcome(True, await self.describe(jpeg))

    async def _wait_for_tray(self, a: dict[str, Any]) -> ToolOutcome:
        if self.wait_tray is None:
            return ToolOutcome(False, "wait_for_tray is unavailable (no Tray loaded button on this server).")
        seconds = min(max(int(60 if a.get("seconds") is None else a["seconds"]), 5), 300)
        try:
            ok = await asyncio.wait_for(self.wait_tray(), seconds)
        except TimeoutError:
            ok = False
        if ok:
            return ToolOutcome(True, "Confirmed: the tray was loaded or emptied.", {"loaded": True})
        return ToolOutcome(True, f"No confirmation in {seconds} s.", {"loaded": False})

    async def _check_in_result(self, a: dict[str, Any]) -> ToolOutcome:
        answer = str(a.get("answer", "")).strip()
        if answer not in ("yes", "no", "no_answer"):
            return ToolOutcome(False, "answer must be yes, no or no_answer.")
        self._emit("check_in", answer, data={"answer": answer})
        return ToolOutcome(True, "Check-in video started." if answer == "yes" else "Check-in declined.",
                           {"answer": answer})

    async def _learn_place(self, a: dict[str, Any]) -> ToolOutcome:
        if self.places is None:
            return ToolOutcome(False, "learn_place is unavailable (no memory on this server).")
        p = self.perception() if self.perception is not None else None
        markers = list(getattr(p, "markers", ()) or ())
        marker = None
        if markers:   # the biggest (closest) card in view
            marker = max(markers, key=lambda m: float(getattr(m, "size", 0) or getattr(m, "w", 0) or 0)).id
        name = str(a.get("name") or "").strip()
        description = ""
        if not name or marker is None:
            jpeg = await self._snap()
            if jpeg is None and not name:
                return ToolOutcome(False, "No camera frame to read the sign from. Ask for the place's name.")
            if jpeg is not None:
                from app.brain.vision_check import describe_scene
                q = ("What place or station name is printed on the sign or card in view? Answer with just the "
                     "name in a few words, or 'none'. Then, after ' | ', describe the spot in one short sentence.")
                answer = await (self.describe(jpeg, question=q) if self.describe is not None
                                else describe_scene(jpeg, question=q))
                read, _, description = answer.partition("|")
                read = read.strip().strip(".").strip()
                if not name and read.lower() not in ("", "none", "no sign"):
                    name = read
        if not name:
            return ToolOutcome(False, "I couldn't read a name on a sign. Ask what this place is called.")
        if marker is None and not description:
            return ToolOutcome(False, f"No marker card in view for {name!r}. Ask them to hold the card in front of you.")
        place = self.places.set_place(name, marker=marker, description=description.strip())
        self._emit("place", place["name"], data={"name": place["name"], "marker": marker})
        where = f"marker {marker}" if marker is not None else "its look (no marker; slower to find)"
        return ToolOutcome(True, f"Saved the place {place['name']!r} by {where}.", place)

    async def _forget(self, a: dict[str, Any]) -> ToolOutcome:
        key = str(a.get("key", "")).strip()
        if key in self.memory:
            del self.memory[key]
            return ToolOutcome(True, f"Forgot {key}.")
        keys = ", ".join(self.memory) or "none"
        return ToolOutcome(True, f"Nothing remembered for {key!r}. Known keys: {keys}.")

    async def _remember(self, a: dict[str, Any]) -> ToolOutcome:
        key, value = str(a.get("key", "")).strip(), str(a.get("value", "")).strip()
        if not key:
            return ToolOutcome(False, "remember needs a key.")
        self.memory.pop(key, None)   # re-insert so the newest facts come last in the summary
        self.memory[key] = value
        return ToolOutcome(True, f"Remembered {key}.")

    async def _this_is(self, a: dict[str, Any]) -> ToolOutcome:
        return self.this_is(str(a.get("name") or ""))

    def this_is(self, name: str) -> ToolOutcome:
        """Save the look of the person in front as `name` (see `save_look`)."""
        if self.registry is None or self.perception is None:
            return ToolOutcome(False, "this_is is unavailable right now (no camera or no saved-looks store on this robot).")
        return save_look(name, self.registry, self.perception())

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


# --- this_is (#62): save the look of the person in front ---------------------------------------


def clean_name(name: str) -> str:
    """'  mom. ' -> 'mom': one space between words, no surrounding quotes or punctuation."""
    return " ".join(str(name).split()).strip(" .,!?;:\"'")


def person_in_front(perception: Any, config: Any = None) -> tuple[Any, str]:
    """Who "the person in front" is, as (person, how) or (None, why not).

    The locked follow target if there is one (`how` = "locked target"); else the widest person
    near the center by the lock's own engage rules (|cx - 0.5| <= engage_max_offset, width at
    least engage_min_w), unless a second centered person is nearly as wide (ambiguous).
    `why not` is "nobody", "too far" or "ambiguous"."""
    from app.vision.tracking import LockConfig
    from app.vision.types import TargetStatus

    target = getattr(perception, "target", None)
    if target is not None and target.status is TargetStatus.LOCKED and target.person is not None:
        return target.person, "locked target"
    cfg = config or LockConfig()
    centered = sorted((p for p in perception.people
                       if p.score >= cfg.min_det_score and abs(p.box.cx - 0.5) <= cfg.engage_max_offset),
                      key=lambda p: -p.box.w)
    if not centered:
        return None, "nobody"
    best = centered[0]
    if best.box.w < cfg.engage_min_w:
        return None, "too far"
    if len(centered) > 1 and centered[1].box.w >= SIMILAR_WIDTH * best.box.w:
        return None, "ambiguous"
    return best, "in front"


def save_look(name: str, registry: Any, perception: Any, *, max_age_s: float = LOOK_MAX_AGE_S,
              clock: Callable[[], float] = time.monotonic) -> ToolOutcome:
    """Histogram the person in front (`person_in_front`) and `registry.save(name, parts)`.

    `perception` is the vision worker's newest Perception (or None). Never raises for the
    expected failures: each comes back as ToolOutcome(False, text to relay)."""
    name = clean_name(name)
    if not name:
        return ToolOutcome(False, "this_is needs the person's name.")
    if len(name) > NAME_MAX:
        return ToolOutcome(False, f"That name is too long (at most {NAME_MAX} characters).")
    if registry is None:
        return ToolOutcome(False, "this_is is unavailable right now (no saved-looks store on this robot).")
    if perception is None:
        return ToolOutcome(False, "I can't see right now: the camera has no picture yet.")
    published = getattr(perception, "published_at", None)
    age = clock() - published if isinstance(published, (int, float)) else 0.0
    if age > max_age_s:
        return ToolOutcome(False, f"I can't see right now: the camera's last picture is {age:.0f} s old.")
    person, how = person_in_front(perception)
    if person is None:
        why = {
            "nobody": "Nobody is standing in front of me. Ask them to stand in front of me, facing me, then try again.",
            "too far": ("The person in front of me is too far away to see their clothes. Ask them to come "
                        "closer (one or two steps away), then try again."),
            "ambiguous": (f"Two people are standing in front of me, so I don't know which one is {name}. "
                          f"Ask {name} to stand in front of me alone, then try again."),
        }[how]
        return ToolOutcome(False, why, {"reason": how})

    from app.vision.tracking import body_part_histograms

    parts = body_part_histograms(perception.frame.image, person, perception.people)   # masks whoever stands in front
    occluded = ToolOutcome(False, f"I can't see enough of {name}'s clothes (something is in the way). Ask them to "
                                  f"stand in front of me with nothing in between, then try again.", {"reason": "occluded"})
    if parts is None:
        return occluded
    replaced = name in registry
    note = ""
    try:
        registry.save(name, parts)
    except ValueError:
        return occluded
    except OSError as e:   # saved in memory; only the file failed (registry.save updates memory first)
        log.warning("this_is: couldn't write the saved looks: %s", e)
        note = " (Only until a restart: the file couldn't be written.)"
    seen = " and ".join(part for part, ok in (("shirt", parts.torso is not None), ("trousers", parts.legs is not None)) if ok)
    b = person.box
    log.info("this_is: saved %s (%s, %s)", name, how, seen)
    return ToolOutcome(
        True,
        f"{'Updated' if replaced else 'Saved'} what {name} looks like ({seen}). find_person can find {name} now, "
        f"until they change clothes.{note}",
        {"name": name, "replaced": replaced, "from": how, "torso": parts.torso is not None,
         "legs": parts.legs is not None, "box": [round(v, 3) for v in (b.x1, b.y1, b.x2, b.y2)]},
    )
