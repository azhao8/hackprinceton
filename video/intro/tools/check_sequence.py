"""Finds frames in an image sequence that differ from both neighbours while the neighbours agree (render glitches).
Usage: uv run --with numpy --with pillow python tools/check_sequence.py <dir>  → prints bad frame numbers"""
import sys, os, re
import numpy as np
from PIL import Image
d = sys.argv[1]
files = sorted(f for f in os.listdir(d) if re.search(r"\d+\.(jpe?g|png)$", f))
def load(f):
    return np.asarray(Image.open(os.path.join(d, f)).convert("L").resize((240, 135)), dtype=np.float32)
frames = [load(f) for f in files]
bad = []
for i in range(1, len(frames) - 1):
    a, b, c = frames[i - 1], frames[i], frames[i + 1]
    dab, dbc, dac = np.abs(a - b).mean(), np.abs(b - c).mean(), np.abs(a - c).mean()
    if dab > 3 * dac + 1.5 and dbc > 3 * dac + 1.5:
        bad.append(int(re.search(r"(\d+)\.", files[i]).group(1)))
print(" ".join(map(str, bad)))
