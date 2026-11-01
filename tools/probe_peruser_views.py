"""Does Explorer ever keep a full per-user folder-type view in HKCU?

The auto-enable design writes the 备注 column into a per-user copy of a folder
type's default view:

    HKCU\Software\Microsoft\Windows\CurrentVersion\Explorer\FolderTypes\<ft>
        \TopViews\{00000000-0000-0000-0000-000000000000}\ColumnList

That is only worth doing if Explorer reads per-user folder types at all. This
probe looks for prior art: any per-user folder-type key (in either hive) that
carries a TopViews subkey, and what those keys contain.

Read-only.
"""

import ctypes
import sys
from ctypes import byref, c_void_p, c_ulong, c_wchar_p, create_unicode_buffer
from ctypes import wintypes as wt

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)

ROOTS = {"HKCU": c_void_p(0x80000001), "HKLM": c_void_p(0x80000002)}
KEY_READ = 0x20019
ERROR_SUCCESS = 0
ERROR_NO_MORE_ITEMS = 259

FT = r"Software\Microsoft\Windows\CurrentVersion\Explorer\FolderTypes"


def open_key(root, path):
    h = c_void_p()
    rc = advapi32.RegOpenKeyExW(root, c_wchar_p(path), 0, KEY_READ, byref(h))
    return (h if rc == ERROR_SUCCESS else None)


def subkeys(h):
    out, i = [], 0
    while True:
        buf = create_unicode_buffer(512)
        cch = c_ulong(512)
        rc = advapi32.RegEnumKeyExW(h, c_ulong(i), buf, byref(cch), None, None, None, None)
        if rc != ERROR_SUCCESS:
            break
        out.append(buf.value)
        i += 1
    return out


def values(h):
    out, i = [], 0
    while True:
        buf = create_unicode_buffer(512)
        cch = c_ulong(512)
        type_ = c_ulong()
        cb = c_ulong()
        rc = advapi32.RegEnumValueW(h, c_ulong(i), buf, byref(cch), None, byref(type_), None, byref(cb))
        if rc != ERROR_SUCCESS:
            break
        out.append((buf.value, type_.value, cb.value))
        i += 1
    return out


def main():
    for hive_name, root in ROOTS.items():
        top = open_key(root, FT)
        if not top:
            print("%s FolderTypes: absent" % hive_name)
            continue
        types = subkeys(top)
        with_views = []
        for ft in types:
            hft = open_key(root, FT + "\\" + ft)
            if not hft:
                continue
            kids = subkeys(hft)
            if "TopViews" in kids:
                htv = open_key(root, FT + "\\" + ft + "\\TopViews")
                view_names = subkeys(htv) if htv else []
                with_views.append((ft, view_names, values(hft)))
            else:
                print("%s  %s  values=%r" % (hive_name, ft, [n for n, _, _ in values(hft)]))
            if hft:
                advapi32.RegCloseKey(hft)

        print("%s: %d folder types, %d of them with a TopViews subkey" % (
            hive_name, len(types), len(with_views)))
        for ft, view_names, own_values in with_views:
            print("   %s  views=%d %r  values=%r" % (
                ft, len(view_names), view_names[:3], [n for n, _, _ in own_values]))
        advapi32.RegCloseKey(top)

    # If HKCU has no folder-type views at all, say so plainly: the design then
    # rests on Explorer honouring a per-user copy, which must be confirmed on
    # real hardware before we call the feature working.
    hkc = open_key(ROOTS["HKCU"], FT)
    if hkc:
        types = subkeys(hkc)
        withviews = 0
        for ft in types:
            h = open_key(ROOTS["HKCU"], FT + "\\" + ft + "\\TopViews")
            if h:
                withviews += 1
                advapi32.RegCloseKey(h)
        print()
        print("VERDICT: HKCU folder types=%d, with TopViews=%d" % (len(types), withviews))
        if withviews == 0:
            print("  no prior art on this machine -- a per-user view copy is a NEW")
            print("  key group, not a conflict, but its effect needs one real check.")
        advapi32.RegCloseKey(hkc)
    return 0


if __name__ == "__main__":
    sys.exit(main())
