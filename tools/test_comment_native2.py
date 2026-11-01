# -*- coding: utf-8 -*-
"""Probe 2: can we set System.Comment (PKEY_Comment) on REAL files of various
types through the native property system, with no custom handler installed?

If yes for a type, Explorer's built-in 备注 column can hold the remark natively
for that type and we need no custom property handler there.
"""
import ctypes, os, shutil, sys, glob
from ctypes import wintypes, POINTER

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "build", "_comment_probe2")
os.makedirs(OUT, exist_ok=True)

ole32 = ctypes.WinDLL("ole32")
shell32 = ctypes.WinDLL("shell32")

COINIT_APARTMENTTHREADED = 0x2


class GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_uint32), ("Data2", ctypes.c_uint16),
                ("Data3", ctypes.c_uint16), ("Data4", ctypes.c_ubyte * 8)]

    def __str__(self):
        d4 = "".join("%02X" % b for b in self.Data4)
        return "{%08X-%04X-%04X-%s-%s}" % (self.Data1, self.Data2, self.Data3,
                                           d4[:4], d4[4:])


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


class PROPVARIANT(ctypes.Structure):
    _fields_ = [("vt", ctypes.c_uint16), ("r1", ctypes.c_uint16),
                ("r2", ctypes.c_uint16), ("r3", ctypes.c_uint16),
                ("ptr", ctypes.c_void_p), ("pad2", ctypes.c_ubyte * 8)]


VT_EMPTY, VT_LPWSTR = 0, 31
IID_IPropertyStore = guid("{886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99}")
FMTID_SUMMARY = guid("{F29F85E0-4FF9-1068-AB91-08002B27B3D9}")
PKEY_COMMENT = PROPERTYKEY(FMTID_SUMMARY, 6)

SHGetPropertyStoreFromParsingName = shell32.SHGetPropertyStoreFromParsingName
SHGetPropertyStoreFromParsingName.argtypes = [
    ctypes.c_wchar_p, ctypes.c_void_p, ctypes.c_uint32,
    ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)]
SHGetPropertyStoreFromParsingName.restype = ctypes.c_long
ole32.PropVariantClear.argtypes = [ctypes.POINTER(PROPVARIANT)]

GPS_DEFAULT, GPS_HANDLERPROPERTIESONLY, GPS_READWRITE = 0x0, 0x1, 0x2


def vcall(obj, index, restype, *argtypes):
    vtbl = ctypes.cast(obj, POINTER(POINTER(ctypes.c_void_p)))[0]
    fn = ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)(vtbl[index])
    return fn


def open_store(path, flags):
    ps = ctypes.c_void_p()
    hr = SHGetPropertyStoreFromParsingName(path, None, flags,
                                           ctypes.byref(IID_IPropertyStore),
                                           ctypes.byref(ps))
    return hr & 0xFFFFFFFF, ps


def get_count(ps):
    n = ctypes.c_uint32()
    hr = vcall(ps, 3, ctypes.c_long, POINTER(ctypes.c_uint32))(ps, ctypes.byref(n)) & 0xFFFFFFFF
    return hr, n.value


def get_value(ps, key):
    pv = PROPVARIANT()
    hr = vcall(ps, 5, ctypes.c_long, POINTER(PROPERTYKEY), POINTER(PROPVARIANT))(
        ps, ctypes.byref(key), ctypes.byref(pv)) & 0xFFFFFFFF
    val = None
    if hr == 0 and pv.vt == VT_LPWSTR and pv.ptr:
        val = ctypes.wstring_at(pv.ptr)
    if pv.vt != VT_EMPTY:
        ole32.PropVariantClear(ctypes.byref(pv))
    return hr, pv.vt, val


def set_value(ps, key, text):
    pv = PROPVARIANT()
    pv.vt = VT_LPWSTR
    buf = ctypes.create_unicode_buffer(text)
    pv.ptr = ctypes.cast(buf, ctypes.c_void_p)
    hr = vcall(ps, 6, ctypes.c_long, POINTER(PROPERTYKEY), POINTER(PROPVARIANT))(
        ps, ctypes.byref(key), ctypes.byref(pv)) & 0xFFFFFFFF
    return hr


