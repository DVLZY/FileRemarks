"""Render one of the shot_editor.py PNGs as ASCII, so the layout is inspectable.

The shots are written by shot_editor.py with PNG filter type 0 on every row and
8-bit truecolour, which makes decoding here trivial.
"""
import sys
import zlib

RAMP = "@%#*+=-:. "          # dark -> light


def read_png(path):
    data = open(path, "rb").read()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    pos = 8
    width = height = None
    idat = b""
    while pos < len(data):
        (length,) = (int.from_bytes(data[pos:pos + 4], "big"),)
        tag = data[pos + 4:pos + 8]
        payload = data[pos + 8:pos + 8 + length]
        pos += 12 + length
        if tag == b"IHDR":
            width = int.from_bytes(payload[0:4], "big")
            height = int.from_bytes(payload[4:8], "big")
        elif tag == b"IDAT":
            idat += payload
        elif tag == b"IEND":
            break
    raw = zlib.decompress(idat)
    stride = width * 3 + 1
    rows = []
    for y in range(height):
        row = raw[y * stride:(y + 1) * stride]
        assert row[0] == 0, "unexpected PNG filter %d" % row[0]
        px = row[1:]
        rows.append([(px[x * 3], px[x * 3 + 1], px[x * 3 + 2])
                     for x in range(width)])
    return width, height, rows


def main():
    path = sys.argv[1]
    cols = int(sys.argv[2]) if len(sys.argv) > 2 else 110
    width, height, rows = read_png(path)
    print("%s  %dx%d" % (path, width, height))
    step_x = max(1, width // cols)
    step_y = step_x * 2                  # characters are about twice as tall
    for y in range(0, height, step_y):
        line = []
        for x in range(0, width, step_x):
            block = [rows[yy][xx]
                     for yy in range(y, min(y + step_y, height))
                     for xx in range(x, min(x + step_x, width))]
            lum = sum((r * 299 + g * 587 + b * 114) // 1000 for r, g, b in block)
            lum //= max(1, len(block))
            line.append(RAMP[min(len(RAMP) - 1, lum * len(RAMP) // 256)])
        print("".join(line).rstrip())
    return 0


if __name__ == "__main__":
    sys.exit(main())
