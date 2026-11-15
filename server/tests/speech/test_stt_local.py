"""Local speech to text (app/speech/stt_local.py, #81): VAD turns, partials, MicHub, fallbacks.

Fakes stand in for Silero and Parakeet (CI is Linux without MLX): a tone is "speech" and the fake
transcriber says one more word per 0.3 s of tone. The last tests use the real models and are
skipped unless the "local" group is installed and the model is cached (macOS).
"""

from __future__ import annotations

import asyncio
import logging
import threading
from types import SimpleNamespace

import numpy as np
import pytest

from app.mlx_lock import MLX_LOCK
from app.speech import stt_local
from app.speech.mic import MicHub
from app.speech.stt_local import FRAME, FRAME_S, RATE, LocalSTT, _keyterm_fixer, _Resampler

from .test_mic import FakeSTT

WORDS = "hey Miguel come here please and bring the blue cup".split()


def _rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(x)))) if len(x) else 0.0


class EnergyVad:
    def probs(self, frames):
        return [1.0 if _rms(f) > 0.02 else 0.0 for f in frames]


class FakeEngine:
    """Says one word of WORDS per 0.3 s of tone in the audio. Records how it was called."""

    def __init__(self, fail_load: bool = False, words: list[str] = WORDS) -> None:
        self.fail_load = fail_load
        self.words = words
        self.loads = 0
        self.calls: list[float] = []          # seconds of audio per transcription
        self.lock_held: list[bool] = []
        self.threads: set[int] = set()

    def load(self) -> None:
        self.loads += 1
        self.lock_held.append(MLX_LOCK.locked())
        if self.fail_load:
            raise RuntimeError("no model here")

    def new_vad(self):
        return EnergyVad()

    def transcribe(self, audio: np.ndarray) -> str:
        self.calls.append(len(audio) / RATE)
        self.lock_held.append(MLX_LOCK.locked())
        self.threads.add(threading.get_ident())
        voiced = sum(1 for i in range(0, len(audio) - FRAME + 1, FRAME) if _rms(audio[i:i + FRAME]) > 0.02)
        return " ".join(self.words[: int(voiced * FRAME_S / 0.3)])


def tone(seconds: float, rate: int = RATE) -> np.ndarray:
    t = np.arange(int(seconds * rate)) / rate
    return (0.3 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)


def silence(seconds: float, rate: int = RATE) -> np.ndarray:
    return np.zeros(int(seconds * rate), np.float32)


def pcm(*parts: np.ndarray) -> bytes:
    return (np.concatenate(parts) * 32767).astype("<i2").tobytes()


async def feed(session, data: bytes, rate: int = RATE, chunk_s: float = 0.1) -> None:
    """Send audio in phone-sized chunks, letting the worker (and its threads) keep up."""
    step = int(rate * chunk_s) * 2
    for i in range(0, len(data), step):
        session.send_audio(data[i:i + step])
        await asyncio.sleep(0.004)


async def settle(session, timeout: float = 2.0) -> None:
    """Wait until the session has processed everything sent so far."""
    for _ in range(int(timeout / 0.01)):
        if not session._pending and not session.in_turn:
            await asyncio.sleep(0.05)
            if not session._pending:
                return
        await asyncio.sleep(0.01)


def make(engine=None, **kw) -> LocalSTT:
    return LocalSTT(engine or FakeEngine(), **kw)


def recorder():
    events: list[tuple[str, str]] = []
    return events, lambda kind, text: events.append((kind, text))


# --- VAD segmentation --------------------------------------------------------------------------

