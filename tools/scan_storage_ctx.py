# -*- coding: utf-8 -*-
"""Print all UTF-16LE strings in windows.storage.dll that mention 'shellex'
plus their neighbouring strings, to reveal how the shell resolves property
handlers (wildcard '*' vs per-extension vs PropertySystem key)."""
import re

PATH = r"C:\Windows\System32\windows.storage.dll"


def strings16_with_pos(data):
    out = []
    i = 0
    n = len(data)
    while i < n - 1:
        if 0x20 <= data[i] <= 0x7E and data[i + 1] == 0:
            start = i
            chars = []
            while i + 1 < n and data[i + 1] == 0 and 0x20 <= data[i] <= 0x7E:
                chars.append(chr(data[i]))
                i += 2
            if len(chars) >= 4:
                out.append((start, "".join(chars)))
            continue
        i += 1
    return out


def main():
    data = open(PATH, "rb").read()
    strs = strings16_with_pos(data)
    for idx, (pos, s) in enumerate(strs):
        if "shellex" in s.lower() or s == "PropertyHandler" or "PropertyHandlers" in s:
            lo = max(0, idx - 6)
            hi = min(len(strs), idx + 7)
            print("---- offset 0x%X  %r" % (pos, s))
            for j in range(lo, hi):
                mark = ">>" if j == idx else "  "
                print("   %s %r" % (mark, strs[j][1]))
    # also report immediate neighbours containing '*'
    print()
    print("strings that are exactly '*' :", [ (p,s) for p,s in strs if s == "*" ][:10])


if __name__ == "__main__":
    main()
