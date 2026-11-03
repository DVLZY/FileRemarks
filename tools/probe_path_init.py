# -*- coding: utf-8 -*-
"""Which initialisation does the property handler accept?

A property handler can be handed an IShellItem, a path, or a stream. Which one
Windows uses decides whether the 备注 column can work at all, and it changed
between builds:

  * v1.13 - v1.15 implemented IInitializeWithStream. The shell then drove the
    handler with a *stream*, whose STATSTG name is a bare file name, so the
    alternate data stream holding the remark was looked up under the wrong path
    and the column came up empty.
  * v1.16 and later implement only IInitializeWithItem / IInitializeWithFile, so
    the shell has to hand over a real path -- which is what the remark needs.

This probe loads the DLL straight from dist/ (no registration is touched) and
asserts both halves of that statement:

  1. IInitializeWithStream is NOT offered (E_NOINTERFACE), so a host cannot pick
     the pathless route;
  2. IInitializeWithFile IS offered, and after Initialize(full path) the store
     returns the remark through System.Comment.

Pass a DLL path as argv[1] to check another build instead (it will fail on
v1.13 - v1.15, which is the point).
"""
import ctypes
import os
import sys
import uuid
from ctypes import POINTER, Structure, byref, c_uint32, c_void_p, c_wchar_p

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DLL_PATH = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    ROOT, "dist", "FileRemarksPropHandler.dll")

WORK = os.path.join(ROOT, "build", "_path_probe")
TARGET_NAME = "带备注的文件.txt"
REMARK = "这条备注必须能从属性处理器里读出来"

CLSID_HANDLER = "{B4C8E6D1-7A2F-4c3b-9D5E-1F6C2A8B3D41}"
IID_ICLASSFACTORY = "{00000001-0000-0000-C000-000000000046}"
IID_IINITWITHFILE = "{B7D14566-0509-4CCE-A71F-0A554233BD9B}"
IID_IINITWITHSTREAM = "{B824B49D-22AC-4161-AC8A-9916E8FA3F7F}"
IID_IPROPERTYSTORE = "{886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99}"
PKEY_COMMENT = "{F29F85E0-4FF9-1068-AB91-08002B27B3D9}"
PID_COMMENT = 6

S_OK = 0
E_NOINTERFACE = 0x80004002

FAILS = []


class GUID(Structure):
    _fields_ = [("Data1", c_uint32), ("Data2", ctypes.c_uint16),
                ("Data3", ctypes.c_uint16), ("Data4", ctypes.c_ubyte * 8)]


def guid(s):
    return GUID.from_buffer_copy(uuid.UUID(s).bytes_le)


class PROPERTYKEY(Structure):
    _fields_ = [("fmtid", GUID), ("pid", ctypes.c_ulong)]


class PROPVARIANT(Structure):
    # PROPVARIANT is a VARTYPE (2 bytes) plus three reserved WORDs, and then a
    # union at offset 8. An extra c_void_p in the header shifts that union and
    # every value read out of it comes back empty.
    _fields_ = [("vt", ctypes.c_ushort), ("r1", ctypes.c_ushort),
                ("r2", ctypes.c_ushort), ("r3", ctypes.c_ushort),
                ("p", ctypes.c_void_p)]


def hx(v):
    return "0x%08X" % (v & 0xFFFFFFFF)


def check(ok, what, detail=""):
    print(("  PASS " if ok else "  FAIL ") + what + ("  [%s]" % detail if detail else ""))
    if not ok:
        FAILS.append(what)
    return ok


class Vtbl:
    """Reads function pointers out of a COM object's vtable."""

    def __init__(self, obj, index):
        self.obj = obj
        self.addr = ctypes.cast(ctypes.cast(obj, POINTER(c_void_p))[0],
                                POINTER(c_void_p))[index]


