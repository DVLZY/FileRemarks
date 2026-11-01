"""How much does the property handler actually contribute to a file's columns?

Explorer's property store for a file is composed from several sources (the
filesystem, the OLE property set inside the file, and the registered property
handler). If we take over a type's handler slot we only lose the columns the
handler itself supplied -- provided we forward them, or they come from
somewhere else.

This probe measures that contribution directly: it compares the number of
properties in the full store against the number returned with
GPS_HANDLERPROPERTIESONLY, which restricts the store to the handler's own
properties.

Run:  PYTHONIOENCODING=utf-8 python tools/test_handler_only.py
"""

import ctypes
import os
import sys
from ctypes import (POINTER, byref, c_long, c_uint16, c_uint32, c_ubyte,
                    c_void_p, c_wchar_p)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = os.path.join(ROOT, "build", "_chain_matrix")


class GUID(ctypes.Structure):
    _fields_ = [("Data1", c_uint32), ("Data2", c_uint16),
                ("Data3", c_uint16), ("Data4", c_ubyte * 8)]

    def __str__(self):
        d4 = "".join("%02X" % b for b in self.Data4)
        return "{%08X-%04X-%04X-%s-%s}" % (
            self.Data1, self.Data2, self.Data3, d4[:4], d4[4:])


class PROPERTYKEY(ctypes.Structure):
    _fields_ = [("fmtid", GUID), ("pid", c_uint32)]


def guid(text):
    p = text.strip("{}").split("-")
    g = GUID()
    g.Data1, g.Data2, g.Data3 = int(p[0], 16), int(p[1], 16), int(p[2], 16)
    raw = bytes.fromhex(p[3] + p[4])
    for i in range(8):
        g.Data4[i] = raw[i]
    return g


IID_IPropertyStore = guid("{886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99}")

ole32 = ctypes.WinDLL("ole32")
shell32 = ctypes.WinDLL("shell32")
shell32.SHGetPropertyStoreFromParsingName.argtypes = [
    c_wchar_p, c_void_p, c_uint32, POINTER(GUID), POINTER(c_void_p)]
shell32.SHGetPropertyStoreFromParsingName.restype = c_long

GPS_DEFAULT = 0x00000000
GPS_HANDLERPROPERTIESONLY = 0x00000001

PKEY_COMMENT = (guid("{F29F85E0-4FF9-1068-AB91-08002B27B3D9}"), 6)


def vcall(obj, index, restype, *argtypes):
    vtbl = ctypes.cast(obj, POINTER(POINTER(c_void_p)))[0]
    fn = ctypes.WINFUNCTYPE(restype, c_void_p, *argtypes)(vtbl[index])
    return fn


def release(obj):
    if obj:
        vcall(obj, 2, ctypes.c_ulong)(obj)


def count_props(path, flags):
    store = c_void_p()
    hr = shell32.SHGetPropertyStoreFromParsingName(
        path, None, flags, byref(IID_IPropertyStore), byref(store))
    if hr < 0 or not store:
        return None, hr
    n = c_uint32(0)
    vcall(store, 3, c_long, POINTER(c_uint32))(store, byref(n))
    release(store)
    return n.value, hr


def has_comment(path):
    store = c_void_p()
    hr = shell32.SHGetPropertyStoreFromParsingName(
        path, None, GPS_DEFAULT, byref(IID_IPropertyStore), byref(store))
    if hr < 0 or not store:
        return None
    key = PROPERTYKEY()
    key.fmtid = PKEY_COMMENT[0]
    key.pid = PKEY_COMMENT[1]
    pv = (c_ubyte * 32)()
    hr2 = vcall(store, 5, c_long, POINTER(PROPERTYKEY), c_void_p)(
        store, byref(key), ctypes.byref(pv))
    vt = ctypes.cast(pv, POINTER(c_uint16))[0]
    ole32.PropVariantClear(ctypes.byref(pv))
    release(store)
    return (hr2, vt)


def main():
    ole32.CoInitializeEx(None, 0x2)
    try:
        if not os.path.isdir(WORK):
            print("run tools/test_chain_matrix.py first (no samples)")
            return 1

        print("%-8s %8s %8s %10s   %s" % (
            "ext", "full", "handler", "handler%", "interpretation"))
        print("-" * 78)
        for name in sorted(os.listdir(WORK)):
            ext = os.path.splitext(name)[1]
            path = os.path.join(WORK, name)
            if not os.path.isfile(path):
                continue
            full, hr_full = count_props(path, GPS_DEFAULT)
            hand, hr_hand = count_props(path, GPS_HANDLERPROPERTIESONLY)
            if full is None or hand is None:
                print("%-8s %8s %8s %10s   store error full=0x%08X hand=0x%08X"
                      % (ext, full, hand, "-",
                         hr_full & 0xFFFFFFFF, hr_hand & 0xFFFFFFFF))
                continue
            pct = 0.0 if not full else 100.0 * hand / full
            if hand == 0:
                note = "handler adds NOTHING -> takeover costs no columns"
            elif hand == full:
                note = "store IS the handler -> must forward it"
            else:
                note = "handler supplies %d of %d columns" % (hand, full)
            print("%-8s %8d %8d %9.0f%%   %s" % (ext, full, hand, pct, note))

        print()
        print("System.Comment readability per type:")
        for name in sorted(os.listdir(WORK)):
            path = os.path.join(WORK, name)
            if not os.path.isfile(path):
                continue
            got = has_comment(path)
            if got is None:
                print("  %-8s store unavailable" % os.path.splitext(name)[1])
            else:
                hr2, vt = got
                print("  %-8s GetValue hr=0x%08X vt=%d"
                      % (os.path.splitext(name)[1], hr2 & 0xFFFFFFFF, vt))
        return 0
    finally:
        ole32.CoUninitialize()


if __name__ == "__main__":
    sys.exit(main())
