"""Cartesia TTS client against a fake Cartesia server on 127.0.0.1 (no network, no real key)."""

from __future__ import annotations

import asyncio
import json
import logging

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from app.speech import CartesiaTTS, TTSError
from app.speech.tts import DEFAULT_VOICE_ID, normalize_text

KEY = "sk_car_SECRET_test_key_123"
VOICE = "voice-abc"
MP3 = b"ID3\x04fake-mp3-bytes"


class FakeCartesia:
    """A fake /tts/bytes endpoint that records requests and replies as configured."""

    def __init__(self, *, status=200, body=MP3, content_type="audio/mpeg", delay=0.0):
        self.status = status
        self.body = body
        self.content_type = content_type
        self.delay = delay
        self.requests: list[dict] = []

    async def handle(self, request: web.Request) -> web.Response:
        self.requests.append(
            {"path": request.path, "headers": dict(request.headers), "json": await request.json()}
        )
        if self.delay:
            await asyncio.sleep(self.delay)
        if isinstance(self.body, bytes):
            return web.Response(status=self.status, body=self.body, content_type=self.content_type)
        return web.Response(status=self.status, text=self.body, content_type=self.content_type)


def run(fake: FakeCartesia, scenario, **kw):
    """Start the fake server, build a client pointed at it, run `scenario(tts)`, close both."""

    async def main():
        app = web.Application()
        app.router.add_post("/tts/bytes", fake.handle)
        server = TestServer(app, host="127.0.0.1")
        await server.start_server()
        kw.setdefault("timeout_s", 2.0)
        tts = CartesiaTTS(KEY, VOICE, base_url=str(server.make_url("")), **kw)
        try:
            return await scenario(tts)
        finally:
            await tts.close()
            await server.close()

    return asyncio.run(main())


# --- request shape ---------------------------------------------------------------


def test_request_url_headers_and_body():
    fake = FakeCartesia()

    async def scenario(tts):
        return await tts.synth("Hello there")

    audio = run(fake, scenario)
    assert audio == MP3 and isinstance(audio, bytes)
    assert len(fake.requests) == 1
    req = fake.requests[0]
    assert req["path"] == "/tts/bytes"
    assert req["headers"]["Authorization"] == f"Bearer {KEY}"
    assert req["headers"]["Cartesia-Version"] == "2026-08-14"
    assert req["headers"]["Content-Type"].startswith("application/json")
    body = req["json"]
    assert body["model_id"] == "sonic-3.6"
    assert body["transcript"] == "Hello there"
    assert body["voice"] == {"id": VOICE}
    assert body["output_format"] == {"container": "mp3", "sample_rate": 44100, "bit_rate": 128000}
    assert "generation_config" not in body
    assert CartesiaTTS.MEDIA_TYPE == "audio/mpeg"


def test_speed_goes_in_generation_config_when_set():
    fake = FakeCartesia()

    async def scenario(tts):
        await tts.synth("Faster")

    run(fake, scenario, speed=1.2, model="sonic-3", version="2025-04-16")
    req = fake.requests[0]
    assert req["json"]["generation_config"] == {"speed": 1.2}
    assert req["json"]["model_id"] == "sonic-3"
    assert req["headers"]["Cartesia-Version"] == "2025-04-16"


def test_speed_out_of_range_rejected():
    with pytest.raises(ValueError):
        CartesiaTTS(KEY, VOICE, speed=3.0)
    with pytest.raises(ValueError):
        CartesiaTTS("", VOICE)


# --- cache and dedupe ------------------------------------------------------------


def test_cache_hit_makes_no_second_request():
    fake = FakeCartesia()

    async def scenario(tts):
        a = await tts.synth("On it!")
        b = await tts.synth("  On   it! ")  # same line after normalization
        return a, b

    a, b = run(fake, scenario)
    assert a == b == MP3
    assert len(fake.requests) == 1


def test_cache_is_lru_and_bounded():
    fake = FakeCartesia()

    async def scenario(tts):
        await tts.synth("one")
        await tts.synth("two")
        await tts.synth("one")  # hit; "two" is now least recent
        await tts.synth("three")  # evicts "two"
        await tts.synth("one")  # still cached
        await tts.synth("two")  # refetched

    run(fake, scenario, cache_size=2)
    assert [r["json"]["transcript"] for r in fake.requests] == ["one", "two", "three", "two"]


def test_concurrent_calls_share_one_request():
    fake = FakeCartesia(delay=0.1)

    async def scenario(tts):
        return await asyncio.gather(*(tts.synth("Hi!") for _ in range(5)))

    results = run(fake, scenario)
    assert results == [MP3] * 5
    assert len(fake.requests) == 1


def test_one_waiter_cancelling_does_not_cancel_the_shared_request():
    fake = FakeCartesia(delay=0.1)

    async def scenario(tts):
        first = asyncio.ensure_future(tts.synth("Hi!"))
        second = asyncio.ensure_future(tts.synth("Hi!"))
        await asyncio.sleep(0.02)
        first.cancel()
        return await second

    assert run(fake, scenario) == MP3
    assert len(fake.requests) == 1


