"""Miguel's cloned voice (#84): Qwen3-TTS behind MIGUEL_TTS=clone, with a fake model. The real-model
test runs only where mlx-audio, the model and the reference clip are present (CI skips it)."""

from __future__ import annotations

import asyncio
import io
import wave
from pathlib import Path

import numpy as np
import pytest

import app.__main__ as server
from app.speech import tts_local
from app.speech.tts_local import CLONE_REF, KokoroTTS, QwenCloneEngine, find_clone


class FakeChunk:
    def __init__(self, n):
        self.audio = np.full(n, 0.1, dtype=np.float32)


class FakeQwen:
    def __init__(self):
        self.calls = []

    def generate(self, **kw):
        self.calls.append(kw)
        yield FakeChunk(240)
        yield FakeChunk(120)


def engine_with(model) -> QwenCloneEngine:
    e = QwenCloneEngine(Path("/m"), Path("/r.wav"), "the reference words")
    e._model, e._ref = model, "REF"
    return e


def test_each_sentence_is_streamed_with_the_reference():
    qwen = FakeQwen()
    chunks = list(engine_with(qwen).segments("On it! I'll bring your water.  ", "clone:full", 1.0))
    assert [c.size for c in chunks] == [240, 120, 240, 120]
    assert [c["text"] for c in qwen.calls] == ["On it!", "I'll bring your water."]
    for kw in qwen.calls:
        assert kw["ref_audio"] == "REF" and kw["ref_text"] == "the reference words"
        assert kw["stream"] is True and kw["lang_code"] == "english" and kw["split_pattern"] == ""


def test_the_client_makes_one_wav_from_the_streamed_chunks():
    tts = KokoroTTS("clone:full", engine=_Loaded(engine_with(FakeQwen())), lock=_NoLock())
    wav = asyncio.run(_say(tts, "On it!"))
    with wave.open(io.BytesIO(wav)) as w:
        pad = round((tts_local.LEAD_SILENCE_S + tts_local.TAIL_SILENCE_S) * 24000)   # silence around the line (#91)
        assert w.getframerate() == 24000 and w.getnframes() == 360 + pad


class _Loaded:
    """The engine with load/prepare as no-ops (the fake model is already in place)."""

    def __init__(self, e):
        self.e = e

    def load(self):
        pass

    def prepare(self):
        pass

    def segments(self, *a):
        return self.e.segments(*a)


class _NoLock:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


async def _say(tts, text):
    try:
        return await tts.synth(text)
    finally:
        await tts.close()


def test_find_clone_explains_what_is_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(tts_local.importlib.util, "find_spec", lambda m: object())
    path, text, why = find_clone(ref=tmp_path / "nope.wav")
    assert path is None and "reference clip" in why
    (tmp_path / "v.wav").write_bytes(b"RIFF")
    path, text, why = find_clone(ref=tmp_path / "v.wav")
    assert path is None and "transcript" in why
    (tmp_path / "v.txt").write_text("  Good   morning!\n")

    def missing(*a, **k):
        raise FileNotFoundError("not cached")

    import sys
    import types

    huggingface_hub = types.ModuleType("huggingface_hub")   # CI doesn't install it (local group only)
    monkeypatch.setitem(sys.modules, "huggingface_hub", huggingface_hub)
    monkeypatch.setattr(huggingface_hub, "snapshot_download", missing, raising=False)
    path, text, why = find_clone(ref=tmp_path / "v.wav")
    assert path is None and "hf download" in why
    snap = tmp_path / "snap"
    snap.mkdir()
    (snap / "config.json").write_text("{}")
    monkeypatch.setattr(huggingface_hub, "snapshot_download", lambda *a, **k: str(snap))
    assert find_clone(ref=tmp_path / "v.wav") == (snap, "Good morning!", None)


def test_make_tts_clone_and_its_fallbacks(monkeypatch, caplog):
    caplog.set_level("INFO")
    monkeypatch.setenv("MIGUEL_TTS", "clone")
    sentinel = object()
    monkeypatch.setattr(KokoroTTS, "clone_from_env", classmethod(lambda cls, env=None: sentinel))
    assert server.make_tts() is sentinel
    # no clone: Kokoro; no Kokoro either: Cartesia (here: no key, so Safari's voice)
    monkeypatch.setattr(KokoroTTS, "clone_from_env", classmethod(lambda cls, env=None: None))
    kokoro = type("FakeKokoro", (), {"voice": "af_heart"})()
    monkeypatch.setattr(KokoroTTS, "from_env", classmethod(lambda cls, env=None: kokoro))
    assert server.make_tts() is kokoro
    assert "MIGUEL_TTS=clone but the cloned voice is unavailable; trying Kokoro" in caplog.text
    monkeypatch.setattr(KokoroTTS, "from_env", classmethod(lambda cls, env=None: None))
    monkeypatch.delenv("CARTESIA_API_KEY", raising=False)
    assert server.make_tts() is None


def test_real_cloned_voice_speaks():
    pytest.importorskip("mlx_audio")
    path, ref_text, why = find_clone()
    if path is None:
        pytest.skip(f"cloned voice unavailable: {why}")
    tts = KokoroTTS.clone_from_env({})
    assert tts is not None and tts.voice == f"clone:{Path(CLONE_REF).stem}"
    wav = asyncio.run(_say(tts, "On it!"))
    with wave.open(io.BytesIO(wav)) as w:
        assert w.getframerate() == 24000 and 0.3 < w.getnframes() / 24000 < 4.0


class ThreadRecorder:
    """An engine that notes which thread runs load and each generator step (MLX streams are per thread)."""

    def __init__(self):
        self.threads = []

    def load(self):
        import threading

        self.threads.append(threading.get_ident())

    def prepare(self):
        pass

    def segments(self, text, voice, speed):
        import threading
        import time

        for _ in range(4):
            time.sleep(0.01)
            self.threads.append(threading.get_ident())
            yield np.zeros(240, dtype=np.float32)


def test_every_model_step_runs_on_one_thread_even_when_the_pool_is_busy():
    import threading

    eng = ThreadRecorder()
    tts = KokoroTTS("clone:full", engine=eng, lock=_NoLock())

    async def run():
        busy = [asyncio.to_thread(__import__("time").sleep, 0.05) for _ in range(8)]   # other work in the pool
        try:
            await asyncio.gather(tts.synth("One. Two."), tts.synth("Three."), *busy)
        finally:
            await tts.close()

    asyncio.run(run())
    assert len(eng.threads) >= 9 and len(set(eng.threads)) == 1
    assert eng.threads[0] != threading.get_ident()   # never the event loop's thread
