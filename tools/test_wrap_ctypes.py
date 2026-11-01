# -*- coding: utf-8 -*-
"""Verify the wrapper path: for a type Windows already has a property handler
for (.jpg / .exe), our handler must forward every native property and add the
备注 (System.Comment) on top -- without enumerating the same key twice.

Runs fully in-process: the registry is only READ (FindNative reads the real
HKLM associations), which the sandbox allows.
"""
import ctypes
import os
import shutil
import sys
from ctypes import POINTER, byref, c_void_p, c_uint32, c_uint16, c_ubyte, c_wchar_p

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ole32 = ctypes.WinDLL("ole32")
shell32 = ctypes.WinDLL("shell32")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = os.path.join(ROOT, "build", "_wrap_test")

HRESULT = ctypes.c_long
DWORD = c_uint32
ULONG = ctypes.c_ulong
VT_EMPTY = 0
VT_LPWSTR = 31

IID_IClassFactory = "{00000001-0000-0000-C000-000000000046}"
IID_IPropertyStore = "{886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99}"
IID_IInitializeWithItem = "{7F73BE3F-FB79-493C-A6C7-7EE14E245841}"
IID_IShellItem = "{43826D1E-E718-42EE-BC55-A1E261C37BFE}"
CLSID_HANDLER = "{B4C8E6D1-7A2F-4c3b-9D5E-1F6C2A8B3D41}"
# System.Comment -- the built-in property Windows labels 备注.
PKEY_REMARK = ("{F29F85E0-4FF9-1068-AB91-08002B27B3D9}", 6)


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
    _fields_ = [("vt", c_uint16), ("r1", c_uint16), ("r2", c_uint16), ("r3", c_uint16),
                ("ptr", c_void_p), ("pad2", c_ubyte * 8)]


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
    """Create our handler for `path`; returns the IPropertyStore pointer."""
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


def native_clsid(ext):
    import winreg
    for root, sub in (
        (winreg.HKEY_LOCAL_MACHINE,
         r"SOFTWARE\Microsoft\Windows\CurrentVersion\PropertySystem\PropertyHandlers" + "\\" + ext),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Classes" + "\\" + ext + r"\ShellEx\PropertyHandler"),
    ):
        try:
            with winreg.OpenKey(root, sub) as k:
                return winreg.QueryValueEx(k, "")[0]
        except OSError:
            continue
    return None


def keys_of(ps):
    getcount = vcall(ps, 3, HRESULT, POINTER(DWORD))
    getat = vcall(ps, 4, HRESULT, DWORD, POINTER(PROPERTYKEY))
    c = DWORD()
    assert (getcount(ps, byref(c)) & 0xFFFFFFFF) == 0
    out = []
    for i in range(c.value):
        k = PROPERTYKEY()
        hr = getat(ps, i, byref(k)) & 0xFFFFFFFF
        out.append((guid_str(k.fmtid), k.pid, hr))
    return out


def get_value(ps, pkey):
    getv = vcall(ps, 5, HRESULT, POINTER(PROPERTYKEY), POINTER(PROPVARIANT))
    pk = PROPERTYKEY(guid(pkey[0]), pkey[1])
    pv = PROPVARIANT()
    hr = getv(ps, byref(pk), byref(pv)) & 0xFFFFFFFF
    val = None
    if pv.vt == VT_LPWSTR and pv.ptr:
        val = ctypes.cast(pv.ptr, c_wchar_p).value
    vt = pv.vt
    if pv.ptr:
        ole32.PropVariantClear(byref(pv))
    return hr, vt, val


def set_value(ps, pkey, text):
    setv = vcall(ps, 6, HRESULT, POINTER(PROPERTYKEY), POINTER(PROPVARIANT))
    pk = PROPERTYKEY(guid(pkey[0]), pkey[1])
    pv = PROPVARIANT()
    if text is None:
        pv.vt = VT_EMPTY
    else:
        pv.vt = VT_LPWSTR
        pv.ptr = ctypes.cast(c_wchar_p(text), c_void_p)
    return setv(ps, byref(pk), byref(pv)) & 0xFFFFFFFF


def commit(ps):
    return vcall(ps, 7, HRESULT)(ps) & 0xFFFFFFFF