def main():
    os.makedirs(WORK, exist_ok=True)
    target = os.path.join(WORK, TARGET_NAME)
    with open(target, "wb") as f:
        f.write(b"x")
    with open(target + ":remark", "wb") as f:
        f.write(REMARK.encode("utf-8"))

    ole32 = ctypes.WinDLL("ole32")
    k32 = ctypes.WinDLL("kernel32")
    ole32.CoInitializeEx(None, 2)

    k32.LoadLibraryW.restype = c_void_p
    k32.LoadLibraryW.argtypes = [c_wchar_p]
    lib = k32.LoadLibraryW(DLL_PATH)
    if not check(bool(lib), "the DLL loads", DLL_PATH):
        return 1

    k32.GetProcAddress.restype = c_void_p
    k32.GetProcAddress.argtypes = [c_void_p, ctypes.c_char_p]
    addr = k32.GetProcAddress(c_void_p(lib), b"DllGetClassObject")
    if not check(bool(addr), "DllGetClassObject is exported"):
        return 1
    get_class = ctypes.WINFUNCTYPE(ctypes.c_long, POINTER(GUID), POINTER(GUID),
                                   c_void_p)(addr)
    factory = c_void_p()
    hr = get_class(byref(guid(CLSID_HANDLER)), byref(guid(IID_ICLASSFACTORY)),
                   byref(factory))
    if not check(hr == S_OK, "the class factory is created", hx(hr)):
        return 1
    create_addr = ctypes.cast(ctypes.cast(factory, POINTER(c_void_p))[0],
                              POINTER(c_void_p))[3]
    create = ctypes.WINFUNCTYPE(ctypes.c_long, c_void_p, c_void_p, POINTER(GUID),
                                c_void_p)(create_addr)

    # --- 1) the pathless route must NOT exist -------------------------------
    probe = c_void_p()
    hr = create(factory, None, byref(guid(IID_IINITWITHSTREAM)), byref(probe))
    # hr comes back as a signed c_long, so mask before comparing with an
    # 0x8000xxxx code; without the mask this check fails on a correct DLL.
    check((hr & 0xFFFFFFFF) == E_NOINTERFACE,
          "IInitializeWithStream is refused, so the shell must pass a path", hx(hr))
    if hr == S_OK and probe:
        Vtbl(probe, 2) and None  # keep the pointer alive; nothing to release here

    # --- 2) the path route must work ---------------------------------------
    obj = c_void_p()
    hr = create(factory, None, byref(guid(IID_IINITWITHFILE)), byref(obj))
    if not check(hr == S_OK, "IInitializeWithFile is offered", hx(hr)):
        return 1

    init_addr = ctypes.cast(ctypes.cast(obj, POINTER(c_void_p))[0],
                            POINTER(c_void_p))[3]
    init = ctypes.WINFUNCTYPE(ctypes.c_long, c_void_p, c_wchar_p, c_uint32)(init_addr)
    hr = init(obj, ctypes.c_wchar_p(target), 0)
    check(hr == S_OK, "Initialize(full path) succeeds", hx(hr))

    qi_addr = ctypes.cast(ctypes.cast(obj, POINTER(c_void_p))[0],
                          POINTER(c_void_p))[0]
    qi = ctypes.WINFUNCTYPE(ctypes.c_long, c_void_p, POINTER(GUID), c_void_p)(qi_addr)
    store = c_void_p()
    hr = qi(obj, byref(guid(IID_IPROPERTYSTORE)), byref(store))
    if not check(hr == S_OK, "the initialised handler offers IPropertyStore", hx(hr)):
        return 1

    count = c_uint32(0)
    get_count = ctypes.WINFUNCTYPE(ctypes.c_long, c_void_p,
                                   POINTER(c_uint32))(Vtbl(store, 3).addr)
    hr = get_count(store, byref(count))
    check(hr == S_OK and count.value >= 1, "the store has at least one key",
          "count=%d" % count.value)

    pv = PROPVARIANT()
    pkey = PROPERTYKEY(guid(PKEY_COMMENT), PID_COMMENT)
    get_value = ctypes.WINFUNCTYPE(ctypes.c_long, c_void_p, POINTER(PROPERTYKEY),
                                   POINTER(PROPVARIANT))(Vtbl(store, 5).addr)
    hr = get_value(store, byref(pkey), byref(pv))
    value = None
    if hr == S_OK and pv.vt == 31 and pv.p:          # VT_LPWSTR
        value = ctypes.wstring_at(pv.p)
    check(hr == S_OK and value == REMARK,
          "the remark comes back through System.Comment", repr(value))

    if pv.vt and pv.p:
        ole32.PropVariantClear.argtypes = [POINTER(PROPVARIANT)]
        ole32.PropVariantClear(byref(pv))

    print()
    if FAILS:
        print("PATH-INIT CHECKS FAILED  (%d)" % len(FAILS))
        return 1
    print("ALL PATH-INIT CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
