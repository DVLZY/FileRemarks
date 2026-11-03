# -*- coding: utf-8 -*-
"""Verify the OOXML path: our handler serves .docx/.pptx/.xlsx itself.

Requirements exercised here:
  * a real .docx still exposes the document properties Office used to show
    (Title / Author / Pages / Template / Total editing time);
  * the ADS remark wins over docProps/core.xml <dc:description>;
  * a 0-byte "新建 Word 文档", a damaged file and an OLE (encrypted-style)
    container renamed to .docx all still show the ADS remark -- the reason this
    path exists -- and expose nothing else, without ever crashing.

Runs fully in-process against build/FileRemarksPropHandler.dll. The registry is
only read (the handler reads real associations), which the sandbox allows.
"""
import ctypes
import os
import shutil
import sys
from ctypes import POINTER, byref, c_void_p, c_uint32, c_uint16, c_ubyte, c_wchar_p

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ole32 = ctypes.WinDLL("ole32")
shell32 = ctypes.WinDLL("shell32")
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = os.path.join(ROOT, "build", "_ooxml_test")
SAMPLES = os.path.join(ROOT, "build", "_tmp")

HRESULT = ctypes.c_long
DWORD = c_uint32
ULONG = ctypes.c_ulong
VT_EMPTY = 0
VT_UI4 = 19
VT_UI8 = 21
VT_LPWSTR = 31

IID_IClassFactory = "{00000001-0000-0000-C000-000000000046}"
IID_IPropertyStore = "{886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99}"
IID_IInitializeWithItem = "{7F73BE3F-FB79-493C-A6C7-7EE14E245841}"
IID_IShellItem = "{43826D1E-E718-42EE-BC55-A1E261C37BFE}"
CLSID_HANDLER = "{B4C8E6D1-7A2F-4c3b-9D5E-1F6C2A8B3D41}"
SYS = "{F29F85E0-4FF9-1068-AB91-08002B27B3D9}"
PKEY_REMARK = (SYS, 6)
PKEY_TITLE = (SYS, 2)
PKEY_AUTHOR = (SYS, 4)
PKEY_TEMPLATE = (SYS, 7)
PKEY_TOTAL_TIME = (SYS, 10)
PKEY_PAGES = (SYS, 14)

failures = []


def check(ok, msg):
    print(("  ok   " if ok else "  FAIL ") + msg)
    if not ok:
        failures.append(msg)


class GUID(ctypes.Structure):
    _fields_ = [("Data1", c_uint32), ("Data2", c_uint16), ("Data3", c_uint16),
                ("Data4", c_ubyte * 8)]


def guid(s):
    p = s.strip("{}").split("-")
    g = GUID()
    g.Data1 = int(p[0], 16)
    g.Data2 = int(p[1], 16)
    g.Data3 = int(p[2], 16)
    for i, b in enumerate(bytes.fromhex(p[3] + p[4])):
        g.Data4[i] = b
    return g


def guid_str(g):
    h = [g.Data4[i] for i in range(8)]
    return "{%08X-%04X-%04X-%02X%02X-%s}" % (
        g.Data1, g.Data2, g.Data3, h[0], h[1],
        "".join("%02X" % x for x in h[2:]))


class PROPERTYKEY(ctypes.Structure):
    _fields_ = [("fmtid", GUID), ("pid", DWORD)]


class PROPVARIANT(ctypes.Structure):
    # vt + 3 reserved WORDs, then a 16-byte union. Values are read through the
    # union by offset (see union_u32/union_u64/union_ptr) so the same struct
    # works for VT_LPWSTR, VT_UI4 and VT_UI8.
    _fields_ = [("vt", c_uint16), ("r1", c_uint16), ("r2", c_uint16), ("r3", c_uint16),
                ("data", c_ubyte * 16)]


def union_ptr(pv):
    return ctypes.cast(ctypes.byref(pv), POINTER(c_void_p))[1]


def union_u32(pv):
    return ctypes.cast(ctypes.byref(pv), POINTER(c_uint32))[2]


def union_u64(pv):
    return ctypes.cast(ctypes.byref(pv), POINTER(ctypes.c_uint64))[1]



