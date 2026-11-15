"""Cartesia text to speech: Miguel's voice as mp3 bytes.

`CartesiaTTS.synth(text)` sends one `POST /tts/bytes` request to Cartesia and
returns the mp3. Lines are cached in memory (LRU), and concurrent calls for the
same line share one request, so canned lines ("On it!") cost one request each.

`CartesiaTTS.stream(text)` yields the same mp3 in chunks as Cartesia sends them:
/tts/bytes answers with a chunked body while it generates. Measured Sat Nov 14
(sonic-3.6, mp3 44.1 kHz, from the hackathon Wi-Fi): first byte after 330-420 ms;
the whole file after ~520 ms for a 19-character line and ~820 ms for a
105-character one. A reader that joins late gets the chunks so far, then the rest
(`synth` and `stream` share one request).

Configure from the environment with `CartesiaTTS.from_env()` (names in
`server/.env.example`): CARTESIA_API_KEY (required), CARTESIA_VOICE_ID,
CARTESIA_MODEL, CARTESIA_SPEED. Without a key it returns None and the phone
falls back to Safari's built-in voice.

The API key never appears in exceptions, logs or repr.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections import OrderedDict
from collections.abc import AsyncIterator, Iterable, Mapping

import aiohttp

log = logging.getLogger("app.speech.tts")

# The example voice id in Cartesia's docs (docs.cartesia.ai). A placeholder:
# pick Miguel's voice in Cartesia's voice library and set CARTESIA_VOICE_ID.
DEFAULT_VOICE_ID = "db6b0ed5-d5d3-463d-ae85-518a07d3c2b4"
DEFAULT_MODEL = "sonic-3.6"
SPEED_RANGE = (0.6, 1.5)  # Cartesia's generation_config.speed range (sonic-3+)

_EXCERPT_CHARS = 200


class TTSError(Exception):
    """Text to speech failed. The message never contains the API key."""


class _Pending:
    """One line being fetched: the chunks so far, and whether (and how) it ended."""

    def __init__(self) -> None:
        self.chunks: list[bytes] = []
        self.done = False
        self.error: BaseException | None = None
        self._changed = asyncio.Event()

    def add(self, chunk: bytes) -> None:
        self.chunks.append(chunk)
        self._wake()

    def finish(self, error: BaseException | None = None) -> None:
        self.done, self.error = True, error
        self._wake()

    def _wake(self) -> None:
        changed, self._changed = self._changed, asyncio.Event()
        changed.set()                    # everyone waiting on the old event wakes up

    async def changed(self) -> None:
        await self._changed.wait()

    async def result(self) -> bytes:
        while not self.done:
            await self.changed()
        if self.error is not None:
            raise self.error
        return b"".join(self.chunks)


def normalize_text(text: str, max_chars: int) -> str:
    """Strip, collapse whitespace and cap at `max_chars` (at a word break when one is near)."""
    clean = " ".join(str(text).split())
    if len(clean) <= max_chars:
        return clean
    cut = clean[:max_chars]
    space = cut.rfind(" ")
    if space >= max_chars * 0.6:  # don't throw away most of the line to find a word break
        cut = cut[:space]
    return cut.rstrip()


class CartesiaTTS:
    """Cartesia `/tts/bytes` client with an LRU cache and in-flight dedupe."""

    MEDIA_TYPE = "audio/mpeg"

    def __init__(
        self,
        api_key: str,
        voice_id: str,
        model: str = DEFAULT_MODEL,
        *,
        speed: float | None = None,
        base_url: str = "https://api.cartesia.ai",
        version: str = "2026-08-14",
        timeout_s: float = 8.0,
        max_chars: int = 300,
        cache_size: int = 200,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("api_key is empty")
        if not voice_id:
            raise ValueError("voice_id is empty")
        if speed is not None and not (SPEED_RANGE[0] <= speed <= SPEED_RANGE[1]):
            raise ValueError(f"speed {speed} is outside {SPEED_RANGE[0]}-{SPEED_RANGE[1]}")
        if max_chars < 1:
            raise ValueError("max_chars must be at least 1")
        self._api_key = api_key
        self.voice_id = voice_id
        self.model = model
        self.speed = speed
        self.base_url = base_url.rstrip("/")
        self.version = version
        self.timeout_s = timeout_s
        self.max_chars = max_chars
        self.cache_size = max(0, cache_size)
        self._session = session
        self._own_session = False
        self._cache: OrderedDict[tuple, bytes] = OrderedDict()
        self._inflight: dict[tuple, _Pending] = {}
        self._tasks: set[asyncio.Task[None]] = set()

    def __repr__(self) -> str:
        return (
            f"CartesiaTTS(model={self.model!r}, voice_id={self.voice_id!r}, "
            f"speed={self.speed!r}, base_url={self.base_url!r})"
        )

    @classmethod
    def from_env(cls, env: Mapping[str, str] = os.environ) -> CartesiaTTS | None:
        """Build from CARTESIA_* variables, or None (with a log line saying why) if unconfigured."""
        key = (env.get("CARTESIA_API_KEY") or "").strip()
        if not key:
            log.info("Cartesia voice off: CARTESIA_API_KEY is not set (the phone uses Safari's voice)")
            return None
        voice = (env.get("CARTESIA_VOICE_ID") or "").strip()
        if not voice:
            voice = DEFAULT_VOICE_ID
            log.warning(
                "CARTESIA_VOICE_ID is not set: using Cartesia's example voice %s; "
                "replace it with Miguel's voice id",
                voice,
            )
        model = (env.get("CARTESIA_MODEL") or "").strip() or DEFAULT_MODEL
        speed: float | None = None
        raw_speed = (env.get("CARTESIA_SPEED") or "").strip()
        if raw_speed:
            try:
                speed = float(raw_speed)
            except ValueError:
                log.warning("CARTESIA_SPEED=%r is not a number: using the default speed", raw_speed)
            else:
                if not (SPEED_RANGE[0] <= speed <= SPEED_RANGE[1]):
                    log.warning(
                        "CARTESIA_SPEED=%s is outside %s-%s: using the default speed",
                        speed, *SPEED_RANGE,
                    )
                    speed = None
        log.info("Cartesia voice on: model %s, voice %s, speed %s", model, voice, speed or "default")
        return cls(key, voice, model, speed=speed)

    # --- public ---------------------------------------------------------------

    async def synth(self, text: str) -> bytes:
        """Return mp3 bytes for `text`. Raises TTSError on empty text or any API failure."""
        key, clean = self._key(text)
        cached = self._cached(key)
        if cached is not None:
            return cached
        # the fetch runs in its own task: one caller giving up never cancels it for the others
        return await self._start(key, clean).result()

    def cached(self, text: str) -> bytes | None:
        """The mp3 for `text` if it is in the cache (no request)."""
        try:
            key, _ = self._key(text)
        except TTSError:
            return None
        return self._cached(key)

    async def stream(self, text: str) -> AsyncIterator[bytes]:
        """Yield the mp3 for `text` in chunks as they arrive (all at once if cached).

        Raises TTSError before the first chunk if the request fails; a failure after audio has
        started just ends the stream early (it is logged)."""
        key, clean = self._key(text)
        cached = self._cached(key)
        if cached is not None:
            yield cached
            return
        pending = self._start(key, clean)
        sent = 0
        while True:
            while sent < len(pending.chunks):
                sent += 1
                yield pending.chunks[sent - 1]
            if pending.done:
                if pending.error is not None and sent == 0:
                    raise pending.error
                return
            await pending.changed()

    def _key(self, text: str) -> tuple[tuple, str]:
        clean = normalize_text(text, self.max_chars)
        if not clean:
            raise TTSError("nothing to say: the text is empty")
        return (self.model, self.voice_id, self.speed, clean), clean

    def _cached(self, key: tuple) -> bytes | None:
        cached = self._cache.get(key)
        if cached is not None:
            self._cache.move_to_end(key)
        return cached

    def _start(self, key: tuple, clean: str) -> _Pending:
        pending = self._inflight.get(key)
        if pending is None:
            pending = self._inflight[key] = _Pending()
            task = asyncio.ensure_future(self._run(key, clean, pending))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
        return pending

    async def prewarm(self, lines: Iterable[str]) -> int:
        """Synthesize each line into the cache; return how many succeeded. Never raises."""
        ok = 0
        try:
            items = list(lines)
        except Exception as e:  # noqa: BLE001 - a bad iterable must not take the caller down
            log.warning("TTS prewarm: could not read the lines (%s)", type(e).__name__)
            return 0
        for line in items:
            try:
                await self.synth(line)
                ok += 1
            except TTSError as e:
                log.warning("TTS prewarm: %r failed: %s", str(line)[:40], e)
            except Exception as e:  # noqa: BLE001
                log.warning("TTS prewarm: %r failed: %s", str(line)[:40], self._scrub(repr(e)))
        log.info("TTS prewarm: %d of %d lines cached", ok, len(items))
        return ok

    async def close(self) -> None:
        """Close the HTTP session if this client created it (a given session is left open)."""
        for task in list(self._tasks):   # lines still being fetched
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        if self._own_session and self._session is not None:
            session, self._session, self._own_session = self._session, None, False
            if not session.closed:
                await session.close()

    # --- internals ------------------------------------------------------------

    async def _run(self, key: tuple, clean: str, pending: _Pending) -> None:
        error: BaseException | None = None
        try:
            await self._fetch_politely(clean, pending)
        except asyncio.CancelledError:
            error = TTSError("the request was cancelled")
            raise
        except TTSError as e:
            error = e
        except Exception as e:  # noqa: BLE001 - anything else is a failed line, never a crash
            error = TTSError(self._scrub(f"Cartesia request failed: {type(e).__name__}: {e}"))
        finally:
            self._inflight.pop(key, None)
            if error is None and self.cache_size:
                self._cache[key] = b"".join(pending.chunks)
                self._cache.move_to_end(key)
                while len(self._cache) > self.cache_size:
                    self._cache.popitem(last=False)
            pending.finish(error)

    async def _fetch_politely(self, clean: str, pending: _Pending) -> None:
        """At most CARTESIA_MAX_CONCURRENT requests at once (default 1, in order), and a short retry when
        Cartesia says it's busy. Sat night: the new plan answered HTTP 429 "concurrency_limited" when
        every sentence of a reply was prefetched at once."""
        if getattr(self, "_sem", None) is None:
            self._sem = asyncio.Semaphore(max(1, int(os.environ.get("CARTESIA_MAX_CONCURRENT", "1") or 1)))
        for attempt in range(4):
            async with self._sem:
                try:
                    await self._fetch(clean, pending.add)
                    return
                except TTSError as e:
                    busy = "HTTP 429" in str(e)
                    if not busy or pending.chunks or attempt == 3:
                        raise
            await asyncio.sleep(0.3 * (attempt + 1))   # busy: wait a moment, then try again

    def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
            self._own_session = True
        return self._session

    def _scrub(self, s: str) -> str:
        return s.replace(self._api_key, "***") if self._api_key else s

    def _body(self, text: str) -> dict:
        body: dict = {
            "model_id": self.model,
            "transcript": text,
            "voice": {"id": self.voice_id},
            "output_format": {"container": "mp3", "sample_rate": 44100, "bit_rate": 128000},
        }
        if self.speed is not None:
            body["generation_config"] = {"speed": self.speed}
        return body

    async def _fetch(self, text: str, on_chunk) -> None:
        """POST /tts/bytes and hand each chunk of the (chunked) mp3 to on_chunk as it arrives."""
        url = f"{self.base_url}/tts/bytes"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Cartesia-Version": self.version,
            "Content-Type": "application/json",
        }
        timeout = aiohttp.ClientTimeout(total=self.timeout_s)
        got = 0
        try:
            async with self._get_session().post(
                url, json=self._body(text), headers=headers, timeout=timeout
            ) as resp:
                if resp.status != 200:
                    data = await resp.read()
                    excerpt = " ".join(data[:_EXCERPT_CHARS].decode("utf-8", "replace").split())
                    raise TTSError(self._scrub(f"Cartesia returned HTTP {resp.status}: {excerpt}"))
                ctype = resp.content_type or ""
                if not (ctype.startswith("audio/") or ctype == "application/octet-stream"):
                    raise TTSError(f"Cartesia returned {ctype or 'no content type'}, not audio")
                async for chunk in resp.content.iter_any():
                    if chunk:
                        got += len(chunk)
                        on_chunk(chunk)
                if not got:
                    raise TTSError("Cartesia returned no audio")
        except TTSError:
            raise
        except (asyncio.TimeoutError, TimeoutError):
            raise TTSError(f"Cartesia timed out after {self.timeout_s:g} s") from None
        except aiohttp.ClientError as e:
            raise TTSError(self._scrub(f"Cartesia request failed: {type(e).__name__}: {e}")) from None
