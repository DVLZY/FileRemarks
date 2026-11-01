# -*- coding: utf-8 -*-
"""Read-only: what does the machine actually have for FolderTypes / ColumnList?"""
import sys
import winreg as wr

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

GENERIC = "{5c4f28b5-f869-4e84-8e60-f11db97c5cc7}"
DOCS = "{7d49d726-3c21-4f05-99aa-fdc2c9474656}"
PICS = "{b3690e58-e961-423b-b687-386ebfd83239}"
DOWN = "{885a186e-a440-4ada-812b-db871b942259}"
MUSIC = "{94d6ddcc-4a68-4175-a374-bd584a510b78}"
VIDEO = "{5fa96407-7e77-483c-ac93-691d05850de8}"
NAMES = {
    GENERIC: "Generic", DOCS: "Documents", PICS: "Pictures",
    DOWN: "Downloads", MUSIC: "Music", VIDEO: "Videos",
}
ALLVIEW = "{00000000-0000-0000-0000-000000000000}"
FT = r"Software\Microsoft\Windows\CurrentVersion\Explorer\FolderTypes"


def subkeys(root, path):
    try:
        k = wr.OpenKey(root, path, 0, wr.KEY_READ)
    except OSError as e:
        return None, str(e)
    out = []
    i = 0
    while True:
        try:
            out.append(wr.EnumKey(k, i))
        except OSError:
            break
        i += 1
    wr.CloseKey(k)
    return out, None


def values(root, path):
    try:
        k = wr.OpenKey(root, path, 0, wr.KEY_READ)
    except OSError as e:
        return None, str(e)
    out = {}
    i = 0
    while True:
        try:
            name, data, typ = wr.EnumValue(k, i)
        except OSError:
            break
        out[name or "(default)"] = (typ, data)
        i += 1
    wr.CloseKey(k)
    return out, None


print("=" * 70)
print("HKLM FolderTypes: does each folder type exist, which TopViews?")
print("=" * 70)
for g in NAMES:
    subs, err = subkeys(wr.HKEY_LOCAL_MACHINE, FT + "\\" + g)
    if err:
        print("%-10s HKLM key: MISSING (%s)" % (NAMES[g], err))
        continue
    tv, err2 = subkeys(wr.HKEY_LOCAL_MACHINE, FT + "\\" + g + "\\TopViews")
    print("%-10s HKLM present; TopViews=%s" % (NAMES[g], tv if not err2 else err2))

print()
print("=" * 70)
print("ColumnList values (HKLM then HKCU) per folder type")
print("=" * 70)
for g in NAMES:
    path = FT + "\\" + g + "\\TopViews\\" + ALLVIEW
    for label, root in (("HKLM", wr.HKEY_LOCAL_MACHINE), ("HKCU", wr.HKEY_CURRENT_USER)):
        vals, err = values(root, path)
        if err:
            print("%-10s %s: no key" % (NAMES[g], label))
            continue
        cl = vals.get("ColumnList")
        if cl is None:
            print("%-10s %s: key exists, NO ColumnList  (values: %s)"
                  % (NAMES[g], label, ", ".join(sorted(vals)) or "none"))
        else:
            txt = cl[1] if isinstance(cl[1], str) else str(cl[1])
            print("%-10s %s: ColumnList len=%d hasComment=%s"
                  % (NAMES[g], label, len(txt), "System.Comment" in txt))
            print("           %s" % txt[:200])

print()
print("=" * 70)
print("Our bookkeeping: Software\\FileRemarks (HKLM = v1.8 era, HKCU = v1.9+ era)")
print("=" * 70)
for label, root in (("HKLM", wr.HKEY_LOCAL_MACHINE), ("HKCU", wr.HKEY_CURRENT_USER)):
    subs, err = subkeys(root, r"Software\FileRemarks")
    if err:
        print("%s Software\\FileRemarks: absent" % label)
        continue
    print("%s Software\\FileRemarks subkeys: %s" % (label, subs))
    backups, err2 = subkeys(root, r"Software\FileRemarks\ColumnList")
    if err2:
        print("   ColumnList backups: %s" % err2)
    else:
        print("   ColumnList backups: %d -> %s" % (len(backups), [NAMES.get(b, b) for b in backups]))

print()
print("=" * 70)
print("HKCU FolderTypes (any per-user folder type keys at all?)")
print("=" * 70)
subs, err = subkeys(wr.HKEY_CURRENT_USER, FT)
if err:
    print("HKCU FolderTypes missing:", err)
else:
    print("HKCU FolderTypes keys: %d" % len(subs))
    for s in subs[:12]:
        tv, e = subkeys(wr.HKEY_CURRENT_USER, FT + "\\" + s + "\\TopViews")
        print("   %s  TopViews=%s" % (s, tv if not e else "none"))
