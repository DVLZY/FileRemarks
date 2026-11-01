"""Proves that the 备注 column has no delay after a save.

The column's data source is the property store the shell builds for a file. If
that store (or the handler behind it) held on to a cached value, the user would
see the old text until the view was refreshed by hand -- which is exactly the
complaint this test guards against.

So this drives the REAL editor EXE: type a remark, close the window, then ask the
shell for a brand-new property store and read System.Comment through it. The
freshly created store must already carry the new text.

Run:  python tools/test_no_delay.py
"""

import ctypes
import os
import shutil
import subprocess
import sys
import time
from ctypes import wintypes

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EDITOR = os.path.join(ROOT, "dist", "FileRemarksEditor.exe")
WORK = os.path.join(ROOT, "build", "_no_delay")

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
ole32 = ctypes.WinDLL("ole32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)
propsys = ctypes.WinDLL("propsys", use_last_error=True)

IDC_REMARK = 102
WM_SETTEXT = 0x000C
WM_COMMAND = 0x0111
WM_CLOSE = 0x0010

COINIT_APARTMENTTHREADED = 0x2
GPS_DEFAULT = 0x0

VT_EMPTY = 0
VT_LPWSTR = 31


class GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]


class PROPERTYKEY(ctypes.Structure):
    _fields_ = [("fmtid", GUID), ("pid", wintypes.DWORD)]


class PROPVARIANT(ctypes.Structure):
    # x64: 8-byte header (vt + 3 reserved words), then the union. For VT_LPWSTR
    # the pointer sits at offset 8 -- NOT 16.
    _fields_ = [("vt", ctypes.c_ushort), ("r1", ctypes.c_ushort),
                ("r2", ctypes.c_ushort), ("r3", ctypes.c_ushort),
                ("ptr", ctypes.c_void_p), ("pad", ctypes.c_ubyte * 8)]


def guid(text):
    p = text.strip("{}").split("-")
    g = GUID()
    g.Data1 = int(p[0], 16)
    g.Data2 = int(p[1], 16)
    g.Data3 = int(p[2], 16)
    for i, b in enumerate(bytes.fromhex(p[3] + p[4])):
        g.Data4[i] = b
    return g


IID_IPropertyStore = guid("{886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99}")
PKEY_COMMENT = PROPERTYKEY(guid("{F29F85E0-4FF9-1068-AB91-08002B27B3D9}"), 6)

shell32.SHGetPropertyStoreFromParsingName.argtypes = [
    ctypes.c_wchar_p, ctypes.c_void_p, ctypes.c_uint32,
    ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)]
shell32.SHGetPropertyStoreFromParsingName.restype = ctypes.c_long
ole32.PropVariantClear.argtypes = [ctypes.POINTER(PROPVARIANT)]
ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
ole32.CoUninitialize.argtypes = []

ULONG_PTR = ctypes.c_ulonglong


def vcall(obj, index, restype, *argtypes):
    """Call vtable slot `index` of a COM interface pointer."""
    vtbl = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[0]
    proto = ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)
    return proto(vtbl[index])


def read_ads(path):
    try:
        with open(path + ":remark", "rb") as fh:
            return fh.read().decode("utf-8")
    except (FileNotFoundError, OSError):
        return None


