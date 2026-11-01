# Numeric checks on the rendered logo (no eyes needed): the artwork must be
# inside the tile, the corners transparent, the bubble white and the bars blue.
import sys

from PIL import Image

sys.path.insert(0, "tools")
from preview_logo import render  # noqa: E402

fail = []


def px(img, x, y):
    return img.getpixel((x, y))


for size in (16, 24, 32, 48, 256):
    img = render(size)
    w, h = img.size
    print("== %dx%d" % (w, h))

    # 1. Corners fully transparent.
    for name, (x, y) in {
        "tl": (0, 0), "tr": (w - 1, 0), "bl": (0, h - 1), "br": (w - 1, h - 1),
    }.items():
        r, g, b, a = px(img, x, y)
        if a > 4:
            fail.append("%d corner %s alpha=%d" % (size, name, a))
        print("   corner %s alpha=%d" % (name, a))

    # 2. Centre of the tile is opaque and blue-ish somewhere near the edges.
    cx, cy = w // 2, h // 2
    r, g, b, a = px(img, cx, cy)
    print("   centre rgba=%s" % ((r, g, b, a),))
    if a < 250:
        fail.append("%d centre not opaque (a=%d)" % (size, a))

    # 3. A point on the tile rim (inside horizontally, near the top) must be
    #    blue: the bubble starts at 19.5% of the height.
    rim_y = int(h * 0.12)
    r, g, b, a = px(img, cx, rim_y)
    print("   rim rgba=%s" % ((r, g, b, a),))
    if not (b > r + 40 and b > g + 20 and a > 200):
        fail.append("%d rim pixel not blue: %s" % (size, (r, g, b, a)))

    # 4. The white bubble body must be visible: sample the middle-left of the
    #    bubble (between the left edge and the first bar).
    bx = int(w * 0.22)
    by = int(h * 0.42)
    r, g, b, a = px(img, bx, by)
    print("   bubble rgba=%s" % ((r, g, b, a),))
    if not (r > 240 and g > 240 and b > 240 and a > 200):
        fail.append("%d bubble pixel not white: %s" % (size, (r, g, b, a)))

    # 5. A bar pixel must be blue and darker than the tile top.
    bar_x = int(w * 0.40)
    bar_y = int(h * 0.32)
    r, g, b, a = px(img, bar_x, bar_y)
    print("   bar rgba=%s" % ((r, g, b, a),))
    if not (b > 150 and b > r + 60 and a > 200):
        fail.append("%d bar pixel not blue: %s" % (size, (r, g, b, a)))

    # 6. The tile is inset by 5.5%, so the outermost column is transparent.
    r, g, b, a = px(img, 0, h // 2)
    print("   margin alpha=%d" % a)
    if a > 8:
        fail.append("%d left margin not transparent (a=%d)" % (size, a))

print()
if fail:
    print("FAILURES:")
    for f in fail:
        print("  -", f)
    raise SystemExit(1)
print("LOGO GEOMETRY CHECKS PASSED")
