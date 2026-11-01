# -*- coding: utf-8 -*-
"""Read-only: what does a per-user FolderTypes "DefaultView" GUID point at?

HKCU\\...\\Explorer\\FolderTypes\\{4DCAFE13-...}\\DefaultView = {5586158E-F4E6-409E-B47C-4D216F40B912}

If {5586158E-...} exists as a folder type (HKLM or HKCU) with its own TopViews
default view, then the per-user override shape Explorer understands is a
REDIRECT: "use that other folder type's default view for this folder type".
That would let a per-user, no-admin product switch a folder type to a view whose
ColumnList it can control -- without ever touching the TrustedInstaller-owned
HKLM FolderTypes keys.
"""
import sys
import winreg as wr

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = r"Software\Microsoft\Windows\CurrentVersion\Explorer\FolderTypes"
VIEW = r"\TopViews\{00000000-0000-0000-0000-000000000000}"

TARGETS = [
    "{5586158E-F4E6-409E-B47C-4D216F40B912}",
    "{1295023A-B086-4A37-97CC-6CC75E80E020}",
]


def exists(root, path):
    try:
        k = wr.OpenKey(root, path, 0, wr.KEY_READ)
    except OSError:
        return None
    nk, nv = wr.QueryInfoKey(k)[0], wr.QueryInfoKey(k)[1]
    subs, vals = [], []
    for i in range(nk):
        try:
            subs.append(wr.EnumKey(k, i))
        except OSError:
            break
    for i in range(nv):
        try:
            name, data, typ = wr.EnumValue(k, i)
            vals.append((name or "(Default)", data, typ))
        except OSError:
            break
    wr.CloseKey(k)
    return subs, vals


for t in TARGETS:
    print("=" * 78)
    for root, tag in ((wr.HKEY_LOCAL_MACHINE, "HKLM"), (wr.HKEY_CURRENT_USER, "HKCU")):
        got = exists(root, BASE + "\\" + t)
        if got is None:
            print("%s %s : absent" % (tag, t))
            continue
        subs, vals = got
        print("%s %s : %d subkeys %s" % (tag, t, len(subs), subs[:6]))
        for name, data, typ in vals:
            print("     val %-12s type=%d %r" % (name, typ, data))
        for sub in subs:
            if sub.lower() == "topviews":
                got2 = exists(root, BASE + "\\" + t + "\\TopViews")
                print("     TopViews -> %s" % (got2[0] if got2 else "?"))
                for v in (got2[0] if got2 else []):
                    got3 = exists(root, BASE + "\\" + t + VIEW)
                    print("        %s values=%s" % (v, [x[0] for x in (got3[1] if got3 else [])]))
                    for name, data, typ in (got3[1] if got3 else []):
                        if name == "ColumnList":
                            print("           ColumnList len=%d comment=%s"
                                  % (len(str(data)), "System.Comment" in str(data)))
                            print("           %s" % str(data)[:200])

print()
print("=" * 78)
print("Which folder types does HKCU override, and to what?")
root = wr.HKEY_CURRENT_USER
try:
    k = wr.OpenKey(root, BASE, 0, wr.KEY_READ)
except OSError:
    print("  HKCU FolderTypes absent")
else:
    for i in range(wr.QueryInfoKey(k)[0]):
        ft = wr.EnumKey(k, i)
        print("  %s" % ft)
    wr.CloseKey(k)