def test_vad_segments_synthetic_audio_into_turns_and_drops_blips():
    async def main():
        engine = FakeEngine()
        stt = make(engine)
        events, on_event = recorder()
        s = await stt.session(None, on_event=on_event)
        await feed(s, pcm(silence(0.5), tone(1.0), silence(1.0),       # a turn
                          tone(0.1), silence(1.0),                       # a blip: under 250 ms
                          tone(1.5), silence(1.0)))                      # another turn
        await settle(s)
        got = [s.utterances.get_nowait() for _ in range(s.utterances.qsize())]
        await s.close()
        return engine, events, got

    engine, events, got = asyncio.run(main())
    kinds = [k for k, _ in events if k != "update"]
    assert kinds == ["start", "end", "start", "end", "start", "end"]
    ends = [t for k, t in events if k == "end"]
    assert ends == ["hey Miguel come", "", "hey Miguel come here please"]
    assert [u.text for u in got] == ["hey Miguel come", "hey Miguel come here please"]
    u = got[0]
    assert u.source == "senior" and u.meta["channel"] == "mic" and u.meta["stt"] == "local"
    assert u.meta["t_speech_end"] <= u.meta["t_final"]
    # the final transcription got the speech plus a little before and after, not the trailing silence
    assert 1.0 < u.meta["audio_s"] < 1.0 + 0.3 + 0.2 + 2 * FRAME_S
    assert u.meta["audio_s"] in [round(c, 2) for c in engine.calls]


def test_end_of_turn_waits_for_the_configured_silence():
    async def main(end_ms):
        stt = make(end_silence_ms=end_ms)
        events, on_event = recorder()
        s = await stt.session(None, on_event=on_event)
        await feed(s, pcm(tone(1.0), silence(0.4)))
        await settle(s, 0.3)
        ended_early = any(k == "end" for k, _ in events)
        await feed(s, pcm(silence(0.6)))
        await settle(s)
        await s.close()
        return ended_early, any(k == "end" for k, _ in events)

    assert asyncio.run(main(300)) == (True, True)
    assert asyncio.run(main(700)) == (False, True)


def test_long_speech_is_cut_at_the_cap():
    async def main():
        engine = FakeEngine()
        stt = make(engine, max_utterance_s=1.5, partial_every_s=10)
        s = await stt.session(None)
        await feed(s, pcm(tone(4.0), silence(1.0)))
        await settle(s)
        await s.close()
        return engine, s.utterances.qsize()

    engine, turns = asyncio.run(main())
    assert turns >= 2
    assert max(engine.calls) <= 1.5 + FRAME_S


# --- partials, then the final ------------------------------------------------------------------

def test_partials_while_they_talk_then_one_final():
    async def main():
        engine = FakeEngine()
        stt = make(engine)
        events, on_event = recorder()
        s = await stt.session(None, on_event=on_event)
        await feed(s, pcm(tone(3.0), silence(1.0)))
        await settle(s)
        await s.close()
        return engine, events, s.utterances.get_nowait()

    engine, events, u = asyncio.run(main())
    kinds = [k for k, _ in events]
    assert kinds[0] == "start" and kinds[-1] == "end"
    updates = [t for k, t in events if k == "update"]
    assert len(updates) >= 2                                   # about one every 0.7 s of audio
    assert all(WORDS[: len(t.split())] == t.split() for t in updates)
    assert len(set(updates)) == len(updates)                  # only changes are sent
    assert events[-1] == ("end", " ".join(WORDS[:10]))
    assert u.text == events[-1][1]
    assert all(engine.lock_held)                               # every model call held MLX_LOCK...
    assert threading.main_thread().ident not in engine.threads  # ...in a worker thread


def test_closing_mid_turn_transcribes_what_was_said():
    async def main():
        stt = make()
        s = await stt.session(None)
        await feed(s, pcm(tone(1.0)))
        await s.close()
        return s.utterances.get_nowait()

    assert asyncio.run(main()).text == "hey Miguel come"


# --- through MicHub --------------------------------------------------------------------------

