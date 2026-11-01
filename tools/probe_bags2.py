# Read-only probe: find bag entries that carry a ColumnList, to see whether a
# per-folder saved view overrides the FolderTypes default columns.
import winreg

HKCU = winreg.HKEY_CURRENT_USER
BAGS = "Software\\Classes\\Local Settings\\Software\\Microsoft\\Windows\\Shell\\Bags"


def find(path, out, depth=0):
    if depth > 3:
        return
    try:
        k = winreg.OpenKey(HKCU, path)
    except OSError:
        return
    nsub, nval, _ = winreg.QueryInfoKey(k)
    for i in range(nval):
        try:
            vn, vd, vt = winreg.EnumValue(k, i)
        except OSError:
            continue
        if vn in ("ColumnList", "ColumnListA") or "Columns" in vn:
            out.append((path, vn, vd, vt))
    for i in range(nsub):
        try:
            nm = winreg.EnumKey(k, i)
        except OSError:
            break
        find(path + "\\" + nm, out, depth + 1)


hits = []
find(BAGS, hits)
print("entries with column info:", len(hits))
seen = {}
for path, vn, vd, vt in hits:
    key = vn
    seen.setdefault(key, 0)
    seen[key] += 1
    if seen[key] <= 6:
        print("  %s\\%s (vt=%d) = %s" % (path, vn, vt, str(vd)[:220]))
print("counts by value name:", seen)

# Look at one folder bag end to end.
top = winreg.OpenKey(HKCU, BAGS)
names = [winreg.EnumKey(top, i) for i in range(min(3, winreg.QueryInfoKey(top)[0]))]
for nm in names:
    p = BAGS + "\\" + nm
    try:
        k = winreg.OpenKey(HKCU, p)
    except OSError:
        continue
    print("\n--- bag", nm, "subkeys:", [winreg.EnumKey(k, i) for i in range(winreg.QueryInfoKey(k)[0])])
