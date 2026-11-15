"""Local voice (KokoroTTS, #81) with a fake model; the real-model test runs only where mlx-audio and the
model are installed (CI is Linux without mlx, so it skips there)."""

from __future__ import annotations

import asyncio
import io
import threading
import wave

import numpy as np
import pytest

import app.__main__ as server
from app.speech import tts_local
from app.speech.tts import TTSError
from app.speech.tts_local import KokoroTTS, clean_for_speech, pcm16, wav_bytes


class FakeEngine:
    """Stands in for Kokoro: one short tone per sentence. Records what it was asked and whether the
    MLX lock was held for each model step."""

    def __init__(self, *, fail_load: Exception | None = None, fail_text: str | None = None, delay=0.0):
        self.fail_load, self.fail_text, self.delay = fail_load, fail_text, delay
        self.loads = self.prepares = 0
        self.texts: list[str] = []
        self.lock: threading.Lock | None = None
        self.held: list[bool] = []

    def load(self):
        self.loads += 1
        if self.fail_load:
            raise self.fail_load

    def prepare(self):
        self.prepares += 1

    def segments(self, text, voice, speed):
        self.texts.append(text)
        for sentence in text.split(". "):
            if self.delay:
                import time

                time.sleep(self.delay)
            self.held.append(self.lock is not None and self.lock.locked())
            if self.fail_text and self.fail_text in sentence:
                raise RuntimeError("model blew up")
            yield np.full(240 * max(1, len(sentence)), 0.5, dtype=np.float32)


def make(engine=None, **kw):
    engine = engine or FakeEngine()
    lock = threading.Lock()
    engine.lock = lock
    return KokoroTTS("af_test", engine=engine, lock=lock, **kw), engine


def parse_wav(data: bytes):
    with wave.open(io.BytesIO(data)) as w:
        return w.getnchannels(), w.getsampwidth(), w.getframerate(), w.readframes(w.getnframes())


# --- WAV ---------------------------------------------------------------------

def test_wav_is_pcm16_24khz_mono_with_the_right_lengths():
    pcm = pcm16(np.array([0.0, 0.5, -0.5, 1.0, -1.0, 2.0, -2.0], dtype=np.float32))
    assert np.frombuffer(pcm, "<i2").tolist() == [0, 16384, -16384, 32767, -32767, 32767, -32767]   # clipped
    data = wav_bytes(pcm)
    assert data[:4] == b"RIFF" and data[8:16] == b"WAVEfmt "
    assert int.from_bytes(data[4:8], "little") == len(data) - 8          # RIFF size
    assert data[36:40] == b"data" and int.from_bytes(data[40:44], "little") == len(pcm)
    assert parse_wav(data) == (1, 2, 24000, pcm)
    assert len(wav_bytes(b"")) == 44


def test_every_line_has_real_silence_before_and_after_the_speech():
    """#91: the phone clips the first and last ~100-200 ms of a clip, so the words must not start or end there."""
    tts, _ = make()

    async def t():
        return await tts.synth("Hi")
    pcm = np.frombuffer(parse_wav(asyncio.run(t()))[3], "<i2")
    lead, tail = round(tts_local.LEAD_SILENCE_S * 24000), round(tts_local.TAIL_SILENCE_S * 24000)
    assert lead >= 0.15 * 24000 and tail >= 0.2 * 24000          # at least what Cartesia's mp3s carried
    assert not pcm[:lead].any() and not pcm[-tail:].any()       # digital silence at both ends
    assert pcm[lead] != 0 and pcm[-tail - 1] != 0                # and the speech itself is all there
    assert len(pcm) == lead + 240 * 2 + tail                     # FakeEngine: 240 samples per character


# --- text --------------------------------------------------------------------

@pytest.mark.parametrize("raw, spoken", [
    ("**Done!** ✅ Your _tea_ is on the way 🍵.", "Done! Your tea is on the way."),
    ("I ❤️ you, Mom 👍🏽", "I you, Mom"),
    ("👨‍👩‍👧 Family time! 🇺🇸", "Family time!"),
    ("# Plan\n- get **water**\n- [call Ann](tel:123)", "Plan. get water. call Ann."),
    ("Set `snake_case` to ~~old~~ new.", "Set snake_case to old new."),
    ("Here is your water, Mom.", "Here is your water, Mom."),
    ("It's 72°F and 3 * 4 = 12.", "It's 72°F and 3 4 = 12."),
])
def test_emojis_and_markdown_are_not_spoken(raw, spoken):
    assert clean_for_speech(raw) == spoken


