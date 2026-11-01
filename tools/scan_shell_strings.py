# -*- coding: utf-8 -*-
"""Scan Windows system binaries for registry-path strings that reveal HOW the
shell resolves property handlers. Answers: does the shell ever build a path
containing 'shellex\\PropertyHandler' (wildcard / per-ext), or only
'PropertySystem\\PropertyHandlers'?
"""
import os, sys, re

TARGETS = [
    r"C:\Windows\System32\shell32.dll",
    r"C:\Windows\System32\windows.storage.dll",
    r"C:\Windows\System32\propsys.dll",
    r"C:\Windows\System32\twinui.dll",
    r"C:\Windows\System32\explorerframe.dll",
    r"C:\Windows\explorer.exe",
    r"C:\Windows\System32\shell32.dll.mui",
]

KEYWORDS = [b"PropertyHandler", b"PropertyHandlers", b"shellex"]

def utf16_strings(data, start, end, maxlen=200):
    """Return the UTF-16LE string covering data[start:end]."""
    # expand left to string start (align to even offset)
    s = start
    while s - 2 >= 0 and (0x20 <= data[s - 2] <= 0x7E or data[s - 2] in (0x5C, 0x2A, 0x2E)):
        s -= 2
    e = end
    while e + 1 < len(data) and (0x20 <= data[e] <= 0x7E or data[e] in (0x5C, 0x2A, 0x2E)):
        e += 2
    if e - s > maxlen * 2:
        return None
    try:
        return data[s:e].decode("utf-16-le")
    except Exception:
        return None

def main():
    for path in TARGETS:
        if not os.path.isfile(path):
            print("MISSING", path)
            continue
        data = open(path, "rb").read()
        print("=== %s  (%d bytes)" % (path, len(data)))
        hits = set()
        for kw in KEYWORDS:
            needle = kw.decode().encode("utf-16-le")
            idx = 0
            while True:
                i = data.find(needle, idx)
                if i < 0:
                    break
                idx = i + 1
                if i % 2 != 0:
                    continue
                s = utf16_strings(data, i, i + len(needle))
                if s:
                    hits.add(s)
        for h in sorted(hits):
            print("   ", ascii(h))

if __name__ == "__main__":
    main()
