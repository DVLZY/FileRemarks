# -*- coding: utf-8 -*-
"""Read-only: for every folder type, dump the TopViews default-view values.

Question this answers: why did EnableCommentColumn() only manage to append
System.Comment to Music and Videos, leaving Generic/Documents/Pictures/Downloads
untouched?

Hypothesis: Explorer stores the default ColumnList of a folder type in the
key's (Default) value for some types and in an explicit "ColumnList" value for
others. The code only ever reads/writes the value NAMED "ColumnList", so every
type whose default lives in (Default) is invisible to it -- ReadCurrentList
returns None and AddToFolderType bails out.
"""
import sys
import winreg as wr

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

VIEW = r"\TopViews\{00000000-0000-0000-0000-000000000000}"
FT = r"Software\Microsoft\Windows\CurrentVersion\Explorer\FolderTypes"

WANT = {
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


def values(root, path):
    try:
        k = wr.OpenKey(root, path, 0, wr.KEY_READ)
    except OSError:
        return None
    out = []
    n = wr.QueryInfoKey(k)[1]
    for i in range(n):
        try:
            name, data, typ = wr.EnumValue(k, i)
        except OSError:
            break
        out.append((name or "(Default)", data, typ))
    wr.CloseKey(k)
    return out


def show(root, label, ft):
    path = FT + "\\" + ft + VIEW
    got = values(root, path)
    if got is None:
        print("  %-4s %s : (no view key)" % (label, ft))
        return
    print("  %-4s %s" % (label, ft))
    for name, data, typ in got:
        if isinstance(data, str):
            has = "System.Comment" in data
            print("        %-16s type=%d len=%3d comment=%s"
                  % (name, typ, len(data), "YES" if has else "no"))
            print("             %s" % data[:120])
        else:
            print("        %-16s type=%d raw=%r" % (name, typ, data))


print("=" * 78)
print("the six folder types the code knows about")
for ft, label in WANT.items():
    show(wr.HKEY_LOCAL_MACHINE, "HKLM", ft)
    show(wr.HKEY_CURRENT_USER, "HKCU", ft)

print()
print("=" * 78)
print("our backups (Software\\FileRemarks\\ColumnList)")
for ft, label in WANT.items():
    for root, tag in ((wr.HKEY_CURRENT_USER, "HKCU"), (wr.HKEY_LOCAL_MACHINE, "HKLM")):
        got = values(root, r"Software\FileRemarks\ColumnList\%s" % ft)
        if got:
            for name, data, typ in got:
                print("  %-4s %-10s %-16s %s" % (tag, label, name, str(data)[:100]))

print()
print("=" * 78)
print("ALL folder types that expose a TopViews default view")
allft = subkeys(wr.HKEY_LOCAL_MACHINE, FT)
print("folder types in HKLM: %d" % len(allft))
for ft in sorted(allft):
    path = FT + "\\" + ft + VIEW
    got = values(wr.HKEY_LOCAL_MACHINE, path)
    if not got:
        continue
    names = [g[0] for g in got]
    default_is_list = "(Default)" in names
    named = "ColumnList" in names
    if default_is_list or named:
        print("  %s  (Default)=%-5s ColumnList=%-5s  %s"
              % (ft, default_is_list, named, WANT.get(ft, "")))
