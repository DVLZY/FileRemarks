# -*- coding: utf-8 -*-
"""In-process COM test for FileRemarksPropHandler.dll via ctypes.

Loads the real built DLL, creates the property handler through DllGetClassObject,
binds it to a real temp file, then exercises SetValue / Commit / GetValue and
checks the NTFS :remark ADS from Python. This gives genuine runtime evidence
without needing to spawn a native process (blocked in this sandbox).
"""
import ctypes
from ctypes import wintypes, POINTER, byref, c_void_p, c_uint32, c_uint16, c_ubyte

ole32 = ctypes.WinDLL("ole32")
shell32 = ctypes.WinDLL("shell32")

HRESULT = ctypes.c_long
ULONG = ctypes.c_ulong
DWORD = ctypes.c_uint32


class GUID(ctypes.Structure):
    _fields_ = [("Data1", DWORD), ("Data2", c_uint16), ("Data3", c_uint16),
                ("Data4", c_ubyte * 8)]

    def __init__(self, s=None):
        super().__init__()
        if s:
            # parse {XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX}
            s = s.strip("{}")
            parts = s.split("-")
            self.Data1 = int(parts[0], 16)
            self.Data2 = int(parts[1], 16)
            self.Data3 = int(parts[2], 16)
            b = bytes.fromhex(parts[3] + parts[4])
            for i, v in enumerate(b):
                self.Data4[i] = v


class PROPERTYKEY(ctypes.Structure):
    _fields_ = [("fmtid", GUID), ("pid", DWORD)]


# 24 bytes on x64: 8-byte header (vt + 3 reserved WORDs) then the union.
# VT_LPWSTR stores its pointer at offset 8 (start of the union).
class PROPVARIANT(ctypes.Structure):
    _fields_ = [("vt", c_uint16), ("r1", c_uint16), ("r2", c_uint16), ("r3", c_uint16),
                ("ptr", c_void_p), ("pad2", c_ubyte * 8)]


VT_EMPTY = 0
VT_LPWSTR = 31

IID_IClassFactory = GUID("{00000001-0000-0000-C000-000000000046}")
IID_IPropertyStore = GUID("{886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99}")
IID_IInitializeWithItem = GUID("{7F73BE3F-FB79-493C-A6C7-7EE14E245841}")
CLSID_HANDLER = GUID("{B4C8E6D1-7A2F-4c3b-9D5E-1F6C2A8B3D41}")
# The remark is published as the built-in System.Comment, which Windows
# already labels "备注" (fmtid {F29F85E0-4FF9-1068-AB91-08002B27B3D9}, pid 6).
PKEY_REMARK = PROPERTYKEY(GUID("{F29F85E0-4FF9-1068-AB91-08002B27B3D9}"), 6)


def vcall(obj, index, restype, *argtypes):
    vtbl = ctypes.cast(obj, POINTER(c_void_p))[0]
    fn = ctypes.cast(vtbl, POINTER(c_void_p))[index]
    proto = ctypes.CFUNCTYPE(restype, c_void_p, *argtypes)
    return proto(fn)


def qi(obj, iid):
    fn = vcall(obj, 0, HRESULT, POINTER(GUID), POINTER(c_void_p))
    out = c_void_p()
    hr = fn(obj, byref(iid), byref(out))
    return hr, out


def release(obj):
    fn = vcall(obj, 2, ULONG)
    return fn(obj)


