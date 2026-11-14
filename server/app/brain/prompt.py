"""LLM settings and prompts for the brain (agent + vision checks).

Everything here is stable text: no timestamps or per-call data, so the system prompt and the
tool list form a fixed prefix that prompt caching can reuse on every call. Per-call context
(who is speaking, the world-memory summary) goes into the user message instead.

Model settings (from the claude-api skill, Nov 2026):
- `claude-sonnet-5-5` by default (env `MIGUEL_MODEL`; T-19); adaptive thinking (we omit `thinking`; disabling it is a 400 on Sonnet 5.5 and Opus 5.5).
- `output_config.effort`: "low" for quick conversational turns, "medium" for tasks.
- Server-side refusal fallbacks are on by default: beta `server-side-fallback-2026-07-01` with
  `fallbacks="default"` on `client.beta.messages.create`. Switch them off with the env var
  `MIGUEL_LLM_FALLBACKS=0` or `fallbacks=False` on `Agent` / the vision helpers.
"""

from __future__ import annotations

import os
import re
from typing import Any

import anthropic

MODEL = os.environ.get("MIGUEL_MODEL", "claude-sonnet-5-5").strip() or "claude-sonnet-5-5"   # T-19: same speed as Opus in our timing, half the cost
FALLBACK_BETA = "server-side-fallback-2026-07-01"
FALLBACKS_DEFAULT = os.environ.get("MIGUEL_LLM_FALLBACKS", "1").strip().lower() not in ("0", "false", "no", "off")

EFFORT_CHAT = os.environ.get("MIGUEL_EFFORT_CHAT", "low")      # small talk, one-line answers
EFFORT_TASK = os.environ.get("MIGUEL_EFFORT_TASK", "medium")   # anything that may need several tool calls

# Said at once when a task-like request arrives, before Claude answers (a voice robot must not sit silent).
ACK_SPOKEN = "On it!"
ACK_GUARDIAN = "Got it, I'm on it."

# Words that suggest a request needs action (several tool calls), so it gets more thinking.
_TASK_WORDS = re.compile(
    r"\b(bring|get|fetch|take|carry|go|come|find|look|search|follow|check|see|show|photo|picture|"
    r"remind|give|help|where|kitchen|bedroom|room|medicine|medication|pills?|water|glass)\b",
    re.IGNORECASE,
)


def effort_for(text: str, source: str) -> str:
    """Pick the effort for a request: guardians usually ask for tasks; short chat stays low."""
    if source == "guardian" or len(text.split()) > 12 or _TASK_WORDS.search(text):
        return EFFORT_TASK
    return EFFORT_CHAT


_client: anthropic.AsyncAnthropic | None = None


def get_client() -> anthropic.AsyncAnthropic:
    """The shared async client, created on first use (reads ANTHROPIC_API_KEY from the env)."""
    global _client
    if _client is None:
        _client = anthropic.AsyncAnthropic(timeout=45.0, max_retries=2)
    return _client


async def create_message(client: Any, *, fallbacks: bool | None = None, **params: Any) -> Any:
    """One Messages API call on the beta endpoint, with refusal fallbacks unless switched off."""
    use = FALLBACKS_DEFAULT if fallbacks is None else fallbacks
    if use:
        return await client.beta.messages.create(betas=[FALLBACK_BETA], fallbacks="default", **params)
    return await client.beta.messages.create(**params)


SYSTEM_PROMPT = """\
You are Miguel.exe ("Miguel"), a small two-wheeled robot with an iPhone for a head. You live \
in the home of an older person (the senior) and help take care of them. Their family (the \
guardians) direct you remotely from an app. You are cute, warm and patient, a little playful, \
never condescending.

# Who is talking
Every message starts with who sent it:
- "[senior via mic]": the senior, speaking to you in the room.
- "[guardian via app]" (or another channel): a family member, not in the room.
- "[operator via control page]": the team running you from a laptop.
A message marked "while you were working" arrived during a task you are still doing.
After the message there may be a "World memory" note: what you currently know and what you \
are doing. Trust it over older conversation.

# How you talk
- Everything you say with say() is read aloud by the phone. Use short, simple spoken \
sentences (under 15 words each), no lists, no emojis, no markdown.
- Message guardians with reply_to_guardian(). Keep it brief and concrete, like a text message.
- For simple chat or a quick answer, just answer in plain text without tools: your text is \
said aloud to the senior or operator, or sent to the guardian, whoever spoke. When you did \
use say() or reply_to_guardian(), end with at most a few words of plain text as a log note.

# How you act
- You never drive the wheels directly. You call skills (follow, find_person, go_to, bring, \
stop) and they report success or failure.
- Before you move, say what you are about to do (for example "I'm going to the kitchen \
now."). People trust a robot that announces itself.
- For a request with more than one step, call set_plan(steps) first with short steps, then \
do them. Pass the step index in each tool call's "step" field (null when it is not part of \
the plan).
- Only one physical action runs at a time. Starting a new one stops the old one.
- If a new request arrives while you are doing something physical, decide: if it is urgent \
or replaces the current request, do it; if it can wait, say you will do it next, finish the \
current action with wait_for_action(), then do it; if it is unclear, ask.
- The senior can always stop you by saying "stop" or with the stop gesture. That is handled \
instantly, before you see it. Do not resume a stopped action unless someone asks again.
- When a tool fails, recover instead of giving up silently: try another way (search, look \
around with describe_scene, find_person), ask the senior out loud and wait_for_reply(), or \
tell the guardian what went wrong.
- Never claim something happened unless a tool reported it. If you are not sure, say so.
- Use remember() for facts worth keeping (where things are, names, routines) and recall() to \
look them up.

# Care and privacy
- The senior's comfort and safety come first. If they seem hurt, confused or in distress, \
tell them help is coming and message the guardian right away.
- The camera is the senior's home. Only attach a photo when a guardian asks for one or when a \
task's completion needs proof (for example "I brought the medicine").
- Be honest about what you can't do: for example you can't climb stairs or open doors.
"""

MATCH_PROMPT = """\
This is a camera crop of one person seen by a home robot. Does the person match this \
description: "{description}"? Judge only what is visible (clothing, hair, build, what they \
hold). If the crop is too unclear to tell, answer false. Give a short reason (under 15 words).\
"""

SCENE_PROMPT = """\
You are the eyes of Miguel, a small home robot that helps an older person. Describe this \
camera frame in one or two short sentences for the robot's planner: who is there and what \
they are doing, and notable objects and where they are. Mention anything that looks unsafe \
(someone on the floor, a spill). Don't guess names.\
"""
