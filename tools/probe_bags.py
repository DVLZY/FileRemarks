# Read-only probe: per-user folder view state (Bags / BagMRU), to decide how to
# make the 备注 column show by default after install.
import winreg

BAGS = ("Software\\Classes\\Local Settings\\Software\\Microsoft\\Windows\\Shell\\Bags")
BAGMRU = ("Software\\Classes\\Local Settings\\Software\\Microsoft\\Windows\\Shell\\BagMRU")


def walk(root, path, depth=0, maxdepth=3, limit=8):
    try:
        k = winreg.OpenKey(root, path)
    except OSError:
        return
    nsub, nval, _ = winreg.QueryInfoKey(k)
    vals = []
    for i in range(min(nval, limit)):
        vals.append(winreg.EnumValue(k, i))
    print("  " * depth + path.split("\\")[-1] + "  values=%d subkeys=%d" % (nval, nsub))
    for v in vals:
        d = v[1]
        s = str(d)
        print("  " * depth + "    %r = %s" % (v[0], s[:160]))
    if depth >= maxdepth:
        return
    for i in range(min(nsub, limit)):
        try:
            nm = winreg.EnumKey(k, i)
        except OSError:
            break
        walk(root, path + "\\" + nm, depth + 1, maxdepth, limit)


HKCU = winreg.HKEY_CURRENT_USER
print("=== Bags top level ===")
walk(HKCU, BAGS, 0, 1, 20)
print()
print("=== AllFolders ===")
walk(HKCU, BAGS + "\\AllFolders", 0, 3, 30)
print()
print("=== bag sample with a ColumnList ===")
try:
    top = winreg.OpenKey(HKCU, BAGS)
    names = [winreg.EnumKey(top, i) for i in range(winreg.QueryInfoKey(top)[0])]
except OSError as e:
    names = []
    print("no Bags:", e)
print("bag count:", len(names), names[:12])
for nm in names[:12]:
    for sub in ("Shell", "ShellNoRoam"):
        p = BAGS + "\\" + nm + "\\" + sub
        try:
            k = winreg.OpenKey(HKCU, p)
        except OSError:
            continue
        nval = winreg.QueryInfoKey(k)[1]
        for i in range(nval):
            vn, vd, vt = winreg.EnumValue(k, i)
            if "Column" in vn or "LogicalView" in vn or vn in ("Mode", "FolderType"):
                print("  %s\\%s  %s = %s" % (nm, sub, vn, str(vd)[:200]))
