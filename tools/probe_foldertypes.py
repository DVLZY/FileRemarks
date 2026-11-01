# Read-only probe: how Explorer stores the per-folder-type column layout.
# Used to work out how to make the "备注" column show up by default.
import winreg

FT = "SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Explorer\\FolderTypes"
GENERIC = "{5c4f28b5-f869-4e84-8e60-f11db97c5cc7}"


def dump_columns(vk, label):
    try:
        ck = winreg.OpenKey(vk, "Columns")
    except OSError:
        return
    n = winreg.QueryInfoKey(ck)[0]
    print("    %s Columns: %d" % (label, n))
    for i in range(n):
        try:
            sk = winreg.OpenKey(ck, str(i))
        except OSError:
            continue
        vals = {}
        for j in range(winreg.QueryInfoKey(sk)[1]):
            nm, vd, vt = winreg.EnumValue(sk, j)
            vals[nm] = vd
        print("      [%d] %s" % (i, vals))


k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, FT + "\\" + GENERIC)
print("values:")
for i in range(winreg.QueryInfoKey(k)[1]):
    print("   ", winreg.EnumValue(k, i))

tv = winreg.OpenKey(k, "TopViews")
views = [winreg.EnumKey(tv, i) for i in range(winreg.QueryInfoKey(tv)[0])]
print("views:", views)
for v in views:
    vk = winreg.OpenKey(tv, v)
    print("--", v)
    for i in range(winreg.QueryInfoKey(vk)[1]):
        print("    val", winreg.EnumValue(vk, i))
    print("    subkeys", [winreg.EnumKey(vk, i) for i in range(winreg.QueryInfoKey(vk)[0])])
    dump_columns(vk, v)

# Also check what a normal user's saved view state looks like.
userbase = "Software\\Microsoft\\Windows\\CurrentVersion\\Explorer"
try:
    uk = winreg.OpenKey(winreg.HKEY_CURRENT_USER, userbase + "\\FolderTypes")
    print("\nHKCU FolderTypes subkeys:",
          [winreg.EnumKey(uk, i) for i in range(winreg.QueryInfoKey(uk)[0])][:20])
except OSError as e:
    print("\nHKCU FolderTypes: not present (%s)" % e)
