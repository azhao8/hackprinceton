"""Make reference clips of Miguel's Cartesia voice for voice cloning.

Uses the same voice, model and speed as the server (server/.env), asks for WAV 24 kHz mono, and
writes one clip per section plus a joined full clip, each with its exact transcript next to it.
MIGUEL_TTS=clone (#84) reads models/miguel-voice/full.wav and full.txt. Costs a few cents of Cartesia.
Run from server/:  uv run --env-file .env python -m app.speech.make_voice_ref [out dir]
"""

import json
import os
import struct
import sys
import urllib.error
import urllib.request
import wave
from pathlib import Path

RATE = 24000
VERSION = "2026-08-14"   # same as app/speech/tts.py

# Short sentences in Miguel's usual register: a greeting, a question, an exclamation and a
# reassurance, with varied sounds (no names that are hard to say, numbers spelled out).
SECTIONS = {
    "a_greeting": "Good morning! I'm Miguel. I brought your water and your morning pills, "
                  "and they're right here on my tray.",
    "b_question": "Would you like me to call your daughter? She asked how you were feeling "
                  "yesterday, so I think she'd love to hear from you.",
    "c_caution": "Oh, careful there! Take your time. I'll wait right beside you, and if you "
                 "need anything at all, just say my name.",
}
GAP_S = 0.35   # silence between sections in the full clip


def synth(text: str) -> bytes:
    body = {
        "model_id": os.environ.get("CARTESIA_MODEL") or "sonic-3.6",
        "transcript": text,
        "voice": {"id": os.environ["CARTESIA_VOICE_ID"]},
        "output_format": {"container": "raw", "encoding": "pcm_s16le", "sample_rate": RATE},
        "language": "en",
    }
    speed = (os.environ.get("CARTESIA_SPEED") or "").strip()
    if speed:
        body["generation_config"] = {"speed": float(speed)}
    req = urllib.request.Request(
        "https://api.cartesia.ai/tts/bytes", data=json.dumps(body).encode(), method="POST",
        headers={"Authorization": f"Bearer {os.environ['CARTESIA_API_KEY']}",
                 "Cartesia-Version": VERSION, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.read()
    except urllib.error.HTTPError as e:
        raise SystemExit(f"Cartesia returned HTTP {e.code}: {e.read()[:300].decode('utf-8', 'replace')}")


def trim(pcm: bytes, threshold: int = 300, pad_s: float = 0.08) -> bytes:
    """Cut leading and trailing silence, keeping a short pad."""
    n = len(pcm) // 2
    s = struct.unpack(f"<{n}h", pcm[: n * 2])
    loud = [i for i, v in enumerate(s) if abs(v) > threshold]
    if not loud:
        return pcm
    pad = int(pad_s * RATE)
    a, b = max(0, loud[0] - pad), min(n, loud[-1] + pad)
    return pcm[a * 2: b * 2]


def write(path: Path, pcm: bytes, text: str) -> float:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm)
    path.with_suffix(".txt").write_text(text + "\n")
    return len(pcm) / 2 / RATE


def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[2] / "models" / "miguel-voice"
    out.mkdir(parents=True, exist_ok=True)
    gap = b"\x00\x00" * int(GAP_S * RATE)
    parts = []
    for name, text in SECTIONS.items():
        pcm = trim(synth(text))
        print(f"{name}: {write(out / f'{name}.wav', pcm, text):.1f} s")
        parts.append(pcm)
    full = gap.join(parts)
    print(f"full: {write(out / 'full.wav', full, ' '.join(SECTIONS.values())):.1f} s")


if __name__ == "__main__":
    main()
