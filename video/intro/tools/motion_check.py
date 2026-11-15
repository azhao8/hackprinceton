"""Frame-to-frame change across a render, to catch pops, jumps and dead spots.
Usage: uv run --with numpy --with matplotlib python tools/motion_check.py video.mp4 out.png"""
import json, subprocess, sys
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

video, out = sys.argv[1], sys.argv[2]
w, h = 320, 180
raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", video, "-vf", f"scale={w}:{h}", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                     capture_output=True, check=True).stdout
fr = np.frombuffer(raw, np.uint8).reshape(-1, h, w).astype(np.float32)
d = np.abs(np.diff(fr, axis=0)).mean(axis=(1, 2))
fps = 60
t = np.arange(1, len(fr)) / fps
T = json.load(open("src/timeline.json"))
fig, ax = plt.subplots(figsize=(18, 4))
ax.plot(t, d, lw=0.8)
for k, v in T.items():
    if isinstance(v, (int, float)) and k not in ("fps", "duration", "wordStagger", "wordDur"):
        ax.axvline(v, color="r", lw=0.5, alpha=0.5); ax.text(v, d.max(), k, rotation=90, fontsize=7, va="top")
ax.set_ylabel("mean |Δ| per frame"); plt.tight_layout(); plt.savefig(out, dpi=80)
# report frames whose change is far above their neighbours (possible pops)
med = np.convolve(d, np.ones(9) / 9, mode="same")
spikes = np.where((d > 3 * med + 0.3) & (d > 0.8))[0]
print("frames:", len(fr), "spikes:", [(int(i + 1), round(float(t[i]), 3), round(float(d[i]), 2)) for i in spikes][:30])
