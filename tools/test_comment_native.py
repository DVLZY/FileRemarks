# -*- coding: utf-8 -*-
"""Probe: does Windows itself support a per-file 'Comments' (System.Comment)
property on arbitrary file types, without any custom property handler?

If yes, the whole FileRemarks design can shrink to "write that property".
If no, we must ship a property handler.
"""
import ctypes, os, sys
from ctypes import wintypes, POINTER

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "build", "_comment_probe")
os.makedirs(OUT, exist_ok=True)

ole32 = ctypes.WinDLL("ole32")
shell32 = ctypes.WinDLL("shell32")
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

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
    g.Data1 = int(p[0], 16)
    g.Data2 = int(p[1], 16)
    g.Data3 = int(p[2], 16)
    tail = bytes.fromhex(p[3] + p[4])
    for i in range(8):
        g.Data4[i] = tail[i]
    return g


class PROPERTYKEY(ctypes.Structure):
    _fields_ = [("fmtid", GUID), ("pid", ctypes.c_uint32)]

    def __str__(self):
        return "%s,%d" % (self.fmtid, self.pid)


class PROPVARIANT(ctypes.Structure):
    _fields_ = [("vt", ctypes.c_uint16), ("r1", ctypes.c_uint16),
                ("r2", ctypes.c_uint16), ("r3", ctypes.c_uint16),
                ("ptr", ctypes.c_void_p), ("pad2", ctypes.c_ubyte * 8)]


VT_EMPTY, VT_LPWSTR, VT_BSTR = 0, 31, 8

IID_IPropertyStore = guid("{886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99}")

# System.Comment and a few siblings from the Summary Information fmtid.
FMTID_SUMMARY = "{F29F85E0-4FF9-1068-AB91-08002B27B3D9}"
PKEY = {
    "Title": PROPERTYKEY(guid(FMTID_SUMMARY), 2),
    "Subject": PROPERTYKEY(guid(FMTID_SUMMARY), 3),
    "Author": PROPERTYKEY(guid(FMTID_SUMMARY), 4),
    "Keywords": PROPERTYKEY(guid(FMTID_SUMMARY), 5),
    "Comment": PROPERTYKEY(guid(FMTID_SUMMARY), 6),
}


SHGetPropertyStoreFromParsingName = shell32.SHGetPropertyStoreFromParsingName
SHGetPropertyStoreFromParsingName.argtypes = [
    ctypes.c_wchar_p, ctypes.c_void_p, ctypes.c_uint32,
    ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)]
SHGetPropertyStoreFromParsingName.restype = ctypes.c_long
ole32.PropVariantClear.argtypes = [ctypes.POINTER(PROPVARIANT)]
ole32.PropVariantClear.restype = ctypes.c_long
kernel32.FindClose.argtypes = [ctypes.c_void_p]
kernel32.FindClose.restype = wintypes.BOOL


def vcall(obj, index, restype, *argtypes):
    vtbl = ctypes.cast(obj, POINTER(POINTER(ctypes.c_void_p)))[0]
    fn = ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)(vtbl[index])
    return fn


def open_store(path, flags):
    ps = ctypes.c_void_p()
    hr = SHGetPropertyStoreFromParsingName(
        path, None, flags, ctypes.byref(IID_IPropertyStore), ctypes.byref(ps))
    return hr & 0xFFFFFFFF, ps


def get_value(ps, key):
    pv = PROPVARIANT()
    fn = vcall(ps, 5, ctypes.c_long, POINTER(PROPERTYKEY), POINTER(PROPVARIANT))
    hr = fn(ps, ctypes.byref(key), ctypes.byref(pv)) & 0xFFFFFFFF
    val = None
    if hr == 0 and pv.vt == VT_LPWSTR and pv.ptr:
        val = ctypes.wstring_at(pv.ptr)
        ole32.PropVariantClear(ctypes.byref(pv))
    elif pv.vt != VT_EMPTY:
        ole32.PropVariantClear(ctypes.byref(pv))
    return hr, pv.vt, val


def set_value(ps, key, text):
    pv = PROPVARIANT()
    pv.vt = VT_LPWSTR
    buf = ctypes.create_unicode_buffer(text)
    pv.ptr = ctypes.cast(buf, ctypes.c_void_p)
    fn = vcall(ps, 6, ctypes.c_long, POINTER(PROPERTYKEY), POINTER(PROPVARIANT))
    hr = fn(ps, ctypes.byref(key), ctypes.byref(pv)) & 0xFFFFFFFF
    del buf
    return hr


