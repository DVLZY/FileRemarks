# -*- coding: utf-8 -*-
"""Read-only: understand the current ColumnList state and saved views.

Answers three questions:
  1. Which folder types have a TopViews ColumnList, and which of them already
     mention System.Comment? (coverage of the current hardcoded list of six)
  2. What did our own backups record as the "original"? (had Windows already
     shipped System.Comment there, or did we append it?)
  3. Does this user have saved per-folder views (Bags/BagMRU)? Those override
     the folder-type default, so they decide whether patching the default can
     ever be visible without a per-folder change.
"""
import sys
import winreg as wr

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

FT = r"Software\Microsoft\Windows\CurrentVersion\Explorer\FolderTypes"
ALLVIEW = "{00000000-0000-0000-0000-000000000000}"
KNOWN = {
    "{5c4f28b5-f869-4e84-8e60-f11db97c5cc7}": "Generic",
    "{7d49d726-3c21-4f05-99aa-fdc2c9474656}": "Documents",
    "{b3690e58-e961-423b-b687-386ebfd83239}": "Pictures",
    "{885a186e-a440-4ada-812b-db871b942259}": "Downloads",
    "{94d6ddcc-4a68-4175-a374-bd584a510b78}": "Music",
    "{5fa96407-7e77-483c-ac93-691d05850de8}": "Videos",
}


def subkeys(root, path):
    try:
        k = wr.OpenKey(root, path, 0, wr.KEY_READ)
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


def getvalue(root, path, name):
    try:
        k = wr.OpenKey(root, path, 0, wr.KEY_READ)
    except OSError:
        return None
    try:
        v = wr.QueryValueEx(k, name)[1]
    except OSError:
        v = None
    wr.CloseKey(k)
    return v


def as_text(v):
    if isinstance(v, str):
        return v
    return repr(v)


hklm = subkeys(wr.HKEY_LOCAL_MACHINE, FT)
print("=" * 78)
print("1) every HKLM folder type whose TopViews default carries a ColumnList")
print("=" * 78)
covered = 0
total = 0
for g in hklm:
    path = FT + "\\" + g + "\\TopViews\\" + ALLVIEW
    cl = getvalue(wr.HKEY_LOCAL_MACHINE, path, "ColumnList")
    if not isinstance(cl, str):
        continue
    total += 1
    has = "System.Comment" in cl
    name = KNOWN.get(g.lower(), KNOWN.get(g, "(not in our list)"))
    if name != "(not in our list)":
        covered += 1
    print("%-30s %-18s len=%-4d comment=%s" % (g, name, len(cl), "YES" if has else "no"))

print()
print("folder types with a ColumnList: %d   in our hardcoded list: %d" % (total, covered))

print()
print("=" * 78)
print("2) our backups: Software\\FileRemarks\\ColumnList\\<guid>")
print("=" * 78)
for label, root in (("HKLM", wr.HKEY_LOCAL_MACHINE), ("HKCU", wr.HKEY_CURRENT_USER)):
    subs = subkeys(root, r"Software\FileRemarks\ColumnList")
    if not subs:
        print("%s: no backups" % label)
        continue
    for g in subs:
        orig = getvalue(root, r"Software\FileRemarks\ColumnList" + "\\" + g, "")
        cur = getvalue(root, FT + "\\" + g + "\\TopViews\\" + ALLVIEW, "ColumnList")
        nm = KNOWN.get(g.lower(), KNOWN.get(g, g))
        print("%s %-12s orig_len=%-4s orig_hasComment=%s  cur_hasComment=%s"
              % (label, nm,
                 len(orig) if isinstance(orig, str) else "?",
                 ("YES" if "System.Comment" in orig else "no") if isinstance(orig, str) else "?",
                 ("YES" if "System.Comment" in cur else "no") if isinstance(cur, str) else "MISSING"))

print()
print("=" * 78)
print("3) saved per-folder views (these override the folder-type default)")
print("=" * 78)


def walk(root, path, depth, maxdepth, hits, counter):
    subs = subkeys(root, path)
    counter[0] += len(subs)
    if depth >= maxdepth:
        return
    for s in subs:
        walk(root, path + "\\" + s, depth + 1, maxdepth, hits, counter)


for path in (
    r"Software\Microsoft\Windows\Shell\BagMRU",
    r"Software\Microsoft\Windows\ShellNoRoam\BagMRU",
    r"Software\Microsoft\Windows\Shell\Bags",
    r"Software\Microsoft\Windows\ShellNoRoam\Bags",
):
    n = [0]
    walk(wr.HKEY_CURRENT_USER, path, 0, 3, [], n)
    top = subkeys(wr.HKEY_CURRENT_USER, path)
    print("%-46s top=%-3d total(<=3 deep)=%d" % (path, len(top), n[0]))