def vcall(obj, index, restype, *argtypes):
    vtbl = ctypes.cast(obj, POINTER(c_void_p))[0]
    fn = ctypes.cast(vtbl, POINTER(c_void_p))[index]
    return ctypes.CFUNCTYPE(restype, c_void_p, *argtypes)(fn)


def qi(obj, iid_str):
    fn = vcall(obj, 0, HRESULT, POINTER(GUID), POINTER(c_void_p))
    out = c_void_p()
    hr = fn(obj, byref(guid(iid_str)), byref(out))
    return hr & 0xFFFFFFFF, out


def release(obj):
    vcall(obj, 2, ULONG)(obj)


def open_handler(path, lib):
    cf = c_void_p()
    hr = lib.DllGetClassObject(byref(guid(CLSID_HANDLER)), byref(guid(IID_IClassFactory)), byref(cf))
    assert (hr & 0xFFFFFFFF) == 0, "DllGetClassObject 0x%08X" % (hr & 0xFFFFFFFF)
    create = vcall(cf, 3, HRESULT, c_void_p, POINTER(GUID), POINTER(c_void_p))
    obj = c_void_p()
    hr = create(cf, None, byref(guid(IID_IInitializeWithItem)), byref(obj))
    assert (hr & 0xFFFFFFFF) == 0, "CreateInstance 0x%08X" % (hr & 0xFFFFFFFF)

    shell32.SHCreateItemFromParsingName.argtypes = [
        c_wchar_p, c_void_p, POINTER(GUID), POINTER(c_void_p)]
    shell32.SHCreateItemFromParsingName.restype = HRESULT
    psi = c_void_p()
    hr = shell32.SHCreateItemFromParsingName(path, None, byref(guid(IID_IShellItem)), byref(psi))
    assert (hr & 0xFFFFFFFF) == 0, "SHCreateItemFromParsingName 0x%08X" % (hr & 0xFFFFFFFF)

    init = vcall(obj, 3, HRESULT, c_void_p, DWORD)
    hr = init(obj, psi, 0)
    assert (hr & 0xFFFFFFFF) == 0, "Initialize 0x%08X" % (hr & 0xFFFFFFFF)
    release(psi)

    hr, ps = qi(obj, IID_IPropertyStore)
    assert hr == 0, "QI(IPropertyStore) 0x%08X" % hr
    return ps


def get_count(ps):
    c = DWORD()
    getcount = vcall(ps, 3, HRESULT, POINTER(DWORD))
    assert (getcount(ps, byref(c)) & 0xFFFFFFFF) == 0
    return c.value


def get_at(ps, index):
    getat = vcall(ps, 4, HRESULT, DWORD, POINTER(PROPERTYKEY))
    k = PROPERTYKEY()
    hr = getat(ps, index, byref(k)) & 0xFFFFFFFF
    return hresult_ok(hr), (guid_str(k.fmtid).upper(), k.pid)


def hresult_ok(hr):
    return hr == 0


def get_value(ps, pkey):
    getv = vcall(ps, 5, HRESULT, POINTER(PROPERTYKEY), POINTER(PROPVARIANT))
    pk = PROPERTYKEY(guid(pkey[0]), pkey[1])
    pv = PROPVARIANT()
    hr = getv(ps, byref(pk), byref(pv)) & 0xFFFFFFFF
    val = None
    if pv.vt == VT_LPWSTR and union_ptr(pv):
        val = ctypes.cast(union_ptr(pv), c_wchar_p).value
    elif pv.vt == VT_UI4:
        val = union_u32(pv)
    elif pv.vt == VT_UI8:
        val = union_u64(pv)
    vt = pv.vt
    if pv.vt != VT_EMPTY:
        ole32.PropVariantClear(byref(pv))
    return hr, vt, val


def set_value(ps, pkey, text):
    setv = vcall(ps, 6, HRESULT, POINTER(PROPERTYKEY), POINTER(PROPVARIANT))
    pk = PROPERTYKEY(guid(pkey[0]), pkey[1])
    pv = PROPVARIANT()
    keep = None
    if text is None:
        pv.vt = VT_EMPTY
    else:
        pv.vt = VT_LPWSTR
        keep = c_wchar_p(text)
        ctypes.cast(ctypes.byref(pv), POINTER(c_void_p))[1] = ctypes.cast(keep, c_void_p)
    return setv(ps, byref(pk), byref(pv)) & 0xFFFFFFFF


