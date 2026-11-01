"""Check whether we can instantiate Windows' own property handler for a type
and read its properties, so our handler can forward (chain) them instead of
replacing them.

No registry writes are needed: the CLSIDs come from a read-only registry scan.
"""
import ctypes
import os
import sys
import winreg
from ctypes import wintypes

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PH = r"SOFTWARE\Microsoft\Windows\CurrentVersion\PropertySystem\PropertyHandlers"
BUILD = os.path.join(ROOT, "build", "_chain_test")


class GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_uint32), ("Data2", ctypes.c_uint16),
                ("Data3", ctypes.c_uint16), ("Data4", ctypes.c_ubyte * 8)]


class PROPERTYKEY(ctypes.Structure):
    _fields_ = [("fmtid", GUID), ("pid", ctypes.c_uint32)]


class PROPVARIANT(ctypes.Structure):
    _fields_ = [("vt", ctypes.c_uint16), ("r1", ctypes.c_uint16),
                ("r2", ctypes.c_uint16), ("r3", ctypes.c_uint16),
                ("ptr", ctypes.c_void_p), ("pad2", ctypes.c_ubyte * 8)]


def guid(s):
    p = s.strip("{}").split("-")
    g = GUID()
    g.Data1 = int(p[0], 16)
    g.Data2 = int(p[1], 16)
    g.Data3 = int(p[2], 16)
    b = bytes.fromhex(p[3] + p[4])
    for i, v in enumerate(b):
        g.Data4[i] = v
    return g


def fmt_guid(g):
    return "{%08X-%04X-%04X-%02X%02X-%02X%02X%02X%02X%02X%02X}" % (
        g.Data1, g.Data2, g.Data3,
        g.Data4[0], g.Data4[1], g.Data4[2], g.Data4[3],
        g.Data4[4], g.Data4[5], g.Data4[6], g.Data4[7])


IID_IUnknown = guid("{00000000-0000-0000-C000-000000000046}")
IID_IPropertyStore = guid("{886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99}")
IID_IInitializeWithItem = guid("{7F73BE3F-FB79-493C-A6C7-7EE14E245841}")
IID_IInitializeWithStream = guid("{B824B49D-22AC-4161-AC8A-9916E8FA3F7F}")
IID_IInitializeWithFile = guid("{B7D14566-0509-4CCE-A71F-0A554233BD9B}")
IID_IShellItem = guid("{43826D1E-E718-42EE-BC55-A1E261C37BFE}")

ole32 = ctypes.WinDLL("ole32")
shell32 = ctypes.WinDLL("shell32")
shlwapi = ctypes.WinDLL("shlwapi")
propsys = ctypes.WinDLL("propsys")
kernel32 = ctypes.WinDLL("kernel32")

ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
ole32.CoInitializeEx.restype = ctypes.c_long
ole32.CoCreateInstance.argtypes = [ctypes.POINTER(GUID), ctypes.c_void_p, ctypes.c_uint32,
                                   ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)]
ole32.CoCreateInstance.restype = ctypes.c_long
shell32.SHCreateItemFromParsingName.argtypes = [ctypes.c_wchar_p, ctypes.c_void_p,
                                                ctypes.POINTER(GUID),
                                                ctypes.POINTER(ctypes.c_void_p)]
shell32.SHCreateItemFromParsingName.restype = ctypes.c_long
shlwapi.SHCreateStreamOnFileEx.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32,
                                           wintypes.BOOL, ctypes.c_void_p,
                                           ctypes.POINTER(ctypes.c_void_p)]
shlwapi.SHCreateStreamOnFileEx.restype = ctypes.c_long
ole32.PropVariantClear.argtypes = [ctypes.POINTER(PROPVARIANT)]
ole32.PropVariantClear.restype = ctypes.c_long


def vcall(obj, index, restype, *argtypes):
    vtbl = ctypes.cast(obj, ctypes.POINTER(ctypes.c_void_p))[0]
    fn = ctypes.cast(vtbl, ctypes.POINTER(ctypes.c_void_p))[index]
    proto = ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)
    return proto(fn)


def release(obj):
    vcall(obj, 2, ctypes.c_ulong)(obj)


