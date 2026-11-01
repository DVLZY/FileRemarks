# -*- coding: utf-8 -*-
"""Read-only: is there ANY per-user place where Explorer keeps folder-type /
default-view column information?

The product now installs per-user and never elevates, so it can only write
HKCU. Before designing "auto enable the 备注 column" it matters a great deal
whether Explorer reads a per-user override of the folder type defaults at all.
"""
import sys
import winreg as wr

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def subkeys(root, path):
    try:
        k = wr.OpenKey(root, path, 0, wr.KEY_READ)
    except OSError:
        return None
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


CANDIDATES = [
    r"Software\Microsoft\Windows\CurrentVersion\Explorer\FolderTypes",
    r"Software\Classes\Local Settings\Software\Microsoft\Windows\Shell\FolderTypes",
    r"Software\Classes\Local Settings\Software\Microsoft\Windows\CurrentVersion\Explorer",
    r"Software\Microsoft\Windows\Shell\FolderTypes",
]

for p in CANDIDATES:
    ks = subkeys(wr.HKEY_CURRENT_USER, p)
    if ks is None:
        print("HKCU %-90s : absent" % p)
    else:
        print("HKCU %-90s : %d subkeys" % (p, len(ks)))
        for k in ks[:10]:
            vals = values(wr.HKEY_CURRENT_USER, p + "\\" + k)
            print("      %s  values=%s" % (k, [v[0] for v in (vals or [])]))

print()
print("=" * 78)
print("AllFolders bag: the per-user 'view settings for every folder'")
ALL = r"Software\Classes\Local Settings\Software\Microsoft\Windows\Shell\Bags\AllFolders"
ks = subkeys(wr.HKEY_CURRENT_USER, ALL)
print("  subkeys: %s" % ks)
for k in (ks or []):
    vals = values(wr.HKEY_CURRENT_USER, ALL + "\\" + k) or []
    print("  %s: %d values" % (k, len(vals)))
    for name, data, typ in vals:
        if isinstance(data, bytes):
            print("      %-22s type=%d bytes=%d head=%s" % (name, typ, len(data), data[:24].hex()))
        else:
            print("      %-22s type=%d %s" % (name, typ, str(data)[:60]))

print()
print("=" * 78)
print("Same AllFolders bag under the plain Shell root")
for base in (r"Software\Microsoft\Windows\Shell\Bags\AllFolders",
             r"Software\Microsoft\Windows\ShellNoRoam\Bags\AllFolders"):
    ks = subkeys(wr.HKEY_CURRENT_USER, base)
    print("  %s : %s" % (base, ks))
    for k in (ks or []):
        vals = values(wr.HKEY_CURRENT_USER, base + "\\" + k) or []
        names = [v[0] for v in vals]
        print("      %-10s %d values, ColInfo=%s" % (k, len(vals), "ColInfo" in names))
