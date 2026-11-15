"""Finds render glitches in an image sequence: a frame, or a run of up to 12 frames, that jumps far
away from the frame before it and then jumps back, so the frames on either side of the run agree.
(A real change, like a scene transition or a scroll, doesn't come back to where it started.)

Usage: uv run --with numpy --with pillow python tools/check_sequence.py <dir>  → prints bad frame numbers
"""
import os
import re
import sys

import numpy as np
from PIL import Image

MAX_RUN = 12
d = sys.argv[1]
files = sorted(f for f in os.listdir(d) if re.search(r"\d+\.(jpe?g|png)$", f))


def load(f):
    return np.asarray(Image.open(os.path.join(d, f)).convert("L").resize((240, 135)), dtype=np.float32)


frames = [load(f) for f in files]
diff = lambda a, b: float(np.abs(frames[a] - frames[b]).mean())
bad = []
i = 1
while i < len(frames) - 1:
    jump_in = diff(i - 1, i)
    found = None
    if jump_in > 6:
        for j in range(i, min(len(frames) - 1, i + MAX_RUN)):
            jump_out = diff(j, j + 1)
            if jump_out > 6 and diff(i - 1, j + 1) < 0.3 * min(jump_in, jump_out):
                found = j
                break
    if found is not None:
        bad.extend(int(re.search(r"(\d+)\.", files[k]).group(1)) for k in range(i, found + 1))
        i = found + 1
    else:
        i += 1
print(" ".join(map(str, bad)))