def test_failures_are_not_cached():
    fake = FakeCartesia(status=500, body="boom", content_type="text/plain")

    async def scenario(tts):
        with pytest.raises(TTSError):
            await tts.synth("retry me")
        fake.status, fake.body, fake.content_type = 200, MP3, "audio/mpeg"
        return await tts.synth("retry me")

    assert run(fake, scenario) == MP3
    assert len(fake.requests) == 2


# --- text ------------------------------------------------------------------------


def test_normalization_and_length_cap():
    fake = FakeCartesia()
    long_line = "word " * 100  # 500 chars

    async def scenario(tts):
        await tts.synth("  Hello\n\n  there\tfriend  ")
        await tts.synth(long_line)

    run(fake, scenario, max_chars=50)
    assert fake.requests[0]["json"]["transcript"] == "Hello there friend"
    capped = fake.requests[1]["json"]["transcript"]
    assert len(capped) <= 50 and capped.endswith("word") and capped == capped.strip()


def test_normalize_text_hard_cut_without_spaces():
    assert normalize_text("x" * 20, 8) == "x" * 8
    assert normalize_text("  a  b  ", 300) == "a b"


def test_empty_text_raises_without_request():
    fake = FakeCartesia()

    async def scenario(tts):
        for text in ("", "   ", "\n\t"):
            with pytest.raises(TTSError):
                await tts.synth(text)

    run(fake, scenario)
    assert fake.requests == []


# --- errors ----------------------------------------------------------------------


def test_non_200_raises_with_status_and_excerpt():
    fake = FakeCartesia(
        status=401, body=json.dumps({"error": "bad key " + "x" * 500}), content_type="application/json"
    )

    async def scenario(tts):
        with pytest.raises(TTSError) as ei:
            await tts.synth("Hi")
        return str(ei.value)

    msg = run(fake, scenario)
    assert "401" in msg and "bad key" in msg
    assert len(msg) < 300  # an excerpt, not the whole body


def test_timeout_raises_tts_error():
    fake = FakeCartesia(delay=1.0)

    async def scenario(tts):
        with pytest.raises(TTSError) as ei:
            await tts.synth("slow")
        return str(ei.value)

    assert "timed out" in run(fake, scenario, timeout_s=0.1)


def test_network_error_raises_tts_error():
    async def main():
        # nothing listens on port 9 of 127.0.0.1 (discard; closed on dev machines)
        tts = CartesiaTTS(KEY, VOICE, base_url="http://127.0.0.1:9", timeout_s=1.0)
        try:
            with pytest.raises(TTSError) as ei:
                await tts.synth("Hi")
            return str(ei.value)
        finally:
            await tts.close()

    msg = asyncio.run(main())
    assert KEY not in msg


def test_wrong_content_type_raises():
    fake = FakeCartesia(body='{"ok": true}', content_type="application/json")

    async def scenario(tts):
        with pytest.raises(TTSError) as ei:
            await tts.synth("Hi")
        return str(ei.value)

    assert "not audio" in run(fake, scenario)


def test_key_never_in_errors_or_logs(caplog):
    caplog.set_level(logging.DEBUG)
    # the server echoes the key back in its error body; the client must scrub it
    fake = FakeCartesia(status=403, body=f"invalid key {KEY}", content_type="text/plain")

    async def scenario(tts):
        with pytest.raises(TTSError) as ei:
            await tts.synth("Hi")
        n = await tts.prewarm(["a", "b"])
        return str(ei.value), repr(ei.value), n, repr(tts)

    msg, rep, n, tts_repr = run(fake, scenario)
    assert n == 0
    assert "403" in msg
    for text in (msg, rep, tts_repr, caplog.text):
        assert KEY not in text


# --- from_env --------------------------------------------------------------------


def test_from_env_missing_key_returns_none(caplog):
    caplog.set_level(logging.INFO)
    assert CartesiaTTS.from_env({}) is None
    assert CartesiaTTS.from_env({"CARTESIA_API_KEY": "  "}) is None
    assert "CARTESIA_API_KEY" in caplog.text


def test_from_env_defaults_voice_and_model(caplog):
    caplog.set_level(logging.INFO)
    tts = CartesiaTTS.from_env({"CARTESIA_API_KEY": KEY, "CARTESIA_MODEL": "", "CARTESIA_SPEED": ""})
    assert tts is not None
    assert tts.voice_id == DEFAULT_VOICE_ID
    assert tts.model == "sonic-3.6"
    assert tts.speed is None
    assert "CARTESIA_VOICE_ID" in caplog.text and "replace" in caplog.text
    assert KEY not in caplog.text


def test_from_env_overrides():
    tts = CartesiaTTS.from_env(
        {
            "CARTESIA_API_KEY": KEY,
            "CARTESIA_VOICE_ID": VOICE,
            "CARTESIA_MODEL": "sonic-3",
            "CARTESIA_SPEED": "0.9",
        }
    )
    assert (tts.voice_id, tts.model, tts.speed) == (VOICE, "sonic-3", 0.9)


