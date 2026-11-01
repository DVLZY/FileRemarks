# -*- coding: utf-8 -*-
"""Read-only: inspect the two per-user FolderTypes overrides that already exist.

HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\FolderTypes has two
subkeys on this machine, both carrying a value literally named "DefaultView".
That means the per-user override shape Explorer understands is:

    HKCU\\...\\Explorer\\FolderTypes\\<guid>\\DefaultView\\<view-guid>
        ColumnList = ...

i.e. the per-user equivalent of HKLM's TopViews\\{0000...}. Confirm the shape and
whether ColumnList lives under that DefaultView subkey.
"""
import sys
import winreg as wr

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = r"Software\Microsoft\Windows\CurrentVersion\Explorer\FolderTypes"
ROOT = wr.HKEY_CURRENT_USER


def subkeys(path):
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


def dump(path, indent="  "):
    try:
        k = wr.OpenKey(ROOT, path, 0, wr.KEY_READ)
    except OSError:
        return False
    n = wr.QueryInfoKey(k)[1]
    for i in range(n):
        try:
            name, data, typ = wr.EnumValue(k, i)
        except OSError:
            break
        if isinstance(data, bytes):
            shown = "bytes=%d head=%s" % (len(data), data[:32].hex())
        else:
            shown = "%r" % (data if len(str(data)) < 200 else str(data)[:200])
        print("%s%-18s type=%d %s" % (indent, name or "(Default)", typ, shown))
    wr.CloseKey(k)
    return True


for ft in subkeys(BASE):
    print("=" * 78)
    print("HKCU FolderTypes\\%s" % ft)
    dump(BASE + "\\" + ft)
    for sub in subkeys(BASE + "\\" + ft):
        print("  subkey: %s" % sub)
        dump(BASE + "\\" + ft + "\\" + sub, "        ")
        for sub2 in subkeys(BASE + "\\" + ft + "\\" + sub):
            print("    subkey: %s" % sub2)
            dump(BASE + "\\" + ft + "\\" + sub + "\\" + sub2, "          ")

print()
print("=" * 78)
print("For comparison, the HKLM shape of the same folder types:")
for ft in subkeys(BASE)[:0]:
    pass
FT_LM = wr.HKEY_LOCAL_MACHINE
for ft in ["{4DCAFE13-E6A7-4C28-BE02-CA8C2126280D}",
           "{EA25FBD7-3BF7-409E-B97F-3352240903F4}"]:
    p = BASE + "\\" + ft
    try:
        k = wr.OpenKey(FT_LM, p, 0, wr.KEY_READ)
    except OSError:
        print("  HKLM\\%s : absent" % p)
        continue
    print("  HKLM\\%s : subkeys=%d" % (p, wr.QueryInfoKey(k)[0]))
    for i in range(wr.QueryInfoKey(k)[0]):
        print("      %s" % wr.EnumKey(k, i))
    wr.CloseKey(k)
