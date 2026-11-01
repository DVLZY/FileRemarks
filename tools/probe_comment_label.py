# -*- coding: utf-8 -*-
"""Probe: what does Windows itself call System.Comment (PKEY_Comment)?

The point of this probe is to decide whether our handler should publish the
remark as the *built-in* System.Comment property (which already has a property
description, so no .propdesc of our own is needed) instead of a custom key.
"""
import ctypes
import os
import sys
from ctypes import POINTER, byref, c_void_p, c_uint32, c_uint16, c_wchar_p, c_longlong

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ole32 = ctypes.WinDLL("ole32")
propsys = ctypes.WinDLL("propsys")


class GUID(ctypes.Structure):
    _fields_ = [("Data1", c_uint32), ("Data2", c_uint16), ("Data3", c_uint16),
                ("Data4", ctypes.c_ubyte * 8)]


class PROPERTYKEY(ctypes.Structure):
    _fields_ = [("fmtid", GUID), ("pid", c_uint32)]


def guid(s):
    p = s.strip("{}").split("-")
    g = GUID()
    g.Data1 = int(p[0], 16)
    g.Data2 = int(p[1], 16)
    g.Data3 = int(p[2], 16)
    for i, b in enumerate(bytes.fromhex(p[3] + p[4])):
        g.Data4[i] = b
    return g


IID_IPropertyDescription = guid("{6F79D558-3E96-4549-A1D1-7D75D2288814}")
PKEY_COMMENT = PROPERTYKEY(guid("{F29F85E0-4FF9-1068-AB91-08002B27B3D9}"), 6)


def vcall(obj, index, restype, *argtypes):
    vtbl = ctypes.cast(obj, POINTER(POINTER(c_void_p)))[0]
    fn = ctypes.WINFUNCTYPE(restype, c_void_p, *argtypes)(vtbl[index])
    return lambda *a: fn(obj, *a)


def main():
    hr = ole32.CoInitializeEx(None, 0x2)
    print(f"CoInitializeEx hr={hr & 0xFFFFFFFF:#010x}")
    try:
        propsys.PSGetPropertyDescription.argtypes = [
            POINTER(PROPERTYKEY), POINTER(GUID), POINTER(c_void_p)]
        propsys.PSGetPropertyDescription.restype = ctypes.c_long

        pd = c_void_p()
        hr = propsys.PSGetPropertyDescription(byref(PKEY_COMMENT),
                                              byref(IID_IPropertyDescription), byref(pd))
        print(f"PSGetPropertyDescription(System.Comment) hr={hr & 0xFFFFFFFF:#010x}")
        if hr != 0 or not pd:
            print("no system description for System.Comment")
            return 1

        Release = vcall(pd, 2, ctypes.c_ulong)

        # IPropertyDescription vtable: 3 GetPropertyKey, 4 GetCanonicalName,
        # 5 GetPropertyType, 6 GetDisplayName
        GetCanonicalName = vcall(pd, 4, ctypes.c_long, c_wchar_p, c_uint32)
        buf = ctypes.create_unicode_buffer(256)
        hr = GetCanonicalName(buf, 256)
        print(f"GetCanonicalName hr={hr & 0xFFFFFFFF:#010x} name={buf.value!r}")

        GetDisplayName = vcall(pd, 6, ctypes.c_long, c_wchar_p, c_uint32)
        buf2 = ctypes.create_unicode_buffer(256)
        hr = GetDisplayName(buf2, 256)
        print(f"GetDisplayName   hr={hr & 0xFFFFFFFF:#010x} label={buf2.value!r}")

        # Edit invitation is what Explorer shows in the Details tab editor.
        GetEditInvitation = vcall(pd, 7, ctypes.c_long, c_wchar_p, c_uint32)
        buf3 = ctypes.create_unicode_buffer(256)
        hr = GetEditInvitation(buf3, 256)
        print(f"GetEditInvitation hr={hr & 0xFFFFFFFF:#010x} text={buf3.value!r}")

        Release()
        return 0
    finally:
        ole32.CoUninitialize()


if __name__ == "__main__":
    print(f"cwd={os.getcwd()}")
    sys.exit(main())
