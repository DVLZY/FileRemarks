# -*- coding: utf-8 -*-
"""Read-only: decode the per-user FolderTypes\\<guid>\\DefaultView redirect.

HKCU\\...\\Explorer\\FolderTypes\\{4DCAFE13-E6A7-4C28-BE02-CA8C2126280D}
    DefaultView = {5586158E-F4E6-409E-B47C-4D216F40B912}

Theory: DefaultView names the TopViews sub-key that Explorer should use as this
folder type's default view. If {5586158E...} exists under HKLM ...\\FolderTypes\\
{4DCAFE13...}\\TopViews, that confirms the shape and it gives a per-user,
no-admin way to redirect a folder type to a view whose ColumnList we control:

    HKCU\\...\\FolderTypes\\<FT>\\TopViews\\<our-view-guid>\\ColumnList = ...
    HKCU\\...\\FolderTypes\\<FT>\\DefaultView = <our-view-guid>
"""
import sys
import winreg as wr

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

FT = r"Software\Microsoft\Windows\CurrentVersion\Explorer\FolderTypes"


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
        return []
    out = []
    for i in range(wr.QueryInfoKey(k)[1]):
        try:
            name, data, typ = wr.EnumValue(k, i)
            out.append((name or "(Default)", data, typ))
        except OSError:
            break
    wr.CloseKey(k)
    return out


for ft in ["{4DCAFE13-E6A7-4C28-BE02-CA8C2126280D}",
           "{EA25FBD7-3BF7-409E-B97F-3352240903F4}"]:
    print("=" * 78)
    print("folder type %s" % ft)
    for root, tag in ((wr.HKEY_LOCAL_MACHINE, "HKLM"), (wr.HKEY_CURRENT_USER, "HKCU")):
        tops = subkeys(root, FT + "\\" + ft + "\\TopViews")
        print("  %s TopViews subkeys: %s" % (tag, tops))
        for t in tops:
            vals = values(root, FT + "\\" + ft + "\\TopViews\\" + t)
            names = [v[0] for v in vals]
            cl = [v[1] for v in vals if v[0] == "ColumnList"]
            print("     %s values=%s" % (t, names))
            if cl:
                print("        ColumnList len=%d head=%s" % (len(cl[0]), str(cl[0])[:100]))
        print("  %s top-level values: %s"
              % (tag, [(v[0], str(v[1])[:44]) for v in values(root, FT + "\\" + ft)]))

print()
print("=" * 78)
print("Does ANY folder type in either hive have a DefaultView value?")
for root, tag in ((wr.HKEY_LOCAL_MACHINE, "HKLM"), (wr.HKEY_CURRENT_USER, "HKCU")):
    n = 0
    for ft in subkeys(root, FT):
        for name, data, typ in values(root, FT + "\\" + ft):
            if name == "DefaultView":
                n += 1
                print("  %s %s DefaultView = %s" % (tag, ft, data))
    print("  %s folder types with DefaultView: %d" % (tag, n))
