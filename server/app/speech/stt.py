"""Cartesia speech to text (Ink 2): Miguel's ears.

`CartesiaSTT.session()` opens one realtime WebSocket to Cartesia's turn-detecting endpoint
(`/stt/turns/websocket`): the caller pushes raw 16 kHz mono s16le audio with `send_audio()`, and
every finished turn (`turn.end`) comes back as `Utterance(source="senior", text, meta)`, to a
callback or to `SttSession.utterances` (an asyncio.Queue).

Protocol (docs.cartesia.ai, checked Sat Nov 14; see api-reference/stt/turns/websocket.md):
- URL wss://api.cartesia.ai/stt/turns/websocket?model=ink-2&encoding=pcm_s16le&sample_rate=16000
  &cartesia_version=2026-08-14[&keyterm=Miguel ...]. The version is a required query parameter.
- Auth: `X-API-Key` header for servers (get-started/authenticate-your-client-applications.md says
  `Authorization: Bearer` works too). Browsers would need a short-lived `access_token`, which is
  why the phone streams to our server instead of to Cartesia.
- Client sends binary audio (raw PCM, no header, about 100 ms per chunk, paced in real time) and
  `{"type": "close"}` to flush and end. The stream must stay continuous: send zeros when muted.
- Server sends JSON events, all with `type` and `request_id`: connected, turn.start, turn.update,
  turn.eager_end, turn.resume, turn.end (`transcript` = the turn's final text), error
  (`status_code`, `title`, `message`). There is no confidence or word list in these events.

Reconnects with backoff when the socket drops (a turn in progress is lost). It only (re)connects
while audio is arriving, so an idle phone costs no Cartesia session.

Configure with `CartesiaSTT.from_env()`: CARTESIA_API_KEY (required, shared with TTS),
CARTESIA_STT_MODEL (default ink-2), CARTESIA_STT_KEYTERMS (comma-separated, default "Miguel").
The API key never appears in exceptions, logs or repr.
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import json
import logging
import os
from collections import deque
from collections.abc import Awaitable, Callable, Mapping, Sequence

import aiohttp

from app.brain.types import Utterance

log = logging.getLogger("app.speech.stt")

DEFAULT_MODEL = "ink-2"
DEFAULT_KEYTERMS = ("Miguel",)
SAMPLE_RATE_RANGE = (8000, 48000)   # pcm_s16le, per build-with-cartesia/stt/audio-input.md
MAX_KEYTERMS = 100                  # per connection; 1200 characters in all
MAX_KEYTERM_CHARS = 1200

UtteranceCallback = Callable[[Utterance], Awaitable[None] | None]


class STTError(Exception):
    """Speech to text failed. The message never contains the API key."""


class CartesiaSTT:
    """Factory for realtime Cartesia STT sessions (one WebSocket each)."""

    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_MODEL,
        *,
        keyterms: Sequence[str] = DEFAULT_KEYTERMS,
        base_url: str = "wss://api.cartesia.ai",
        version: str = "2026-08-14",
        chunk_ms: int = 100,
        connect_timeout_s: float = 8.0,
        backoff_s: Sequence[float] = (0.5, 1.0, 2.0, 4.0, 8.0),
        max_buffer_ms: int = 2000,
        turn_params: Mapping[str, float] | None = None,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("api_key is empty")
        self._api_key = api_key
        self.model = model
        self.keyterms = _clean_keyterms(keyterms)
        self.base_url = base_url.rstrip("/")
        self.version = version
        self.chunk_ms = max(10, int(chunk_ms))
        self.connect_timeout_s = connect_timeout_s
        self.backoff_s = tuple(backoff_s) or (1.0,)
        self.max_buffer_ms = max(self.chunk_ms, int(max_buffer_ms))
        self.turn_params = dict(turn_params or {})   # e.g. {"turn_end_timeout_ms": 3000}
        self._http = session
        self._sessions: set[SttSession] = set()

    def __repr__(self) -> str:
        return f"CartesiaSTT(model={self.model!r}, keyterms={self.keyterms!r}, base_url={self.base_url!r})"

    @classmethod
    def from_env(cls, env: Mapping[str, str] = os.environ) -> CartesiaSTT | None:
        """Build from CARTESIA_* variables, or None (with a log line saying why) if unconfigured."""
        key = (env.get("CARTESIA_API_KEY") or "").strip()
        if not key:
            log.info("Cartesia hearing off: CARTESIA_API_KEY is not set (push-to-talk still works)")
            return None
        model = (env.get("CARTESIA_STT_MODEL") or "").strip() or DEFAULT_MODEL
        raw_terms = env.get("CARTESIA_STT_KEYTERMS")
        terms = DEFAULT_KEYTERMS if raw_terms is None else [t for t in raw_terms.split(",")]
        stt = cls(key, model, keyterms=terms)
        log.info("Cartesia hearing on: model %s, keyterms %s", model, list(stt.keyterms) or "none")
        return stt

    async def session(
        self,
        on_utterance: UtteranceCallback | None = None,
        *,
        sample_rate: int = 16000,
    ) -> SttSession:
        """Start a live session. It connects when the first audio arrives."""
        if not (SAMPLE_RATE_RANGE[0] <= int(sample_rate) <= SAMPLE_RATE_RANGE[1]):
            raise ValueError(f"sample_rate {sample_rate} is outside {SAMPLE_RATE_RANGE[0]}-{SAMPLE_RATE_RANGE[1]}")
        s = SttSession(self, int(sample_rate), on_utterance)
        self._sessions.add(s)
        s._start()
        return s

    async def close(self) -> None:
        """Close every open session (server shutdown). A given aiohttp session is left open."""
        sessions, self._sessions = list(self._sessions), set()
        if sessions:
            await asyncio.gather(*(s.close(drain_timeout_s=1.0) for s in sessions), return_exceptions=True)

    # --- used by SttSession ---------------------------------------------------

    def _url_and_params(self, sample_rate: int) -> tuple[str, list[tuple[str, str]]]:
        params: list[tuple[str, str]] = [
            ("model", self.model),
            ("encoding", "pcm_s16le"),
            ("sample_rate", str(sample_rate)),
            ("cartesia_version", self.version),
        ]
        params += [("keyterm", t) for t in self.keyterms]
        params += [(k, str(v)) for k, v in self.turn_params.items()]
        return f"{self.base_url}/stt/turns/websocket", params

    def _headers(self) -> dict[str, str]:
        return {"X-API-Key": self._api_key, "Cartesia-Version": self.version}

    def _scrub(self, s: str) -> str:
        return s.replace(self._api_key, "***") if self._api_key else s


def _clean_keyterms(terms: Sequence[str]) -> tuple[str, ...]:
    out: list[str] = []
    total = 0
    for t in terms:
        t = " ".join(str(t).split())
        if not t or t in out:
            continue
        if len(out) >= MAX_KEYTERMS or total + len(t) > MAX_KEYTERM_CHARS:
            log.warning("STT keyterms: dropping %r (Cartesia allows %d terms, %d characters)",
                        t, MAX_KEYTERMS, MAX_KEYTERM_CHARS)
            continue
        out.append(t)
        total += len(t)
    return tuple(out)


class SttSession:
    """One live speech-to-text stream. Use `send_audio()`, read `utterances` (or the callback), `close()`."""

    def __init__(self, stt: CartesiaSTT, sample_rate: int, on_utterance: UtteranceCallback | None) -> None:
        self._stt = stt
        self.sample_rate = sample_rate
        self._on_utterance = on_utterance
        self.utterances: asyncio.Queue[Utterance] = asyncio.Queue()
        self.chunk_bytes = sample_rate * 2 * stt.chunk_ms // 1000
        self._max_chunks = max(1, stt.max_buffer_ms // stt.chunk_ms)
        self._pending = bytearray()                      # audio not yet a whole chunk
        self._buf: deque[bytes] = deque()                # whole chunks waiting for the socket
        self._wake = asyncio.Event()                     # set when audio arrives or close() starts
        self._closing = False
        self._closed = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._http: aiohttp.ClientSession | None = stt._http
        self._own_http = False
        self.connected = False
        self.connects = 0          # successful connections (reconnects = connects - 1)
        self.request_id: str | None = None
        self.in_turn = False       # between turn.start and turn.end
        self.dropped_chunks = 0

    def __repr__(self) -> str:
        return f"SttSession(rate={self.sample_rate}, connected={self.connected}, connects={self.connects})"

    # --- public ---------------------------------------------------------------

    def send_audio(self, pcm: bytes) -> None:
        """Queue raw mono s16le audio at `sample_rate`. Never blocks; drops the oldest audio if Cartesia lags."""
        if self._closing or not pcm:
            return
        self._pending += pcm
        while len(self._pending) >= self.chunk_bytes:
            self._push(bytes(self._pending[: self.chunk_bytes]))
            del self._pending[: self.chunk_bytes]

    async def close(self, drain_timeout_s: float = 3.0) -> None:
        """Flush the audio, ask Cartesia to finish (`close`), deliver the last turns, then stop."""
        if self._closing:
            await self._closed.wait()
            return
        self._closing = True
        if self._pending and len(self._pending) % 2 == 0:
            self._push(bytes(self._pending))
        self._pending.clear()
        self._wake.set()
        try:
            if self._task is not None:
                await asyncio.wait_for(asyncio.shield(self._task), drain_timeout_s)
        except TimeoutError:
            log.info("STT: Cartesia did not finish within %.1f s; closing anyway", drain_timeout_s)
        finally:
            if self._task is not None and not self._task.done():
                self._task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await self._task
            if self._ws is not None and not self._ws.closed:
                with contextlib.suppress(Exception):
                    await self._ws.close()
            if self._own_http and self._http is not None and not self._http.closed:
                await self._http.close()
            self.connected = False
            self._stt._sessions.discard(self)
            self._closed.set()

    # --- internals ------------------------------------------------------------

    def _start(self) -> None:
        self._task = asyncio.ensure_future(self._run())

    def _push(self, chunk: bytes) -> None:
        self._buf.append(chunk)
        while len(self._buf) > self._max_chunks:   # keep latency bounded: old audio is worth less
            self._buf.popleft()
            self.dropped_chunks += 1
        self._wake.set()

    def _get_http(self) -> aiohttp.ClientSession:
        if self._http is None or self._http.closed:
            self._http = aiohttp.ClientSession()
            self._own_http = True
        return self._http

    async def _run(self) -> None:
        failures = 0
        while True:
            # (re)connect only while there is audio to send
            while not self._buf:
                if self._closing:
                    return
                self._wake.clear()
                await self._wake.wait()
            try:
                await self._connect_and_stream()
                failures = 0
                if self._closing:
                    return
                log.info("STT: Cartesia closed the stream; reconnecting when audio arrives")
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001 - any failure means: back off and try again
                self.connected = False
                if self._closing:
                    return
                delay = self._stt.backoff_s[min(failures, len(self._stt.backoff_s) - 1)]
                failures += 1
                log.warning("STT: Cartesia connection failed (%s); retrying in %.1f s",
                            self._stt._scrub(_describe(e)), delay)
                await asyncio.sleep(delay)
                if self._closing:
                    return   # don't reconnect just to flush: the socket that had the turn is gone

    async def _connect_and_stream(self) -> None:
        url, params = self._stt._url_and_params(self.sample_rate)
        ws = await self._get_http().ws_connect(
            url,
            params=params,
            headers=self._stt._headers(),
            timeout=aiohttp.ClientWSTimeout(ws_receive=None, ws_close=5.0),
            heartbeat=20.0,
            max_msg_size=1 << 20,
        )
        self._ws = ws
        self.connected = True
        self.connects += 1
        log.info("STT: connected to Cartesia (%s, %d Hz)%s", self._stt.model, self.sample_rate,
                 " (reconnect)" if self.connects > 1 else "")
        reader = asyncio.ensure_future(self._read(ws))
        try:
            while not reader.done():
                if self._buf:
                    await ws.send_bytes(self._buf.popleft())
                    continue
                if self._closing:
                    with contextlib.suppress(Exception):
                        await ws.send_str(json.dumps({"type": "close"}))
                    await asyncio.wait({reader})   # Cartesia flushes the last turns, then closes the socket
                    break
                self._wake.clear()
                waiter = asyncio.ensure_future(self._wake.wait())
                try:
                    await asyncio.wait({waiter, reader}, return_when=asyncio.FIRST_COMPLETED)
                finally:
                    waiter.cancel()
            if reader.done() and not reader.cancelled() and reader.exception() is not None:
                raise reader.exception()  # type: ignore[misc]
        finally:
            if not reader.done():
                reader.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await reader
            self.connected = False
            self.in_turn = False
            if not ws.closed:
                with contextlib.suppress(Exception):
                    await ws.close()

    async def _read(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        async for msg in ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                try:
                    event = json.loads(msg.data)
                except ValueError:
                    log.warning("STT: Cartesia sent text that is not JSON (%d chars)", len(msg.data))
                    continue
                if isinstance(event, dict):
                    await self._handle(event)
            elif msg.type == aiohttp.WSMsgType.ERROR:
                raise STTError(self._stt._scrub(f"WebSocket error: {_describe(ws.exception())}"))
        code = ws.close_code
        if code not in (None, 1000) and not self._closing:
            raise STTError(f"Cartesia closed the socket with code {code}")

    async def _handle(self, event: dict) -> None:
        kind = event.get("type")
        if event.get("request_id"):
            self.request_id = str(event["request_id"])
        if kind == "turn.start":
            self.in_turn = True
        elif kind == "turn.end":
            self.in_turn = False
            text = " ".join(str(event.get("transcript") or "").split())
            if text:
                await self._deliver(Utterance(
                    source="senior",
                    text=text,
                    # Cartesia's turn events carry no confidence score; None keeps the key present
                    meta={"channel": "mic", "confidence": None, "request_id": self.request_id,
                          "model": self._stt.model},
                ))
        elif kind == "error":
            log.warning("STT: Cartesia error %s %s: %s", event.get("status_code"), event.get("title"),
                        self._stt._scrub(str(event.get("message"))[:200]))

    async def _deliver(self, u: Utterance) -> None:
        log.info("STT heard: %r", u.text[:120])
        if self._on_utterance is None:
            self.utterances.put_nowait(u)
            return
        try:
            r = self._on_utterance(u)
            if inspect.isawaitable(r):
                await r
        except Exception as e:  # noqa: BLE001 - a bad callback must not kill the stream
            log.warning("STT: utterance callback failed: %s", _describe(e))


def _describe(e: BaseException | None) -> str:
    if e is None:
        return "unknown error"
    text = str(e)
    return f"{type(e).__name__}: {text}" if text else type(e).__name__
