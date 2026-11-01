# -*- coding: utf-8 -*-
"""Read-only: do saved per-folder views (Bags) carry their own ColumnList?

This decides whether patching the FolderTypes default is enough. If any bag
holds a ColumnList, that value wins for its folder and the folder-type default
is ignored, so the column would not appear in folders the user already opened.
"""
import sys
import winreg as wr

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = wr.HKEY_CURRENT_USER
BAGS = r"Software\Microsoft\Windows\Shell\Bags"
ALLFOLDERS = BAGS + r"\AllFolders"


def enum_keys(path):
    try:
        k = wr.OpenKey(ROOT, path, 0, wr.KEY_READ)
    except OSError:
        return []
    out, i = [], 0
    while True:
        try:
            out.append(wr.EnumKey(k, i))
        except OSError:
            break
        i += 1
    wr.CloseKey(k)
    return out


def find_column_list(path, depth, maxdepth, hits):
    try:
        k = wr.OpenKey(ROOT, path, 0, wr.KEY_READ)
    except OSError:
        return
    nval = wr.QueryInfoKey(k)[1]
    for i in range(nval):
        try:
            n, d, t = wr.EnumValue(k, i)
        except OSError:
            break
        if n and "ColumnList" in n:
            hits.append((path, n, t, d))
    wr.CloseKey(k)
    if depth >= maxdepth:
        return
    for s in enum_keys(path):
        find_column_list(path + "\\" + s, depth + 1, maxdepth, hits)


hits = []
find_column_list(ALLFOLDERS, 0, 2, hits)
print("AllFolders subtree: %d ColumnList values" % len(hits))
for h in hits[:5]:
    print("  [%s] %s type=%d" % (h[0], h[1], h[2]))

tops = enum_keys(BAGS)
print("Bags top-level keys: %d" % len(tops))

hits2 = []
scanned = 0
for t in tops:
    p = BAGS + "\\" + t
    find_column_list(p, 0, 2, hits2)
    scanned += 1

print("scanned %d bag roots; %d ColumnList values found" % (scanned, len(hits2)))
for h in hits2[:8]:
    print("  [%s] %s type=%d" % (h[0], h[1], h[2]))
    if isinstance(h[3], str):
        print("     %s" % h[3][:150])

# A bag that names its folder type tells us whether the view follows a template.
print()
print("sample bag contents (one bag, non-position values):")
if tops:
    p = BAGS + "\\" + tops[5]
    for sub in enum_keys(p):
        sp = p + "\\" + sub
        try:
            k = wr.OpenKey(ROOT, sp, 0, wr.KEY_READ)
        except OSError:
            continue
        nval = wr.QueryInfoKey(k)[1]
        shown = 0
        for i in range(nval):
            n, d, t = wr.EnumValue(k, i)
            if shown < 8 and not any(x in (n or "") for x in ("Pos", "WinPos")):
                print("  %s\\%s  %s = %s" % (sub, n, t, str(d)[:80]))
                shown += 1
        wr.CloseKey(k)
