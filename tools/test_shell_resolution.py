# -*- coding: utf-8 -*-
"""
End-to-end test of SHELL PROPERTY-HANDLER RESOLUTION (no admin needed).

Question this answers with evidence instead of guesswork:
  For a given file, does Windows actually pick up OUR property handler, and does
  our "备注" key show up in the property store Explorer would build?

Method: register the handler under HKCU\\Software\\Classes (per-user, so no
admin rights are required), then call the shell's own
SHGetPropertyStoreFromParsingName() -- the very API Explorer uses -- and
enumerate the returned keys looking for our PKEY.  Everything is undone at the
end (finally block).

Scenarios:
  A. only  HKCR\\*\\shellex\\PropertyHandler          (what v1.2 ships)
  B. A + per-extension HKCR\\.ext\\shellex\\PropertyHandler
  C. B + per-extension ...\\PropertySystem\\PropertyHandlers\\.ext  (HKCU copy)

Files tested: .txt .md .py .json (no system handler) and .jpg .exe (system
handler exists in HKLM\\...\\PropertySystem\\PropertyHandlers).
"""
import ctypes
import os
import shutil
import sys
import tempfile
import winreg
from ctypes import POINTER, byref, c_uint16, c_uint32, c_ubyte, c_void_p, c_wchar_p

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DLL = os.path.join(ROOT, "build", "FileRemarksPropHandler.dll")

CLSID_STR = "{B4C8E6D1-7A2F-4c3b-9D5E-1F6C2A8B3D41}"
FMTID_STR = "{B4C8E6D1-7A2F-4c3b-9D5E-1F6C2A8B3D40}"
PID = 2

ole32 = ctypes.WinDLL("ole32")
shell32 = ctypes.WinDLL("shell32")
kernel32 = ctypes.WinDLL("kernel32")


class GUID(ctypes.Structure):
    _fields_ = [("Data1", c_uint32), ("Data2", c_uint16), ("Data3", c_uint16),
                ("Data4", c_ubyte * 8)]


class PROPERTYKEY(ctypes.Structure):
    _fields_ = [("fmtid", GUID), ("pid", c_uint32)]


def _guid(s):
    s = s.strip("{}")
    p = s.split("-")
    g = GUID()
    g.Data1 = int(p[0], 16)
    g.Data2 = int(p[1], 16)
    g.Data3 = int(p[2], 16)
    tail = bytes.fromhex(p[3] + p[4])
    for i, b in enumerate(tail):
        g.Data4[i] = b
    return g


IID_IPropertyStore = _guid("{886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99}")
PKEY_REMARK = PROPERTYKEY(_guid(FMTID_STR), PID)
PKEY_REMARK_LOOSE = PKEY_REMARK.fmtid.Data1, PKEY_REMARK.pid


def fmt_guid(g):
    tail = bytes(g.Data4)
    return "{%08X-%04X-%04X-%s-%s}" % (g.Data1, g.Data2, g.Data3,
                                       tail[:2].hex().upper(), tail[2:].hex().upper())


def vcall(obj, index, restype, *argtypes):
    vtbl = ctypes.cast(obj, POINTER(POINTER(c_void_p)))[0]
    fn = ctypes.WINFUNCTYPE(restype, c_void_p, *argtypes)(vtbl[index])
    return lambda *a: fn(obj, *a)


# --- shell API -------------------------------------------------------------
shell32.SHGetPropertyStoreFromParsingName.argtypes = [
    c_wchar_p, c_void_p, c_uint32, POINTER(GUID), POINTER(c_void_p)]
shell32.SHGetPropertyStoreFromParsingName.restype = ctypes.c_long
ole32.CoInitializeEx.argtypes = [c_void_p, c_uint32]
ole32.CoInitializeEx.restype = ctypes.c_long


def store_keys(path, flags=0):
    """Return (hr, [ (fmtid_str, pid), ... ]) for the shell property store."""
    ps = c_void_p()
    hr = shell32.SHGetPropertyStoreFromParsingName(path, None, flags,
                                                   byref(IID_IPropertyStore), byref(ps))
    if hr < 0 or not ps:
        return hr, []
    try:
        GetCount = vcall(ps, 3, ctypes.c_long, POINTER(c_uint32))
        GetAt = vcall(ps, 4, ctypes.c_long, c_uint32, POINTER(PROPERTYKEY))
        c = c_uint32()
        if GetCount(byref(c)) < 0:
            return hr, []
        out = []
        for i in range(c.value):
            k = PROPERTYKEY()
            if GetAt(i, byref(k)) >= 0:
                out.append((fmt_guid(k.fmtid), k.pid))
        return hr, out
    finally:
        vcall(ps, 2, ctypes.c_ulong)()


# --- registry helpers ------------------------------------------------------
HKCU = winreg.HKEY_CURRENT_USER
CLS_CLASSES = r"Software\Classes"
CLSID_KEY = CLS_CLASSES + r"\CLSID" + "\\" + CLSID_STR
PH_SHELLEX = r"Software\Classes\*\shellex\PropertyHandler"
PS_PH = r"Software\Microsoft\Windows\CurrentVersion\PropertySystem\PropertyHandlers"

created = []


