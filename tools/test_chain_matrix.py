"""Decide, with evidence, which file types FileRemarks may safely take over.

For every extension that Windows already associates with a property handler we
resolve that handler's CLSID, create it in-process, initialise it with whatever
interface it supports (item / file / stream), and then ask for IPropertyStore.

If a native handler exposes IPropertyStore, our own handler can wrap it and
forward every native property, so taking the slot over costs the user nothing.
If it does not, taking the slot over would hide the type's native columns, so
that type must be left alone.

Run:  PYTHONIOENCODING=utf-8 python tools/test_chain_matrix.py
"""

import ctypes
import os
import shutil
import struct
import sys
from ctypes import (POINTER, byref, c_long, c_uint16, c_uint32, c_ubyte,
                    c_void_p, c_wchar_p)
from ctypes import wintypes

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = os.path.join(ROOT, "build", "_chain_matrix")


# --------------------------------------------------------------------------
# COM plumbing
# --------------------------------------------------------------------------
class GUID(ctypes.Structure):
    _fields_ = [("Data1", c_uint32), ("Data2", c_uint16),
                ("Data3", c_uint16), ("Data4", c_ubyte * 8)]

    def __str__(self):
        d4 = "".join("%02X" % b for b in self.Data4)
        return "{%08X-%04X-%04X-%s-%s}" % (
            self.Data1, self.Data2, self.Data3, d4[:4], d4[4:])


class PROPERTYKEY(ctypes.Structure):
    _fields_ = [("fmtid", GUID), ("pid", c_uint32)]


class PROPVARIANT(ctypes.Structure):
    _fields_ = [("vt", c_uint16), ("r1", c_uint16), ("r2", c_uint16),
                ("r3", c_uint16), ("ptr", c_void_p), ("pad", c_ubyte * 8)]


def guid(text):
    p = text.strip("{}").split("-")
    g = GUID()
    g.Data1 = int(p[0], 16)
    g.Data2 = int(p[1], 16)
    g.Data3 = int(p[2], 16)
    raw = bytes.fromhex(p[3] + p[4])
    for i in range(8):
        g.Data4[i] = raw[i]
    return g


IID_IUnknown = guid("{00000000-0000-0000-C000-000000000046}")
IID_IPropertyStore = guid("{886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99}")
IID_IInitializeWithItem = guid("{7F73BE3F-FB79-493C-A6C7-7EE14E245841}")
IID_IInitializeWithStream = guid("{B824B49D-22AC-4161-AC8A-9916E8FA3F7F}")
IID_IInitializeWithFile = guid("{B7D14566-0509-4CCE-A71F-0A554233BD9B}")

ole32 = ctypes.WinDLL("ole32")
shlwapi = ctypes.WinDLL("shlwapi")
shobjidl = ctypes.WinDLL("shell32")
advapi = ctypes.WinDLL("advapi32")


def vcall(obj, index, restype, *argtypes):
    vtbl = ctypes.cast(obj, POINTER(POINTER(c_void_p)))[0]
    fn = ctypes.WINFUNCTYPE(restype, c_void_p, *argtypes)(vtbl[index])
    return fn


def release(obj):
    if obj:
        try:
            vcall(obj, 2, ctypes.c_ulong)(obj)
        except Exception:
            pass


def qi(punk, iid):
    out = c_void_p()
    hr = vcall(punk, 0, c_long, ctypes.POINTER(GUID), POINTER(c_void_p))(
        punk, byref(iid), byref(out))
    return hr, out


# --------------------------------------------------------------------------
# Sample files: one per extension we want to judge.
# --------------------------------------------------------------------------
PICTURES = [os.path.join(os.environ.get("USERPROFILE", ""), "Pictures"),
            os.path.join(os.environ.get("PUBLIC", r"C:\Users\Public"), "Pictures"),
            r"C:\Windows\Web\Wallpaper",
            r"C:\Windows\Web\4K\Wallpaper\Windows",
            r"C:\Windows\Web\Screen",
            r"C:\Windows\Web",
            r"C:\Windows\System32"]


def find_sample(exts):
    for base in PICTURES:
        if not os.path.isdir(base):
            continue
        for dirpath, _dirs, files in os.walk(base):
            for f in files:
                if os.path.splitext(f)[1].lower() in exts:
                    full = os.path.join(dirpath, f)
                    try:
                        if os.path.getsize(full) > 512:
                            return full
                    except OSError:
                        pass
            # Shallower walk keeps this fast; System32 needs one extra level.
            if dirpath.count(os.sep) - base.count(os.sep) >= 2:
                _dirs[:] = []
    return None


