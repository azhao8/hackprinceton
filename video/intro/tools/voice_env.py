"""Mouth-movement envelopes (60 Hz) and durations from the voice lines, trimmed the same way the mixer trims them.
Usage: uv run --with numpy --with scipy python tools/voice_env.py <voice-dir> <out-json>"""
import json, os, sys
import numpy as np
import scipy.signal as sg
from scipy.io import wavfile

vdir, out = sys.argv[1], sys.argv[2]
env = {}
for key in ("line1", "line2", "line3"):
    p = os.path.join(vdir, f"{key}.wav")
    if not os.path.exists(p):
        continue
    sr, v = wavfile.read(p)
    v = v.astype(np.float64)
    if v.ndim > 1: v = v.mean(axis=1)
    v /= np.abs(v).max() + 1e-9
    idx = np.where(np.abs(v) > 0.02)[0]
    v = v[max(0, idx[0] - int(0.01 * sr)): idx[-1] + int(0.05 * sr)]
    # speech band energy, smoothed like a jaw (fast open, slower close)
    b = sg.sosfilt(sg.butter(2, [180, 3000], "band", fs=sr, output="sos"), v)
    hop = sr // 60
    n = len(b) // hop
    rms = np.sqrt((b[: n * hop].reshape(n, hop) ** 2).mean(axis=1))
    rms /= np.percentile(rms, 95) + 1e-9
    sm = np.zeros_like(rms)
    for i, r in enumerate(rms):
        prev = sm[i - 1] if i else 0
        sm[i] = prev + (r - prev) * (0.7 if r > prev else 0.35)
    env[key] = [round(float(min(1, x)), 3) for x in sm]
    print(f"{key}: {len(v)/sr:.2f}s")
json.dump(env, open(out, "w"))