def setval(path, name, value):
    winreg.CreateKeyEx(HKCU, path, 0, winreg.KEY_SET_VALUE)
    if path not in created:
        created.append(path)
    with winreg.OpenKey(HKCU, path, 0, winreg.KEY_SET_VALUE) as k:
        winreg.SetValueEx(k, name, 0, winreg.REG_SZ, value)


def deltree(path):
    def rec(p):
        try:
            with winreg.OpenKey(HKCU, p, 0, winreg.KEY_ALL_ACCESS) as k:
                subs = []
                i = 0
                while True:
                    try:
                        subs.append(winreg.EnumKey(k, i))
                    except OSError:
                        break
                    i += 1
            for s in subs:
                rec(p + "\\" + s)
            winreg.DeleteKey(HKCU, p)
        except OSError:
            pass
    rec(path)


def register_clsid():
    setval(CLSID_KEY, "", "FileRemarks Property Handler")
    setval(CLSID_KEY + r"\InprocServer32", "", DLL)
    setval(CLSID_KEY + r"\InprocServer32", "ThreadingModel", "Apartment")


def unregister_all():
    deltree(CLSID_KEY)
    deltree(r"Software\Classes\*\shellex\PropertyHandler")
    deltree(PS_PH)
    for ext in (".txt", ".md", ".py", ".json", ".jpg", ".exe"):
        deltree(r"Software\Classes" + "\\" + ext + r"\shellex\PropertyHandler")


# --- test files ------------------------------------------------------------
def make_files(tmp):
    files = {}
    for ext in (".txt", ".md", ".py", ".json"):
        p = os.path.join(tmp, "sample" + ext)
        with open(p, "w", encoding="utf-8") as f:
            f.write("hello\n")
        files[ext] = p
    # a real .jpg if we can find one on the machine, else fake bytes
    jpg = None
    for base in (os.path.join(os.environ.get("USERPROFILE", ""), "Pictures"),
                 os.path.join(os.environ.get("PUBLIC", r"C:\Users\Public"), "Pictures")):
        if os.path.isdir(base):
            for dirpath, _dirs, names in os.walk(base):
                for n in names:
                    if n.lower().endswith((".jpg", ".jpeg")):
                        jpg = os.path.join(dirpath, n)
                        break
                if jpg:
                    break
        if jpg:
            break
    p = os.path.join(tmp, "sample.jpg")
    if jpg:
        shutil.copyfile(jpg, p)
    else:
        with open(p, "wb") as f:
            f.write(b"\xff\xd8\xff\xe0" + b"\x00" * 64)
    files[".jpg"] = p
    exe = os.path.join(tmp, "sample.exe")
    shutil.copyfile(sys.executable if sys.executable.lower().endswith(".exe")
                    else os.path.join(os.environ["WINDIR"], "system32", "notepad.exe"), exe)
    files[".exe"] = exe
    return files


def has_remark(keys):
    for g, pid in keys:
        if pid == PID and g.upper() == FMTID_STR.upper():
            return True
    return False


def probe(files, label):
    print("\n--- %s ---" % label)
    for ext, p in files.items():
        hr, keys = store_keys(p)
        print("  %-6s hr=0x%08X props=%-3d remark=%s"
              % (ext, hr & 0xFFFFFFFF, len(keys), "YES" if has_remark(keys) else "no "))

    # what does the same store look like for .jpg without our handler? (baseline)
    return


def main():
    if not os.path.exists(DLL):
        print("missing", DLL)
        return 1
    hr = ole32.CoInitializeEx(None, 2)
    if hr < 0:
        print("CoInitializeEx 0x%08X" % (hr & 0xFFFFFFFF))
    tmp = os.path.join(ROOT, "build", "_res_test")
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp, exist_ok=True)
    ok = True
    try:
        files = make_files(tmp)
        # write a remark into every file so our handler returns a value
        for p in files.values():
            with open(p + ":remark", "wb") as f:
                f.write("测试备注".encode("utf-8"))

        print("== baseline: nothing registered ==")
        probe(files, "baseline (no FileRemarks registration)")
        base = {ext: store_keys(p)[1] for ext, p in files.items()}

        unregister_all()
        register_clsid()
        setval(PH_SHELLEX, "", CLSID_STR)
        probe(files, "A: HKCR\\*\\shellex\\PropertyHandler only")

        for ext in (".txt", ".md", ".py", ".json", ".jpg", ".exe"):
            setval(r"Software\Classes" + "\\" + ext + r"\shellex\PropertyHandler",
                   "", CLSID_STR)
        probe(files, "B: A + per-extension HKCR\\.ext\\shellex\\PropertyHandler")

        for ext in (".txt", ".md", ".py", ".json", ".jpg", ".exe"):
            setval(PS_PH + "\\" + ext, "", CLSID_STR)
        probe(files, "C: B + HKCU ...PropertySystem\\PropertyHandlers\\.ext")

        # raw check: does the handler dll load and answer in-process at all?
        print("\n== sanity: direct COM store for sample.txt ==")
        print("   (already proven by tools/test_prophandler_ctypes.py)")
    finally:
        unregister_all()
        shutil.rmtree(tmp, ignore_errors=True)
        ole32.CoUninitialize()
    print("\nDONE (all HKCU test keys removed)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