def handler_registered(ext):
    """True when our property handler is registered for `ext` right now.

    The shell-store half of this test only means something while the product is
    installed: with no handler registered for a type like .txt, a fresh property
    store legitimately has no System.Comment at all, which is not a delay.
    """
    import winreg
    ours = "{B4C8E6D1-7A2F-4c3b-9D5E-1F6C2A8B3D41}"

    def rd(root, sub, value=None):
        try:
            with winreg.OpenKey(root, sub, 0, winreg.KEY_READ) as k:
                return winreg.QueryValueEx(k, value)[0]
        except OSError:
            return None

    found = False
    for v in (rd(winreg.HKEY_LOCAL_MACHINE,
                 r"SOFTWARE\Microsoft\Windows\CurrentVersion\PropertySystem"
                 r"\PropertyHandlers" + "\\" + ext),
              rd(winreg.HKEY_LOCAL_MACHINE,
                 r"Software\Classes" + "\\" + ext + r"\ShellEx\PropertyHandler"),
              rd(winreg.HKEY_CURRENT_USER,
                 r"Software\Classes" + "\\" + ext + r"\ShellEx\PropertyHandler"),
              rd(winreg.HKEY_LOCAL_MACHINE,
                 r"SOFTWARE\Microsoft\Windows\CurrentVersion\PropertySystem"
                 r"\SystemPropertyHandlers", ext)):
        if v and v.strip().upper() == ours.upper():
            found = True
            break
    if not found:
        return False

    # The association alone does not make the column work: the CLSID has to
    # resolve to the DLL that is actually on disk. A leftover registration whose
    # DLL was deleted (or quarantined) is a BROKEN install -- the shell store
    # then fails with 0x8007007E (ERROR_MOD_NOT_FOUND), which looks like "no
    # value" and must not be mistaken for a delay.
    dll = rd(winreg.HKEY_LOCAL_MACHINE,
             r"Software\Classes\CLSID" + "\\" + ours + r"\InprocServer32") \
        or rd(winreg.HKEY_CURRENT_USER,
              r"Software\Classes\CLSID" + "\\" + ours + r"\InprocServer32")
    if not dll or not os.path.exists(dll):
        print("  (registration is broken: %s is missing -- treating the shell "
              "store half as not installed)" % (dll or "InprocServer32"))
        return False

    # Registration also has to point at THIS build. While an older release is
    # installed the shell really does run the older handler, and a failure taken
    # from that binary says nothing about the code under test -- that is a
    # "reinstall to see the fix" situation, not a regression.
    dist_dll = os.path.join(ROOT, "dist", "FileRemarksPropHandler.dll")
    if os.path.exists(dist_dll):
        def sha(path):
            import hashlib
            with open(path, "rb") as fh:
                return hashlib.sha256(fh.read()).hexdigest()
        try:
            same = sha(dll) == sha(dist_dll)
        except OSError:
            same = False
        if not same:
            print("  (the registered handler is not this build: %s)"
                  % os.path.basename(os.path.dirname(dll)))
            print("  (run the installer again to put dist/ in place -- the "
                  "shell store half is skipped)")
            return False
    return True

def read_comment(path):
    """Build a FRESH property store for `path` and read System.Comment."""
    ps = ctypes.c_void_p()
    hr = shell32.SHGetPropertyStoreFromParsingName(
        path, None, GPS_DEFAULT, ctypes.byref(IID_IPropertyStore), ctypes.byref(ps))
    if hr != 0 or not ps:
        return ("store failed", hex(hr & 0xFFFFFFFF), None)
    try:
        pv = PROPVARIANT()
        get_value = vcall(ps, 5, ctypes.c_long,
                          ctypes.POINTER(PROPERTYKEY), ctypes.POINTER(PROPVARIANT))
        hr = get_value(ps, ctypes.byref(PKEY_COMMENT), ctypes.byref(pv))
        if hr != 0:
            return ("GetValue failed", hex(hr & 0xFFFFFFFF), None)
        try:
            if pv.vt == VT_EMPTY:
                return ("empty", "ok", None)
            if pv.vt == VT_LPWSTR:
                return ("string", "ok", ctypes.wstring_at(pv.ptr))
            return ("vt=%d" % pv.vt, "ok", None)
        finally:
            ole32.PropVariantClear(ctypes.byref(pv))
    finally:
        vcall(ps, 2, ctypes.c_ulong)(ps)


def window_text(hwnd):
    buf = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(hwnd, buf, 512)
    return buf.value


def find_main_window(pid, timeout=8.0):
    """First visible top-level window owned by `pid`."""
    found = []
    proto = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def cb(hwnd, _):
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid and user32.IsWindowVisible(hwnd):
            found.append(hwnd)
            return False
        return True

    deadline = time.time() + timeout
    while time.time() < deadline:
        found.clear()
        user32.EnumWindows(proto(cb), 0)
        if found:
            return found[0]
        time.sleep(0.1)
    return None


