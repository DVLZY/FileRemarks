"""Does Windows already have a 备注 column schema, and is it System.Comment?

If PKEY_Comment has a registered property description with the Chinese name
备注, then the cleanest design is: store the remark in the ADS as usual, but
publish it through the ALREADY EXISTING System.Comment key. Explorer then shows
it in its built-in 备注 column, and we need no custom .propdesc column at all.

Run:  PYTHONIOENCODING=utf-8 python tools/test_comment_schema.py
"""

import ctypes
import sys
from ctypes import (POINTER, c_long, c_uint16, c_uint32, c_ubyte, c_void_p,
                    c_wchar, c_wchar_p)

MAX_PATH = 260


class GUID(ctypes.Structure):
    _fields_ = [("Data1", c_uint32), ("Data2", c_uint16),
                ("Data3", c_uint16), ("Data4", c_ubyte * 8)]


class PROPERTYKEY(ctypes.Structure):
    _fields_ = [("fmtid", GUID), ("pid", c_uint32)]


class PROPVARIANT(ctypes.Structure):
    _fields_ = [("vt", c_uint16), ("r1", c_uint16), ("r2", c_uint16),
                ("r3", c_uint16), ("ptr", c_void_p), ("pad", c_ubyte * 8)]


def guid(text):
    p = text.strip("{}").split("-")
    g = GUID()
    g.Data1, g.Data2, g.Data3 = int(p[0], 16), int(p[1], 16), int(p[2], 16)
    raw = bytes.fromhex(p[3] + p[4])
    for i in range(8):
        g.Data4[i] = raw[i]
    return g


PKEY_COMMENT = PROPERTYKEY(guid("{F29F85E0-4FF9-1068-AB91-08002B27B3D9}"), 6)
PKEY_REMARK = PROPERTYKEY(guid("{B4C8E6D1-7A2F-4c3b-9D5E-1F6C2A8B3D40}"), 2)

propsys = ctypes.WinDLL("propsys")
ole32 = ctypes.WinDLL("ole32")
ole32.PropVariantClear.argtypes = [c_void_p]
ole32.PropVariantClear.restype = c_long

propsys.PSGetPropertyDescription.argtypes = [
    POINTER(PROPERTYKEY), POINTER(GUID), POINTER(c_void_p)]
propsys.PSGetPropertyDescription.restype = c_long
propsys.PSGetPropertyDescriptionListFromString.argtypes = [
    c_wchar_p, POINTER(GUID), POINTER(c_void_p)]
propsys.PSGetPropertyDescriptionListFromString.restype = c_long
propsys.IPropertyDescription_GetDisplayName = None


def get_attr(pdesc, propkey):
    """Read a string attribute of an IPropertyDescription."""
    pv = PROPVARIANT()
    vtbl = ctypes.cast(pdesc, POINTER(POINTER(c_void_p)))[0]
    # IPropertyDescription vtable: GetDisplayName is index 6 in the SDK order
    # (GetPropertyKey 5, GetCanonicalName 6, GetDisplayName 7, ...).
    fn = ctypes.WINFUNCTYPE(c_long, c_void_p, POINTER(PROPERTYKEY), POINTER(PROPVARIANT))(vtbl[7])
    hr = fn(pdesc, ctypes.byref(propkey), ctypes.byref(pv))
    text = None
    if hr >= 0 and pv.vt == 31 and pv.ptr:
        text = ctypes.cast(pv.ptr, c_wchar_p).value
    ole32.PropVariantClear(ctypes.byref(pv))
    return hr, text


def describe(label, key):
    pdesc = c_void_p()
    hr = propsys.PSGetPropertyDescription(
        ctypes.byref(key), ctypes.byref(guid("{4B6CE8B0-1C5B-4cb3-97C6-9B1F8D0A38A1}")),
        ctypes.byref(pdesc))
    # IID above is arbitrary; retry with the real IID_IPropertyDescription.
    if hr < 0:
        pdesc = c_void_p()
        hr = propsys.PSGetPropertyDescription(
            ctypes.byref(key),
            ctypes.byref(guid("{6F79D558-3E96-4549-A1D1-7D75D2288814}")),
            ctypes.byref(pdesc))
    print("  %-22s PSGetPropertyDescription hr=0x%08X" % (label, hr & 0xFFFFFFFF))
    if hr >= 0 and pdesc:
        hr2, name = get_attr(pdesc, key)
        print("  %-22s display name: hr=0x%08X value=%r"
              % ("", hr2 & 0xFFFFFFFF, name))
        ctypes.cast(pdesc, POINTER(POINTER(c_void_p)))[0][2]  # noop
        vtbl = ctypes.cast(pdesc, POINTER(POINTER(c_void_p)))[0]
        ctypes.WINFUNCTYPE(c_long, c_void_p)(vtbl[2])(pdesc)  # Release
    return hr >= 0


def main():
    ole32.CoInitializeEx(None, 0x2)
    try:
        print("Property descriptions visible to the shell:")
        describe("System.Comment", PKEY_COMMENT)
        describe("our custom remark", PKEY_REMARK)

        print()
        print("Columns in the built-in 'Details' view for a folder:")
        lst = c_void_p()
        hr = propsys.PSGetPropertyDescriptionListFromString(
            "prop:System.Comment;System.FileName;System.Size", 
            ctypes.byref(guid("{6F79D558-3E96-4549-A1D1-7D75D2288814}")),
            ctypes.byref(lst))
        print("  PSGetPropertyDescriptionListFromString hr=0x%08X" % (hr & 0xFFFFFFFF))
        if lst:
            vtbl = ctypes.cast(lst, POINTER(POINTER(c_void_p)))[0]
            n = c_uint32(0)
            ctypes.WINFUNCTYPE(c_long, c_void_p, POINTER(c_uint32))(vtbl[3])(
                lst, ctypes.byref(n))
            print("  entries: %d (System.Comment resolved by the shell: %s)"
                  % (n.value, "yes" if (hr >= 0 and n.value >= 1) else "no"))
            ctypes.WINFUNCTYPE(c_long, c_void_p)(vtbl[2])(lst)
        return 0
    finally:
        ole32.CoUninitialize()


if __name__ == "__main__":
    sys.exit(main())
