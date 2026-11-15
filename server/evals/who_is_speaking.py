"""Real-API check: does the agent name the person the camera sees, or whoever it talked with before?

A scripted conversation against the real Claude API with a fake camera (no robot, no vision):
Alex introduces himself ("this is Alex", saved with a faked this_is) and chats, then a different
person is in view (Sarah, someone unrecognized, or nobody) and asks "who am I?" / "what's my name?"
/ "remind me of my appointment". A case fails when the answer treats the speaker as Alex (says or
guesses the name, or reads out Alex's appointment) or, with Sarah in view, doesn't use Sarah's name.

    cd server && uv run --env-file .env python -m evals.who_is_speaking [reps]

About 2 + 5 * reps API calls (the setup runs once; each case starts from a copy of its history).
"""

from __future__ import annotations

import asyncio
import copy
import re
import sys

from app.brain.agent import Agent
from app.brain.tools import ToolBox, ToolOutcome
from app.brain.types import Utterance

UNKNOWN = "someone I don't recognize (center, near)"


class FakeRegistry:
    def __init__(self) -> None:
        self.saved: list[str] = ["Sarah"]   # Sarah was saved on an earlier day

    def names(self) -> list[str]:
        return list(self.saved)


class FakeCameraTools(ToolBox):
    """A ToolBox whose camera sees whatever the script says; this_is always succeeds."""

    def __init__(self) -> None:
        super().__init__(registry=FakeRegistry())
        self.seeing: list[tuple[str, str]] | str = "nobody"   # [(name or "", "center, near")] or "nobody"

    def this_is(self, name: str) -> ToolOutcome:
        self.registry.saved.append(name)
        return ToolOutcome(True, f"Saved what {name} looks like (shirt and trousers). find_person can find "
                                 f"{name} now, until they change clothes.")

    def people_in_view(self, *a, **kw) -> str | None:   # the note before the fix (#78)
        if self.seeing == "nobody":
            return "nobody"
        return "; ".join(f"{n or 'someone I don\'t recognize'} ({where})" for n, where in self.seeing)

    def camera_view(self, *a, **kw):   # the structured view after the fix (#113)
        from app.brain.tools import CameraView, Seen
        if self.seeing == "nobody":
            return CameraView()
        return CameraView(people=tuple(Seen(n or None, *where.split(", ")) for n, where in self.seeing))


def make_agent(tools: FakeCameraTools) -> Agent:
    agent = Agent(tools, ack=False, keepalive_s=0)

    async def no_reply(seconds: float):   # a question asked out loud gets no answer in this script
        return None

    agent.wait_for_senior = no_reply   # type: ignore[method-assign]
    return agent


async def turn(agent: Agent, tools: FakeCameraTools, seeing, words: str) -> str:
    tools.seeing = seeing
    before = len(agent.events)
    await agent.handle(Utterance("senior", words))
    await agent.idle()
    return " ".join(e.text for e in agent.events[before:] if e.kind == "say")


ALEX_AS_SPEAKER = r"\b(you're|you are|hi|hello|thanks|okay|sure),? alex\b|\balex\?|is that you|are you alex"
READS_ALEX_NOTE = r"dentist|tuesday|3 ?pm"

CASES = [
    # (name, camera, words, wrong(answer) -> bool): wrong = treats the speaker as Alex (names or
    # guesses Alex, or reads out Alex's appointment); with Sarah in view, also not using her name
    ("sarah: who am I", [("Sarah", "center, near")], "Miguel, who am I?",
     lambda a: "alex" in a.lower() or "sarah" not in a.lower()),
    ("sarah: my appointment", [("Sarah", "center, near")], "Miguel, remind me of my appointment.",
     lambda a: bool(re.search(f"{ALEX_AS_SPEAKER}|{READS_ALEX_NOTE}", a, re.I)) or "sarah" not in a.lower()),
    ("stranger: what's my name", [("", "center, near")], "Miguel, what's my name?",
     lambda a: "alex" in a.lower()),
    ("stranger: my appointment", [("", "center, near")], "Miguel, remind me of my appointment.",
     lambda a: bool(re.search(f"alex|{READS_ALEX_NOTE}", a, re.I))),
    ("nobody: who am I", "nobody", "Miguel, who am I?",
     lambda a: "alex" in a.lower()),
]


async def main(reps: int) -> None:
    tools = FakeCameraTools()
    setup = make_agent(tools)
    print("setup 1:", await turn(setup, tools, [("", "center, near")], "Miguel, this is Alex."))
    tools.memory["Alex's dentist appointment"] = "Tuesday at 3 pm"
    print("setup 2:", await turn(setup, tools, [("Alex", "center, near")],
                                 "Miguel, thanks. How are you doing today?"))
    wrong = total = 0
    for name, seeing, words, is_wrong in CASES:
        for _ in range(reps):
            t = FakeCameraTools()
            t.registry.saved = list(tools.registry.saved)
            t.memory = dict(tools.memory)
            agent = make_agent(t)
            for attr in ("_history", "_talked_with"):   # the conversation so far
                if hasattr(setup, attr):
                    setattr(agent, attr, copy.deepcopy(getattr(setup, attr)))
            answer = await turn(agent, t, seeing, words)
            bad = is_wrong(answer)
            wrong += bad
            total += 1
            print(f"{'WRONG' if bad else 'ok   '} {name:26} {answer!r}")
    print(f"\nwrong person: {wrong} of {total}")


if __name__ == "__main__":
    asyncio.run(main(int(sys.argv[1]) if len(sys.argv) > 1 else 3))