def commit(ps):
    return vcall(ps, 7, HRESULT)(ps) & 0xFFFFFFFF


def read_ads(path, name="remark"):
    """Reads the UTF-8 ADS written by the product, through Win32 directly."""
    kernel32.CreateFileW.restype = c_void_p
    kernel32.CreateFileW.argtypes = [c_wchar_p, DWORD, DWORD, c_void_p, DWORD, DWORD, c_void_p]
    h = kernel32.CreateFileW(path + ":" + name, 0x80000000, 0x7, None, 3, 0x80, None)
    if not h or h == ctypes.c_void_p(-1).value:
        return None
    try:
        buf = ctypes.create_string_buffer(8192)
        got = DWORD()
        kernel32.ReadFile(c_void_p(h), buf, 8192, byref(got), None)
        return buf.raw[:got.value].decode("utf-8", "replace")
    finally:
        kernel32.CloseHandle(c_void_p(h))


def copy_sample(src_name, dst_name):
    src = os.path.join(SAMPLES, src_name)
    os.makedirs(WORK, exist_ok=True)
    dst = os.path.join(WORK, dst_name)
    if os.path.exists(src):
        try:
            if os.path.exists(dst):
                os.remove(dst)
            shutil.copy2(src, dst)
        except OSError as exc:
            print("  (could not copy %s: %s)" % (src_name, exc))
            return None
        return dst
    print("  (sample %s missing)" % src_name)
    return None


