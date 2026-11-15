import sys
from PIL import Image, ImageDraw
src, out, x0,y0,x1,y1, scale, step = sys.argv[1], sys.argv[2], *map(int, sys.argv[3:9])
im = Image.open(src).convert("RGBA")
bg = Image.new("RGBA", im.size, (40,90,40,255)); bg.alpha_composite(im)
c = bg.crop((x0,y0,x1,y1)).resize(((x1-x0)*scale,(y1-y0)*scale), Image.NEAREST).convert("RGB")
d = ImageDraw.Draw(c)
for x in range((x0//step+1)*step, x1, step):
    X=(x-x0)*scale; d.line([(X,0),(X,c.height)], fill=(255,0,255) if x%(step*5)==0 else (0,200,255), width=1); d.text((X+2,2), str(x), fill=(255,0,0))
for y in range((y0//step+1)*step, y1, step):
    Y=(y-y0)*scale; d.line([(0,Y),(c.width,Y)], fill=(255,0,255) if y%(step*5)==0 else (0,200,255), width=1); d.text((2,Y+2), str(y), fill=(255,0,0))
c.save(out)
