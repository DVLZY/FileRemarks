"""Where exactly does Explorer keep the per-folder column set?

Adding System.Comment to a folder type's default view only decides the columns
for a folder that has no saved view yet. A folder the user has already opened
has its own saved view, and the saved view wins. That saved state lives in the
Shell "bags", so before deciding whether we may touch it we need the exact key
shape: which subkey holds ColInfo, how many bags have one, and how large the
values are.

Read-only. Prints a summary plus a few examples.
"""

import ctypes
import sys
from ctypes import POINTER, byref, c_void_p, c_ulong, c_wchar_p, create_unicode_buffer
from ctypes import wintypes as wt

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)

HKCU = c_void_p(0x80000001)
KEY_READ = 0x20019
ERROR_SUCCESS = 0
ERROR_NO_MORE_ITEMS = 259

BAGS = r"Software\Classes\Local Settings\Software\Microsoft\Windows\Shell\Bags"


def open_key(root, path):
    h = c_void_p()
    rc = advapi32.RegOpenKeyExW(root, c_wchar_p(path), 0, KEY_READ, byref(h))
    if rc != ERROR_SUCCESS:
        return None, rc
    return h, 0


def close(h):
    if h:
        advapi32.RegCloseKey(h)


def subkeys(h):
    names = []
    i = 0
    while True:
        buf = create_unicode_buffer(512)
        cch = c_ulong(512)
        rc = advapi32.RegEnumKeyExW(h, c_ulong(i), buf, byref(cch), None, None, None, None)
        if rc == ERROR_NO_MORE_ITEMS:
            break
        if rc != ERROR_SUCCESS:
            break
        names.append(buf.value)
        i += 1
    return names


def value_info(h, name):
    """(type, size) for one value, or None."""
    type_ = c_ulong()
    cb = c_ulong()
    rc = advapi32.RegQueryValueExW(h, c_wchar_p(name), None, byref(type_), None, byref(cb))
    if rc != ERROR_SUCCESS:
        return None
    return type_.value, cb.value


def values(h):
    names = []
    i = 0
    while True:
        buf = create_unicode_buffer(512)
        cch = c_ulong(512)
        type_ = c_ulong()
        cb = c_ulong()
        rc = advapi32.RegEnumValueW(h, c_ulong(i), buf, byref(cch), None, byref(type_), None, byref(cb))
        if rc == ERROR_NO_MORE_ITEMS:
            break
        if rc != ERROR_SUCCESS:
            break
        names.append((buf.value, type_.value, cb.value))
        i += 1
    return names


def main():
    root, rc = open_key(HKCU, BAGS)
    if not root:
        print("cannot open %s (rc=0x%08X)" % (BAGS, rc))
        return 1

    roots = subkeys(root)
    print("bag roots: %d" % len(roots))

    with_colinfo = []
    total_shell = 0
    total_colinfo = 0
    shapes = {}

    for bag in roots:
        hb, _ = open_key(root, bag)
        if not hb:
            continue
        for child in subkeys(hb):
            cp = bag + "\\" + child
            hc, _ = open_key(root, cp)
            if not hc:
                continue
            if child.lower() == "shell":
                total_shell += 1
            info = value_info(hc, "ColInfo")
            if info:
                total_colinfo += 1
                with_colinfo.append((cp, info[1]))
                # Which bag subkey shape carries it?
                shape = child.lower()
                shapes[shape] = shapes.get(shape, 0) + 1
            close(hc)
        close(hb)
    close(root)

    print("paths containing a 'Shell' subkey: %d" % total_shell)
    print("paths containing ColInfo: %d" % total_colinfo)
    print("bag subkey names that carry ColInfo: %r" % shapes)

    if with_colinfo:
        sizes = sorted(sz for _, sz in with_colinfo)
        print("ColInfo sizes: min=%d median=%d max=%d" % (
            sizes[0], sizes[len(sizes) // 2], sizes[-1]))
        print("first examples:")
        for path, sz in with_colinfo[:6]:
            print("   %-64s %d bytes" % (path, sz))

    # AllFolders is the template Explorer uses for folders with no bag of their
    # own, so check whether it has a column set too.
    for probe in ("AllFolders\\Shell", "AllFolders\\ShellNoRoam"):
        h, rc = open_key(HKCU, BAGS + "\\" + probe)
        if h:
            names = [n for n, _, _ in values(h)]
            print("%s: values=%r" % (probe, names))
            close(h)
        else:
            print("%s: absent (rc=0x%08X)" % (probe, rc))

    return 0


if __name__ == "__main__":
    sys.exit(main())
