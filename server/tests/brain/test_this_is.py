"""this_is (#62, "Miguel, this is Mom"): save the look of the person in front, then find them by name.

Synthetic frames from the tracking tests (painted people, no model, no camera) and a real
in-memory PeopleRegistry; the agent test uses the scripted fake Anthropic client."""

from __future__ import annotations

import asyncio
import json
import time

from app.arbiter import Arbiter
from app.brain.agent import Agent
from app.brain.tools import ToolBox, save_look
from app.brain.types import Utterance
from app.skills import SkillContext, SkillRunner
from app.vision.people import PeopleRegistry
from app.vision.types import Frame, TargetState, TargetStatus
from app.vision.worker import Perception
from tests.brain.test_agent import FakeClient, Quick, last_user, msg, text, tool
from tests.vision.test_tracking import BLACK, BLUE, GREEN, RED, WHITE, YELLOW, Walker, parts_of, render

MOM = dict(pants=BLUE, shirt=RED)
DAD = dict(pants=BLACK, shirt=GREEN)
KID = dict(pants=WHITE, shirt=YELLOW)


def perceive(walkers: list[Walker], locked: int | None = None, published_at: float | None = None) -> Perception:
    """A Perception of these walkers; `locked` = index of the follow target (None: not following)."""
    dets, image = render(0, walkers)
    if locked is None:
        target = TargetState(TargetStatus.IDLE)
    else:
        person = dets.people[locked]
        target = TargetState(TargetStatus.LOCKED, person=person, last_seen_cx=person.box.cx)
    return Perception(frame=Frame(dets.frame_t, 0, image), detections=dets, target=target, engage_pending=False,
                      engaged_seq=1 if locked is not None else 0, latency_s=0.03, fps=20.0,
                      published_at=time.monotonic() if published_at is None else published_at)


def who(registry: PeopleRegistry, colors: dict) -> str | None:
    """Whom the registry recognizes in a fresh frame of someone dressed like this."""
    hit = registry.match(parts_of(Walker(0.5, **colors), index=7))
    return None if hit is None else hit[0]


def toolbox(p: Perception | None, registry: PeopleRegistry | None = None) -> tuple[ToolBox, PeopleRegistry]:
    reg = registry or PeopleRegistry(None)
    return ToolBox(registry=reg, perception=lambda: p), reg


def this_is(tools: ToolBox, name: str):
    return asyncio.run(tools.call("this_is", {"name": name}))


# --- who is "in front" ---


def test_saves_the_widest_centered_person():
    p = perceive([Walker(0.45, w=0.3, **MOM), Walker(0.68, w=0.14, **KID), Walker(0.88, w=0.3, **DAD)])
    tools, reg = toolbox(p)   # the kid is centered but much narrower; Dad is wide but off to the side
    out = this_is(tools, "Mom")
    assert out.ok and out.text.startswith("Saved what Mom looks like (shirt and trousers).")
    assert out.data["from"] == "in front" and out.data["replaced"] is False and out.data["name"] == "Mom"
    assert reg.names() == ["Mom"]
    assert who(reg, MOM) == "Mom" and who(reg, DAD) is None and who(reg, KID) is None


def test_saves_the_locked_follow_target_even_if_someone_else_is_in_front():
    p = perceive([Walker(0.5, w=0.3, **MOM), Walker(0.85, w=0.2, **DAD)], locked=1)
    tools, reg = toolbox(p)
    out = this_is(tools, "Dad")
    assert out.ok and out.data["from"] == "locked target"
    assert who(reg, DAD) == "Dad" and who(reg, MOM) is None


def test_saving_again_replaces_the_look_case_insensitively():
    reg = PeopleRegistry(None)
    first = save_look("Mom", reg, perceive([Walker(0.5, **DAD)]))   # oops: that was Dad standing there
    assert first.ok and who(reg, DAD) == "Mom"
    again = save_look("  mom. ", reg, perceive([Walker(0.5, **MOM)]))
    assert again.ok and again.data["replaced"] is True and again.text.startswith("Updated what mom looks like")
    assert reg.names() == ["mom"] and who(reg, MOM) == "mom" and who(reg, DAD) is None


def test_the_saved_look_survives_a_restart(tmp_path):
    path = tmp_path / "people.json"
    assert save_look("Mom", PeopleRegistry(path), perceive([Walker(0.5, **MOM)])).ok
    assert json.loads(path.read_text())["people"][0]["name"] == "Mom"
    assert who(PeopleRegistry(path), MOM) == "Mom"


# --- failures: clear text, nothing saved ---


def test_nobody_in_front():
    for walkers in ([], [Walker(0.9, **MOM)], [Walker(0.1, **DAD), Walker(0.88, **MOM)]):   # empty, or off to the side
        tools, reg = toolbox(perceive(walkers))
        out = this_is(tools, "Mom")
        assert not out.ok and out.text.startswith("Nobody is standing in front of me.") and out.data["reason"] == "nobody"
        assert reg.names() == []


