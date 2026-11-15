"""Local text to speech (issue #81): Miguel's voice from Kokoro-82M on this Mac, as WAV bytes.

`KokoroTTS` has the same interface as `CartesiaTTS` (synth, stream, cached, prewarm, close; an LRU
cache; concurrent calls for one line share one synthesis; failures raise TTSError), so the API's
`/tts` route and prefetch use it unchanged. Turn it on with MIGUEL_TTS=local (default: cartesia);
MIGUEL_KOKORO_VOICE picks the voice (default af_heart). Needs `uv sync --group local` and the model
in the Hugging Face cache (`uv run hf download mlx-community/Kokoro-82M-bf16`).

Audio: WAV, PCM 16-bit, 24 kHz, mono (MEDIA_TYPE audio/wav, so `/tts` sends that Content-Type).
iOS Safari plays it in an <audio> element; no ffmpeg needed.

Streaming: `stream()` yields the whole line once it is made. A WAV header carries the data length,
so the first bytes can't go out before the last sentence is done (and the phone builds a blob from
the whole body anyway). Kokoro is fast enough that it doesn't matter: measured on the M5 Pro, about
0.06 s for "Here is your water, Mom." and about 0.17 s for three sentences.

Model calls run in a worker thread (asyncio.to_thread) holding app.mlx_lock.MLX_LOCK, one sentence at
a time (split on . ! ?), so local hearing gets a turn between sentences and the event loop never
blocks. Lines are made one at a time, in order. `prewarm()` (run in the background at startup)
loads the model and warms it up first: the first line otherwise takes about 3 s (spaCy loading).

Offline: the model and voice are read from the local Hugging Face cache only (never downloaded at
runtime), and spaCy's en_core_web_sm comes from the local group. `from_env()` returns None, with a
log line saying why, when mlx-audio or the model is missing; the server then tries Cartesia.

Cloned voice (#84, MIGUEL_TTS=clone): `QwenCloneEngine` runs Qwen3-TTS 0.6B Base, which copies the
voice in a reference clip (default models/miguel-voice/full.wav, Miguel's Cartesia voice, with its
transcript in full.txt next to it; git-ignored, made by `python -m app.speech.make_voice_ref`).
Same client (`KokoroTTS.clone_from_env()`), same WAV out. Qwen is
always run with stream=True inside, even though a line still leaves as one WAV: without streaming it
decodes the whole reference again on every call (about 0.25 s more). Measured on the M5 Pro: about
0.4 s for "On it!", 1 s for a long sentence, 0.18 s to the first chunk, 4.6 s for the first line after
loading (encoding the reference; done by the warm-up). It ignores the speed setting.

Text: emojis and markdown are dropped before speaking (Kokoro would otherwise read "asterisk" or
skip oddly), then `normalize_text` collapses whitespace and caps the length, as for Cartesia.
"""

from __future__ import annotations

import asyncio
import importlib.util
import io
import logging
import os
import re
import shutil
import tempfile
import threading
import time
import wave
from collections import OrderedDict
from collections.abc import AsyncIterator, Iterable, Iterator, Mapping
from pathlib import Path
from typing import Any, Protocol

from app.speech.tts import TTSError, _Pending, normalize_text

log = logging.getLogger("app.speech.tts_local")

DEFAULT_REPO = "mlx-community/Kokoro-82M-bf16"
DEFAULT_VOICE = "af_heart"
SAMPLE_RATE = 24000
SPLIT_SENTENCES = r"(?<=[.!?])\s+"   # one segment per sentence: the first one is ready sooner
WARMUP_LINE = "Hello there."
CLONE_REPO = "mlx-community/Qwen3-TTS-12Hz-0.6B-Base-bf16"
CLONE_REF = Path(__file__).resolve().parents[2] / "models" / "miguel-voice" / "full.wav"
CLONE_CHUNK_S = 0.32     # Qwen streaming step: the MLX lock is let go between chunks
ESPEAK_MAX_PATH = 159                # espeak-ng ignores a data path of 160+ characters (N_PATH_HOME)


# --- text --------------------------------------------------------------------