def test_a_line_of_only_emojis_is_nothing_to_say():
    tts, engine = make()

    async def t():
        with pytest.raises(TTSError, match="nothing to say"):
            await tts.synth("🎉🎉 ✅")
        assert tts.cached("🎉") is None
    asyncio.run(t())
    assert engine.texts == []


def test_text_is_cleaned_then_normalized_and_capped():
    tts, engine = make(max_chars=20)

    async def t():
        await tts.synth("  **Hello**   there,   my dear friend Margaret  ✅ ")
    asyncio.run(t())
    assert engine.texts[-1] == "Hello there, my"    # cut at a word break, as for Cartesia


# --- cache, sharing, loading ---------------------------------------------------

def test_synth_makes_a_wav_loads_once_and_caches_the_line():
    tts, engine = make()

    async def t():
        a = await tts.synth("Here is your water, Mom.")
        b = await tts.synth("  Here is your   water, Mom. ✅")   # same line once cleaned: cached
        assert a is b and tts.cached("Here is your water, Mom.") is a
        chunks = [c async for c in tts.stream("Here is your water, Mom.")]
        assert chunks == [a]
        return a
    data = asyncio.run(t())
    assert parse_wav(data)[:3] == (1, 2, 24000)
    assert engine.loads == 1 and engine.prepares == 1
    assert engine.texts == [tts_local.WARMUP_LINE, "Here is your water, Mom."]
    assert engine.held and all(engine.held)                     # every model step held the MLX lock


def test_concurrent_calls_for_one_line_share_one_synthesis():
    tts, engine = make(FakeEngine(delay=0.02))

    async def t():
        async def streamed():
            return b"".join([c async for c in tts.stream("Good morning. Pills. Water.")])
        results = await asyncio.gather(*(tts.synth("Good morning. Pills. Water.") for _ in range(4)), streamed())
        assert len({id(r) for r in results[:4]}) == 1 and results[4] == results[0]
    asyncio.run(t())
    assert engine.texts.count("Good morning. Pills. Water.") == 1


def test_the_cache_is_lru_and_bounded():
    tts, engine = make(cache_size=2)

    async def t():
        await tts.synth("One.")
        await tts.synth("Two.")
        await tts.synth("One.")      # One is now the most recent
        await tts.synth("Three.")    # evicts Two
        assert tts.cached("One.") and tts.cached("Three.") and tts.cached("Two.") is None
    asyncio.run(t())


def test_a_model_failure_is_a_tts_error_and_is_not_cached():
    tts, engine = make(FakeEngine(fail_text="boom"))

    async def t():
        with pytest.raises(TTSError, match="local voice failed"):
            await tts.synth("This goes boom.")
        assert tts.cached("This goes boom.") is None
        assert await tts.synth("This is fine.")       # one bad line doesn't break the voice
    asyncio.run(t())


def test_a_load_failure_is_reported_once_and_prewarm_never_raises():
    tts, engine = make(FakeEngine(fail_load=OSError("weights missing")))

    async def t():
        assert await tts.prewarm(["On it!"]) == 0
        with pytest.raises(TTSError, match="failed to load"):
            await tts.synth("On it!")
    asyncio.run(t())
    assert engine.loads == 1


def test_prewarm_loads_then_caches_the_lines():
    tts, engine = make()

    async def t():
        assert await tts.prewarm(["On it!", "🎉", "Got it."]) == 2
        assert tts.cached("On it!") and tts.cached("Got it.")
        await tts.close()
    asyncio.run(t())


# --- the /tts route: content type per backend ----------------------------------

def test_tts_route_sends_audio_wav_for_the_local_voice():
    from tests.test_api import with_client

    tts, _ = make()

    async def t(c, s):
        r = await c.get("/tts", params={"text": "Here is your water, Mom."})        # not cached: streamed
        assert r.status == 200 and r.headers["Content-Type"] == "audio/wav"
        body = await r.read()
        assert parse_wav(body)[2] == 24000
        r = await c.get("/tts", params={"text": "Here is your water, Mom."})        # cached: whole
        assert r.headers["Content-Type"] == "audio/wav" and await r.read() == body
        assert r.headers["Content-Length"] == str(len(body))
        r = await c.get("/tts", params={"text": "✅"})                               # nothing to say
        assert r.status == 502
    with_client(t, tts)


