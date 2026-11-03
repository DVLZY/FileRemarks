# -*- coding: utf-8 -*-
"""Why the installer asks for administrator rights, proved by measurement.

v1.9 made the whole product per-user (HKCU registration, no UAC) to get rid of
the SmartScreen "发行者未知" dialog. That worked for file types Windows has no
handler for, but it silently broke the types that DO have one -- `.exe` most
visibly, where Explorer's column came up empty.

The reason is measurable without any registry write: pick a type whose machine
key names a handler (`.png` -> the WIC handler) and whose user key names ours,
then ask the shell for that file's property store and watch which DLL gets
loaded. It loads the machine one, i.e. the HKCU association is ignored -- and
for `.exe` the machine handler then fails with 0x80070715
(ERROR_RESOURCE_TYPE_NOT_FOUND), which is why the 备注 column is empty.

    python tools/probe_elevation_needed.py
"""
import ctypes
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = os.path.join(ROOT, "build", "_elev_needed")
OUR_CLSID = "{B4C8E6D1-7A2F-4c3b-9D5E-1F6C2A8B3D41}"

ole32 = ctypes.WinDLL("ole32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
kernel32.GetModuleHandleW.restype = ctypes.c_void_p

FAILS = []


def check(ok, what, detail=""):
    print("  %s  %s%s" % ("PASS" if ok else "FAIL", what,
                          ("  [%s]" % detail) if detail else ""))
    if not ok:
        FAILS.append(what)
    return ok


class GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_ulong), ("Data2", ctypes.c_ushort),
                ("Data3", ctypes.c_ushort), ("Data4", ctypes.c_ubyte * 8)]


def guid(s):
    out = GUID()
    ole32.CLSIDFromString(ctypes.c_wchar_p(s), ctypes.byref(out))
    return out


def handler_value(root, ext, shape):
    import winreg
    if shape == "shellex":
        sub = "Software\\Classes\\%s\\ShellEx\\PropertyHandler" % ext
    else:
        sub = ("Software\\Microsoft\\Windows\\CurrentVersion\\PropertySystem"
               "\\PropertyHandlers\\%s" % ext)
    try:
        with winreg.OpenKey(root, sub) as key:
            return winreg.QueryValueEx(key, "")[0]
    except OSError:
        return None


def make_png(path):
    import struct
    import zlib
    raw = b"\x00" + b"\xff\x00\x00" * 2

    def chunk(tag, data):
        body = tag + data
        return (struct.pack(">I", len(data)) + body
                + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF))

    blob = (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 1, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw))
            + chunk(b"IEND", b""))
    with open(path, "wb") as fh:
        fh.write(blob)


def our_dll_loaded():
    return bool(kernel32.GetModuleHandleW(ctypes.c_wchar_p(
        "FileRemarksPropHandler.dll")))


def store_for(path):
    import ctypes.wintypes  # noqa: F401
    iid = guid("{886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99}")
    shell32.SHGetPropertyStoreFromParsingName.argtypes = [
        ctypes.c_wchar_p, ctypes.c_void_p, ctypes.c_ulong,
        ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)]
    shell32.SHGetPropertyStoreFromParsingName.restype = ctypes.c_long
    store = ctypes.c_void_p()
    hr = shell32.SHGetPropertyStoreFromParsingName(
        path, None, 0, ctypes.byref(iid), ctypes.byref(store))
    if hr >= 0 and store:
        vtbl = ctypes.cast(ctypes.cast(store, ctypes.POINTER(ctypes.c_void_p))[0],
                           ctypes.POINTER(ctypes.c_void_p))
        release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtbl[2])
        release(store)
    return hr


def main():
    print("elevation-needed probe")
    # The shell store needs an apartment; without it every call answers
    # CO_E_NOTINITIALIZED and the measurement proves nothing.
    ole32.CoInitializeEx(None, 2)  # COINIT_APARTMENTTHREADED
    import winreg
    os.makedirs(WORK, exist_ok=True)
    png = os.path.join(WORK, "which_handler.png")
    make_png(png)

    hkcu = handler_value(winreg.HKEY_CURRENT_USER, ".png", "shellex")
    hklm = handler_value(winreg.HKEY_LOCAL_MACHINE, ".png", "shellex")
    print("  .png handler  HKCU=%s  HKLM=%s" % (hkcu, hklm))

    if hkcu != OUR_CLSID:
        print("  (this machine has no per-user .png association -- install a"
              " per-user build to reproduce the measurement)")
    loaded_before = our_dll_loaded()
    hr = store_for(png)
    loaded_after = our_dll_loaded()
    print("  store hr=0x%08X  our DLL loaded before=%s after=%s"
          % (hr & 0xFFFFFFFF, loaded_before, loaded_after))

    if hkcu == OUR_CLSID and hklm and hklm != OUR_CLSID:
        check(not (loaded_after and not loaded_before),
              "the shell spoke to the MACHINE handler, not the per-user one",
              "HKCU names ours, HKLM names %s" % hklm)

    # The installer must now carry the elevation request and the honest
    # fallback text, otherwise a machine-wide registration can never happen.
    setups = [f for f in os.listdir(os.path.join(ROOT, "dist", "releases"))
              if f.startswith("FileRemarks_Setup_v") and f.endswith(".exe")]
    if not setups:
        check(False, "a versioned setup exists in dist/releases")
        return 1

    def newest(names):
        def key(name):
            digits = name.split("_v")[1][:-4].split(".")
            return [int(x) for x in digits]
        return sorted(names, key=key)[-1]

    setup = os.path.join(ROOT, "dist", "releases", newest(setups))
    blob = open(setup, "rb").read()
    print("  setup: %s (%d bytes)" % (os.path.basename(setup), len(blob)))
    check("runas".encode("utf-16-le") in blob,
          "the setup can request an elevated token", "wide \"runas\" present")
    check("/elevated".encode("utf-16-le") in blob,
          "it relaunches itself elevated once", "wide \"/elevated\" present")
    check("需要管理员权限".encode("utf-16-le") in blob,
          "it carries the honest no-admin fallback text")

    print("")
    if FAILS:
        print("%d check(s) FAILED" % len(FAILS))
        return 1
    print("ALL ELEVATION-NEEDED CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