def commit(ps):
    return vcall(ps, 7, ctypes.c_long)(ps) & 0xFFFFFFFF


def release(ps):
    if ps:
        vcall(ps, 2, ctypes.c_ulong)(ps)


def find_real(pattern, searchdirs):
    for d in searchdirs:
        if not d or not os.path.isdir(d):
            continue
        hits = glob.glob(os.path.join(d, pattern), recursive=True)
        if hits:
            return hits[0]
    return None


def main():
    print("CoInitializeEx hr=0x%08X" % (ole32.CoInitializeEx(None, COINIT_APARTMENTTHREADED) & 0xFFFFFFFF))

    sources = {
        "jpg": find_real("**/*.jpg", [os.path.join(os.environ.get("USERPROFILE", ""), "Pictures"),
                                     os.path.join(os.environ.get("PUBLIC", ""), "Pictures"),
                                     r"C:\Windows\Web"]),
        "png": find_real("**/*.png", [os.path.join(os.environ.get("USERPROFILE", ""), "Pictures"),
                                     os.path.join(os.environ.get("PUBLIC", ""), "Pictures"),
                                     r"C:\Windows\Web",
                                     r"C:\Windows\System32"]),
        "exe": r"C:\Windows\System32\notepad.exe",
        "dll": r"C:\Windows\System32\version.dll",
        "docx": find_real("**/*.docx", [os.path.join(os.environ.get("USERPROFILE", ""), "Documents"),
                                       os.path.join(os.environ.get("USERPROFILE", ""), "Desktop"),
                                       ROOT]),
        "mp3": find_real("**/*.mp3", [os.path.join(os.environ.get("USERPROFILE", ""), "Music")]),
        "txt": None, "md": None, "py": None, "ini": None,
    }

    results = {}
    for ext, src in sources.items():
        dst = os.path.join(OUT, "real_" + ext + "." + ext)
        if os.path.exists(dst):
            os.remove(dst)
        if src and os.path.isfile(src):
            try:
                shutil.copy2(src, dst)
            except OSError as e:
                print("  .%-5s copy failed: %s" % (ext, e)); continue
        else:
            with open(dst, "wb") as f:
                f.write(b"hello remark probe\n")
            src = "<synthetic>"

        print("\n=== .%s   (source: %s)" % (ext, src))
        hr, ps = open_store(dst, GPS_READWRITE)
        print("  open(GPS_READWRITE) hr=0x%08X" % hr)
        if hr != 0 or not ps:
            hr, ps = open_store(dst, GPS_DEFAULT)
            print("  open(GPS_DEFAULT) hr=0x%08X" % hr)
            if hr != 0 or not ps:
                results[ext] = "NO STORE"
                print("  -> cannot even read a property store")
                continue
            hr_c, vt, before = get_value(ps, PKEY_COMMENT)
            print("  read-only store: Comment hr=0x%08X vt=%d %r" % (hr_c, vt, before))
            release(ps)
            results[ext] = "READ-ONLY"
            continue

        hr_c, n = get_count(ps)
        hr_g, vt, before = get_value(ps, PKEY_COMMENT)
        print("  GetCount=0x%08X n=%d | Comment before vt=%d %r" % (hr_c, n, vt, before))
        hr_s = set_value(ps, PKEY_COMMENT, "原生备注测试")
        hr_k = commit(ps) if hr_s == 0 else 0xFFFFFFFF
        print("  SetValue hr=0x%08X  commit hr=0x%08X" % (hr_s, hr_k))
        release(ps)

        hr, ps = open_store(dst, GPS_DEFAULT)
        if hr == 0 and ps:
            hr_g, vt, after = get_value(ps, PKEY_COMMENT)
            print("  REOPEN: hr=0x%08X vt=%d %r" % (hr_g, vt, after))
            results[ext] = "OK %r" % (after,)
            release(ps)
        else:
            results[ext] = "REOPEN FAILED"

    ole32.CoUninitialize()
    print("\n===== SUMMARY =====")
    for k, v in results.items():
        print("  .%-5s %s" % (k, v))
    return 0


if __name__ == "__main__":
    sys.exit(main())