def test_someone_too_far_away():
    tools, reg = toolbox(perceive([Walker(0.5, w=0.08, **MOM)]))
    out = this_is(tools, "Mom")
    assert not out.ok and "too far away" in out.text and out.data["reason"] == "too far" and reg.names() == []


def test_two_similar_people_both_centered_is_ambiguous():
    tools, reg = toolbox(perceive([Walker(0.38, w=0.24, **MOM), Walker(0.62, w=0.22, **DAD)]))
    out = this_is(tools, "Mom")
    assert not out.ok and out.data["reason"] == "ambiguous"
    assert out.text == ("Two people are standing in front of me, so I don't know which one is Mom. "
                        "Ask Mom to stand in front of me alone, then try again.")
    assert reg.names() == []


def test_a_person_hidden_behind_someone_else_is_too_occluded():
    # Following Dad, but Mom stepped right in front of him: none of his clothes are visible.
    p = perceive([Walker(0.5, w=0.2, depth=10.0, **DAD), Walker(0.5, w=0.34, depth=1.0, **MOM)], locked=0)
    tools, reg = toolbox(p)
    out = this_is(tools, "Dad")
    assert not out.ok and out.data["reason"] == "occluded" and "can't see enough of Dad's clothes" in out.text
    assert reg.names() == []


def test_no_camera_is_unavailable_and_no_frame_or_a_stale_one_is_refused():
    out = this_is(ToolBox(), "Mom")   # no registry, no perception: the tool is declared but unavailable
    assert not out.ok and "unavailable" in out.text
    out = this_is(ToolBox(registry=PeopleRegistry(None)), "Mom")
    assert not out.ok and "unavailable" in out.text
    tools, _ = toolbox(None)
    assert this_is(tools, "Mom").text == "I can't see right now: the camera has no picture yet."
    tools, reg = toolbox(perceive([Walker(0.5, **MOM)], published_at=time.monotonic() - 5))
    out = this_is(tools, "Mom")
    assert not out.ok and "last picture is 5 s old" in out.text and reg.names() == []


def test_name_is_needed_and_capped():
    tools, reg = toolbox(perceive([Walker(0.5, **MOM)]))
    assert this_is(tools, "  ").text == "this_is needs the person's name."
    assert "too long" in this_is(tools, "x" * 41).text
    assert reg.names() == []


def test_tool_is_declared_strict_and_known_people_reach_the_world_memory():
    tools, reg = toolbox(perceive([Walker(0.5, **MOM)]))
    d = next(t for t in tools.definitions() if t["name"] == "this_is")
    assert d["strict"] and d["input_schema"]["required"] == ["name", "step"]
    assert "People you know by sight: nobody yet." in tools.memory_summary()
    this_is(tools, "Mom")
    assert "People you know by sight: Mom." in tools.memory_summary()
    assert "know by sight" not in ToolBox().memory_summary()   # no registry: not mentioned


# --- the agent: "this is Mom", later "find Mom" ---


def test_agent_saves_a_look_with_this_is_then_finds_that_person_by_name():
    reg = PeopleRegistry(None)
    built = []

    def find_person(name=None, description=None):
        assert name in reg, "find_person must see the look this_is saved (same registry)"
        built.append((name, description))
        return Quick("find_person", detail=f"found {name}")

    def after_this_is(kw):
        result = last_user(kw)[0]
        assert result["tool_use_id"] == "t1" and "is_error" not in result
        assert result["content"].startswith("Saved what Mom looks like")
        return msg(tool("say", "t2", text="Nice to meet you, Mom!", step=None))

    def after_find(kw):
        result = last_user(kw)[0]
        assert result["tool_use_id"] == "t3" and result["content"] == "find_person: found Mom"
        return msg(text("Found Mom."), stop="end_turn")

    script = [
        msg(tool("this_is", "t1", name="Mom", step=None)),
        after_this_is,
        msg(text("Met Mom."), stop="end_turn"),
        msg(tool("find_person", "t3", name="Mom", description=None, step=None)),
        after_find,
    ]
    runner = SkillRunner(SkillContext(Arbiter()))
    tools = ToolBox(runner, {"find_person": find_person}, registry=reg,
                    perception=lambda: perceive([Walker(0.5, w=0.3, **MOM)]))
    client = FakeClient(script)
    agent = Agent(tools, client=client, ack=False)

    async def scenario():
        await agent.handle(Utterance("senior", "Miguel, this is Mom"))
        await agent.idle()
        await agent.handle(Utterance("guardian", "Can you find Mom?"))
        await agent.idle()

    asyncio.run(scenario())
    assert built == [("Mom", None)]
    assert [e.text for e in agent.events if e.kind == "say"] == ["Nice to meet you, Mom!"]
    assert any(e.kind == "reply" and e.text == "Found Mom." for e in agent.events)
    assert "this_is" in [t["name"] for t in client.calls[0]["tools"]]
    second_request = client.calls[3]["messages"][-2]["content"]   # (the last one sets the effort)
    assert "People you know by sight: Mom." in second_request[-1]["text"]   # the world memory note
