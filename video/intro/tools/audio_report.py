# Renders a loudness/spectrogram report of the mix with timeline markers: tools/audio_report.py out.png
import json, sys
import numpy as np
from scipy.io import wavfile
import scipy.signal as sg
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
T = json.load(open("src/timeline.json"))
fig, axes = plt.subplots(3, 1, figsize=(18, 10), sharex=True)
for name, col in (("mix", "k"), ("stem_music", "tab:orange"), ("stem_sfx", "tab:blue"), ("stem_voice", "tab:green")):
    try: sr, x = wavfile.read(f"public/audio/{name}.wav")
    except FileNotFoundError: continue
    x = x.astype(float) / 32768; m = x.mean(1)
    hop = int(0.02 * sr); n = len(m) // hop
    rms = np.sqrt((m[: n * hop].reshape(n, hop) ** 2).mean(1)) + 1e-9
    axes[0].plot(np.arange(n) * 0.02, 20 * np.log10(rms), col, lw=1, label=name)
    if name == "mix":
        f, t, S = sg.spectrogram(m, sr, nperseg=2048, noverlap=1536)
        axes[1].pcolormesh(t, f, 10 * np.log10(S + 1e-12), shading="auto", vmin=-120, vmax=-40, cmap="magma")
        axes[1].set_ylim(0, 6000)
        axes[2].plot(np.arange(len(m)) / sr, m, "k", lw=0.3)
axes[0].set_ylim(-70, 0); axes[0].legend(loc="upper right"); axes[0].set_ylabel("RMS dBFS")
ev = {k: v for k, v in T.items() if isinstance(v, (int, float)) and k not in ("fps", "duration", "wordStagger", "wordDur")}
for k, v in ev.items():
    for ax in axes: ax.axvline(v, color="tab:red", lw=0.6, alpha=0.6)
    axes[0].text(v, -2, k, rotation=90, fontsize=7, va="top")
for s in T["stats"]:
    axes[0].axvline(s["in"], color="tab:purple", lw=0.8)
plt.tight_layout(); plt.savefig(sys.argv[1], dpi=80)