class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def test_wake_word_in_a_partial_turns_the_ring_on_before_they_finish():
    async def main():
        stt = make()
        inbox: asyncio.Queue = asyncio.Queue()
        hub = MicHub(stt, inbox, "Miguel", clock=Clock())
        seen = []

        def on_event(kind, text):
            hub.on_stt_event(kind, text)
            seen.append((kind, text, hub.listening()))

        s = await stt.session(hub.on_heard, on_event=on_event)
        await feed(s, pcm(tone(1.0)))                 # still talking
        await asyncio.sleep(0.1)
        ring_mid_sentence = hub.listening() and hub.listen_reason() == "wake"
        await feed(s, pcm(tone(0.6), silence(1.0)))
        await settle(s)
        await s.close()
        return ring_mid_sentence, seen, inbox.get_nowait(), hub

    ring, seen, u, hub = asyncio.run(main())
    assert ring
    first_on = next(i for i, (_, _, on) in enumerate(seen) if on)
    assert seen[first_on][0] == "update" and "Miguel" in seen[first_on][1]
    assert seen[-1][0] == "end"
    assert u.text == "come here please" and u.meta["via"] == "wake" and u.meta["addressed"] is True
    assert u.meta["raw"] == "hey Miguel come here please"
    assert not hub.listening()


def test_half_duplex_muted_mic_while_miguel_talks_then_his_question_opens_the_answer_window():
    async def main():
        clock = Clock()
        stt = make(FakeEngine(words="yes please i would love some".split()))
        inbox: asyncio.Queue = asyncio.Queue()
        hub = MicHub(stt, inbox, "Miguel", clock=clock)
        events, on_event = recorder()

        def both(kind, text):
            hub.on_stt_event(kind, text)
            on_event(kind, text)

        s = await stt.session(hub.on_heard, on_event=both)
        hub._control('{"type": "voice", "busy": true, "text": "Would you like some tea?"}')
        await feed(s, pcm(silence(2.0)))              # the phone sends zeros while he talks
        await settle(s)
        during = (list(events), hub.listening())
        hub._control('{"type": "voice", "busy": false}')
        await feed(s, pcm(tone(1.0), silence(1.0)))   # an answer: no wake word needed
        await settle(s)
        await s.close()
        return during, inbox.get_nowait(), hub

    (events_during, listening_during), u, hub = asyncio.run(main())
    assert events_during == [] and listening_during is False
    assert u.text == "yes please i" and u.meta["via"] == "question"
    assert hub.ignored == 0


def test_speech_during_his_line_does_not_light_the_ring():
    """If the phone ever leaks audio while he talks, the wake word in a partial doesn't show the ring."""
    async def main():
        stt = make()
        hub = MicHub(stt, asyncio.Queue(), "Miguel", clock=Clock())
        s = await stt.session(hub.on_heard, on_event=hub.on_stt_event)
        hub._control('{"type": "voice", "busy": true, "text": "Here you go."}')
        await feed(s, pcm(tone(1.5)))
        await asyncio.sleep(0.1)
        lit = hub.listening()
        await s.close()
        return lit

    assert asyncio.run(main()) is False


# --- rates, keyterms, loading and fallbacks --------------------------------------------------------

def test_48k_audio_is_resampled_to_16k():
    async def main():
        engine = FakeEngine()
        stt = make(engine, partial_every_s=10)
        s = await stt.session(None, sample_rate=48000)   # soxr here if installed, else linear
        await feed(s, pcm(silence(0.3, 48000), tone(1.2, 48000), silence(1.0, 48000)), rate=48000)
        await settle(s)
        await s.close()
        return engine, s.utterances.get_nowait()

    engine, u = asyncio.run(main())
    assert u.text == "hey Miguel come here"
    assert 1.2 < u.meta["audio_s"] < 1.2 + 0.3 + 0.2 + 2 * FRAME_S


def test_linear_resampler_keeps_its_place_across_chunks():
    r = _Resampler(48000)
    r._soxr = None                                  # the fallback path (no soxr on CI)
    x = np.sin(np.arange(48000) / 48000 * 2 * np.pi * 5).astype(np.float32)
    out = np.concatenate([r(x[i:i + 1000]) for i in range(0, len(x), 1000)])
    assert abs(len(out) - 16000) <= 1
    assert np.allclose(out, x[::3][: len(out)], atol=1e-3)


