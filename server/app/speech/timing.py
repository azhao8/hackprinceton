"""One log line per spoken turn: how long from the end of someone's speech to Miguel's voice.

    turn timing (ms after the end of speech): transcript 410 | Claude asked 415 | first text 1230 |
    say 1240 | audio asked 1262 | audio first byte 1610 | playback 1700 | "Sure, here I come."

The stages come from four places, all on the server's monotonic clock:
- speech to text (app/speech/stt.py): `t_speech_end` (the transcript last grew; our best guess at
  when they stopped talking, Cartesia sends no timestamps) and `t_final` (turn.end arrived);
- the agent (app/brain/agent.py): `llm_start`, `first_text`, `say` in the first say's data.timing;
- the API's /tts route: `tts_request`, `tts_first_byte`;
- the phone, over /mic: `playback` (the line started playing; {"type": "voice", "busy": true, "id"}).
A turn the phone never reports playing is logged anyway after `log_after_s`, or when the next starts.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from typing import Any

log = logging.getLogger("app.speech.timing")

STAGES = (
    ("t_final", "transcript"),
    ("llm_start", "Claude asked"),
    ("first_text", "first text"),
    ("say", "say"),
    ("tts_request", "audio asked"),
    ("tts_first_byte", "audio first byte"),
    ("playback", "playback"),
)


def _norm(text: str | None) -> str:
    return " ".join(str(text or "").split())


class TurnTimer:
    def __init__(self, clock: Callable[[], float] = time.monotonic, log_after_s: float = 20.0) -> None:
        self.clock = clock
        self.log_after_s = log_after_s
        self._turn: dict[str, Any] | None = None
        self.last: dict[str, Any] | None = None   # the last logged turn: {"text", "ms": {stage: ms}}

    def start(self, timing: dict[str, Any], text: str) -> None:
        """The agent's first line of a turn (its say event's data.timing)."""
        self.flush()
        turn = {"marks": {k: v for k, v in timing.items() if isinstance(v, (int, float))},
                "text": _norm(text), "id": None}
        self._turn = turn
        try:
            asyncio.get_running_loop().call_later(self.log_after_s, self._expire, turn)
        except RuntimeError:
            pass

    def said(self, sid: int, text: str) -> None:
        """The line went into the phone's say queue with this id."""
        if self._turn is not None and self._turn["id"] is None and _norm(text) == self._turn["text"]:
            self._turn["id"] = sid

    def narrow(self, full: str, first: str) -> None:
        """The turn's first line goes to the phone in pieces (sentences): follow the first piece."""
        if self._turn is not None and self._turn["id"] is None and _norm(full) == self._turn["text"]:
            self._turn["text"] = _norm(first)

    def mark(self, stage: str, text: str | None = None) -> None:
        """A stage of the current turn's first line (once; `text` must be that line if given)."""
        t = self._turn
        if t is not None and stage not in t["marks"] and (text is None or _norm(text) == t["text"]):
            t["marks"][stage] = self.clock()

    def playback(self, sid: int | None, text: str | None) -> None:
        """The phone started playing a line: if it is the turn's first line, log the turn."""
        t = self._turn
        if t is None:
            return
        if (sid is not None and sid == t["id"]) or (sid is None and _norm(text) == t["text"]):
            self.mark("playback")
            self.flush()

    def _expire(self, turn: dict[str, Any]) -> None:
        if self._turn is turn:
            self.flush()

    def flush(self) -> None:
        t, self._turn = self._turn, None
        if t is None:
            return
        marks = t["marks"]
        zero = next((marks[k] for k in ("t_speech_end", "t_final", "heard") if k in marks), None)
        if zero is None:
            return
        ms = {name: round(1000 * (marks[key] - zero)) for key, name in STAGES if key in marks}
        self.last = {"text": t["text"], "ms": ms}
        origin = "the end of speech" if "t_speech_end" in marks else "the message"
        parts = " | ".join(f"{name} {v}" for name, v in ms.items())
        log.info('turn timing (ms after %s): %s | "%s"', origin, parts, t["text"][:60])
