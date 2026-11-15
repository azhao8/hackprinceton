# Contact sheet of review frames: tools/contact.py out.png f1.png f2.png ... (2 columns, half size)
import sys
from PIL import Image, ImageDraw
out, files = sys.argv[1], sys.argv[2:]
ims = [Image.open(f).convert("RGB").resize((960, 540)) for f in files]
cols = 2; rows = (len(ims) + 1) // 2
sheet = Image.new("RGB", (cols * 960 + 10, rows * 550), (40, 40, 40))
for i, (im, f) in enumerate(zip(ims, files)):
    x, y = (i % cols) * 970, (i // cols) * 550
    sheet.paste(im, (x, y)); ImageDraw.Draw(sheet).text((x + 8, y + 6), f.split("/")[-1], fill=(255, 80, 80))
sheet.save(out)