def qi(obj, iid):
    out = ctypes.c_void_p()
    hr = vcall(obj, 0, ctypes.c_long, ctypes.POINTER(GUID),
               ctypes.POINTER(ctypes.c_void_p))(obj, ctypes.byref(iid), ctypes.byref(out))
    return hr, out


def read_str(pv):
    if pv.vt == 31 and pv.ptr:
        return ctypes.wstring_at(pv.ptr)
    return "<vt=%d>" % pv.vt


def handler_clsid(ext):
    for sub, name in ((PH + "\\" + ext, None),
                      (r"SOFTWARE\Classes" + "\\" + ext + r"\ShellEx\PropertyHandler", None)):
        try:
            h = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, sub, 0, winreg.KEY_READ)
        except OSError:
            continue
        try:
            v, t = winreg.QueryValueEx(h, name if name else "")
            winreg.CloseKey(h)
            return v
        except OSError:
            winreg.CloseKey(h)
    return None


def make_file(ext):
    os.makedirs(BUILD, exist_ok=True)
    dst = os.path.join(BUILD, "chain" + ext)
    if os.path.exists(dst):
        return dst
    if ext in (".png", ".jpg", ".jpeg"):
        for cand in (os.path.join(os.environ.get("SystemRoot", r"C:\Windows"),
                                  "Web", "4K", "Wallpaper", "Windows", "img0_1920x1200.jpg"),
                     os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "Web",
                                  "Screen", "img100.jpg")):
            if os.path.exists(cand):
                if ext in (".png",):
                    continue
                with open(cand, "rb") as f:
                    data = f.read()
                with open(dst, "wb") as f:
                    f.write(data)
                return dst
        for base in (os.environ.get("USERPROFILE", ""), os.environ.get("PUBLIC", "")):
            for dirpath, _dirs, files in os.walk(os.path.join(base, "Pictures")):
                for fn in files:
                    if fn.lower().endswith(ext):
                        with open(os.path.join(dirpath, fn), "rb") as f:
                            data = f.read()
                        with open(dst, "wb") as f:
                            f.write(data)
                        return dst
        return None
    if ext == ".exe":
        src = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "notepad.exe")
        with open(src, "rb") as f:
            data = f.read()
        with open(dst, "wb") as f:
            f.write(data)
        return dst
    if ext in (".txt", ".md", ".py", ".json"):
        with open(dst, "wb") as f:
            f.write(b"chain probe\n")
        return dst
    return None