def make_sample(ext):
    """Copy a real file of this type into WORK so the native handler has data."""
    os.makedirs(WORK, exist_ok=True)
    dst = os.path.join(WORK, "sample" + ext)
    if os.path.exists(dst):
        return dst
    candidates = []
    if ext in (".jpg", ".jpeg"):
        candidates = [os.path.join(os.environ.get("PUBLIC", r"C:\Users\Public"), "Pictures"),
                      os.path.join(os.environ.get("USERPROFILE", ""), "Pictures")]
    elif ext == ".exe":
        candidates = [os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32")]
    for base in candidates:
        for dirpath, _dirs, files in os.walk(base):
            for f in files:
                if f.lower().endswith(ext):
                    src = os.path.join(dirpath, f)
                    try:
                        if os.path.getsize(src) > 4096:
                            shutil.copy2(src, dst)
                            return dst
                    except OSError:
                        pass
            if dirpath.count(os.sep) - base.count(os.sep) > 3:
                continue
    # No real image on this machine: synthesize a valid one so the native
    # photo metadata handler still has something real to parse.
    if ext in (".jpg", ".jpeg", ".png"):
        try:
            from PIL import Image
            size = (160, 90)
            palette = [(i * 5) % 256 for i in range(3)]
            img = Image.new("RGB", size, tuple(palette))
            for x in range(size[0]):
                for y in range(size[1]):
                    img.putpixel((x, y), ((x * 3) % 256, (y * 5) % 256, (x + y) % 256))
            img.save(dst, "JPEG" if ext in (".jpg", ".jpeg") else "PNG")
            return dst
        except Exception as exc:  # noqa: BLE001
            print("  (could not synthesize an image: %s)" % exc)
    return None


def main():
    hr = ole32.CoInitializeEx(None, 0x2)
    print("CoInitializeEx hr=0x%08X" % (hr & 0xFFFFFFFF))
    lib = ctypes.WinDLL(os.path.join(ROOT, "build", "FileRemarksPropHandler.dll"))
    lib.DllGetClassObject.argtypes = [POINTER(GUID), POINTER(GUID), POINTER(c_void_p)]
    lib.DllGetClassObject.restype = HRESULT
    failures = []
    try:
        for ext in (".exe", ".jpg"):
            print("\n=== %s ===" % ext)
            clsid = native_clsid(ext)
            print("  native handler CLSID: %s" % clsid)
            sample = make_sample(ext)
            if not sample:
                print("  (no real sample of this type available)")
                continue
            print("  sample: %s (%d bytes)" % (sample, os.path.getsize(sample)))

            ps = open_handler(sample, lib)
            ks = keys_of(ps)
            print("  GetCount = %d" % len(ks))
            bad = [k for k in ks if k[2] != 0]
            print("  GetAt failures: %s" % (bad if bad else "none"))

            remark_key = (PKEY_REMARK[0].upper(), PKEY_REMARK[1])
            own = [k for k in ks if k[0].upper() == remark_key[0] and k[1] == remark_key[1]]
            print("  System.Comment enumerated %d time(s) (must be <= 1)" % len(own))
            if len(own) > 1:
                failures.append("%s: System.Comment enumerated twice" % ext)
            if bad:
                failures.append("%s: GetAt failed for %d key(s)" % (ext, len(bad)))

            # Native values must still be readable through the wrapper.
            native_reads = 0
            for fmtid, pid, _hr in ks[:6]:
                if len(own) and fmtid.upper() == remark_key[0] and pid == remark_key[1]:
                    continue
                vhr, vt, val = get_value(ps, (fmtid, pid))
                if vhr == 0 and vt not in (0,):
                    native_reads += 1
                    shown = val if val is not None else "<vt=%d>" % vt
                    print("    native %s pid=%d vt=%d -> %s" % (fmtid[:9], pid, vt, shown))
            print("  native properties readable through wrapper: %d" % native_reads)
            if native_reads == 0:
                failures.append("%s: no native property readable through wrapper" % ext)

            # Writing our remark must not disturb the native side.
            text = "包装测试 remark for " + ext
            hr_set = set_value(ps, PKEY_REMARK, text)
            hr_commit = commit(ps)
            print("  SetValue(remark) hr=0x%08X  Commit hr=0x%08X" % (hr_set, hr_commit))
            if hr_set != 0 or hr_commit != 0:
                failures.append("%s: remark write failed" % ext)
            ads = sample + ":remark"
            got = open(ads, "rb").read().decode("utf-8") if os.path.exists(ads) else None
            print("  ADS :remark -> %r" % got)
            if got != text:
                failures.append("%s: ADS roundtrip mismatch" % ext)
            vhr, vt, val = get_value(ps, PKEY_REMARK)
            print("  GetValue(remark) hr=0x%08X vt=%d -> %r" % (vhr, vt, val))
            if val != text:
                failures.append("%s: GetValue did not return our remark" % ext)
            os.remove(ads)
            release(ps)

        print("")
        if failures:
            print("FAILURES:")
            for f in failures:
                print("  - " + f)
            return 1
        print("ALL WRAP-SURROUND TESTS PASSED")
        return 0
    finally:
        ole32.CoUninitialize()


if __name__ == "__main__":
    sys.exit(main())