def make_samples():
    os.makedirs(WORK, exist_ok=True)
    made = {}

    def put(ext, source):
        dst = os.path.join(WORK, "sample" + ext)
        if not os.path.exists(dst):
            try:
                shutil.copy2(source, dst)
            except OSError as exc:
                print("  (could not copy %s: %s)" % (source, exc))
                return
        made[ext] = dst

    # Images/audio/video: a real file is required, handlers validate content.
    for group in ((".jpg", ".jpeg"), (".png",), (".gif",), (".bmp",),
                  (".ico",), (".tif", ".tiff"), (".webp",)):
        src = find_sample(set(group))
        if src:
            put(group[0], src)

    for ext, src in ((".exe", r"C:\Windows\System32\notepad.exe"),
                     (".dll", r"C:\Windows\System32\version.dll"),
                     (".sys", r"C:\Windows\System32\drivers\tcpip.sys"),
                     (".msi", None)):
        if src and os.path.exists(src):
            put(ext, src)

    # Anything else available in the user's own folders.
    wanted = {".doc": None, ".docx": None, ".xls": None, ".xlsx": None,
              ".ppt": None, ".pptx": None, ".mp3": None, ".mp4": None,
              ".zip": None, ".7z": None, ".rar": None, ".pdf": None,
              ".wav": None, ".avi": None, ".rtf": None}
    search_roots = [os.path.join(os.environ.get("USERPROFILE", ""), d)
                    for d in ("Documents", "Desktop", "Downloads", "Music",
                              "Videos", "Pictures")]
    search_roots += [r"C:\Windows\Help"]
    for tree in search_roots:
        if not os.path.isdir(tree):
            continue
        for dirpath, _dirs, files in os.walk(tree):
            if dirpath.count(os.sep) - tree.count(os.sep) >= 4:
                _dirs[:] = []
            for f in files:
                e = os.path.splitext(f)[1].lower()
                if e in wanted and wanted[e] is None and e not in made:
                    wanted[e] = os.path.join(dirpath, f)
                    put(e, wanted[e])

    return made


# --------------------------------------------------------------------------
# Registry lookups
# --------------------------------------------------------------------------
import winreg

PH_PATH = (r"SOFTWARE\Microsoft\Windows\CurrentVersion\PropertySystem"
           r"\PropertyHandlers")


def native_clsid(ext):
    for path in (PH_PATH + "\\" + ext, r"SOFTWARE\Classes" + ext +
                 r"\ShellEx\PropertyHandler"):
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path) as k:
                val, _typ = winreg.QueryValueEx(k, "")
                if val:
                    return val
        except OSError:
            pass
    return None


# --------------------------------------------------------------------------
# The actual probe
# --------------------------------------------------------------------------
def probe(ext, path):
    clsid_text = native_clsid(ext)
    if not clsid_text:
        return ext, "FREE", None, None

    clsid = guid(clsid_text)
    punk = c_void_p()
    hr = ole32.CoCreateInstance(byref(clsid), None, 1, byref(IID_IUnknown),
                               byref(punk))
    if hr < 0 or not punk:
        return ext, "CREATE FAIL", clsid_text, "0x%08X" % (hr & 0xFFFFFFFF)

    init_kind = None
    init_hr = -1

    h, p = qi(punk, IID_IInitializeWithItem)
    if h >= 0 and p:
        psi = c_void_p()
        hr2 = shobjidl.SHCreateItemFromParsingName(
            c_wchar_p(path), None, byref(IID_IUnknown), byref(psi))
        if hr2 >= 0 and psi:
            init_hr = vcall(p, 3, c_long, c_void_p, c_uint32)(p, psi, 0)
            release(psi)
            init_kind = "item"
        release(p)

    if init_kind is None:
        h, p = qi(punk, IID_IInitializeWithStream)
        if h >= 0 and p:
            stream = c_void_p()
            hr2 = shlwapi.SHCreateStreamOnFileEx(
                c_wchar_p(path), 0x80000000, 1, False, None, byref(stream))
            if hr2 >= 0 and stream:
                init_hr = vcall(p, 3, c_long, c_void_p, c_uint32)(p, stream, 0)
                release(stream)
                init_kind = "stream"
            release(p)

    if init_kind is None:
        h, p = qi(punk, IID_IInitializeWithFile)
        if h >= 0 and p:
            init_hr = vcall(p, 3, c_long, ctypes.c_wchar_p, c_uint32)(
                p, path, 0)
            init_kind = "file"
            release(p)

    if init_kind is None:
        release(punk)
        return ext, "NO INIT INTERFACE", clsid_text, None
    if init_hr < 0:
        release(punk)
        return ext, "INIT FAIL", clsid_text, "0x%08X" % (init_hr & 0xFFFFFFFF)

    h, ps = qi(punk, IID_IPropertyStore)
    if h < 0 or not ps:
        release(punk)
        return ext, "NO IPropertyStore (%s)" % init_kind, clsid_text, \
            "0x%08X" % (h & 0xFFFFFFFF)

    count = c_uint32(0)
    vcall(ps, 3, c_long, POINTER(c_uint32))(ps, byref(count))
    release(ps)
    release(punk)
    return ext, "CHAINABLE (%s)" % init_kind, clsid_text, int(count.value)


def main():
    ole32.CoInitializeEx(None, 0x2)
    try:
        samples = make_samples()
        if not samples:
            print("no sample files available")
            return 1

        print("extension  verdict                          native CLSID / count")
        print("-" * 78)
        chainable, blocked, free = [], [], []
        for ext in sorted(samples):
            ext_, verdict, clsid, extra = probe(ext, samples[ext])
            print("%-10s %-32s %s %s" % (ext_, verdict, clsid or "",
                                         extra if extra is not None else ""))
            if verdict.startswith("CHAINABLE"):
                chainable.append(ext_)
            elif verdict == "FREE":
                free.append(ext_)
            else:
                blocked.append(ext_)

        print()
        print("CHAINABLE (safe to take over, native columns preserved):",
              " ".join(chainable) or "(none)")
        print("FREE      (no system handler at all):", " ".join(free) or "(none)")
        print("BLOCKED   (taking over would hide native columns):",
              " ".join(blocked) or "(none)")
        return 0
    finally:
        ole32.CoUninitialize()


if __name__ == "__main__":
    sys.exit(main())