_EMOJI = re.compile(
    "["
    "\U0001F000-\U0001FAFF"   # emoji, pictographs, flags (regional indicators), skin tones
    "\U00002600-\U000027BF"   # misc symbols and dingbats (sun, heart, check mark)
    "\U00002300-\U000023FF"   # misc technical (watch, alarm clock, hourglass)
    "\U00002B00-\U00002BFF"   # arrows and stars
    "\U0000FE00-\U0000FE0F"   # variation selectors
    "\U0000200D"              # zero-width joiner
    "\U000020E3"              # combining keycap
    "\U000E0020-\U000E007F"   # tag characters (subdivision flags)
    "]+"
)
_MD_LINK = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")           # [text](url) -> text; images too
_MD_CODE = re.compile(r"`+([^`]*)`+")                         # `code` -> code
_MD_EMPH = re.compile(r"(\*{1,3}|_{2,3}|~~)(?=\S)(.+?)(?<=\S)\1")   # **bold**, *it*, __b__, ~~s~~
_MD_UNDERSCORE_IT = re.compile(r"(?<!\w)_(?=\S)(.+?)(?<=\S)_(?!\w)")  # _it_, not snake_case
_MD_LINE_START = re.compile(r"(?m)^\s{0,3}(?:#{1,6}\s+|>\s?|[-*+]\s+|\d+[.)]\s+)")
_MD_LEFTOVER = re.compile(r"[*#`~|]+|(?<!\w)_+|_+(?!\w)")    # stray markers nothing else matched


def clean_for_speech(text: str) -> str:
    """Drop emojis and markdown so only words are spoken ("**Done!** ✅" -> "Done!")."""
    s = str(text)
    s = _EMOJI.sub(" ", s)
    s = _MD_LINK.sub(r"\1", s)
    s = _MD_CODE.sub(r"\1", s)
    s = _MD_LINE_START.sub("", s)
    for _ in range(2):   # nested: ***bold italic***, **_both_**
        s = _MD_EMPH.sub(r"\2", s)
        s = _MD_UNDERSCORE_IT.sub(r"\1", s)
    s = _MD_LEFTOVER.sub(" ", s)
    lines = [" ".join(line.split()) for line in s.splitlines()]
    lines = [line for line in lines if line]
    if len(lines) > 1:   # a heading or list item ends a sentence, not a run-on
        lines = [line if line[-1] in ".!?,;:" else line + "." for line in lines]
    s = re.sub(r"\s+([,.!?;:])", r"\1", " ".join(lines))   # "Done !" left by a removed emoji
    return s.strip()


# --- WAV ---------------------------------------------------------------------

def pcm16(samples: Any) -> bytes:
    """Float samples in [-1, 1] (a numpy-compatible array) as little-endian 16-bit PCM."""
    import numpy as np

    a = np.asarray(samples, dtype=np.float32).reshape(-1)
    return (np.clip(a, -1.0, 1.0) * 32767.0).round().astype("<i2").tobytes()


def wav_bytes(pcm: bytes, sample_rate: int = SAMPLE_RATE) -> bytes:
    """A complete WAV file (PCM 16-bit, mono) around `pcm`."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm)
    return buf.getvalue()


# --- the model ---------------------------------------------------------------

class Engine(Protocol):
    """What KokoroTTS needs from the model (tests pass a fake)."""

    def load(self) -> None:
        """Load the weights (MLX work: called holding the MLX lock)."""

    def prepare(self) -> None:
        """Slow CPU-only setup (spaCy, G2P): called without the MLX lock."""

    def segments(self, text: str, voice: str, speed: float) -> Iterator[Any]:
        """Audio for `text`, one float32 array (24 kHz mono) per sentence. Each `next()` runs the model."""


def find_model(voice: str, repo: str = DEFAULT_REPO) -> tuple[Path | None, str | None]:
    """The model's local snapshot, or (None, why not). Never touches the network."""
    for mod in ("mlx", "mlx_audio", "misaki", "huggingface_hub"):
        if importlib.util.find_spec(mod) is None:
            return None, f"{mod} is not installed (run: cd server && uv sync --group local)"
    try:
        from huggingface_hub import snapshot_download

        path = Path(snapshot_download(repo, local_files_only=True))
    except Exception as e:  # noqa: BLE001 - LocalEntryNotFoundError and friends
        return None, (f"the model {repo} is not downloaded ({type(e).__name__}; "
                      f"run: cd server && uv run hf download {repo})")
    if not (path / "config.json").is_file():
        return None, f"the model snapshot {path} has no config.json (download it again)"
    if not (path / "voices" / f"{voice}.safetensors").is_file():
        return None, f"voice {voice!r} is not in {path / 'voices'} (check MIGUEL_KOKORO_VOICE)"
    return path, None


