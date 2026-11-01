# -*- coding: utf-8 -*-
"""Probe: can we instantiate a *system* property handler in-process and drive it
with IInitializeWithItem (or WithFile / WithStream)? If yes, our handler can
chain to the native handler (forward all other property keys) instead of
destroying the columns Windows already provides for that type.

Reads HKLM\\...\\PropertySystem\\PropertyHandlers\\.ext (read-only) to discover
the CLSID Windows uses for a given extension, then tries to create it and
initialize it for a real file of that type.
"""
import ctypes, os, sys, glob
from ctypes import wintypes, POINTER

ole32 = ctypes.WinDLL("ole32")
shell32 = ctypes.WinDLL("shell32")
import winreg

COINIT_APARTMENTTHREADED = 0x2
CLSCTX_INPROC_SERVER = 0x1

PROPERTY_HANDLERS_KEY = r"SOFTWARE\Microsoft\Windows\CurrentVersion\PropertySystem\PropertyHandlers"


class GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_uint32), ("Data2", ctypes.c_uint16),
                ("Data3", ctypes.c_uint16), ("Data4", ctypes.c_ubyte * 8)]

    def __str__(self):
        d4 = "".join("%02X" % b for b in self.Data4)
        return "{%08X-%04X-%04X-%s-%s}" % (self.Data1, self.Data2, self.Data3, d4[:4], d4[4:])


def guid(s):
    p = s.strip("{}").split("-")
    g = GUID()
    g.Data1 = int(p[0], 16); g.Data2 = int(p[1], 16); g.Data3 = int(p[2], 16)
    tail = bytes.fromhex(p[3] + p[4])
    for i in range(8):
        g.Data4[i] = tail[i]
    return g


class PROPERTYKEY(ctypes.Structure):
    _fields_ = [("fmtid", GUID), ("pid", ctypes.c_uint32)]


IID_IUnknown = guid("{00000000-0000-0000-C000-000000000046}")
IID_IPropertyStore = guid("{886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99}")
IID_IInitializeWithItem = guid("{7F73BE3F-FB79-493C-A6C7-7EE14E245841}")
IID_IInitializeWithFile = guid("{B7D14566-0509-4CCE-A71F-0A554233BD9B}")
IID_IInitializeWithStream = guid("{B824B49D-22AC-4161-AC8A-9916E8FA3F7F}")
IID_IShellItem = guid("{43826D1E-E718-42EE-BC55-A1E261C37BFE}")

ole32.CoInitializeEx.restype = ctypes.c_long
ole32.CoCreateInstance.restype = ctypes.c_long
ole32.CoCreateInstance.argtypes = [ctypes.POINTER(GUID), ctypes.c_void_p, ctypes.c_uint32,
                                   ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)]
shell32.SHCreateItemFromParsingName.restype = ctypes.c_long
shell32.SHCreateItemFromParsingName.argtypes = [ctypes.c_wchar_p, ctypes.c_void_p,
                                               ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)]


def vcall(obj, index, restype, *argtypes):
    vtbl = ctypes.cast(obj, POINTER(POINTER(ctypes.c_void_p)))[0]
    fn = ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)(vtbl[index])
    return fn


def qi(obj, iid):
    out = ctypes.c_void_p()
    hr = vcall(obj, 0, ctypes.c_long, POINTER(GUID), POINTER(ctypes.c_void_p))(
        obj, ctypes.byref(iid), ctypes.byref(out)) & 0xFFFFFFFF
    return hr, out


def release(obj):
    if obj:
        vcall(obj, 2, ctypes.c_ulong)(obj)


def handler_clsid_for_ext(ext):
    try:
        k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, PROPERTY_HANDLERS_KEY, 0, winreg.KEY_READ)
    except OSError as e:
        return None, "cannot open PropertyHandlers: %s" % e
    try:
        try:
            val, _ = winreg.QueryValueEx(k, ext)
        except OSError:
            return None, "no PropertyHandlers entry"
        return val, None
    finally:
        winreg.CloseKey(k)


def shell_item(path):
    si = ctypes.c_void_p()
    hr = shell32.SHCreateItemFromParsingName(path, None, ctypes.byref(IID_IShellItem),
                                             ctypes.byref(si)) & 0xFFFFFFFF
    return hr, si


def probe(path):
    ext = os.path.splitext(path)[1].lower()
    print("\n=== %s  (ext %s)" % (path, ext))
    clsid_str, err = handler_clsid_for_ext(ext)
    print("  HKLM PropertyHandlers[%s] = %s %s" % (ext, clsid_str, ("(%s)" % err) if err else ""))
    if not clsid_str:
        print("  -> no system handler for this type; nothing to chain to")
        return

    clsid = guid(clsid_str)
    pv = ctypes.c_void_p()
    hr = ole32.CoCreateInstance(ctypes.byref(clsid), None, CLSCTX_INPROC_SERVER,
                                ctypes.byref(IID_IUnknown), ctypes.byref(pv)) & 0xFFFFFFFF
    print("  CoCreateInstance -> 0x%08X" % hr)
    if hr != 0 or not pv:
        return

    for name, iid in (("IPropertyStore", IID_IPropertyStore),
                      ("IInitializeWithItem", IID_IInitializeWithItem),
                      ("IInitializeWithFile", IID_IInitializeWithFile),
                      ("IInitializeWithStream", IID_IInitializeWithStream)):
        h, o = qi(pv, iid)
        print("  QI %-22s -> 0x%08X" % (name, h))
        release(o)

    h, item = shell_item(path)
    print("  SHCreateItemFromParsingName -> 0x%08X" % h)
    if h == 0 and item:
        h_init, init = qi(pv, IID_IInitializeWithItem)
        if h_init == 0 and init:
            hr2 = vcall(init, 3, ctypes.c_long, ctypes.c_void_p, ctypes.c_uint32)(
                init, item, 0) & 0xFFFFFFFF
            print("  IInitializeWithItem::Initialize -> 0x%08X" % hr2)
            h_ps, ps = qi(pv, IID_IPropertyStore)
            if h_ps == 0 and ps:
                n = ctypes.c_uint32()
                hr3 = vcall(ps, 3, ctypes.c_long, POINTER(ctypes.c_uint32))(ps, ctypes.byref(n)) & 0xFFFFFFFF
                print("  chained GetCount -> 0x%08X  count=%d" % (hr3, n.value))
                release(ps)
            release(init)
        release(item)
    release(pv)


def main():
    print("CoInitializeEx -> 0x%08X" % (ole32.CoInitializeEx(None, COINIT_APARTMENTTHREADED) & 0xFFFFFFFF))
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    candidates = []
    for pat, dirs in (
        ("*.png", [r"C:\Windows\System32", r"C:\Windows\Web"]),
        ("*.jpg", [os.path.join(os.environ.get("USERPROFILE", ""), "Pictures"), r"C:\Windows\Web"]),
        ("*.docx", [os.path.join(os.environ.get("USERPROFILE", ""), "Documents"), root]),
        ("*.exe", [r"C:\Windows\System32"]),
        ("*.mp4", [os.path.join(os.environ.get("USERPROFILE", ""), "Videos")]),
    ):
        for d in dirs:
            if not d or not os.path.isdir(d):
                continue
            hit = glob.glob(os.path.join(d, "**", pat), recursive=True)
            if hit:
                candidates.append(hit[0])
                break
    for c in candidates:
        probe(c)
    ole32.CoUninitialize()
    return 0


if __name__ == "__main__":
    sys.exit(main())
