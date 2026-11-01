# -*- coding: utf-8 -*-
"""Read-only: what does the STANDARD default view subkey contain per folder type?

{00000000-0000-0000-0000-000000000000} is the "All items" / default view of a
folder type. If we want to publish the same view plus one column under HKCU, we
must copy whatever Explorer expects to find there, so dump it.
"""
import sys
import winreg as wr

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

FT = r"Software\Microsoft\Windows\CurrentVersion\Explorer\FolderTypes"
DEF = r"\TopViews\{00000000-0000-0000-0000-000000000000}"

WANT = [
    ("{5c4f28b5-f869-4e84-8e60-f11db97c5cc7}", "Generic"),
    ("{7d49d726-3c21-4f05-99aa-fdc2c9474656}", "Documents"),
    ("{b3690e58-e961-423b-b687-386ebfd83239}", "Pictures"),
    ("{885a186e-a440-4ada-812b-db871b942259}", "Downloads"),
    ("{94d6ddcc-4a68-4175-a374-bd584a510b78}", "Music"),
    ("{5fa96407-7e77-483c-ac93-691d05850de8}", "Videos"),
]


def dump(root, path, indent="  "):
    try:
        k = wr.OpenKey(root, path, 0, wr.KEY_READ)
    except OSError:
        print(indent + "(absent)")
        return
    for i in range(wr.QueryInfoKey(k)[1]):
        try:
            name, data, typ = wr.EnumValue(k, i)
        except OSError:
            break
        shown = data
        if isinstance(data, str) and len(data) > 90:
            shown = data[:90] + "..."
        elif isinstance(data, bytes):
            shown = "<%d bytes>" % len(data)
        print(indent + "%-24s type=%-2s %r" % (name or "(Default)", typ, shown))
    wr.CloseKey(k)


for guid, label in WANT:
    print("=" * 78)
    print("%s %s" % (label, guid))
    print("  parent folder-type values:")
    dump(wr.HKEY_LOCAL_MACHINE, FT + "\\" + guid, "    ")
    print("  default view {0000...} values:")
    dump(wr.HKEY_LOCAL_MACHINE, FT + "\\" + guid + DEF, "    ")
