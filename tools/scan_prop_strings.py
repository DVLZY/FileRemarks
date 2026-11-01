# -*- coding: utf-8 -*-
"""Dump UTF-16LE strings containing 'Propert' from key shell binaries, to learn
the exact registry vocabulary the shell uses for property-handler resolution."""
import os

TARGETS = [
    r"C:\Windows\System32\windows.storage.dll",
    r"C:\Windows\System32\propsys.dll",
    r"C:\Windows\System32\shell32.dll",
]
MAX = 400


def strings16(data):
    out = []
    i = 0
    n = len(data) - 1
    while i < n - 1:
        # try to start a UTF-16LE printable run at even offset
        if i % 2 == 0 and 0x20 <= data[i] <= 0x7E and data[i + 1] == 0:
            start = i
            cur = []
            while i + 1 < len(data):
                lo, hi = data[i], data[i + 1]
                if hi == 0 and (0x20 <= lo <= 0x7E or lo in (0x2A,)):
                    cur.append(chr(lo))
                    i += 2
                else:
                    break
            if len(cur) >= 6:
                out.append("".join(cur))
            continue
        i += 1
    return out


def main():
    for path in TARGETS:
        if not os.path.isfile(path):
            print("MISSING", path)
            continue
        data = open(path, "rb").read()
        found = sorted({s for s in strings16(data) if "Propert" in s})
        print("=== %s : %d strings mentioning Propert" % (path, len(found)))
        for s in found[:MAX]:
            print("   ", ascii(s))


if __name__ == "__main__":
    main()
