"""What is System.Comment called in the shell's own (Chinese) UI?

IPropertyDescription vtable layout (after IUnknown's 3 slots):
  3 GetPropertyKey
  4 GetCanonicalName
  5 GetDisplayName
  6 GetEditInvitation
  7 GetType
  8 GetDisplayType

Both GetCanonicalName and GetDisplayName write into a caller buffer:
  HRESULT GetDisplayName(LPWSTR pszName, UINT cchName)

Run:  PYTHONIOENCODING=utf-8 python tools/test_comment_schema2.py
"""

import ctypes
import sys
from ctypes import (POINTER, byref, c_long, c_uint16, c_uint32, c_ubyte,
                    c_void_p, c_wchar, c_wchar_p)

IID_IPropertyDescription = "{6F79D558-3E96-4549-A1D1-7D75D2288814}"


class GUID(ctypes.Structure):
    _fields_ = [("Data1", c_uint32), ("Data2", c_uint16),
                ("Data3", c_uint16), ("Data4", c_ubyte * 8)]


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


propsys = ctypes.WinDLL("propsys")
ole32 = ctypes.WinDLL("ole32")
propsys.PSGetPropertyDescription.argtypes = [
    POINTER(PROPERTYKEY), POINTER(GUID), POINTER(c_void_p)]
propsys.PSGetPropertyDescription.restype = c_long


def vtbl_of(obj):
    return ctypes.cast(obj, POINTER(POINTER(c_void_p)))[0]


def call_str(obj, index):
    buf = ctypes.create_unicode_buffer(512)
    fn = ctypes.WINFUNCTYPE(c_long, c_void_p, c_wchar_p, c_uint32)(vtbl_of(obj)[index])
    hr = fn(obj, ctypes.cast(buf, c_wchar_p), 512)
    return hr, (buf.value if hr >= 0 else None)


def call_key(obj, index):
    out = PROPERTYKEY()
    fn = ctypes.WINFUNCTYPE(c_long, c_void_p, POINTER(PROPERTYKEY))(vtbl_of(obj)[index])
    hr = fn(obj, byref(out))
    return hr, out


def show(label, key):
    pdesc = c_void_p()
    hr = propsys.PSGetPropertyDescription(
        byref(key), byref(guid(IID_IPropertyDescription)), byref(pdesc))
    print("%s:" % label)
    print("   PSGetPropertyDescription hr=0x%08X" % (hr & 0xFFFFFFFF))
    if hr < 0 or not pdesc:
        return
    hr_key, got_key = call_key(pdesc, 3)
    hr_can, canon = call_str(pdesc, 4)
    hr_dis, disp = call_str(pdesc, 5)
    print("   GetPropertyKey    hr=0x%08X pid=%d" % (hr_key & 0xFFFFFFFF, got_key.pid))
    print("   GetCanonicalName  hr=0x%08X %r" % (hr_can & 0xFFFFFFFF, canon))
    print("   GetDisplayName    hr=0x%08X %r" % (hr_dis & 0xFFFFFFFF, disp))
    ctypes.WINFUNCTYPE(c_long, c_void_p)(vtbl_of(pdesc)[2])(pdesc)


def main():
    ole32.CoInitializeEx(None, 0x2)
    try:
        show("System.Comment",
             PROPERTYKEY(guid("{F29F85E0-4FF9-1068-AB91-08002B27B3D9}"), 6))
        print()
        show("System.Title (control)",
             PROPERTYKEY(guid("{F29F85E0-4FF9-1068-AB91-08002B27B3D9}"), 2))
        print()
        show("our custom PKEY (not installed yet)",
             PROPERTYKEY(guid("{B4C8E6D1-7A2F-4c3b-9D5E-1F6C2A8B3D40}"), 2))
        return 0
    finally:
        ole32.CoUninitialize()


if __name__ == "__main__":
    sys.exit(main())