def test_keyterm_near_misses_are_spelled_right():
    fix = _keyterm_fixer(["Miguel"])
    assert fix("hey migel come here") == "hey Miguel come here"
    assert fix("Miguell, stop") == "Miguel, stop"
    assert fix("miguel") == "Miguel"
    assert fix("Michael and Manuel are here") == "Michael and Manuel are here"   # real names stay


def test_model_calls_never_on_the_event_loop_and_loading_in_the_background():
    async def main():
        engine = FakeEngine()
        stt = make(engine)
        task = stt.start_loading()
        assert stt.start_loading() is task         # once
        assert await stt.ready() is True
        return engine, stt

    engine, stt = asyncio.run(main())
    assert engine.loads == 1 and engine.lock_held == [True] and stt.loaded is True


def test_start_loading_without_a_loop_waits_for_the_first_session():
    stt = make()
    assert stt.start_loading() is None and stt.loaded is None


def test_failed_load_hands_the_audio_to_the_fallback(caplog):
    caplog.set_level(logging.INFO, "app.speech.stt_local")
    fallback = FakeSTT()

    async def main():
        stt = make(FakeEngine(fail_load=True), fallback=lambda: fallback)
        events, on_event = recorder()
        s = await stt.session(None, on_event=on_event)
        s.send_audio(b"\x01\x02" * 100)
        for _ in range(200):
            if fallback.sessions and fallback.sessions[0].audio:
                break
            await asyncio.sleep(0.01)
        s.send_audio(b"\x03\x04")
        later = await stt.session(None)           # after the failure: straight to the fallback
        await stt.close()
        return s, later

    s, later = asyncio.run(main())
    assert bytes(fallback.sessions[0].audio) == b"\x01\x02" * 100 + b"\x03\x04"
    assert later is fallback.sessions[1]
    assert "loading" in caplog.text and "no model here" in caplog.text


def test_failed_load_without_a_fallback_drops_the_audio(caplog):
    async def main():
        stt = make(FakeEngine(fail_load=True))
        s = await stt.session(None)
        s.send_audio(b"\x01\x02" * 100)
        await asyncio.sleep(0.1)
        await s.close()
        return s

    s = asyncio.run(main())
    assert s.utterances.empty() and "dropping the phone's audio" in caplog.text


def test_from_env_says_why_when_unavailable(monkeypatch, caplog):
    monkeypatch.setattr(stt_local, "missing_packages", lambda: ["mlx", "parakeet_mlx"])
    assert LocalSTT.from_env({}) is None
    assert "uv sync --group local" in caplog.text
    monkeypatch.setattr(stt_local, "missing_packages", lambda: [])
    monkeypatch.setattr(stt_local, "find_model", lambda m: None)
    assert LocalSTT.from_env({"MIGUEL_STT_MODEL": "someone/missing"}) is None
    assert "someone/missing is not in the Hugging Face cache" in caplog.text


def test_from_env_settings(monkeypatch, tmp_path):
    monkeypatch.setattr(stt_local, "missing_packages", lambda: [])
    (tmp_path / "config.json").write_text("{}")
    (tmp_path / "model.safetensors").write_bytes(b"")
    stt = LocalSTT.from_env({"MIGUEL_STT_MODEL": str(tmp_path), "MIGUEL_STT_END_SILENCE_MS": "500",
                             "MIGUEL_STT_PARTIAL_S": "1", "MIGUEL_STT_MAX_S": "x",
                             "CARTESIA_STT_KEYTERMS": "Miguel, Margaret"})
    assert stt is not None and stt.model == str(tmp_path) and stt.engine.model_dir == str(tmp_path)
    assert stt.end_silence_frames == round(0.5 / FRAME_S)
    assert stt.partial_every == RATE and stt.max_samples == 15 * RATE
    assert stt.keyterms == ("Miguel", "Margaret")


def test_find_model_needs_both_files(tmp_path):
    assert stt_local.find_model(str(tmp_path)) is None
    (tmp_path / "config.json").write_text("{}")
    (tmp_path / "model.safetensors").write_bytes(b"")
    assert stt_local.find_model(str(tmp_path)) == str(tmp_path)