def main():
    hr = ole32.CoInitializeEx(None, 0x2)
    print("CoInitializeEx hr=0x%08X" % (hr & 0xFFFFFFFF))
    lib = ctypes.WinDLL(os.path.join(ROOT, "build", "FileRemarksPropHandler.dll"))
    lib.DllGetClassObject.argtypes = [POINTER(GUID), POINTER(GUID), POINTER(c_void_p)]
    lib.DllGetClassObject.restype = HRESULT
    try:
        # ---- 1. a real package must reproduce the document properties ----
        print("\n=== real .docx: document properties still visible ===")
        real = copy_sample("probe.docx", "real.docx")
        if real:
            print("  size = %d bytes" % os.path.getsize(real))
            ps = open_handler(real, lib)
            count = get_count(ps)
            print("  GetCount = %d" % count)
            check(count >= 8, "GetCount enumerates the docProps values (%d)" % count)
            ok, first = get_at(ps, 0)
            check(ok and first == (PKEY_REMARK[0].upper(), PKEY_REMARK[1]),
                  "GetAt(0) is System.Comment")
            listed = [get_at(ps, i)[1] for i in range(count)]
            check((PKEY_PAGES[0].upper(), PKEY_PAGES[1]) in listed, "PageCount is enumerated")
            check((PKEY_TEMPLATE[0].upper(), PKEY_TEMPLATE[1]) in listed, "Template is enumerated")

            _hr, vt, title = get_value(ps, PKEY_TITLE)
            print("  Title vt=%d value=%r" % (vt, title))
            _hr, vt, author = get_value(ps, PKEY_AUTHOR)
            print("  Author vt=%d value=%r" % (vt, author))
            check(author == "林小橘", "Author comes from core.xml <dc:creator>")
            _hr, vt, pages = get_value(ps, PKEY_PAGES)
            print("  PageCount vt=%d value=%r" % (vt, pages))
            check(vt == VT_UI4 and pages == 1, "PageCount is a UI4 with the real value")
            _hr, vt, total = get_value(ps, PKEY_TOTAL_TIME)
            print("  TotalEditingTime vt=%d value=%r" % (vt, total))
            check(vt == VT_UI8 and total == 2400000000, "TotalTime is minutes -> 100ns units")
            _hr, vt, template = get_value(ps, PKEY_TEMPLATE)
            print("  Template vt=%d value=%r" % (vt, template))
            check(template == "Normal.dotm", "Template comes from app.xml")

            # dc:description is the fallback when the file carries no ADS remark.
            _hr, vt, comment = get_value(ps, PKEY_REMARK)
            print("  Comment (no ADS) vt=%d value=%r" % (vt, comment))
            check(comment == "probe-remark-OK", "Comment falls back to core.xml description")

            ads_text = "ooxml-ads-备注优先"
            hr = set_value(ps, PKEY_REMARK, ads_text)
            check(hr == 0, "SetValue(Comment) hr=0x%08X" % hr)
            hr = commit(ps)
            check(hr == 0, "Commit hr=0x%08X" % hr)
            release(ps)

            got = read_ads(real)
            print("  ADS after commit: %r" % got)
            check(got == ads_text, "remark was written to the ADS")

            ps = open_handler(real, lib)
            _hr, vt, comment = get_value(ps, PKEY_REMARK)
            check(comment == ads_text, "the ADS remark wins over <dc:description>")
            check(get_count(ps) == count, "writing a remark does not duplicate a key")
            release(ps)

        # ---- 2. the files that motivated this: unreadable packages ----
        cases = [
            ("real0.docx", "zero.docx", "0-byte 新建 Word 文档"),
            ("real0.pptx", "zero.pptx", "0-byte 新建 PowerPoint 文档"),
            ("real.xlsx", "real.xlsx", "real xlsx (must keep its doc props)"),
            ("real.doc", "ole.docx", "OLE container renamed to .docx"),
        ]
        for src_name, dst_name, label in cases:
            print("\n=== %s ===" % label)
            path = copy_sample(src_name, dst_name)
            if not path:
                continue
            print("  size = %d bytes" % os.path.getsize(path))
            ps = open_handler(path, lib)   # must not crash or hang
            count = get_count(ps)
            print("  GetCount = %d" % count)
            if dst_name == "real.xlsx":
                check(count >= 5, "a readable package still enumerates its doc props")
            else:
                check(count == 1, "unreadable package exposes only the remark key")
            ok, first = get_at(ps, 0)
            check(ok and first == (PKEY_REMARK[0].upper(), PKEY_REMARK[1]),
                  "GetAt(0) is System.Comment")
            _hr, vt, comment = get_value(ps, PKEY_REMARK)
            print("  Comment before write: vt=%d value=%r" % (vt, comment))
            ads_text = "0字节备注-" + dst_name
            hr = set_value(ps, PKEY_REMARK, ads_text)
            check(hr == 0, "SetValue(Comment) hr=0x%08X" % hr)
            hr = commit(ps)
            check(hr == 0, "Commit hr=0x%08X" % hr)
            release(ps)
            got = read_ads(path)
            print("  ADS after commit: %r" % got)
            check(got == ads_text, "ADS was written even though the package is unreadable")
            ps = open_handler(path, lib)
            _hr, vt, comment = get_value(ps, PKEY_REMARK)
            check(comment == ads_text, "GetValue returns the ADS remark afterwards")
            release(ps)

        # ---- 3. a damaged ZIP must not crash Explorer ----
        print("\n=== damaged file with .docx extension ===")
        broken = os.path.join(WORK, "broken.docx")
        with open(broken, "wb") as f:
            f.write(b"PK\x03\x04" + bytes(range(256)) * 8)
        print("  size = %d bytes" % os.path.getsize(broken))
        ps = open_handler(broken, lib)
        check(get_count(ps) == 1, "damaged package exposes only the remark key")
        release(ps)

        # ---- 4. non-OOXML types are unaffected ----
        print("\n=== delegation untouched ===")
        doc = os.path.join(SAMPLES, "real.doc")
        if os.path.exists(doc):
            ps = open_handler(doc, lib)
            count = get_count(ps)
            print("  .doc GetCount = %d" % count)
            check(count >= 20, "legacy .doc keeps its ~25 delegated keys")
            release(ps)
        else:
            check(False, "real.doc sample missing")
    finally:
        ole32.CoUninitialize()

    print()
    if failures:
        print("FAILURES:")
        for f in failures:
            print("  - " + f)
        return 1
    print("ALL OOXML TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
