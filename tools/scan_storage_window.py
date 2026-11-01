# -*- coding: utf-8 -*-
"""Dump a wide window of strings around the 'PropertyHandler' literal in
windows.storage.dll to reveal the shell-extension kind table."""
import sys

PATH = r"C:\Windows\System32\windows.storage.dll"
ANCHOR = "PropertyHandler"


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
            if len(chars) >= 2:
                out.append((start, "".join(chars)))
            continue
        i += 1
    return out


def main():
    data = open(PATH, "rb").read()
    strs = strings16_with_pos(data)
    for idx, (pos, s) in enumerate(strs):
        if s == ANCHOR:
            lo = max(0, idx - 40)
            hi = min(len(strs), idx + 40)
            print("=== window around offset 0x%X (index %d) ===" % (pos, idx))
            for j in range(lo, hi):
                print("   0x%X  %r" % (strs[j][0], strs[j][1]))
            print()


if __name__ == "__main__":
    main()