def main():
    import os, tempfile
    # SHCreateItemFromParsingName and the handler need an initialized COM apartment.
    hr_init = ole32.CoInitializeEx(None, 0x2)  # COINIT_APARTMENTTHREADED
    print("CoInitializeEx hr=0x%08X" % (hr_init & 0xFFFFFFFF))
    dll = os.path.abspath("build/FileRemarksPropHandler.dll")
    lib = ctypes.WinDLL(dll)
    lib.DllGetClassObject.argtypes = [POINTER(GUID), POINTER(GUID), POINTER(c_void_p)]
    lib.DllGetClassObject.restype = HRESULT

    cf = c_void_p()
    hr = lib.DllGetClassObject(byref(CLSID_HANDLER), byref(IID_IClassFactory), byref(cf))
    print("DllGetClassObject(IClassFactory) hr=0x%08X" % (hr & 0xFFFFFFFF))
    assert hr == 0, "DllGetClassObject failed"

    # IClassFactory::CreateInstance
    create = vcall(cf, 3, HRESULT, c_void_p, POINTER(GUID), POINTER(c_void_p))
    obj = c_void_p()
    hr = create(cf, None, byref(IID_IInitializeWithItem), byref(obj))
    print("CreateInstance(IInitializeWithItem) hr=0x%08X ptr=%s" % (hr & 0xFFFFFFFF, obj))
    assert hr == 0 and obj, "CreateInstance failed"

    # SHCreateItemFromParsingName -> IShellItem
    path = os.path.abspath(os.path.join(tempfile.gettempdir(), "fr_comtest.txt"))
    with open(path, "w", encoding="utf-8") as f:
        f.write("hello")
    shell32.SHCreateItemFromParsingName.argtypes = [wintypes.LPCWSTR, c_void_p,
                                                    POINTER(GUID), POINTER(c_void_p)]
    shell32.SHCreateItemFromParsingName.restype = HRESULT
    psi = c_void_p()
    hr = shell32.SHCreateItemFromParsingName(path, None, byref(IID_IShellItem), byref(psi))
    print("SHCreateItemFromParsingName hr=0x%08X" % (hr & 0xFFFFFFFF))
    assert hr == 0, "SHCreateItemFromParsingName failed"

    # IInitializeWithItem::Initialize(IShellItem*, DWORD)
    init = vcall(obj, 3, HRESULT, c_void_p, DWORD)
    hr = init(obj, psi, 0)
    print("Initialize hr=0x%08X" % (hr & 0xFFFFFFFF))
    assert hr == 0

    # QI for IPropertyStore
    hr, ps = qi(obj, IID_IPropertyStore)
    print("QI(IPropertyStore) hr=0x%08X" % (hr & 0xFFFFFFFF))
    assert hr == 0

    # GetCount / GetAt must enumerate exactly our key.
    getcount = vcall(ps, 3, HRESULT, POINTER(DWORD))
    cnt = DWORD()
    hr = getcount(ps, byref(cnt))
    print("GetCount hr=0x%08X count=%d" % (hr & 0xFFFFFFFF, cnt.value))
    getat = vcall(ps, 4, HRESULT, DWORD, POINTER(PROPERTYKEY))
    k = PROPERTYKEY()
    hr = getat(ps, 0, byref(k))
    print("GetAt(0) hr=0x%08X pid=%d" % (hr & 0xFFFFFFFF, k.pid))
    assert cnt.value == 1 and k.pid == 6, "GetCount/GetAt mismatch"

    # SetValue(VT_LPWSTR "测试备注")
    text = "测试备注 Chinese remark!"
    pv = PROPVARIANT()
    pv.vt = VT_LPWSTR
    pv.ptr = ctypes.cast(ctypes.c_wchar_p(text), c_void_p)
    setv = vcall(ps, 6, HRESULT, POINTER(PROPERTYKEY), POINTER(PROPVARIANT))
    hr = setv(ps, byref(PKEY_REMARK), byref(pv))
    print("SetValue hr=0x%08X" % (hr & 0xFFFFFFFF))
    assert hr == 0

    commit = vcall(ps, 7, HRESULT)
    hr = commit(ps)
    print("Commit hr=0x%08X" % (hr & 0xFFFFFFFF))
    assert hr == 0

    ads = path + ":remark"
    data = open(ads, "rb").read().decode("utf-8")
    print("ADS after SetValue:", repr(data))
    assert data == text, "ADS content mismatch"

    # GetValue
    pv2 = PROPVARIANT()
    getv = vcall(ps, 5, HRESULT, POINTER(PROPERTYKEY), POINTER(PROPVARIANT))
    hr = getv(ps, byref(PKEY_REMARK), byref(pv2))
    got = ctypes.cast(pv2.ptr, ctypes.c_wchar_p).value if pv2.vt == VT_LPWSTR else None
    print("GetValue hr=0x%08X vt=%d value=%r" % (hr & 0xFFFFFFFF, pv2.vt, got))
    assert got == text

    # Clear
    pv3 = PROPVARIANT()
    pv3.vt = VT_EMPTY
    hr = setv(ps, byref(PKEY_REMARK), byref(pv3))
    print("SetValue(EMPTY) hr=0x%08X" % (hr & 0xFFFFFFFF))
    hr = commit(ps)
    print("Commit(clear) hr=0x%08X" % (hr & 0xFFFFFFFF))
    exists = os.path.exists(ads)
    print("ADS exists after clear:", exists)
    if exists:
        try:
            print("  leftover:", repr(open(ads, "rb").read()))
        except OSError as exc:
            print("  leftover unreadable:", exc)
    assert not exists, "ADS should be deleted"

    release(ps)
    release(obj)
    release(cf)
    os.remove(path)
    print("\nALL PROPERTY-HANDLER TESTS PASSED")


import ctypes.wintypes as wt
IID_IShellItem = GUID("{43826D1E-E718-42EE-BC55-A1E261C37BFE}")

if __name__ == "__main__":
    main()
