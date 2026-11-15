"""The phone's microphone: a WebSocket the phone page streams audio into (open question T-13).

Mount it with:

    hub_handler = make_mic_handler(CartesiaSTT.from_env(), inbox, wake_word="Miguel")
    app.router.add_get("/mic", hub_handler)
    hub = hub_handler.hub            # MicHub: note_miguel_spoke(), push_to_talk(), status()

Wire protocol (firmware/balance/phone/mic.js):
- The phone opens `/mic?rate=16000` (wss on the HTTPS port) and sends binary frames of raw mono
  s16le PCM at that rate, continuously (zeros while Miguel talks: half-duplex, and Cartesia wants
  an unbroken stream).
- Text frames are JSON: {"type": "voice", "busy": true|false} when Miguel starts or stops talking
  on the phone. Miguel finishing a line opens the conversation window.
- One phone at a time: a new connection closes the previous one.

Each finished turn from Cartesia goes through the wake-word filter and then into the agent's
inbox as Utterance(source="senior", meta={"channel": "mic", ...}). Without STT configured, audio
is accepted and dropped (one log line), so the page works the same either way.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
import time
from collections.abc import Callable, Sequence
from dataclasses import replace
from typing import Any

from aiohttp import WSMsgType, web

from app.brain.types import Source, Utterance
from app.speech.stt import SAMPLE_RATE_RANGE, CartesiaSTT, SttSession

log = logging.getLogger("app.speech.mic")

DEFAULT_RATE = 16000
CONVERSATION_WINDOW_S = 8.0
_LEAD_INS = r"(?:(?:hey|hi|hello|ok|okay|yo|oh|um|so)[\s,.!?]+)*"


class MicHub:
    """Relays phone audio to speech to text and filters what reaches the agent's inbox."""

    def __init__(
        self,
        stt: CartesiaSTT | None,
        inbox: asyncio.Queue[Utterance],
        wake_word: str | None = None,
        *,
        wake_aliases: Sequence[str] = (),
        window_s: float = CONVERSATION_WINDOW_S,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.stt = stt
        self.inbox = inbox
        self.window_s = window_s
        self.clock = clock
        words = [w for w in [wake_word, *wake_aliases] if w and w.strip()]
        self.wake_word = wake_word.strip() if wake_word and wake_word.strip() else None
        self._wake_re: re.Pattern[str] | None = None
        if self.wake_word:
            alt = "|".join(re.escape(" ".join(w.split())) for w in sorted(words, key=len, reverse=True))
            self._wake_re = re.compile(rf"(?<![\w'])(?:{alt})(?![\w'])", re.IGNORECASE)
        self._lead_re = re.compile(rf"^\s*{_LEAD_INS}$", re.IGNORECASE)
        self._window_until = float("-inf")   # no wake word needed before this time
        self.voice_busy = False              # Miguel is talking on the phone (from the page)
        self._ws: web.WebSocketResponse | None = None
        self._warned_no_stt = False
        self.frames = 0
        self.bytes = 0
        self.ignored = 0                     # utterances dropped by the wake-word filter

    # --- conversation state ---------------------------------------------------

    def note_miguel_spoke(self) -> None:
        """Miguel just said something: the senior can answer without the wake word for a while."""
        self._open_window()

    def in_window(self) -> bool:
        return self.voice_busy or self.clock() < self._window_until

    def _open_window(self) -> None:
        self._window_until = self.clock() + self.window_s

    def status(self) -> dict[str, Any]:
        return {
            "stt": self.stt is not None,
            "phone": self._ws is not None and not self._ws.closed,
            "wake_word": self.wake_word,
            "listening_without_wake_word": self.wake_word is None or self.in_window(),
            "frames": self.frames,
            "ignored": self.ignored,
        }

    # --- what reaches the agent -----------------------------------------------

    def filter(self, text: str) -> tuple[str, dict[str, Any]] | None:
        """Apply the wake word. Returns (text for the agent, extra meta) or None to ignore it."""
        clean = " ".join(text.split())
        if not clean:
            return None
        if self._wake_re is None:
            return clean, {}
        m = self._wake_re.search(clean)
        if m is None:
            if self.in_window():
                self._open_window()          # the conversation continues
                return clean, {"addressed": False, "in_window": True}
            return None
        before, after = clean[: m.start()], clean[m.end():]
        if self._lead_re.match(before):      # "Hey Miguel, come here" -> "come here"
            stripped = after
        else:                                # "Come here, Miguel" -> "Come here"
            stripped = (before.rstrip(" ,;:") + " " + after.lstrip(" ,;:")).strip()
        stripped = re.sub(r"^[\s,.!?;:]+", "", stripped)
        stripped = re.sub(r"\s+([,.!?;:])", r"\1", stripped)
        stripped = re.sub(r"[\s,;:]+$", "", stripped)
        self._open_window()
        if not stripped or not re.search(r"\w", stripped):
            # just "Miguel?": pass the call itself so the agent can answer ("Yes?")
            return clean.strip(" ,.!?"), {"addressed": True, "wake_only": True, "in_window": False}
        return stripped, {"addressed": True, "in_window": False}

    async def on_heard(self, u: Utterance) -> None:
        """STT callback: filter a finished turn and put it in the inbox."""
        result = self.filter(u.text)
        if result is None:
            self.ignored += 1
            log.info("mic: ignored (no wake word): %r", u.text[:80])
            return
        text, extra = result
        meta = {**u.meta, **extra, "raw": u.text}
        self.inbox.put_nowait(replace(u, text=text, meta=meta))

    def push_to_talk(self, text: str, source: Source = "operator") -> Utterance | None:
        """The control page's backup: put a typed (or locally transcribed) line in the inbox.

        Skips the wake word and opens the conversation window. Returns the Utterance, or None if
        the text is empty.
        """
        clean = " ".join(str(text).split())
        if not clean:
            return None
        u = Utterance(source=source, text=clean, meta={"channel": "ptt"})
        self._open_window()
        self.inbox.put_nowait(u)
        return u

    # --- the WebSocket --------------------------------------------------------

    async def handle(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(heartbeat=20.0, max_msg_size=1 << 20)
        await ws.prepare(request)
        rate = _rate(request.query.get("rate"))
        if rate is None:
            await ws.close(code=1003, message=b"rate must be a sample rate between 8000 and 48000")
            return ws
        previous, self._ws = self._ws, ws
        if previous is not None and not previous.closed:
            log.info("mic: a new phone connection replaces the old one")
            with contextlib.suppress(Exception):
                await previous.close(code=1000, message=b"replaced")
        peer = request.remote or "?"
        session: SttSession | None = None
        if self.stt is None:
            if not self._warned_no_stt:
                log.info("mic: phone connected from %s but speech to text is off "
                         "(no CARTESIA_API_KEY): audio is dropped", peer)
                self._warned_no_stt = True
        else:
            session = await self.stt.session(self.on_heard, sample_rate=rate)
            log.info("mic: phone connected from %s, %d Hz", peer, rate)
        odd = b""
        try:
            async for msg in ws:
                if msg.type == WSMsgType.BINARY:
                    data = odd + msg.data
                    if len(data) % 2:         # keep 16-bit samples aligned across frames
                        data, odd = data[:-1], data[-1:]
                    else:
                        odd = b""
                    self.frames += 1
                    self.bytes += len(data)
                    if session is not None:
                        session.send_audio(data)
                elif msg.type == WSMsgType.TEXT:
                    self._control(msg.data)
                elif msg.type == WSMsgType.ERROR:
                    log.info("mic: socket error: %s", ws.exception())
        finally:
            if self._ws is ws:
                self._ws = None
                if self.voice_busy:           # the phone went away mid-line
                    self.voice_busy = False
                    self._open_window()
            if session is not None:
                await session.close()
            log.info("mic: phone disconnected (%s)", peer)
        return ws

    def _control(self, raw: str) -> None:
        try:
            msg = json.loads(raw)
        except ValueError:
            return
        if not isinstance(msg, dict):
            return
        if msg.get("type") == "voice":
            busy = bool(msg.get("busy"))
            if busy or self.voice_busy:       # the window runs from when Miguel finishes talking
                self._open_window()
            self.voice_busy = busy


def _rate(raw: str | None) -> int | None:
    if raw is None or raw == "":
        return DEFAULT_RATE
    try:
        rate = int(raw)
    except ValueError:
        return None
    return rate if SAMPLE_RATE_RANGE[0] <= rate <= SAMPLE_RATE_RANGE[1] else None


def make_mic_handler(
    stt: CartesiaSTT | None,
    inbox: asyncio.Queue[Utterance],
    wake_word: str | None = None,
    **hub_kw: Any,
):
    """Return an aiohttp handler for the phone's mic WebSocket (mount at GET /mic).

    The handler's `.hub` is the MicHub (note_miguel_spoke, push_to_talk, status).
    """
    hub = MicHub(stt, inbox, wake_word, **hub_kw)

    async def mic_ws_handler(request: web.Request) -> web.WebSocketResponse:
        return await hub.handle(request)

    mic_ws_handler.hub = hub  # type: ignore[attr-defined]
    return mic_ws_handler


def push_to_talk(inbox: asyncio.Queue[Utterance], text: str, source: Source = "operator") -> Utterance | None:
    """Put a push-to-talk line in `inbox` without a MicHub (no wake word, no window bookkeeping)."""
    clean = " ".join(str(text).split())
    if not clean:
        return None
    u = Utterance(source=source, text=clean, meta={"channel": "ptt"})
    inbox.put_nowait(u)
    return u
