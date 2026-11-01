"""Is the *native* 备注 (System.Comment) writable for Office-style file types?

For types Windows already has a metadata handler for, we deliberately do not
take the property-handler slot over (that would hide the type's own Details
columns). Instead the editor can write the remark straight into the file's
native System.Comment, which Explorer already shows in its 备注 column.

This probe answers, per type, whether that native write works:
  WRITABLE   SetValue + Commit accepted the remark and it reads back
  READ-ONLY  a store exists but refuses writes
  NO STORE   no writable property store at all -> must use the ADS path

Run:  PYTHONIOENCODING=utf-8 python tools/test_comment_office.py
"""

import ctypes
import os
import shutil
import sys
from ctypes import (POINTER, byref, c_long, c_uint16, c_uint32, c_ubyte,
                    c_void_p, c_wchar_p)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = os.path.join(ROOT, "build", "_comment_office")
SAMPLES = os.path.join(ROOT, "build", "_chain_matrix")

MARK = "备注探针-Office"


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


IID_IPropertyStore = guid("{886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99}")
PKEY_COMMENT = PROPERTYKEY(guid("{F29F85E0-4FF9-1068-AB91-08002B27B3D9}"), 6)

ole32 = ctypes.WinDLL("ole32")
shell32 = ctypes.WinDLL("shell32")
shell32.SHGetPropertyStoreFromParsingName.argtypes = [
    c_wchar_p, c_void_p, c_uint32, POINTER(GUID), POINTER(c_void_p)]
shell32.SHGetPropertyStoreFromParsingName.restype = c_long
ole32.PropVariantClear.argtypes = [c_void_p]
ole32.PropVariantClear.restype = c_long

VT_EMPTY, VT_LPWSTR = 0, 31
GPS_DEFAULT, GPS_READWRITE = 0x0, 0x2


def vcall(obj, index, restype, *argtypes):
    vtbl = ctypes.cast(obj, POINTER(POINTER(c_void_p)))[0]
    return ctypes.WINFUNCTYPE(restype, c_void_p, *argtypes)(vtbl[index])


def release(obj):
    if obj:
        vcall(obj, 2, c_long)(obj)


def open_store(path, flags):
    ps = c_void_p()
    hr = shell32.SHGetPropertyStoreFromParsingName(
        path, None, flags, byref(IID_IPropertyStore), byref(ps))
    if hr < 0 or not ps:
        return None, hr
    return ps, hr


def get_comment(ps):
    pv = PROPVARIANT()
    hr = vcall(ps, 5, c_long, POINTER(PROPERTYKEY), c_void_p)(
        ps, byref(PKEY_COMMENT), byref(pv))
    text = None
    if hr >= 0:
        if pv.vt == VT_LPWSTR and pv.ptr:
            text = ctypes.cast(pv.ptr, c_wchar_p).value
        elif pv.vt != VT_EMPTY:
            text = "<vt=%d>" % pv.vt
    ole32.PropVariantClear(byref(pv))
    return hr, text


def set_comment(ps, value):
    pv = PROPVARIANT()
    if value is None:
        pv.vt = VT_EMPTY
    else:
        pv.vt = VT_LPWSTR
        pv.ptr = ctypes.cast(ctypes.create_unicode_buffer(value), c_void_p)
    hr = vcall(ps, 6, c_long, POINTER(PROPERTYKEY), c_void_p)(
        ps, byref(PKEY_COMMENT), byref(pv))
    return hr


def commit(ps):
    return vcall(ps, 7, c_long)(ps)


def probe(path):
    ps, hr = open_store(path, GPS_READWRITE)
    if ps is None:
        ps, hr2 = open_store(path, GPS_DEFAULT)
        if ps is None:
            return "NO STORE", "open hr=0x%08X" % (hr & 0xFFFFFFFF)
        got = get_comment(ps)
        release(ps)
        return "READ-ONLY", "rw hr=0x%08X, ro comment=%r" % (
            hr & 0xFFFFFFFF, got[1])

    hr_before, before = get_comment(ps)
    hr_set = set_comment(ps, MARK)
    hr_commit = commit(ps)
    release(ps)

    ps2, _ = open_store(path, GPS_DEFAULT)
    after = None
    if ps2:
        after = get_comment(ps2)[1]
        release(ps2)

    if hr_set >= 0 and hr_commit >= 0 and after == MARK:
        # restore whatever was there before so samples stay clean
        ps3, _ = open_store(path, GPS_READWRITE)
        if ps3:
            set_comment(ps3, before)
            commit(ps3)
            release(ps3)
        return "WRITABLE", "roundtrip ok"
    return "FAILED", "set=0x%08X commit=0x%08X after=%r" % (
        hr_set & 0xFFFFFFFF, hr_commit & 0xFFFFFFFF, after)


TARGETS = [".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt",
           ".rtf", ".odt", ".jpg", ".png", ".mp3", ".mp4", ".txt", ".py"]


def main():
    ole32.CoInitializeEx(None, 0x2)
    try:
        os.makedirs(WORK, exist_ok=True)
        print("%-8s %-10s %s" % ("ext", "verdict", "detail"))
        print("-" * 74)
        verdicts = {}
        for ext in TARGETS:
            src = os.path.join(SAMPLES, "sample" + ext)
            if not os.path.isfile(src):
                print("%-8s %-10s %s" % (ext, "-", "no sample file available"))
                continue
            dst = os.path.join(WORK, "probe" + ext)
            shutil.copy2(src, dst)
            verdict, detail = probe(dst)
            verdicts[ext] = verdict
            print("%-8s %-10s %s" % (ext, verdict, detail))

        ok = sorted(e for e, v in verdicts.items() if v == "WRITABLE")
        print()
        print("native 备注 writable for: %s" % (" ".join(ok) if ok else "(none)"))
        return 0
    finally:
        ole32.CoUninitialize()


if __name__ == "__main__":
    sys.exit(main())