def test_from_env_bad_speed_is_ignored(caplog):
    caplog.set_level(logging.WARNING)
    for raw in ("fast", "9"):
        tts = CartesiaTTS.from_env({"CARTESIA_API_KEY": KEY, "CARTESIA_SPEED": raw})
        assert tts is not None and tts.speed is None
    assert "CARTESIA_SPEED" in caplog.text


# --- streaming -------------------------------------------------------------------


class ChunkedCartesia(FakeCartesia):
    """Like the real /tts/bytes: a chunked body written while the audio is made."""

    def __init__(self, chunks=(b"ID3", b"-one", b"-two"), gap=0.05):
        super().__init__()
        self.chunks, self.gap = chunks, gap
        self.last_written: float | None = None

    async def handle(self, request: web.Request) -> web.StreamResponse:
        self.requests.append({"json": await request.json()})
        resp = web.StreamResponse(headers={"Content-Type": "audio/mpeg"})
        await resp.prepare(request)
        for chunk in self.chunks:
            await resp.write(chunk)
            await asyncio.sleep(self.gap)
        self.last_written = asyncio.get_running_loop().time()
        await resp.write_eof()
        return resp


def test_stream_yields_audio_before_the_line_is_finished_and_shares_the_request():
    fake = ChunkedCartesia()

    async def scenario(tts):
        got, first_at = [], None
        whole = asyncio.ensure_future(tts.synth("Hello there."))   # e.g. the server's prefetch
        await asyncio.sleep(0)
        async for chunk in tts.stream("Hello there."):
            if first_at is None:
                first_at = asyncio.get_running_loop().time()
            got.append(chunk)
        cached = [c async for c in tts.stream("Hello there.")]
        return got, first_at, await whole, cached, tts.cached("Hello there.")

    got, first_at, whole, cached, in_cache = run(fake, scenario)
    assert b"".join(got) == whole == b"ID3-one-two"
    assert first_at < fake.last_written                    # played from the first chunk on
    assert len(fake.requests) == 1                         # the stream and the synth shared one request
    assert cached == [b"ID3-one-two"] and in_cache == b"ID3-one-two"


def test_stream_raises_before_any_audio_on_failure():
    fake = FakeCartesia(status=500, body="down", content_type="text/plain")

    async def scenario(tts):
        with pytest.raises(TTSError):
            async for _ in tts.stream("Hi"):
                pass
        return tts.cached("Hi")

    assert run(fake, scenario) is None


# --- prewarm and close -----------------------------------------------------------


def test_prewarm_counts_successes_and_fills_cache():
    fake = FakeCartesia()

    async def scenario(tts):
        n = await tts.prewarm(["On it!", "Hi!", "", "On it!"])  # empty fails; repeat is a hit
        await tts.synth("Hi!")  # cached
        return n

    assert run(fake, scenario) == 3
    assert [r["json"]["transcript"] for r in fake.requests] == ["On it!", "Hi!"]


def test_prewarm_swallows_failures():
    fake = FakeCartesia(status=500, body="down", content_type="text/plain")

    async def scenario(tts):
        return await tts.prewarm(["a", "b", "c"])

    assert run(fake, scenario) == 0
    assert len(fake.requests) == 3


def test_close_closes_own_session_only():
    fake = FakeCartesia()

    async def main():
        app = web.Application()
        app.router.add_post("/tts/bytes", fake.handle)
        server = TestServer(app, host="127.0.0.1")
        await server.start_server()
        base = str(server.make_url(""))
        try:
            own = CartesiaTTS(KEY, VOICE, base_url=base)
            await own.synth("Hi")
            created = own._session
            assert created is not None and not created.closed
            await own.close()
            assert created.closed
            await own.close()  # twice is fine

            shared = aiohttp.ClientSession()
            given = CartesiaTTS(KEY, VOICE, base_url=base, session=shared)
            await given.synth("Hi")
            await given.close()
            assert not shared.closed
            await shared.close()
        finally:
            await server.close()

    asyncio.run(main())
    assert len(fake.requests) == 2


def test_one_request_at_a_time_and_a_retry_when_cartesia_is_busy(monkeypatch):
    from app.speech import tts as tts_mod

    monkeypatch.setenv("CARTESIA_MAX_CONCURRENT", "1")
    client = tts_mod.CartesiaTTS("key-xyz", DEFAULT_VOICE_ID, "sonic-3.6")
    live, peak, calls = [0], [0], []

    async def fetch(text, on_chunk):
        calls.append(text)
        live[0] += 1
        peak[0] = max(peak[0], live[0])
        await asyncio.sleep(0.01)
        live[0] -= 1
        if text == "Two." and calls.count("Two.") == 1:
            raise tts_mod.TTSError('Cartesia returned HTTP 429: {"error_code":"concurrency_limited"}')
        on_chunk(b"mp3:" + text.encode())

    monkeypatch.setattr(client, "_fetch", fetch)

    async def go():
        return await asyncio.gather(client.synth("One."), client.synth("Two."), client.synth("Three."))

    out = asyncio.run(go())
    assert out == [b"mp3:One.", b"mp3:Two.", b"mp3:Three."]
    assert peak[0] == 1 and calls.count("Two.") == 2      # never two at once; the busy one retried
