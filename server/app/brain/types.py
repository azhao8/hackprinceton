"""Shared types for the agent (brain), hearing (speech) and the guardian channel (API).

The agent reads Utterances from one inbox (asyncio.Queue) and publishes AgentEvents. The senior
talks through Miguel's mic (speech-to-text puts Utterance(source="senior") in the inbox); the
guardian talks through the app or the API (Utterance(source="guardian")).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Literal

Source = Literal["senior", "guardian", "operator"]   # operator = the control page on the laptop

EventKind = Literal[
    "heard",      # an utterance was received (echo, for the app/control page transcript)
    "say",        # Miguel says this out loud (TTS on the robot's phone)
    "reply",      # a message to the guardian (text, optional audio_url / photo_url in data)
    "plan",       # the agent's current plan: data = {"steps": [str, ...]}
    "step",       # a plan step changed: data = {"index": int, "status": "running"|"done"|"failed", "detail": str}
    "task",       # task lifecycle: data = {"id": str, "status": "started"|"done"|"failed"|"cancelled", "summary": str}
    "error",      # something went wrong (shown on the control page, short text)
    "check_in",   # the senior answered a check-in request: data = {"answer": "yes"|"no"|"no_answer"}
    "place",      # a place was learned or changed: data = {"name": str, "marker": int|None}
]


@dataclass(frozen=True)
class Utterance:
    source: Source
    text: str
    t: float = field(default_factory=time.monotonic)
    meta: dict[str, Any] = field(default_factory=dict)   # e.g. {"channel": "app"|"imessage"|"mic", "confidence": 0.9}


@dataclass(frozen=True)
class AgentEvent:
    id: int                  # increasing; clients poll/stream "after id"
    kind: EventKind
    text: str = ""
    to: Source | None = None   # who it's for ("guardian" for replies, "senior" for say), None = everyone
    data: dict[str, Any] = field(default_factory=dict)
    t: float = field(default_factory=time.monotonic)

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "kind": self.kind, "text": self.text, "to": self.to, "data": self.data}