# --- make_hearing (app/__main__.py) --------------------------------------------------------------

def _state():
    return SimpleNamespace(agent_inbox=asyncio.Queue(), mic=None)


def test_make_hearing_default_is_cartesia(monkeypatch):
    from app.__main__ import make_hearing
    from app.speech.stt import CartesiaSTT

    monkeypatch.delenv("MIGUEL_STT", raising=False)
    monkeypatch.setenv("CARTESIA_API_KEY", "k")
    state = _state()
    stt = make_hearing(state, "Miguel")
    assert isinstance(stt, CartesiaSTT) and state.mic.hub.stt is stt


def test_make_hearing_local(monkeypatch):
    from app.__main__ import make_hearing

    made = make()
    seen = {}

    def from_env(env=None, *, fallback=None):
        seen["fallback"] = fallback
        return made

    monkeypatch.setenv("MIGUEL_STT", "local")
    monkeypatch.setenv("CARTESIA_API_KEY", "k")
    monkeypatch.setattr(LocalSTT, "from_env", staticmethod(from_env))
    state = _state()
    stt = make_hearing(state, "Miguel")
    assert stt is made and state.mic.hub.stt is made and callable(seen["fallback"])


def test_make_hearing_local_unavailable_falls_back_to_cartesia(monkeypatch, caplog):
    from app.__main__ import make_hearing
    from app.speech.stt import CartesiaSTT

    monkeypatch.setenv("MIGUEL_STT", "local")
    monkeypatch.setenv("CARTESIA_API_KEY", "k")
    monkeypatch.setattr(LocalSTT, "from_env", staticmethod(lambda env=None, *, fallback=None: None))
    stt = make_hearing(_state(), "Miguel")
    assert isinstance(stt, CartesiaSTT) and "trying Cartesia" in caplog.text
    monkeypatch.delenv("CARTESIA_API_KEY")
    state = _state()
    assert make_hearing(state, "Miguel") is None and state.mic.hub.stt is None   # /mic still mounted


# --- the real models (macOS with `uv sync --group local` and the model cached) --------------------

def _real_or_skip():
    if stt_local.missing_packages():
        pytest.skip("local speech packages not installed (uv sync --group local)")
    if stt_local.find_model(stt_local.DEFAULT_MODEL) is None:
        pytest.skip("Parakeet model not in the Hugging Face cache")


def test_real_models_hear_kokoro_speech():
    _real_or_skip()
    try:
        import misaki.espeak  # noqa: F401  sets espeak-ng's paths
        import soxr
        from mlx_audio.tts.utils import load_model
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"Kokoro unavailable: {e}")
    try:
        from huggingface_hub import snapshot_download

        snapshot_download("mlx-community/Kokoro-82M-bf16", local_files_only=True)
    except Exception:  # noqa: BLE001
        pytest.skip("Kokoro model not in the Hugging Face cache")

    from app.speech.tts_local import _short_espeak_data

    _short_espeak_data()   # espeak-ng ignores a long data path (a deep checkout) and the process dies
    with MLX_LOCK:
        tts = load_model("mlx-community/Kokoro-82M-bf16")
        audio24 = np.concatenate([np.asarray(r.audio, np.float32) for r in tts.generate(
            text="Hey Miguel, bring me my glasses please.", voice="af_heart", speed=1.0, lang_code="a")])
    speech = soxr.resample(audio24, 24000, RATE).astype(np.float32)

    async def main():
        stt = LocalSTT.from_env({})
        assert stt is not None and await stt.ready()
        hub = MicHub(stt, asyncio.Queue(), "Miguel")
        s = await stt.session(hub.on_heard, on_event=hub.on_stt_event)
        await feed(s, pcm(silence(0.5), speech, silence(1.2)))
        await settle(s, 5)
        await s.close()
        return hub.inbox.get_nowait()

    u = asyncio.run(main())
    assert "glasses" in u.text.lower() and u.meta["via"] == "wake"
