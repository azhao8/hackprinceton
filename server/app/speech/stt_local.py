"""Local speech to text (issue #81): Miguel's ears without the network.

A drop-in for `CartesiaSTT` (app/speech/stt.py): MicHub calls `session(on_utterance, sample_rate=,
on_event=)`, pushes raw mono s16le audio with `send_audio()`, hears the turn's progress through
`on_event(kind, text)` ("start", "update", "end") and gets each finished turn as
`Utterance(source="senior", text, meta)`. Switch it on with MIGUEL_STT=local (default: cartesia).

How a turn is found and transcribed:
- Silero VAD (silero-vad, CPU, about 0.2 ms per 32 ms frame) scores every 512-sample frame of
  16 kHz audio. Two speech frames in a row start a turn ("start"; 300 ms of audio before them is
  kept so the first syllable isn't cut). MIGUEL_STT_END_SILENCE_MS (600) of silence ends it.
- While they talk, the audio so far is re-transcribed every MIGUEL_STT_PARTIAL_S (0.7 s of audio):
  a changed text goes out as "update", so MicHub spots "Miguel" mid-sentence and the ring and ping
  start before they finish (as with Cartesia's running transcript). These partials may revise
  earlier words; MicHub only looks for the wake word in them.
- At the end of speech one transcription of the whole turn makes the final text ("end", then the
  Utterance). A turn is capped at MIGUEL_STT_MAX_S (15 s): it is cut there and the rest of the
  speech starts a new turn. Under 250 ms of speech is a blip: an empty "end", nothing delivered.
- Parakeet TDT 0.6B v3 (parakeet-mlx, on the GPU) transcribes: about 40 ms for 2 s of speech and
  70 ms for 6 s on the M5 Pro. Its streaming API costs ~150 ms per call whatever the chunk size,
  so partials re-run the batch model on the whole turn instead.
- Parakeet has no keyterm boost, so near misses of the keyterms (default "Miguel", from
  CARTESIA_STT_KEYTERMS when set) are spelled right afterwards ("Migel" -> "Miguel").
- Audio at another rate than 16 kHz is resampled (soxr's stream resampler when installed).

Threads: every Parakeet call runs in a worker thread (asyncio.to_thread) holding
`app.mlx_lock.MLX_LOCK`, shared with the local voice, never on the event loop. Silero is torch on
the CPU, not MLX, so it runs in a worker thread without that lock (it would otherwise wait behind
the voice for each 32 ms frame). A partial that is stale by the time it gets the lock is skipped.

Startup: `from_env()` only checks that the packages are installed and the model is in the Hugging
Face cache (local files only: no network, with or without HF_HUB_OFFLINE). `start_loading()` then
loads and warms up the models in the background (about 2 s); audio that arrives before that waits
(up to 10 s of it). If loading fails anyway, sessions hand over to the fallback (a factory that
makes a CartesiaSTT, called once, when needed) if it gives one, else drop the audio with one log line.

Timing meta, as Cartesia's: `t_speech_end` (time.monotonic() when the last speech frame arrived)
and `t_final` (the final text is ready); app/speech/timing.py logs both per turn.

Settings (env): MIGUEL_STT_MODEL (Hugging Face id or a local folder, default
mlx-community/parakeet-tdt-0.6b-v3), MIGUEL_STT_END_SILENCE_MS (600), MIGUEL_STT_PARTIAL_S (0.7),
MIGUEL_STT_MAX_S (15), MIGUEL_STT_VAD_THRESHOLD (0.5).
"""

from __future__ import annotations

import asyncio
import contextlib
import difflib
import importlib.util
import inspect
import logging
import os
import re
import time
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from app.brain.types import Utterance
from app.mlx_lock import MLX_LOCK
from app.speech.stt import DEFAULT_KEYTERMS, SAMPLE_RATE_RANGE, EventCallback, UtteranceCallback

log = logging.getLogger("app.speech.stt_local")

