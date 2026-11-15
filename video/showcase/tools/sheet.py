# tools/sheet.py out.png scene side:seconds ...  → contact sheet of captured frames (labels on top)
import json, sys
from PIL import Image, ImageDraw
out, scene, picks = sys.argv[1], sys.argv[2], sys.argv[3:]
meta = json.load(open(f"public/capture/{scene}.json"))
ims = []
for p in picks:
    side, sec = p.split(":"); sec = float(sec)
    n = round((sec - meta[side]["start"]) * 60)
    n = max(0, min(meta[side]["frames"] - 1, n))
    im = Image.open(f"public/capture/{scene}/{side}/{n:06d}.jpg").convert("RGB")
    ims.append((f"{side} {sec:.2f}s", im))
w, h = ims[0][1].size; s = 0.34
tw, th = int(w * s), int(h * s)
cols = min(6, len(ims)); rows = (len(ims) + cols - 1) // cols
sheet = Image.new("RGB", (cols * (tw + 8), rows * (th + 26)), (40, 40, 40))
for i, (lab, im) in enumerate(ims):
    x, y = (i % cols) * (tw + 8), (i // cols) * (th + 26)
    sheet.paste(im.resize((tw, th)), (x, y + 20)); ImageDraw.Draw(sheet).text((x + 4, y + 4), lab, fill=(255, 120, 120))
sheet.save(out)