def commit(ps):
    fn = vcall(ps, 7, ctypes.c_long)
    return fn(ps) & 0xFFFFFFFF


def release(ps):
    if ps:
        vcall(ps, 2, ctypes.c_ulong)(ps)


def streams(path):
    """Enumerate ADS names on a file."""
    FindFirstStreamW = kernel32.FindFirstStreamW
    FindFirstStreamW.argtypes = [ctypes.c_wchar_p, ctypes.c_int,
                                 ctypes.c_void_p, wintypes.DWORD]
    FindFirstStreamW.restype = ctypes.c_void_p
    FindNextStreamW = kernel32.FindNextStreamW
    FindNextStreamW.argtypes = [ctypes.c_void_p, ctypes.c_void_p]

    class WIN32_FIND_STREAM_DATA(ctypes.Structure):
        _fields_ = [("StreamSize", ctypes.c_int64),
                    ("cStreamName", ctypes.c_wchar * 296)]

    data = WIN32_FIND_STREAM_DATA()
    h = FindFirstStreamW(path, 0, ctypes.byref(data), 0)
    names = []
    if h != ctypes.c_void_p(-1).value and h:
        names.append(data.cStreamName)
        while FindNextStreamW(h, ctypes.byref(data)):
            names.append(data.cStreamName)
        kernel32.FindClose(h)
    return names


GPS_DEFAULT = 0x0
GPS_HANDLERPROPERTIESONLY = 0x1
GPS_READWRITE = 0x2
GPS_DELAYCREATION = 0x4
GPS_BESTEFFORT = 0x8

TYPES = ["txt", "md", "py", "exe", "jpg", "doc", "bin"]


def main():
    hr = ole32.CoInitializeEx(None, COINIT_APARTMENTTHREADED) & 0xFFFFFFFF
    print("CoInitializeEx hr=0x%08X" % hr)

    ok = True
    for ext in TYPES:
        path = os.path.join(OUT, "sample_" + ext)
        with open(path, "wb") as f:
            f.write(b"probe payload\r\n")
        # binary rename to get exact extension (no .txt appended)
        target = os.path.join(OUT, "probe." + ext)
        if os.path.exists(target):
            os.remove(target)
        os.rename(path, target)
        path = target

        print("\n=== .%s ===" % ext)
        for label, flags in (("GPS_READWRITE", GPS_READWRITE),
                             ("GPS_HANDLERPROPERTIESONLY", GPS_HANDLERPROPERTIESONLY),
                             ("GPS_HANDLERPROPERTIESONLY|READWRITE",
                              GPS_HANDLERPROPERTIESONLY | GPS_READWRITE)):
            hr, ps = open_store(path, flags)
            print("  %-30s open hr=0x%08X" % (label, hr))
            if hr != 0 or not ps:
                continue
            hr_g, vt, before = get_value(ps, PKEY["Comment"])
            cnt = ctypes.c_uint32()
            gcn = vcall(ps, 3, ctypes.c_long, POINTER(ctypes.c_uint32))
            hr_cnt = gcn(ps, ctypes.byref(cnt)) & 0xFFFFFFFF
            print("     GetCount hr=0x%08X n=%d | Comment before: hr=0x%08X vt=%d %r"
                  % (hr_cnt, cnt.value, hr_g, vt, before))
            hr_s = set_value(ps, PKEY["Comment"], "原生备注测试")
            hr_c = commit(ps) if hr_s == 0 else None
            print("     SetValue hr=0x%08X commit=%s"
                  % (hr_s, ("0x%08X" % hr_c) if hr_c is not None else "skipped"))
            release(ps)

        # Re-open read-only and check persistence.
        hr, ps = open_store(path, GPS_DEFAULT)
        if hr == 0 and ps:
            hr_g, vt, after = get_value(ps, PKEY["Comment"])
            print("     after reopen: hr=0x%08X vt=%d %r" % (hr_g, vt, after))
            release(ps)
        print("     streams: %r" % (streams(path),))

    ole32.CoUninitialize()
    print("\nPROBE DONE  (ok=%s)" % ok)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