DEFAULT_MODEL = "mlx-community/parakeet-tdt-0.6b-v3"
RATE = 16000              # what Silero and Parakeet take
FRAME = 512               # Silero's window at 16 kHz: 32 ms
FRAME_S = FRAME / RATE
REQUIRED_PACKAGES = ("mlx", "parakeet_mlx", "silero_vad", "torch", "huggingface_hub")


# --- the models (real ones need the "local" dependency group; tests use fakes) -----------------

class Vad(Protocol):
    def probs(self, frames: Sequence[np.ndarray]) -> list[float]:
        """Speech probability of each 512-sample float32 frame, in order (the model keeps state)."""
        ...


class Engine(Protocol):
    def load(self) -> None:
        """Load and warm up the models (slow, blocking: called in a worker thread)."""
        ...

    def new_vad(self) -> Vad:
        """A fresh voice activity detector for one stream."""
        ...

    def transcribe(self, audio: np.ndarray) -> str:
        """Text of 16 kHz mono float32 audio (blocking; the caller holds MLX_LOCK)."""
        ...


class SileroVad:
    def __init__(self) -> None:
        import torch
        from silero_vad import load_silero_vad

        self._torch = torch
        self._model = load_silero_vad()

    def probs(self, frames: Sequence[np.ndarray]) -> list[float]:
        torch = self._torch
        with torch.inference_mode():
            return [float(self._model(torch.from_numpy(f), RATE).item()) for f in frames]


class MlxEngine:
    """Parakeet (parakeet-mlx) for the words, Silero for speech/no speech."""

    def __init__(self, model_dir: str) -> None:
        self.model_dir = model_dir
        self._model: Any = None

    def load(self) -> None:
        import mlx.core as mx
        from parakeet_mlx import from_pretrained
        from parakeet_mlx.audio import get_logmel

        self._mx, self._logmel = mx, get_logmel
        # a local folder: parakeet-mlx tries hf_hub_download first, which fails on a path without
        # touching the network, then reads the folder
        self._model = from_pretrained(self.model_dir)
        SileroVad().probs([np.zeros(FRAME, np.float32)])                    # loads, and fails here if broken
        rng = np.random.default_rng(0)
        self.transcribe((0.01 * rng.standard_normal(RATE)).astype(np.float32))   # compiles the kernels

    def new_vad(self) -> Vad:
        return SileroVad()

    def transcribe(self, audio: np.ndarray) -> str:
        mel = self._logmel(self._mx.array(audio), self._model.preprocessor_config)
        return self._model.generate(mel)[0].text


def missing_packages() -> list[str]:
    return [p for p in REQUIRED_PACKAGES if importlib.util.find_spec(p) is None]


def find_model(model: str) -> str | None:
    """The local folder holding the model's config.json and model.safetensors, from a path or the
    Hugging Face cache. Never uses the network. None if it isn't there."""
    if os.path.isdir(model):
        folder = model
    else:
        try:
            from huggingface_hub import snapshot_download

            folder = snapshot_download(model, local_files_only=True)
        except Exception:  # noqa: BLE001 - not cached (or no huggingface_hub): not available
            return None
    ok = all((Path(folder) / f).is_file() for f in ("config.json", "model.safetensors"))
    return str(folder) if ok else None


# --- small helpers ----------------------------------------------------------------------------

