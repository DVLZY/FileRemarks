# -*- coding: utf-8 -*-
"""Read-only: enumerate every distinct value name inside the Bags tree.

Goal: find out where Explorer really stores a folder's column layout on this
Windows build. If per-folder ColumnList values exist anywhere, patching the
FolderTypes default alone can never make the column show up in those folders.
"""
import sys
import winreg as wr

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = wr.HKEY_CURRENT_USER
BASES = [
    r"Software\Microsoft\Windows\Shell\Bags",
    r"Software\Microsoft\Windows\ShellNoRoam\Bags",
]


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


def scan(path, depth, maxdepth, names, paths_with_column, samples):
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
        nm = n or "(default)"
        names[nm] = names.get(nm, 0) + 1
        if "Column" in nm:
            paths_with_column.append((path, nm, t))
            if len(samples) < 6:
                samples.append((path, nm, d))
    wr.CloseKey(k)
    if depth >= maxdepth:
        return
    for s in enum_keys(path):
        scan(path + "\\" + s, depth + 1, maxdepth, names, paths_with_column, samples)


for base in BASES:
    tops = enum_keys(base)
    if not tops:
        print("%s : absent" % base)
        continue
    names, cols, samples = {}, [], []
    for t in tops:
        scan(base + "\\" + t, 0, 4, names, cols, samples)
    print("=" * 78)
    print(base)
    print("  bag roots: %d   distinct value names: %d" % (len(tops), len(names)))
    top_names = sorted(names.items(), key=lambda kv: -kv[1])[:24]
    print("  most common value names:")
    for nm, cnt in top_names:
        print("    %-28s %d" % (nm, cnt))
    print("  values whose name contains 'Column': %d" % len(cols))
    for p, nm, t in cols[:8]:
        print("    [%s] %s type=%d" % (p, nm, t))
    for p, nm, d in samples:
        print("    sample %s = %s" % (nm, str(d)[:200]))