def test_tts_route_sends_audio_mpeg_for_cartesia():
    from aiohttp import web
    from aiohttp.test_utils import TestServer

    from app.speech.tts import CartesiaTTS
    from tests.test_api import with_client

    async def handle(request):
        return web.Response(body=b"ID3 fake mp3", content_type="audio/mpeg")

    holder = {}

    async def t(c, s):
        r = await c.get("/tts", params={"text": "Hello."})
        assert r.status == 200 and r.headers["Content-Type"] == "audio/mpeg"
        assert await r.read() == b"ID3 fake mp3"
        await holder["fake"].close()

    class LazyCartesia(CartesiaTTS):   # starts its fake Cartesia inside the test's event loop
        async def _fetch(self, text, on_chunk):
            if "fake" not in holder:
                app = web.Application()
                app.router.add_post("/tts/bytes", handle)
                holder["fake"] = TestServer(app, host="127.0.0.1")
                await holder["fake"].start_server()
                self.base_url = str(holder["fake"].make_url("")).rstrip("/")
            await super()._fetch(text, on_chunk)

    with_client(t, LazyCartesia("sk_test", "voice"))


# --- choosing the voice (make_tts) ---------------------------------------------

def test_make_tts_picks_the_local_voice_when_its_model_is_there(monkeypatch, tmp_path):
    monkeypatch.setenv("MIGUEL_TTS", "local")
    monkeypatch.setenv("MIGUEL_KOKORO_VOICE", "af_bella")
    monkeypatch.setattr(tts_local, "find_model", lambda voice: (tmp_path, None))
    tts = server.make_tts()
    assert isinstance(tts, KokoroTTS) and tts.voice == "af_bella" and tts.MEDIA_TYPE == "audio/wav"


def test_make_tts_falls_back_to_cartesia_then_safari_when_the_model_is_missing(monkeypatch, caplog):
    from app.speech.tts import CartesiaTTS

    caplog.set_level("INFO")
    monkeypatch.setenv("MIGUEL_TTS", "local")
    monkeypatch.setattr(tts_local, "find_model", lambda voice: (None, "the model is not downloaded"))
    monkeypatch.setenv("CARTESIA_API_KEY", "sk_test")
    assert isinstance(server.make_tts(), CartesiaTTS)
    assert "local voice unavailable: the model is not downloaded" in caplog.text
    monkeypatch.delenv("CARTESIA_API_KEY")
    assert server.make_tts() is None                      # the phone uses Safari's voice


def test_make_tts_defaults_to_cartesia(monkeypatch):
    from app.speech.tts import CartesiaTTS

    monkeypatch.delenv("MIGUEL_TTS", raising=False)
    monkeypatch.setenv("CARTESIA_API_KEY", "sk_test")
    monkeypatch.setattr(tts_local, "find_model", lambda voice: pytest.fail("the local voice was not asked for"))
    assert isinstance(server.make_tts(), CartesiaTTS)
    monkeypatch.setenv("MIGUEL_TTS", "elevenlabs")         # unknown: Cartesia, with a warning
    assert isinstance(server.make_tts(), CartesiaTTS)


def test_find_model_says_why_when_the_model_is_missing():
    path, problem = tts_local.find_model("af_heart", repo="mlx-community/no-such-model-for-miguel")
    assert path is None and ("not installed" in problem or "not downloaded" in problem)


# --- the real model (macOS with `uv sync --group local` and the model downloaded) ----

def _real_model():
    path, problem = tts_local.find_model(tts_local.DEFAULT_VOICE)
    return path, problem


@pytest.mark.skipif(_real_model()[0] is None, reason="Kokoro (mlx-audio and the model) is not installed")
def test_the_real_model_speaks_a_line():
    tts = KokoroTTS(model_path=_real_model()[0])

    async def t():
        try:
            return await tts.synth("Here is your water, Mom.")
        finally:
            await tts.close()
    channels, width, rate, pcm = parse_wav(asyncio.run(t()))
    assert (channels, width, rate) == (1, 2, 24000)
    assert 1.0 < len(pcm) / 2 / rate < 4.0               # about 1.9 s of speech
    assert np.abs(np.frombuffer(pcm, "<i2")).max() > 1000   # not silence