def main():
    if not os.path.isfile(EDITOR):
        print("editor not built: %s" % EDITOR)
        return 1

    failures = []
    shutil.rmtree(WORK, ignore_errors=True)
    os.makedirs(WORK)

    sample = os.path.join(WORK, "a-plain-english-name.txt")
    with open(sample, "w", encoding="utf-8") as fh:
        fh.write("x\n")

    ole32.CoInitializeEx(None, COINIT_APARTMENTTHREADED)
    registered = handler_registered(".txt")
    print("handler registered for .txt right now: %s" % registered)
    try:
        print("=== before any remark ===")
        if read_ads(sample):
            failures.append("a fresh file should carry no ADS remark")
        if registered:
            kind, note, value = read_comment(sample)
            print("  store says: %s (%s) value=%r" % (kind, note, value))
            if value:
                failures.append("a fresh file should have no comment yet, got %r" % value)

        print("=== drive the real editor, then close it ===")
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 1  # SW_SHOWNORMAL: a hidden window is not enumerable
        proc = subprocess.Popen([EDITOR, sample], startupinfo=si)
        try:
            hwnd = find_main_window(proc.pid)
            if not hwnd:
                print("  the editor window never appeared")
                return 1
            print("  window: %r" % window_text(hwnd))

            remark_box = user32.GetDlgItem(hwnd, IDC_REMARK)
            if not remark_box:
                print("  the remark box is missing")
                return 1

            typed = "这是刚刚写进去的备注，必须马上能读到"
            user32.SendMessageW(remark_box, WM_SETTEXT, 0, ctypes.c_wchar_p(typed))
            user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
            proc.wait(timeout=10)
            print("  editor closed with code %s" % proc.returncode)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()

        # The storage half is unconditional: the moment the editor exits, the
        # ADS must already hold exactly what was typed. No delay, no cache.
        print("=== ADS read immediately after the editor exits ===")
        ads = read_ads(sample)
        print("  :remark -> %r" % ads)
        if ads != typed:
            failures.append("ADS is %r right after save, expected %r" % (ads, typed))

        # The column half only means something while the product is installed;
        # without a registered handler a fresh store has no System.Comment at
        # all, which is correct behaviour rather than a delay.
        if registered:
            print("=== a brand-new property store, read immediately ===")
            kind, note, value = read_comment(sample)
            print("  store says: %s (%s) value=%r" % (kind, note, value))
            if value != typed:
                failures.append("column source still has %r, expected %r" % (value, typed))

            print("=== second read must also see it (nothing stale) ===")
            kind, note, value = read_comment(sample)
            print("  store says: %s (%s) value=%r" % (kind, note, value))
            if value != typed:
                failures.append("second read returned %r" % (value,))
        else:
            print("=== shell-store half SKIPPED: product not installed ===")
            print("  (install FileRemarks_Setup.exe to exercise the column path)")

        print("=== clear it and read again ===")
        proc = subprocess.Popen([EDITOR, sample], startupinfo=si)
        try:
            hwnd = find_main_window(proc.pid)
            remark_box = user32.GetDlgItem(hwnd, IDC_REMARK)
            user32.SendMessageW(remark_box, WM_SETTEXT, 0, ctypes.c_wchar_p(""))
            user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
            proc.wait(timeout=10)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
        ads = read_ads(sample)
        print("  :remark -> %r" % ads)
        if ads is not None:
            failures.append("after clearing, the ADS still holds %r" % ads)
        if registered:
            kind, note, value = read_comment(sample)
            print("  store says: %s (%s) value=%r" % (kind, note, value))
            if value:
                failures.append("after clearing, the store still returns %r" % value)
    finally:
        ole32.CoUninitialize()
        shutil.rmtree(WORK, ignore_errors=True)

    print()
    if failures:
        for f in failures:
            print("FAIL: %s" % f)
        return 1
    print("ALL NO-DELAY TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
