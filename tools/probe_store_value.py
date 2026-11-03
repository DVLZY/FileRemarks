# -*- coding: utf-8 -*-
"""Read System.Comment (the 备注 property) out of the REAL property store.

This is the layer Explorer uses: ``SHGetPropertyStoreFromParsingName`` with the
registered handler for the extension. ``probe_column_type.py`` asks the UI layer
(Shell.Application) what the column shows; this asks the store itself, so a
disagreement tells you whether the handler or the column wiring is at fault.

    python tools/probe_store_value.py <file> [file ...]

For each file it prints, per GPS flag set, the store HRESULT, how many
properties the handler reports, and the ``System.Comment`` value.
"""
import ctypes
import os
import sys

ole32 = ctypes.WinDLL("ole32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)
propsys = ctypes.WinDLL("propsys", use_last_error=True)


class GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_ulong), ("Data2", ctypes.c_ushort),
                ("Data3", ctypes.c_ushort), ("Data4", ctypes.c_ubyte * 8)]


class PROPERTYKEY(ctypes.Structure):
    """A PROPERTYKEY is a GUID *followed by* a DWORD pid. Handing GetValue a
    pointer to a bare GUID makes it read the pid out of whatever follows and the
    call dies with an access violation -- which is what happened first time."""
    _fields_ = [("fmtid", GUID), ("pid", ctypes.c_ulong)]


def guid(s):
    out = GUID()
    ole32.CLSIDFromString(s, ctypes.byref(out))
    return out


PKEY_Comment = PROPERTYKEY(guid("{F29F85E0-4FF9-1068-AB91-08002B27B3D9}"), 6)
IID_IPropertyStore = guid("{886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99}")
GPS_DEFAULT = 0
GPS_HANDLERPROPERTIESONLY = 0x1
GPS_BESTEFFORT = 0x100


class PROPVARIANT(ctypes.Structure):
    _fields_ = [("vt", ctypes.c_ushort), ("r1", ctypes.c_ushort),
                ("r2", ctypes.c_ushort), ("r3", ctypes.c_ushort),
                ("data", ctypes.c_ulonglong)]


def read(path, flags, label):
    store = ctypes.c_void_p()
    shell32.SHGetPropertyStoreFromParsingName.argtypes = [
        ctypes.c_wchar_p, ctypes.c_void_p, ctypes.c_ulong,
        ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)]
    shell32.SHGetPropertyStoreFromParsingName.restype = ctypes.c_long
    hr = shell32.SHGetPropertyStoreFromParsingName(
        path, None, flags, ctypes.byref(IID_IPropertyStore), ctypes.byref(store))
    if hr < 0:
        print("   %-28s store hr=0x%08X" % (label, hr & 0xFFFFFFFF))
        return
    vtbl = ctypes.cast(ctypes.cast(store, ctypes.POINTER(ctypes.c_void_p))[0],
                       ctypes.POINTER(ctypes.c_void_p))
    get_count = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p,
                                   ctypes.POINTER(ctypes.c_ulong))(vtbl[3])
    get_value = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p,
                                   ctypes.POINTER(PROPERTYKEY),
                                   ctypes.POINTER(PROPVARIANT))(vtbl[5])
    release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtbl[2])

    count = ctypes.c_ulong(0)
    get_count(store, ctypes.byref(count))
    pv = PROPVARIANT()
    hr_val = get_value(store, ctypes.byref(PKEY_Comment), ctypes.byref(pv))
    if hr_val == 0:
        if pv.vt == 31:  # VT_LPWSTR
            text = ctypes.wstring_at(pv.data)
        elif pv.vt == 0:
            text = ""
        else:
            text = "<vt=%d>" % pv.vt
    else:
        text = None
    # PropVariantClear lives in ole32.dll (NOT in propsys.dll, which only ships
    # the schema helpers -- looking it up there fails with "not found").
    ole32.PropVariantClear(ctypes.byref(pv))
    release(store)
    print("   %-28s count=%d hr=0x%08X value=%r"
          % (label, count.value, hr_val & 0xFFFFFFFF, text))


def main():
    files = sys.argv[1:]
    if not files:
        print("usage: python tools/probe_store_value.py <file> [file ...]")
        return 2
    # The shell store needs an apartment; without it every call returns
    # CO_E_NOTINITIALIZED (0x800401F0) and the probe proves nothing.
    ole32.CoInitializeEx(None, 2)  # COINIT_APARTMENTTHREADED
    for path in files:
        path = os.path.abspath(path)
        print(path)
        for flags, label in ((GPS_DEFAULT, "GPS_DEFAULT"),
                             (GPS_HANDLERPROPERTIESONLY, "HANDLERPROPERTIESONLY"),
                             (GPS_BESTEFFORT, "GPS_BESTEFFORT")):
            read(path, flags, label)
    return 0


if __name__ == "__main__":
    sys.exit(main())
