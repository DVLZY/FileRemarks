# Preview of the C++ logo artwork in src/logo.h.
# Ports the exact same geometry so the picture here is what the DLL draws.
import math
import sys

from PIL import Image


def clamp01(v):
    return 0.0 if v < 0 else (1.0 if v > 1 else v)


def round_rect_sdf(x, y, x0, y0, x1, y1, r):
    cx, cy = (x0 + x1) * 0.5, (y0 + y1) * 0.5
    hx, hy = (x1 - x0) * 0.5 - r, (y1 - y0) * 0.5 - r
    hx = max(hx, 0.0)
    hy = max(hy, 0.0)
    dx = abs(x - cx) - hx
    dy = abs(y - cy) - hy
    ax, ay = max(dx, 0.0), max(dy, 0.0)
    if dx > 0 or dy > 0:
        return math.sqrt(ax * ax + ay * ay) - r
    return max(dx, dy) - r


def in_triangle(u, v, ax, ay, bx, by, cx, cy):
    s1 = (bx - ax) * (v - ay) - (by - ay) * (u - ax)
    s2 = (cx - bx) * (v - by) - (cy - by) * (u - bx)
    s3 = (ax - cx) * (v - cy) - (ay - cy) * (u - cx)
    return (s1 >= 0 and s2 >= 0 and s3 >= 0) or (s1 <= 0 and s2 <= 0 and s3 <= 0)


OFFS = (1.0 / 6.0, 0.5, 5.0 / 6.0)


def coverage(x, y, inside):
    hits = 0
    for i in range(3):
        for j in range(3):
            if inside(x + OFFS[i], y + OFFS[j]):
                hits += 1
    return hits / 9.0


def blend(dst, src, cov):
    sa = src[3] * cov
    if sa <= 0:
        return dst
    da = dst[3] * (1.0 - sa)
    out_a = sa + da
    if out_a <= 0:
        return (0.0, 0.0, 0.0, 0.0)
    return (
        (src[0] * sa + dst[0] * da) / out_a,
        (src[1] * sa + dst[1] * da) / out_a,
        (src[2] * sa + dst[2] * da) / out_a,
        out_a,
    )


def render(size):
    S = float(size)
    inset = S * 0.055
    tile_r = S * 0.235
    bx0, bx1 = S * 0.185, S * 0.815
    by0, by1 = S * 0.190, S * 0.645
    b_r = S * 0.115
    t1x, t1y = S * 0.285, by1 - 0.5
    t2x, t2y = S * 0.475, by1 - 0.5
    t3x, t3y = S * 0.335, S * 0.800
    roomy = S >= 40.0
    bars = 3 if roomy else 2
    area_top = S * 0.250 if roomy else S * 0.300
    area_bot = S * 0.590 if roomy else S * 0.560
    gap = S * 0.052 if roomy else S * 0.075
    bar_h = ((area_bot - area_top) - gap * (bars - 1)) / bars
    bar_r = bar_h * 0.5
    bar_len = [1.00, 0.82, 0.62]
    bar_area_w = S * 0.450 if roomy else S * 0.340
    bar_x0 = S * 0.275 if roomy else S * 0.330
    c_top = (0.250, 0.545, 0.980, 1.0)
    c_bot = (0.105, 0.290, 0.845, 1.0)
    c_bubble = (1.0, 1.0, 1.0, 1.0)
    c_bar = (0.145, 0.388, 0.922, 1.0)

    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    px = img.load()
    for y in range(size):
        for x in range(size):
            out = (0.0, 0.0, 0.0, 0.0)
            fx, fy = float(x), float(y)

            def tile_in(u, v):
                return round_rect_sdf(u, v, inset, inset, S - inset, S - inset, tile_r) <= 0.0

            tc = coverage(fx, fy, tile_in)
            if tc > 0:
                t = clamp01((fy + 0.5) / S)
                bg = (
                    c_top[0] + (c_bot[0] - c_top[0]) * t,
                    c_top[1] + (c_bot[1] - c_top[1]) * t,
                    c_top[2] + (c_bot[2] - c_top[2]) * t,
                    1.0,
                )
                out = blend(out, bg, tc)

            def bubble_in(u, v):
                if round_rect_sdf(u, v, bx0, by0, bx1, by1, b_r) <= 0.0:
                    return True
                return in_triangle(u, v, t1x, t1y, t2x, t2y, t3x, t3y)

            out = blend(out, c_bubble, coverage(fx, fy, bubble_in))

            for i in range(bars):
                y0 = area_top + i * (bar_h + gap)
                y1 = y0 + bar_h
                x1 = bar_x0 + bar_area_w * bar_len[i]

                def bar_in(u, v, x0=bar_x0, yy0=y0, xx1=x1, yy1=y1):
                    return round_rect_sdf(u, v, x0, yy0, xx1, yy1, bar_r) <= 0.0

                out = blend(out, c_bar, coverage(fx, fy, bar_in))

            px[x, y] = (
                int(out[0] * 255 + 0.5),
                int(out[1] * 255 + 0.5),
                int(out[2] * 255 + 0.5),
                int(out[3] * 255 + 0.5),
            )
    return img


def main():
    sizes = [16, 24, 32, 48, 64, 128, 256]
    imgs = [render(s) for s in sizes]
    # Contact sheet on a mid-grey background so light/dark details both show.
    pad = 12
    sheet_w = sum(s for s in sizes) + pad * (len(sizes) + 1)
    sheet_h = max(sizes) + pad * 2 + 8
    sheet = Image.new("RGB", (sheet_w, sheet_h), (240, 240, 240))
    x = pad
    for img in imgs:
        sheet.paste(img, (x, pad + (max(sizes) - img.size[0]) // 2), img)
        x += img.size[0] + pad
    sheet.save(sys.argv[1] if len(sys.argv) > 1 else "logo_preview.png")
    # Also save a dark-background version to check the transparent edges.
    dark = Image.new("RGB", (sheet_w, sheet_h), (32, 32, 32))
    x = pad
    for img in imgs:
        dark.paste(img, (x, pad + (max(sizes) - img.size[0]) // 2), img)
        x += img.size[0] + pad
    out = sys.argv[1] if len(sys.argv) > 1 else "logo_preview.png"
    dark.save(out.replace(".png", "_dark.png"))
    imgs[-1].save(out.replace(".png", "_256.png"))
    print("wrote", out)


if __name__ == "__main__":
    main()
