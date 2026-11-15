"""The phone's microphone: a WebSocket the phone page streams audio into (open question T-13).

Mount it with:

    hub_handler = make_mic_handler(CartesiaSTT.from_env(), inbox, wake_word="Miguel")
    app.router.add_get("/mic", hub_handler)
    hub = hub_handler.hub            # MicHub: listening(), set_awaiting(), push_say(), status()

Wire protocol (firmware/balance/phone/mic.js):
- The phone opens `/mic?rate=16000` (wss on the HTTPS port) and sends binary frames of raw mono
  s16le PCM at that rate, continuously (zeros while Miguel talks: half-duplex, and Cartesia wants
  an unbroken stream).
- Phone -> server text frames are JSON:
  - {"type": "voice", "busy": bool, "text"?: str, "id"?: int} when Miguel starts or stops talking,
    and when the next queued line starts (`text` = the line playing, `id` = its /say id if any).
  - {"type": "listen"}: tap-to-talk (the face was tapped): listen for one utterance, no wake word.
  - {"type": "listen_off"}: the face was tapped again while the ring is on: stop listening, and drop
    the turn being heard (it never reaches the agent). Older servers ignore it.
  - {"type": "rtc", "call": str, "sdp"|"candidate": ...} and {"type": "hangup", "call": str}: the
    family video call (#118), handed to app/family.py (`on_call_message`).
- Server -> phone text frames are JSON:
  - {"type": "listen", "on": bool, "why": "wake"|"tap"|"question"|"reply"|null}: Miguel is (not)
    listening for a command: the face shows a glowing ring and pings when it turns on.
  - {"type": "say", "id": int, "text": str}: a line to speak (the same lines as GET /say, pushed
    at once instead of waiting for the page's next poll).
  - {"type": "call", "call": str, "on": bool, "by"?: str}: a family video call started or ended
    (#118); sent again when the phone reconnects mid-call. {"type": "rtc", "call", "sdp"|"candidate"}:
    the family app's WebRTC answer and candidates (app/family.py).
- One phone at a time: a new connection closes the previous one.

During a family video call (#118, `set_call`) Miguel isn't listening at all: no ring, no windows,
and every turn is dropped (the phone also sends zeros), so nothing said on the call reaches the agent.

Turn-taking (Alex, Sat Nov 14): Miguel only takes speech that is meant for him.
- The wake word ("Miguel") anywhere in the sentence. It is spotted in Cartesia's running
  (partial) transcript, so the ring and ping start while the person is still talking.
  "Miguel" alone opens listening for one utterance (like a tap) instead of bothering Claude.
- A second tap while listening closes it (`close_listening`): every open window shuts, the
  agent's wait for a reply stops taking speech, and the turn in progress is dropped.
- Without the wake word, only while listening is open:
  - "reply": the agent is waiting for an answer (wait_for_reply, a check-in question);
  - "question": for `answer_window_s` (default 4 s) after Miguel finishes a line that ends
    with "?" (or one queued as asking, like his introduction: `note_line(asks=True)`, #120);
  - "tap": for `tap_window_s` (default 8 s) after the face is tapped, for one utterance;
  - "wake": the same, after "Miguel" alone.
  A turn that *starts* while listening is open counts even if it ends after the window closed.
- Filler ("uh", "hmm") is always dropped. One- or two-word fragments ("okay", "yeah") count only
  with the wake word or while listening is open (a "yes" answer must still count).
- A short stop phrase ("stop", "wait!") always passes, even without the wake word: stopping is
  instant and never waits for Claude, so a false alarm costs little and a missed one costs a lot.

Each accepted turn goes into the agent's inbox as Utterance(source="senior", meta={"channel":
"mic", "addressed": bool, "via": "wake"|"tap"|"question"|"reply"|"stop"|"open", ...}).
Without STT configured, audio is accepted and dropped (one log line), so the page works the same.

Settings (env, read by make_mic_handler): MIGUEL_ANSWER_WINDOW_S (4), MIGUEL_TAP_LISTEN_S (8).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import re
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from typing import Any

from aiohttp import WSMsgType, web

from app.brain.types import Source, Utterance
from app.speech.stt import SAMPLE_RATE_RANGE, CartesiaSTT, SttSession

log = logging.getLogger("app.speech.mic")

DEFAULT_RATE = 16000
ANSWER_WINDOW_S = 4.0     # no wake word needed this long after Miguel asks a question
SPEECH_DUE_MAX_S = 8.0   # longest wait for a queued line to start playing before listening anyway
TAP_LISTEN_S = 8.0        # listening for one utterance after a tap (or "Miguel" alone)
SHORT_WORDS = 2           # fragments this short need the wake word or an open ear
FILLER = {"uh", "uhh", "um", "umm", "uhm", "hmm", "hm", "hmmm", "mm", "mmm", "mhm", "er", "erm",
          "ah", "ahh", "eh", "huh", "oh", "ooh"}
_LEAD_INS = r"(?:(?:hey|hi|hello|ok|okay|yo|oh|um|so)[\s,.!?]+)*"
_OPEN_VIAS = ("reply", "question", "tap", "wake")


def _env_float(env: Mapping[str, str], name: str, default: float) -> float:
    raw = (env.get(name) or "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        log.warning("%s=%r is not a number: using %g", name, raw, default)
        return default
    return max(0.0, value)


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", text.lower())


def _is_question(line: str | None) -> bool:
    return bool(line) and line.rstrip(" \"'”’)").endswith("?")


def _is_stop(text: str) -> bool:
    from app.brain.agent import stop_requested   # lazy: the brain imports the SDK

    return len(_words(text)) <= 4 and stop_requested(text)


class MicHub:
    """Relays phone audio to speech to text, decides what reaches the agent's inbox, and tells the
    phone when Miguel is listening."""

    def __init__(
        self,
        stt: CartesiaSTT | None,
        inbox: asyncio.Queue[Utterance],
        wake_word: str | None = None,
        *,
        wake_aliases: Sequence[str] = (),
        answer_window_s: float = ANSWER_WINDOW_S,
        tap_window_s: float = TAP_LISTEN_S,
        stop_without_wake: bool = True,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.stt = stt
        self.inbox = inbox
        self.answer_window_s = answer_window_s
        self.tap_window_s = tap_window_s
        self.stop_without_wake = stop_without_wake
        self.clock = clock
        words = [w for w in [wake_word, *wake_aliases] if w and w.strip()]
        self.wake_word = wake_word.strip() if wake_word and wake_word.strip() else None
        self._wake_re: re.Pattern[str] | None = None
        if self.wake_word:
            alt = "|".join(re.escape(" ".join(w.split())) for w in sorted(words, key=len, reverse=True))
            self._wake_re = re.compile(rf"(?<![\w'])(?:{alt})(?![\w'])", re.IGNORECASE)
        self._lead_re = re.compile(rf"^\s*{_LEAD_INS}$", re.IGNORECASE)
        self._question_until = float("-inf")   # Miguel asked something: answers need no wake word
        self._once_until = float("-inf")       # a tap (or "Miguel" alone): one utterance, no wake word
        self._once_why = "tap"
        self.awaiting = False                  # the agent waits for an answer (wait_for_reply)
        self.voice_busy = False                # Miguel is talking on the phone (from the page)
        self.voice_text: str | None = None     # the line he is saying, or said last
        self._queued_text: str | None = None   # the last line queued for the phone (fallback)
        self._asking_text: str | None = None   # that line asks though it doesn't end in "?" (#120)
        self._speech_due_until = float("-inf")  # a line is queued but not playing yet: not listening
        self._turn: dict[str, Any] | None = None     # the turn being transcribed: {opened, wake}
        self._ending: dict[str, Any] | None = None   # the turn that just ended (for on_heard)
        self._ws: web.WebSocketResponse | None = None
        self._out: asyncio.Queue[dict[str, Any]] | None = None
        self._listen_sent: tuple[bool, str | None] | None = None
        self._warned_no_stt = False
        self.on_voice: Callable[[bool, str | None, int | None], None] | None = None   # timing hook (api)
        self.call: dict[str, Any] | None = None      # a family video call is on (#118): not hearing
        self.on_call_message: Callable[[dict[str, Any]], None] | None = None   # the call's messages (family)
        self.frames = 0
        self.bytes = 0
        self.ignored = 0                     # utterances dropped by the filter

    # --- listening state --------------------------------------------------------

    def open_reason(self) -> str | None:
        """Why Miguel takes speech without the wake word right now, or None."""
        if self.call is not None:
            return None                      # on a family video call: what's said is for the family
        if self.voice_busy or self.clock() < self._speech_due_until:
            return None                      # he is talking (mic muted), or about to: his line is on its way
        if self.awaiting:
            return "reply"
        now = self.clock()
        if now < self._question_until:
            return "question"
        if now < self._once_until:
            return self._once_why
        return None

    def listen_reason(self) -> str | None:
        if self.call is not None:
            return None
        if self._turn is not None and self._turn["wake"] and not self.voice_busy:
            return "wake"                    # the name was heard in this turn: listening to the rest
        return self.open_reason()

    def listening(self) -> bool:
        """Miguel is listening for a command: the face shows the ring. The one source of truth for
        the phone, /ws `status.listening` and the family app's "listening" mode."""
        return self.listen_reason() is not None

    def in_window(self) -> bool:
        """Old name for listening() (app/family.py used it)."""
        return self.listening()

    def set_awaiting(self, on: bool) -> None:
        """The agent started (True) or stopped (False) waiting for the senior's answer."""
        self.awaiting = bool(on)
        self._sync()

    def open_once(self, why: str = "tap", seconds: float | None = None) -> None:
        """Listen for one utterance without the wake word (tap-to-talk, or "Miguel" alone)."""
        self._once_until = self.clock() + (self.tap_window_s if seconds is None else seconds)
        self._once_why = why
        self._sync()

    def close_listening(self) -> None:
        """Stop listening now (a second tap on the face while the ring is on). Every open window
        closes, the agent's wait for an answer stops taking speech without the wake word, and the
        turn being heard (or just ended and still being transcribed) is dropped: it never reaches
        the agent."""
        self._question_until = self._once_until = float("-inf")
        self.awaiting = False
        for turn in (self._turn, self._ending):
            if turn is not None:
                turn["cancelled"] = True
                turn["wake"] = False
        self._sync()

    def set_call(self, msg: dict[str, Any] | None) -> None:
        """A family video call started (msg = {"type": "call", "call": id, "on": True, "by": name}) or
        ended (None). While it's on Miguel hears nothing: listening closes, no window opens, every
        turn is dropped. The phone gets the message first (so it mutes before the ring goes off and
        stays quiet: no chime), then the listening state."""
        if msg is not None:
            self.call = dict(msg)
            self.send(self.call)
            self.close_listening()
        elif self.call is not None:
            ended, self.call = self.call, None
            self.send({"type": "call", "call": ended.get("call"), "on": False})
            self._sync()

    def note_line(self, text: str, asks: bool = False) -> None:
        """A line was queued for the phone (fallback for which line he said last). Until the phone says it
        started playing (or SPEECH_DUE_MAX_S passes), he isn't listening: the ring used to light ~2 s
        before his voice, while Cartesia made the audio (Sat night check-in test).
        asks: the line asks something though it doesn't end in "?" (his introduction, #120, ends with
        'Just say "Miguel" first.'): it opens the answer window like a question."""
        self._queued_text = " ".join(str(text).split()) or None
        self._asking_text = self._queued_text if asks else None
        if self._ws is not None:             # only when a phone is there to play it
            self._speech_due_until = self.clock() + SPEECH_DUE_MAX_S
        self._sync()

    def note_miguel_spoke(self, text: str | None = None) -> None:
        """Called after each `say` (app/__main__.py). The answer window now opens when the phone
        reports that the line finished, and only after a question, so this only notes the line."""
        if text:
            self.note_line(text)

    def _voice(self, busy: bool, text: str | None = None, sid: int | None = None) -> None:
        if text:
            self.voice_text = " ".join(str(text).split())
        if busy or self.voice_busy:          # the line started (or ended): no longer waiting for it
            self._speech_due_until = float("-inf")
        if busy and not self.voice_busy:     # he starts talking: earlier windows are over
            self._question_until = self._once_until = float("-inf")
        if not busy and self.voice_busy:     # he finished: a question opens the answer window
            line = self.voice_text or self._queued_text
            if _is_question(line) or (line is not None and line == self._asking_text):
                self._question_until = self.clock() + self.answer_window_s
        self.voice_busy = busy
        if self.on_voice is not None:
            try:
                self.on_voice(busy, self.voice_text, sid)
            except Exception:  # noqa: BLE001 - a broken hook must not break the mic
                log.exception("mic: on_voice hook failed")
        self._sync()

    def status(self) -> dict[str, Any]:
        return {
            "stt": self.stt is not None,
            "phone": self._ws is not None and not self._ws.closed,
            "wake_word": self.wake_word,
            "listening": self.listening(),
            "listening_why": self.listen_reason(),
            "listening_without_wake_word": self.wake_word is None or self.open_reason() is not None,
            "frames": self.frames,
            "ignored": self.ignored,
            "call": self.call is not None,
        }

    # --- the turn in progress (Cartesia's partial transcripts) ------------------

    def on_stt_event(self, kind: str, text: str) -> None:
        if kind == "start":
            self._turn = {"opened": self.open_reason(), "wake": False}
        elif kind in ("update", "eager_end"):
            if self._turn is None:
                self._turn = {"opened": self.open_reason(), "wake": False}
            if (not self._turn["wake"] and not self._turn.get("cancelled")
                    and self._wake_re is not None and self._wake_re.search(text)):
                self._turn["wake"] = True
                log.info("mic: heard the wake word while they talk: %r", text[:80])
        elif kind == "end":                  # an empty end (nothing said, or a dropped socket) delivers nothing
            self._ending, self._turn = (self._turn if text else None), None
        self._sync()

    # --- what reaches the agent -------------------------------------------------

    def filter(self, text: str, opened: str | None = None) -> tuple[str, dict[str, Any]] | None:
        """Apply the turn-taking rules. Returns (text for the agent, extra meta) or None to drop it.

        opened: why listening was open when the turn started (else: right now)."""
        clean = " ".join(text.split())
        if not clean:
            return None
        why = opened or self.open_reason()
        m = self._wake_re.search(clean) if self._wake_re is not None else None
        if m is not None:
            before, after = clean[: m.start()], clean[m.end():]
            if self._lead_re.match(before):      # "Hey Miguel, come here" -> "come here"
                stripped = after
            else:                                # "Come here, Miguel" -> "Come here"
                stripped = (before.rstrip(" ,;:") + " " + after.lstrip(" ,;:")).strip()
            stripped = re.sub(r"^[\s,.!?;:]+", "", stripped)
            stripped = re.sub(r"\s+([,.!?;:])", r"\1", stripped)
            stripped = re.sub(r"[\s,;:]+$", "", stripped)
            rest = _words(stripped)
            if not rest or all(w in FILLER for w in rest):
                self.open_once("wake")           # "Miguel?": ping, then listen for the request
                self._reject(clean, "the wake word alone: listening for the request")
                return None
            self._consume(why)
            return stripped, {"addressed": True, "via": "wake"}
        words = _words(clean)
        if not words or all(w in FILLER for w in words):
            self._reject(clean, "filler")
            return None
        if self._wake_re is None:
            via = why or "open"
        elif why is not None:
            via = why
        elif self.stop_without_wake and _is_stop(clean):
            return clean, {"addressed": False, "via": "stop"}
        else:
            self._reject(clean, "no wake word")
            return None
        if len(words) <= SHORT_WORDS and via not in _OPEN_VIAS and not _is_stop(clean):
            self._reject(clean, "too short")
            return None
        self._consume(via)
        return clean, {"addressed": via in ("tap", "wake"), "via": via}

    def _consume(self, via: str | None) -> None:
        """An utterance was taken: the window it used is spent (Miguel answers next)."""
        if via in ("question", "tap", "wake"):
            self._question_until = self._once_until = float("-inf")

    def _reject(self, text: str, why: str) -> None:
        self.ignored += 1
        log.info("mic: ignored (%s): %r", why, text[:80])

    async def on_heard(self, u: Utterance) -> None:
        """STT callback: filter a finished turn and put it in the inbox."""
        turn, self._ending = self._ending, None
        if self.call is not None:
            self._reject(u.text, "on a family video call")
            return
        if turn is not None and turn.get("cancelled"):
            self._reject(u.text, "tapped off while they talked")
            self._sync()
            return
        result = self.filter(u.text, opened=turn["opened"] if turn else None)
        self._sync()
        if result is None:
            return
        text, extra = result
        meta = {**u.meta, **extra, "raw": u.text}
        self.inbox.put_nowait(replace(u, text=text, meta=meta))

    def push_to_talk(self, text: str, source: Source = "operator") -> Utterance | None:
        """The control page's backup: put a typed (or locally transcribed) line in the inbox.

        Skips the wake word. Returns the Utterance, or None if the text is empty.
        """
        clean = " ".join(str(text).split())
        if not clean:
            return None
        u = Utterance(source=source, text=clean, meta={"channel": "ptt"})
        self.inbox.put_nowait(u)
        return u

    # --- to the phone -----------------------------------------------------------

    def send(self, msg: dict[str, Any]) -> bool:
        """Queue a JSON message for the phone (in order). False if no phone is connected."""
        if self._out is None or self._ws is None or self._ws.closed:
            return False
        self._out.put_nowait(msg)
        return True

    def push_say(self, sid: int, text: str) -> bool:
        """Send a line to speak right away (the page also polls GET /say; it skips ids it has)."""
        return self.send({"type": "say", "id": sid, "text": text})

    def _sync(self) -> None:
        """Tell the phone when listening turns on or off (it pings and shows the ring)."""
        why = self.listen_reason()
        state = (why is not None, why)
        if state == self._listen_sent:
            return
        was_on = self._listen_sent is not None and self._listen_sent[0]
        self._listen_sent = state
        if state[0] != was_on:
            log.info("mic: listening %s", f"ON ({why})" if why else "off")
        self.send({"type": "listen", "on": state[0], "why": why})

    # --- the WebSocket ----------------------------------------------------------

    async def handle(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(heartbeat=20.0, max_msg_size=1 << 20)
        await ws.prepare(request)
        rate = _rate(request.query.get("rate"))
        if rate is None:
            await ws.close(code=1003, message=b"rate must be a sample rate between 8000 and 48000")
            return ws
        previous, self._ws = self._ws, ws
        out: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._out = out
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
            session = await self.stt.session(self.on_heard, sample_rate=rate, on_event=self.on_stt_event)
            log.info("mic: phone connected from %s, %d Hz", peer, rate)
        self._listen_sent = (False, None)     # a new page starts with the ring off
        if self.call is not None:             # reconnected mid-call: the page shows the call again
            out.put_nowait(self.call)
        self._sync()                          # ...so it hears only if Miguel is listening now
        sender = asyncio.ensure_future(self._send_loop(ws, out))
        ticker = asyncio.ensure_future(self._tick(ws))
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
            for task in (sender, ticker):
                task.cancel()
            if self._ws is ws:
                self._ws = None
                self._out = None
                if self.voice_busy:           # the phone went away mid-line
                    self._voice(False)
            if session is not None:
                await session.close()
            log.info("mic: phone disconnected (%s)", peer)
        return ws

    async def _send_loop(self, ws: web.WebSocketResponse, out: asyncio.Queue[dict[str, Any]]) -> None:
        while not ws.closed:
            msg = await out.get()
            try:
                await ws.send_json(msg)
            except Exception as e:  # noqa: BLE001 - the socket is closing; the reader cleans up
                log.info("mic: could not send to the phone: %s", e)
                return

    async def _tick(self, ws: web.WebSocketResponse) -> None:
        """Windows close by time: check about 10 times a second."""
        while not ws.closed:
            await asyncio.sleep(0.1)
            self._sync()

    def _control(self, raw: str) -> None:
        try:
            msg = json.loads(raw)
        except ValueError:
            return
        if not isinstance(msg, dict):
            return
        kind = msg.get("type")
        if kind == "voice":
            text = msg.get("text")
            sid = msg.get("id")
            self._voice(bool(msg.get("busy")), text if isinstance(text, str) else None,
                        sid if isinstance(sid, int) and not isinstance(sid, bool) else None)
        elif kind == "listen":                # tap-to-talk
            log.info("mic: tap-to-talk")
            self.open_once("tap")
        elif kind == "listen_off":            # tapped again while listening: stop
            log.info("mic: tapped off: not listening")
            self.close_listening()
        elif kind in ("rtc", "hangup") and self.on_call_message is not None:   # the family video call
            try:
                self.on_call_message(msg)
            except Exception:  # noqa: BLE001 - a bad call message must not drop the mic
                log.exception("mic: call message failed")


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
    env: Mapping[str, str] = os.environ,
    **hub_kw: Any,
):
    """Return an aiohttp handler for the phone's mic WebSocket (mount at GET /mic).

    The handler's `.hub` is the MicHub. The answer window and the tap window come from
    MIGUEL_ANSWER_WINDOW_S and MIGUEL_TAP_LISTEN_S unless given.
    """
    hub_kw.setdefault("answer_window_s", _env_float(env, "MIGUEL_ANSWER_WINDOW_S", ANSWER_WINDOW_S))
    hub_kw.setdefault("tap_window_s", _env_float(env, "MIGUEL_TAP_LISTEN_S", TAP_LISTEN_S))
    hub = MicHub(stt, inbox, wake_word, **hub_kw)

    async def mic_ws_handler(request: web.Request) -> web.WebSocketResponse:
        return await hub.handle(request)

    mic_ws_handler.hub = hub  # type: ignore[attr-defined]
    return mic_ws_handler


def push_to_talk(inbox: asyncio.Queue[Utterance], text: str, source: Source = "operator") -> Utterance | None:
    """Put a push-to-talk line in `inbox` without a MicHub (no wake word)."""
    clean = " ".join(str(text).split())
    if not clean:
        return None
    u = Utterance(source=source, text=clean, meta={"channel": "ptt"})
    inbox.put_nowait(u)
    return u