def main():
    hr = ole32.CoInitializeEx(None, 0x2)
    print("CoInitializeEx -> 0x%08X" % (hr & 0xFFFFFFFF))

    exts = [".png", ".jpg", ".exe", ".docx", ".txt", ".md"]
    scanned = set()
    for d in (os.environ.get("USERPROFILE", ""), os.environ.get("PUBLIC", "")):
        p = os.path.join(d, "Documents")
        if os.path.isdir(p):
            for dirpath, _dirs, files in os.walk(p):
                for fn in files:
                    if fn.lower().endswith(".docx"):
                        scanned.add(os.path.join(dirpath, fn))
                        break
                if scanned:
                    break

    for ext in exts:
        print("\n=== %s" % ext)
        clsid = handler_clsid(ext)
        print("  system handler clsid:", clsid)
        if ext == ".docx":
            if not scanned:
                print("  no .docx sample; skipped")
                continue
            path = sorted(scanned)[0]
            dst = os.path.join(BUILD, "chain.docx")
            os.makedirs(BUILD, exist_ok=True)
            if not os.path.exists(dst):
                with open(path, "rb") as f:
                    data = f.read()
                with open(dst, "wb") as f:
                    f.write(data)
            path = dst
        else:
            path = make_file(ext)
        if not path:
            print("  no sample file; skipped")
            continue
        print("  sample:", os.path.basename(path))
        if not clsid:
            print("  -> no system handler, nothing to chain")
            continue

        # 1) IShellItem once; reused for the handler under test.
        psi = ctypes.c_void_p()
        hr = shell32.SHCreateItemFromParsingName(path, None, ctypes.byref(IID_IShellItem),
                                                 ctypes.byref(psi))
        print("  SHCreateItemFromParsingName hr=0x%08X" % (hr & 0xFFFFFFFF))
        if hr < 0:
            continue

        # 2) CoCreateInstance the system handler.
        punk = ctypes.c_void_p()
        hr = ole32.CoCreateInstance(ctypes.byref(guid(clsid)), None, 1,
                                    ctypes.byref(IID_IUnknown), ctypes.byref(punk))
        print("  CoCreateInstance hr=0x%08X" % (hr & 0xFFFFFFFF))
        if hr < 0:
            release(psi)
            continue

        # 3) Which init interfaces does it support?
        for name, iid in (("IInitializeWithItem", IID_IInitializeWithItem),
                          ("IInitializeWithStream", IID_IInitializeWithStream),
                          ("IInitializeWithFile", IID_IInitializeWithFile)):
            h, out = qi(punk, iid)
            print("    QI(%-22s) hr=0x%08X" % (name, h & 0xFFFFFFFF))
            if h >= 0:
                release(out)

        # 4) Initialize with whichever interface the handler supports, then
        #    read its properties. This proves (or disproves) chaining.
        h_item, init_item = qi(punk, IID_IInitializeWithItem)
        h_stream, init_stream = qi(punk, IID_IInitializeWithStream)
        h_file, init_file = qi(punk, IID_IInitializeWithFile)
        hr = -1
        if h_item >= 0:
            hr = vcall(init_item, 3, ctypes.c_long, ctypes.c_void_p,
                       ctypes.c_uint32)(init_item, psi, 0)
            print("  Initialize(item) hr=0x%08X" % (hr & 0xFFFFFFFF))
        elif h_stream >= 0:
            stream = ctypes.c_void_p()
            hr_ss = shlwapi.SHCreateStreamOnFileEx(path, 0x80000000, 1, False,
                                                   None, ctypes.byref(stream))
            print("  SHCreateStreamOnFileEx hr=0x%08X" % (hr_ss & 0xFFFFFFFF))
            if hr_ss >= 0:
                hr = vcall(init_stream, 3, ctypes.c_long, ctypes.c_void_p,
                           ctypes.c_uint32)(init_stream, stream, 0)
                print("  Initialize(stream) hr=0x%08X" % (hr & 0xFFFFFFFF))
                release(stream)
        elif h_file >= 0:
            hr = vcall(init_file, 3, ctypes.c_long, ctypes.c_wchar_p,
                       ctypes.c_uint32)(init_file, path, 0)
            print("  Initialize(file) hr=0x%08X" % (hr & 0xFFFFFFFF))
        for h, o in ((h_item, init_item), (h_stream, init_stream),
                     (h_file, init_file)):
            if h >= 0:
                release(o)
        if hr < 0:
            print("  initialization failed; cannot read")
            release(punk)
            release(psi)
            continue
        h, ps = qi(punk, IID_IPropertyStore)
        print("  QI(IPropertyStore) hr=0x%08X" % (h & 0xFFFFFFFF))
        if h >= 0:
            cnt = ctypes.c_uint32(0)
            hr = vcall(ps, 3, ctypes.c_long, ctypes.POINTER(ctypes.c_uint32))(ps, ctypes.byref(cnt))
            print("  GetCount hr=0x%08X count=%d" % (hr & 0xFFFFFFFF, cnt.value))
            if cnt.value:
                pk = PROPERTYKEY()
                hr = vcall(ps, 4, ctypes.c_long, ctypes.c_uint32,
                           ctypes.POINTER(PROPERTYKEY))(ps, 0, ctypes.byref(pk))
                pv = PROPVARIANT()
                hr2 = vcall(ps, 5, ctypes.c_long, ctypes.POINTER(PROPERTYKEY),
                            ctypes.POINTER(PROPVARIANT))(ps, ctypes.byref(pk), ctypes.byref(pv))
                print("  GetAt(0) pid=%d GetValue hr=0x%08X val=%s"
                      % (pk.pid, hr2 & 0xFFFFFFFF, read_str(pv)))
                ole32.PropVariantClear(ctypes.byref(pv))
            release(ps)
        pass
        release(punk)
        release(psi)

    print("\nCHAIN PROBE DONE")


if __name__ == "__main__":
    main()
