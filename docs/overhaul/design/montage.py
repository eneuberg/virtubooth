"""Side-by-side review sheets of mockup shots: montage.py ROUND OUT name-vp [name-vp ...]"""

import sys
from pathlib import Path

from PIL import Image

rnd, out, *names = sys.argv[1:]
d = Path(__file__).parent / "shots" / rnd
ims = [Image.open(d / f"{n}.png").convert("RGB") for n in names]
h = min(1000, max(im.height for im in ims))
ims = [im.resize((max(1, int(im.width * h / im.height)), h)) for im in ims]
W = sum(im.width for im in ims) + 16 * (len(ims) - 1)
m = Image.new("RGB", (W, h), (120, 120, 120))
x = 0
for im in ims:
    m.paste(im, (x, 0))
    x += im.width + 16
m.save(out)