def _env_num(env: Mapping[str, str], name: str, default: float) -> float:
    raw = (env.get(name) or "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        log.warning("%s=%r is not a number: using %g", name, raw, default)
        return default
    if value <= 0:
        log.warning("%s=%r must be above 0: using %g", name, raw, default)
        return default
    return value


class _Resampler:
    """Mono float32 stream resampler to 16 kHz: soxr's stream resampler if installed, else linear
    interpolation that carries its position across chunks."""

    def __init__(self, rate: int) -> None:
        self.rate = rate
        self._soxr: Any = None
        self._pos = 0.0                # next output position, in input samples, from the start of _last
        self._last: np.ndarray = np.zeros(0, np.float32)
        if rate != RATE:
            try:
                import soxr

                self._soxr = soxr.ResampleStream(rate, RATE, 1, dtype="float32")
            except Exception:  # noqa: BLE001 - optional: fall back to linear
                self._soxr = None

    def __call__(self, x: np.ndarray) -> np.ndarray:
        if self.rate == RATE or not len(x):
            return x
        if self._soxr is not None:
            return np.asarray(self._soxr.resample_chunk(x), np.float32)
        buf = np.concatenate([self._last, x])
        step = self.rate / RATE
        n = int(np.floor((len(buf) - 1 - self._pos) / step)) + 1 if len(buf) > self._pos + 1 else 0
        idx = self._pos + step * np.arange(max(n, 0))
        out = np.interp(idx, np.arange(len(buf)), buf).astype(np.float32)
        self._pos += step * max(n, 0)
        keep = min(int(np.floor(self._pos)), len(buf))
        self._last, self._pos = buf[keep:], self._pos - keep
        return out


def _keyterm_fixer(keyterms: Sequence[str]) -> Callable[[str], str]:
    """Spell near misses of one-word keyterms right: "migel" -> "Miguel" (Parakeet has no boost).
    Conservative: same first letter, length within 2, similarity 0.8 or more."""
    terms = [t for t in keyterms if t and len(t.split()) == 1 and len(t) >= 4]
    if not terms:
        return lambda s: s

    def fix_word(m: re.Match[str]) -> str:
        word = m.group(0)
        low = word.lower()
        for t in terms:
            tl = t.lower()
            if low == tl:
                return t
            if (low[0] == tl[0] and abs(len(low) - len(tl)) <= 2
                    and difflib.SequenceMatcher(None, low, tl).ratio() >= 0.8):
                return t
        return word

    return lambda s: re.sub(r"[A-Za-z]+", fix_word, s)


# --- the factory ------------------------------------------------------------------------------

class LocalSTT:
    """Factory for local speech-to-text sessions (same interface as CartesiaSTT)."""

    def __init__(
        self,
        engine: Engine,
        *,
        model: str = DEFAULT_MODEL,
        keyterms: Sequence[str] = DEFAULT_KEYTERMS,
        end_silence_ms: float = 600,
        partial_every_s: float = 0.7,
        max_utterance_s: float = 15.0,
        vad_threshold: float = 0.5,
        start_frames: int = 2,
        preroll_ms: float = 300,
        min_speech_ms: float = 250,
        tail_ms: float = 200,
        max_backlog_s: float = 10.0,
        fallback: Callable[[], Any] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.engine = engine
        self.model = model
        self.keyterms = tuple(" ".join(str(t).split()) for t in keyterms if str(t).strip())
        self._fix = _keyterm_fixer(self.keyterms)
        self.end_silence_frames = max(1, round(end_silence_ms / 1000 / FRAME_S))
        self.partial_every = max(FRAME, round(partial_every_s * RATE))      # samples
        self.max_samples = max(FRAME, round(max_utterance_s * RATE))
        self.threshold = float(vad_threshold)
        self.neg_threshold = max(0.01, self.threshold - 0.15)              # Silero's VADIterator does the same
        self.start_frames = max(1, int(start_frames))
        self.preroll_frames = max(0, round(preroll_ms / 1000 / FRAME_S))
        self.min_speech_frames = max(1, round(min_speech_ms / 1000 / FRAME_S))
        self.tail_frames = max(0, round(tail_ms / 1000 / FRAME_S))
        self.max_backlog_s = max_backlog_s
        self._fallback_factory = fallback
        self._fallback: Any = None
        self.clock = clock
        self._sessions: set[LocalSttSession] = set()
        self._load_task: asyncio.Future[bool] | None = None
        self.loaded: bool | None = None       # None: not yet; True: ready; False: failed
        self.load_error: str | None = None

    def __repr__(self) -> str:
        return f"LocalSTT(model={self.model!r}, keyterms={self.keyterms!r}, loaded={self.loaded})"

    @classmethod
    def from_env(cls, env: Mapping[str, str] = os.environ, *,
                 fallback: Callable[[], Any] | None = None) -> LocalSTT | None:
        """Build from MIGUEL_STT_* variables, or None (with a log line saying why) if the packages
        or the model aren't on this machine. Doesn't load the model: call start_loading()."""
        missing = missing_packages()
        if missing:
            log.warning("local hearing unavailable: missing %s (run: cd server && uv sync --group local)",
                        ", ".join(missing))
            return None
        model = (env.get("MIGUEL_STT_MODEL") or "").strip() or DEFAULT_MODEL
        folder = find_model(model)
        if folder is None:
            log.warning("local hearing unavailable: model %s is not in the Hugging Face cache "
                        "(download it once with network: uv run hf download %s)", model, model)
            return None
        raw_terms = env.get("CARTESIA_STT_KEYTERMS")
        terms = DEFAULT_KEYTERMS if raw_terms is None else raw_terms.split(",")
        stt = cls(
            MlxEngine(folder),
            model=model,
            keyterms=terms,
            end_silence_ms=_env_num(env, "MIGUEL_STT_END_SILENCE_MS", 600),
            partial_every_s=_env_num(env, "MIGUEL_STT_PARTIAL_S", 0.7),
            max_utterance_s=_env_num(env, "MIGUEL_STT_MAX_S", 15.0),
            vad_threshold=min(0.95, _env_num(env, "MIGUEL_STT_VAD_THRESHOLD", 0.5)),
            fallback=fallback,
        )
        log.info("local hearing on: %s (Silero VAD, end after %d ms of silence), keyterms %s",
                 model, round(stt.end_silence_frames * FRAME_S * 1000), list(stt.keyterms) or "none")
        return stt

    def start_loading(self) -> asyncio.Future[bool] | None:
        """Load and warm up the models in a worker thread, in the background. Idempotent. Without a
        running event loop it does nothing: the first session starts the loading then."""
        if self._load_task is None:
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                return None
            self._load_task = asyncio.ensure_future(self._load())
        return self._load_task

    async def ready(self) -> bool:
        """Wait for the models; True if local hearing works."""
        task = self.start_loading()
        assert task is not None   # we are in a coroutine: there is a running loop
        return await asyncio.shield(task)

    def fallback(self) -> Any:
        """The fallback STT (made on first use), or None."""
        if self._fallback is None and self._fallback_factory is not None:
            factory, self._fallback_factory = self._fallback_factory, None
            try:
                self._fallback = factory()
            except Exception as e:  # noqa: BLE001 - no fallback, then
                log.warning("local hearing: the fallback failed to start (%s)", e)
        return self._fallback

    async def _load(self) -> bool:
        t0 = time.monotonic()
        try:
            await asyncio.to_thread(self._load_locked)
        except Exception as e:  # noqa: BLE001 - any failure means: not available
            self.loaded, self.load_error = False, f"{type(e).__name__}: {e}"
            log.error("local hearing: loading %s failed (%s)%s", self.model, self.load_error,
                      "; trying the fallback" if self._fallback_factory is not None else "; /mic drops the audio")
            return False
        self.loaded = True
        log.info("local hearing: %s loaded and warm in %.1f s", self.model, time.monotonic() - t0)
        return True

    def _load_locked(self) -> None:
        with MLX_LOCK:
            self.engine.load()

    async def session(
        self,
        on_utterance: UtteranceCallback | None = None,
        *,
        sample_rate: int = RATE,
        on_event: EventCallback | None = None,
    ) -> Any:
        """Start a live session. Audio that arrives before the models are loaded waits for them."""
        if not (SAMPLE_RATE_RANGE[0] <= int(sample_rate) <= SAMPLE_RATE_RANGE[1]):
            raise ValueError(f"sample_rate {sample_rate} is outside {SAMPLE_RATE_RANGE[0]}-{SAMPLE_RATE_RANGE[1]}")
        if self.loaded is False and (fallback := self.fallback()) is not None:
            return await fallback.session(on_utterance, sample_rate=sample_rate, on_event=on_event)
        s = LocalSttSession(self, int(sample_rate), on_utterance, on_event)
        self._sessions.add(s)
        s._start()
        return s

    async def close(self) -> None:
        """Close every open session and the fallback (server shutdown)."""
        sessions, self._sessions = list(self._sessions), set()
        if sessions:
            await asyncio.gather(*(s.close(drain_timeout_s=1.0) for s in sessions), return_exceptions=True)
        if self._fallback is not None:
            with contextlib.suppress(Exception):
                await self._fallback.close()
        if self._load_task is not None and not self._load_task.done():
            self._load_task.cancel()   # the thread finishes on its own; nobody waits for it

    # --- used by LocalSttSession ---------------------------------------------------------------

    async def transcribe(self, audio: np.ndarray, wanted: Callable[[], bool] | None = None) -> str | None:
        """Transcribe in a worker thread holding MLX_LOCK. None if `wanted()` turned False before
        the lock was free (a stale partial)."""
        return await asyncio.to_thread(self._transcribe_locked, audio, wanted)

    def _transcribe_locked(self, audio: np.ndarray, wanted: Callable[[], bool] | None) -> str | None:
        with MLX_LOCK:
            if wanted is not None and not wanted():
                return None
            t0 = time.perf_counter()
            text = self.engine.transcribe(audio)
            ms = 1000 * (time.perf_counter() - t0)
        log.debug("local STT: %.2f s of audio in %.0f ms%s", len(audio) / RATE, ms, " (partial)" if wanted else "")
        return self._fix(" ".join(str(text or "").split()))


# --- one stream -------------------------------------------------------------------------------

class LocalSttSession:
    """One live stream: `send_audio()`, the callbacks (or `utterances`), `close()`."""

    def __init__(self, stt: LocalSTT, sample_rate: int, on_utterance: UtteranceCallback | None,
                 on_event: EventCallback | None = None) -> None:
        self._stt = stt
        self.sample_rate = sample_rate
        self._on_utterance = on_utterance
        self._on_event = on_event
        self.utterances: asyncio.Queue[Utterance] = asyncio.Queue()
        self._pending = bytearray()           # audio not processed yet
        self._max_pending = int(stt.max_backlog_s * sample_rate) * 2
        self._t_audio = stt.clock()           # when the newest pending audio arrived
        self._wake = asyncio.Event()
        self._closing = False
        self._closed = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._delegate: Any = None            # the fallback's session, if loading failed
        self._resample = _Resampler(sample_rate)
        self._vad: Vad | None = None
        self._carry = np.zeros(0, np.float32) # 16 kHz audio short of a whole frame
        self._preroll: deque[np.ndarray] = deque(maxlen=max(stt.preroll_frames, stt.start_frames))
        self._run_frames = 0                  # speech frames in a row before a turn starts
        # the turn in progress
        self.in_turn = False
        self.turn_id = 0
        self._audio: list[np.ndarray] = []
        self._samples = 0
        self._silence = 0                     # frames of silence since the last speech frame
        self._speech_frames = 0
        self._last_speech_idx = 0             # index in _audio after the last speech frame
        self._t_spoke: float | None = None
        self._next_partial = 0
        self._partial = ""
        self._partial_task: asyncio.Task[None] | None = None
        self.turns = 0
        self.dropped_bytes = 0
        self.connected = True                 # CartesiaSTT's SttSession has it; MicHub doesn't read it

    def __repr__(self) -> str:
        return f"LocalSttSession(rate={self.sample_rate}, in_turn={self.in_turn}, turns={self.turns})"

    # --- public ---------------------------------------------------------------------------------

    def send_audio(self, pcm: bytes) -> None:
        """Queue raw mono s16le audio at `sample_rate`. Never blocks; keeps at most 10 s waiting."""
        if self._closing or not pcm:
            return
        if self._delegate is not None:
            self._delegate.send_audio(pcm)
            return
        self._pending += pcm
        self._t_audio = self._stt.clock()
        over = len(self._pending) - self._max_pending
        if over > 0:
            over += over % 2
            del self._pending[:over]
            self.dropped_bytes += over
        self._wake.set()

    async def close(self, drain_timeout_s: float = 3.0) -> None:
        """Process the audio already sent, finish a turn in progress, then stop."""
        if self._closing:
            await self._closed.wait()
            return
        self._closing = True
        self._wake.set()
        try:
            if self._task is not None:
                await asyncio.wait_for(asyncio.shield(self._task), drain_timeout_s)
        except TimeoutError:
            log.info("local STT: the last turn did not finish within %.1f s; closing anyway", drain_timeout_s)
        finally:
            for task in (self._task, self._partial_task):
                if task is not None and not task.done():
                    task.cancel()
                    with contextlib.suppress(asyncio.CancelledError, Exception):
                        await task
            if self._delegate is not None:
                with contextlib.suppress(Exception):
                    await self._delegate.close()
            self.connected = False
            self._stt._sessions.discard(self)
            self._closed.set()

    # --- the worker -----------------------------------------------------------------------------

    def _start(self) -> None:
        self._task = asyncio.ensure_future(self._run())

    async def _run(self) -> None:
        try:
            if not await self._stt.ready():
                await self._hand_over()
                return
            self._vad = await asyncio.to_thread(self._stt.engine.new_vad)
            while True:
                while not self._pending:
                    if self._closing:
                        break
                    self._wake.clear()
                    await self._wake.wait()
                if not self._pending:
                    break
                data, t_arrived = bytes(self._pending), self._t_audio
                self._pending.clear()
                await self._process(data, t_arrived)
            if self.in_turn:                  # closing mid-turn: transcribe what we have
                await self._end_turn()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - log it; the phone page keeps working, hearing stops
            log.exception("local STT: the session failed; hearing is off until the phone reconnects")

    async def _hand_over(self) -> None:
        fallback = self._stt.fallback()
        if fallback is None:
            log.warning("local STT: models not loaded (%s): dropping the phone's audio", self._stt.load_error)
            self._pending.clear()
            return
        self._delegate = await fallback.session(self._on_utterance, sample_rate=self.sample_rate,
                                                on_event=self._on_event)
        log.info("local STT: handed the phone's audio to %r", fallback)
        if self._pending:
            self._delegate.send_audio(bytes(self._pending))
            self._pending.clear()

    async def _process(self, data: bytes, t_arrived: float) -> None:
        n = len(data) - len(data) % 2
        x = np.frombuffer(data[:n], dtype="<i2").astype(np.float32) / 32768.0
        x16 = self._resample(x)
        buf = np.concatenate([self._carry, x16]) if len(self._carry) else x16
        whole = len(buf) // FRAME * FRAME
        frames = [buf[i:i + FRAME].copy() for i in range(0, whole, FRAME)]
        self._carry = buf[whole:].copy()
        if not frames:
            return
        assert self._vad is not None
        probs = await asyncio.to_thread(self._vad.probs, frames)
        for i, (frame, p) in enumerate(zip(frames, probs)):
            # when this frame's last sample arrived: the newest audio arrived at t_arrived
            t_end = t_arrived - (len(frames) - 1 - i) * FRAME_S - len(self._carry) / RATE
            await self._step(frame, p, t_end)

    async def _step(self, frame: np.ndarray, p: float, t_end: float) -> None:
        stt = self._stt
        speech = p >= stt.threshold
        if not self.in_turn:
            self._preroll.append(frame)
            self._run_frames = self._run_frames + 1 if speech else 0
            if self._run_frames >= stt.start_frames:
                self._begin(t_end)
            return
        self._audio.append(frame)
        self._samples += FRAME
        if speech:
            self._silence = 0
            self._speech_frames += 1
            self._last_speech_idx = len(self._audio)
            self._t_spoke = t_end
        elif p < stt.neg_threshold or self._silence:
            self._silence += 1
        if self._silence >= stt.end_silence_frames or self._samples >= stt.max_samples:
            if self._silence < stt.end_silence_frames:
                log.info("local STT: turn reached %.0f s: cutting it there", stt.max_samples / RATE)
            await self._end_turn()
        elif self._samples >= self._next_partial:
            self._next_partial = self._samples + stt.partial_every
            self._start_partial()

    def _begin(self, t_end: float) -> None:
        self.in_turn = True
        self.turn_id += 1
        self._audio = list(self._preroll)
        self._preroll.clear()
        self._samples = len(self._audio) * FRAME
        self._speech_frames = self._run_frames
        self._run_frames = 0
        self._silence = 0
        self._last_speech_idx = len(self._audio)
        self._t_spoke = t_end
        self._partial = ""
        self._next_partial = self._samples + self._stt.partial_every
        self._notify("start", "")

    def _start_partial(self) -> None:
        if self._partial_task is not None and not self._partial_task.done():
            return                            # one at a time: the next one goes after this one
        tid = self.turn_id
        audio = np.concatenate(self._audio)
        self._partial_task = asyncio.ensure_future(self._run_partial(tid, audio))

    def _wanted(self, tid: int) -> bool:
        return self.in_turn and self.turn_id == tid and not self._closing

    async def _run_partial(self, tid: int, audio: np.ndarray) -> None:
        try:
            text = await self._stt.transcribe(audio, wanted=lambda: self._wanted(tid))
        except Exception as e:  # noqa: BLE001 - a failed partial only costs the early ring
            log.warning("local STT: partial transcription failed: %s", e)
            return
        if text is None or not self._wanted(tid):
            return
        if text and text != self._partial:
            self._partial = text
            self._notify("update", text)

    async def _end_turn(self) -> None:
        stt = self._stt
        self.in_turn = False                  # stale partials see this at once
        self.turns += 1
        keep = min(len(self._audio), self._last_speech_idx + stt.tail_frames)
        audio, speech_frames, t_spoke = self._audio[:keep], self._speech_frames, self._t_spoke
        self._audio, self._samples, self._silence, self._partial = [], 0, 0, ""
        if speech_frames < stt.min_speech_frames or not audio:
            self._notify("end", "")          # a blip: nothing to deliver
            return
        try:
            text = await stt.transcribe(np.concatenate(audio)) or ""
        except Exception as e:  # noqa: BLE001 - the turn is lost, the stream goes on
            log.warning("local STT: transcription failed: %s", e)
            text = ""
        now = stt.clock()
        self._notify("end", text)
        if text:
            await self._deliver(Utterance(
                source="senior",
                text=text,
                t=now,
                meta={"channel": "mic", "confidence": None, "request_id": None, "model": stt.model,
                      "stt": "local", "t_speech_end": t_spoke if t_spoke is not None else now,
                      "t_final": now, "audio_s": round(len(audio) * FRAME_S, 2)},
            ))

    def _notify(self, kind: str, text: str) -> None:
        if self._on_event is None:
            return
        try:
            self._on_event(kind, text)
        except Exception as e:  # noqa: BLE001 - a bad callback must not kill the stream
            log.warning("local STT: event callback failed: %s", e)

    async def _deliver(self, u: Utterance) -> None:
        log.info("STT heard (local): %r", u.text[:120])
        if self._on_utterance is None:
            self.utterances.put_nowait(u)
            return
        try:
            r = self._on_utterance(u)
            if inspect.isawaitable(r):
                await r
        except Exception as e:  # noqa: BLE001 - a bad callback must not kill the stream
            log.warning("local STT: utterance callback failed: %s", e)