def _short_espeak_data() -> None:
    """espeak-ng ignores a data path of 160+ characters; point it at a short copy if ours is that long."""
    import espeakng_loader
    from phonemizer.backend.espeak.wrapper import EspeakWrapper

    data = espeakng_loader.get_data_path()
    if len(data) <= ESPEAK_MAX_PATH:
        return
    short = Path(tempfile.gettempdir()) / "miguel-espeak-ng-data"
    if not (short / "phontab").is_file():
        shutil.copytree(data, short, dirs_exist_ok=True)
    EspeakWrapper.set_data_path(str(short))
    log.info("local voice: espeak-ng data path is %d characters; using a copy at %s", len(data), short)


class KokoroEngine:
    """Kokoro-82M through mlx-audio, from a local snapshot."""

    def __init__(self, model_path: Path, lang_code: str = "a") -> None:
        self.model_path = Path(model_path)
        self.lang_code = lang_code
        self._model: Any = None

    def load(self) -> None:
        import misaki.espeak  # noqa: F401 - sets espeak-ng's library and data paths
        from mlx_audio.tts.utils import load_model

        _short_espeak_data()
        self._model = load_model(self.model_path)   # a Path: read locally, never downloaded

    def prepare(self) -> None:
        get = getattr(self._model, "_get_pipeline", None)   # builds spaCy + G2P (about 3 s)
        if get is not None:
            get(self.lang_code)

    def segments(self, text: str, voice: str, speed: float) -> Iterator[Any]:
        import numpy as np

        for seg in self._model.generate(text=text, voice=voice, speed=speed, lang_code=self.lang_code,
                                        split_pattern=SPLIT_SENTENCES):
            yield np.asarray(seg.audio, dtype=np.float32)


def find_clone(repo: str = CLONE_REPO, ref: Path = CLONE_REF) -> tuple[Path | None, str | None, str | None]:
    """(model snapshot, reference transcript, None), or (None, None, why not). Never touches the network."""
    for mod in ("mlx", "mlx_audio", "huggingface_hub"):
        if importlib.util.find_spec(mod) is None:
            return None, None, f"{mod} is not installed (run: cd server && uv sync --group local)"
    ref = Path(ref)
    if not ref.is_file():
        return None, None, f"the reference clip {ref} is missing (MIGUEL_CLONE_REF)"
    txt = ref.with_suffix(".txt")
    if not txt.is_file() or not txt.read_text().strip():
        return None, None, f"the reference clip needs its exact transcript in {txt}"
    try:
        from huggingface_hub import snapshot_download

        path = Path(snapshot_download(repo, local_files_only=True))
    except Exception as e:  # noqa: BLE001
        return None, None, (f"the model {repo} is not downloaded ({type(e).__name__}; "
                            f"run: cd server && uv run hf download {repo})")
    if not (path / "config.json").is_file():
        return None, None, f"the model snapshot {path} has no config.json (download it again)"
    return path, " ".join(txt.read_text().split()), None


class QwenCloneEngine:
    """Qwen3-TTS Base through mlx-audio, speaking in the voice of a reference clip."""

    def __init__(self, model_path: Path, ref_audio: Path, ref_text: str) -> None:
        self.model_path = Path(model_path)
        self.ref_audio_path = Path(ref_audio)
        self.ref_text = ref_text
        self._model: Any = None
        self._ref: Any = None

    def load(self) -> None:
        from mlx_audio.tts.utils import load_model
        from mlx_audio.utils import load_audio

        self._model = load_model(self.model_path)
        self._ref = load_audio(str(self.ref_audio_path), sample_rate=SAMPLE_RATE)

    def prepare(self) -> None:
        """Nothing CPU-only to do; the warm-up line encodes the reference (cached by mlx-audio)."""

    def segments(self, text: str, voice: str, speed: float) -> Iterator[Any]:
        import numpy as np

        for sentence in (s for s in re.split(SPLIT_SENTENCES, text) if s.strip()):
            for chunk in self._model.generate(text=sentence, ref_audio=self._ref, ref_text=self.ref_text,
                                              lang_code="english", stream=True,
                                              streaming_interval=CLONE_CHUNK_S, split_pattern=""):
                yield np.asarray(chunk.audio, dtype=np.float32)


# --- the client --------------------------------------------------------------

class KokoroTTS:
    """Local Kokoro voice with CartesiaTTS's interface: WAV bytes, an LRU cache and in-flight dedupe."""

    MEDIA_TYPE = "audio/wav"

    def __init__(
        self,
        voice: str = DEFAULT_VOICE,
        *,
        model_path: Path | None = None,
        engine: Engine | None = None,
        speed: float = 1.0,
        max_chars: int = 300,
        cache_size: int = 200,
        lock: Any = None,
    ) -> None:
        if not voice:
            raise ValueError("voice is empty")
        if max_chars < 1:
            raise ValueError("max_chars must be at least 1")
        if engine is None:
            if model_path is None:
                raise ValueError("give a model_path or an engine")
            engine = KokoroEngine(model_path)
        if lock is None:
            from app.mlx_lock import MLX_LOCK

            lock = MLX_LOCK
        self.voice = voice
        self.speed = speed
        self.max_chars = max_chars
        self.cache_size = max(0, cache_size)
        self._engine = engine
        self._lock: threading.Lock = lock
        self._cache: OrderedDict[tuple, bytes] = OrderedDict()
        self._inflight: dict[tuple, _Pending] = {}
        self._tasks: set[asyncio.Task[None]] = set()
        self._load: asyncio.Task[None] | None = None
        self._one_line: asyncio.Lock | None = None   # made lazily, inside the running loop
        self.label = "Kokoro"

    def __repr__(self) -> str:
        return f"KokoroTTS(voice={self.voice!r}, speed={self.speed!r})"

    @classmethod
    def from_env(cls, env: Mapping[str, str] = os.environ) -> KokoroTTS | None:
        """Build from MIGUEL_KOKORO_VOICE, or None (with a log line saying why) if the model is missing."""
        voice = (env.get("MIGUEL_KOKORO_VOICE") or "").strip() or DEFAULT_VOICE
        path, problem = find_model(voice)
        if path is None:
            log.warning("local voice unavailable: %s", problem)
            return None
        log.info("local voice on: Kokoro-82M, voice %s (%s)", voice, path)
        return cls(voice, model_path=path)

    @classmethod
    def clone_from_env(cls, env: Mapping[str, str] = os.environ) -> KokoroTTS | None:
        """The cloned voice (MIGUEL_CLONE_REF, MIGUEL_CLONE_MODEL), or None with a log line saying why."""
        ref = Path((env.get("MIGUEL_CLONE_REF") or "").strip() or CLONE_REF)
        repo = (env.get("MIGUEL_CLONE_MODEL") or "").strip() or CLONE_REPO
        path, ref_text, problem = find_clone(repo, ref)
        if path is None:
            log.warning("cloned voice unavailable: %s", problem)
            return None
        log.info("cloned voice on: %s, from %s", repo, ref)
        tts = cls(f"clone:{ref.stem}", engine=QwenCloneEngine(path, ref, ref_text or ""))
        tts.label = "the cloned voice (Qwen3-TTS)"
        return tts

    # --- public ---------------------------------------------------------------

    async def synth(self, text: str) -> bytes:
        """Return WAV bytes for `text`. Raises TTSError on empty text or a model failure."""
        key, clean = self._key(text)
        cached = self._cached(key)
        if cached is not None:
            return cached
        return await self._start(key, clean).result()

    def cached(self, text: str) -> bytes | None:
        """The WAV for `text` if it is in the cache (no synthesis)."""
        try:
            key, _ = self._key(text)
        except TTSError:
            return None
        return self._cached(key)

    async def stream(self, text: str) -> AsyncIterator[bytes]:
        """Yield the WAV for `text`: one chunk, once the whole line is made (a WAV header needs the length)."""
        yield await self.synth(text)

    async def prewarm(self, lines: Iterable[str]) -> int:
        """Load and warm up the model, then make each line into the cache; return how many succeeded.
        Never raises."""
        try:
            await self._loaded()
        except TTSError as e:
            log.warning("local voice prewarm: %s", e)
            return 0
        ok = 0
        try:
            items = list(lines)
        except Exception as e:  # noqa: BLE001 - a bad iterable must not take the caller down
            log.warning("local voice prewarm: could not read the lines (%s)", type(e).__name__)
            return 0
        for line in items:
            try:
                await self.synth(line)
                ok += 1
            except Exception as e:  # noqa: BLE001
                log.warning("local voice prewarm: %r failed: %s", str(line)[:40], e)
        log.info("local voice prewarm: %d of %d lines cached", ok, len(items))
        return ok

    async def close(self) -> None:
        """Stop waiting for lines being made. (A model call already running finishes in its thread.)"""
        tasks = list(self._tasks) + ([self._load] if self._load is not None else [])
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    # --- internals ------------------------------------------------------------

    def _key(self, text: str) -> tuple[tuple, str]:
        clean = normalize_text(clean_for_speech(text), self.max_chars)
        if not clean:
            raise TTSError("nothing to say: the text is empty (or only emojis and markdown)")
        return (self.voice, self.speed, clean), clean

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

    async def _loaded(self) -> None:
        """Load the model once (shared by everyone waiting); raise TTSError if that failed."""
        if self._load is None:
            self._load = asyncio.ensure_future(self._load_and_warm())
        try:
            await asyncio.shield(self._load)
        except TTSError:
            raise
        except asyncio.CancelledError:
            if self._load.cancelled():
                raise TTSError("the local voice was closed") from None
            raise
        except Exception as e:  # noqa: BLE001
            raise TTSError(f"the local voice failed to load: {type(e).__name__}: {e}") from None

    async def _load_and_warm(self) -> None:
        t0 = time.perf_counter()
        try:
            await asyncio.to_thread(self._locked, self._engine.load)
            await asyncio.to_thread(self._engine.prepare)            # CPU only: hearing can run meanwhile
            await self._make(WARMUP_LINE)
        except TTSError:
            raise
        except Exception as e:  # noqa: BLE001
            log.exception("local voice: loading %s failed", self.label)
            raise TTSError(f"the local voice failed to load: {type(e).__name__}: {e}") from None
        log.info("local voice: %s loaded and warm in %.1f s", self.label, time.perf_counter() - t0)

    def _locked(self, fn, *args):
        with self._lock:
            return fn(*args)

    async def _make(self, text: str) -> bytes:
        """Synthesize one line, sentence by sentence, each model step in a thread holding the MLX lock."""
        if self._one_line is None:
            self._one_line = asyncio.Lock()
        async with self._one_line:   # one line at a time, in order (one model, one pipeline)
            segments = self._engine.segments(text, self.voice, self.speed)
            parts: list[bytes] = []
            while True:
                chunk = await asyncio.to_thread(self._locked, self._next_pcm, segments)
                if chunk is None:
                    break
                parts.append(chunk)
        if not parts:
            raise TTSError("the local voice made no audio")
        return wav_bytes(b"".join(parts))

    @staticmethod
    def _next_pcm(segments: Iterator[Any]) -> bytes | None:
        audio = next(segments, None)
        return None if audio is None else pcm16(audio)

    async def _run(self, key: tuple, clean: str, pending: _Pending) -> None:
        error: BaseException | None = None
        try:
            await self._loaded()
            pending.add(await self._make(clean))
        except asyncio.CancelledError:
            error = TTSError("the request was cancelled")
            raise
        except TTSError as e:
            error = e
        except Exception as e:  # noqa: BLE001 - anything else is a failed line, never a crash
            log.warning("local voice failed for %r", clean[:40], exc_info=True)
            error = TTSError(f"the local voice failed: {type(e).__name__}: {e}")
        finally:
            self._inflight.pop(key, None)
            if error is None and self.cache_size:
                self._cache[key] = b"".join(pending.chunks)
                self._cache.move_to_end(key)
                while len(self._cache) > self.cache_size:
                    self._cache.popitem(last=False)
            pending.finish(error)
