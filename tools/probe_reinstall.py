# -*- coding: utf-8 -*-
"""Re-install ("覆盖安装") end-to-end probe.

Starts the REAL setup executable, clicks the primary button in the real choice
window, and then checks what actually landed on disk. Two things can go wrong
on an overwrite install and both are invisible from the UI's point of view:

  * the copy of a DLL that Explorer already loaded fails, or
  * DoInstall refuses to start because the target directory already exists.

So this probe compares, for every payload file, the sha256 of the installed
copy with ``dist/`` and prints the tail of %TEMP%\\FileRemarks_log.txt -- the
installer's own account of what it did.

Usage:
    python tools/probe_reinstall.py                 # uses the newest setup exe
    python tools/probe_reinstall.py <setup.exe>
"""
import ctypes
import ctypes.wintypes as wt
import hashlib
import winreg
import os
import re
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(ROOT, "dist")
RELEASES = os.path.join(DIST, "releases")
INSTALL_DIR = os.path.join(os.environ.get("LOCALAPPDATA", ""), "FileRemarks")
LOG = os.path.join(os.environ.get("TEMP", ""), "FileRemarks_log.txt")

# v1.14 and later install into per-version sub-directories
# (%LOCALAPPDATA%\FileRemarks\app-1.14\...), because a property handler that
# Explorer has loaded cannot be overwritten or renamed -- so the probe must ask
# the REGISTRATION where the live copy is instead of assuming the root folder.
HANDLER_CLSID = "{B4C8E6D1-7A2F-4c3b-9D5E-1F6C2A8B3D41}"


def registered_dir():
    sub = "Software\\Classes\\CLSID\\" + HANDLER_CLSID + "\\InprocServer32"
    for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(root, sub) as key:
                dll, _ = winreg.QueryValueEx(key, "")
        except OSError:
            continue
        if dll and os.path.exists(dll):
            return os.path.dirname(dll)
    return None

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

user32.EnumWindows.argtypes = [ctypes.c_void_p, wt.LPARAM]
user32.EnumChildWindows.argtypes = [wt.HWND, ctypes.c_void_p, wt.LPARAM]
user32.GetClassNameW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
user32.SendMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.SendMessageW.restype = wt.LPARAM
user32.PostMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.IsWindow.argtypes = [wt.HWND]

WM_CLOSE = 0x0010
BM_CLICK = 0x00F5
FAILS = []


def check(ok, what, detail=""):
    print("  %s  %s%s" % ("PASS" if ok else "FAIL", what,
                          ("  [%s]" % detail) if detail else ""))
    if not ok:
        FAILS.append(what)
    return ok


def text_of(hwnd):
    buf = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(hwnd, buf, 512)
    return buf.value


def class_of(hwnd):
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def windows(cls=None):
    found = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def cb(hwnd, _):
        if user32.IsWindowVisible(hwnd) and (cls is None or class_of(hwnd) == cls):
            found.append(hwnd)
        return True

    user32.EnumWindows(cb, 0)
    return found


def children(hwnd):
    found = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def cb(child, _):
        found.append(child)
        return True

    user32.EnumChildWindows(hwnd, cb, 0)
    return found


def wait_for(cls, timeout):
    deadline = time.time() + timeout
    while time.time() < deadline:
        hits = windows(cls)
        if hits:
            return hits[0]
        time.sleep(0.1)
    return None


def sha16(path):
    try:
        with open(path, "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()[:16]
    except OSError:
        return "MISSING"


def newest_setup():
    best = None
    for name in os.listdir(RELEASES):
        m = re.match(r"FileRemarks_Setup_v(\d+(?:\.\d+)*)\.exe$", name)
        if not m:
            continue
        key = tuple(int(x) for x in m.group(1).split("."))
        if best is None or key > best[0]:
            best = (key, os.path.join(RELEASES, name))
    return best[1] if best else None


def log_tail(n=14):
    if not os.path.exists(LOG):
        return ["(no log)"]
    raw = open(LOG, "rb").read()
    best = ""
    for enc in ("utf-8", "utf-16-le", "utf-16-be"):
        try:
            t = raw.decode(enc)
        except UnicodeDecodeError:
            continue
        score = sum(1 for ch in t if ch.isascii() and (ch.isprintable() or ch in "\r\n"))
        if len(t) and (not best or score > 0):
            if not best:
                best = t
    lines = [l.rstrip() for l in best.splitlines() if l.strip()]
    return lines[-n:]


def main():
    setup = sys.argv[1] if len(sys.argv) > 1 else newest_setup()
    if not setup or not os.path.exists(setup):
        print("no setup exe found")
        return 2
    print("reinstall probe")
    print("  setup  : %s" % setup)
    print("  target : %s" % INSTALL_DIR)
    print("  installed before: %s" % os.path.isdir(INSTALL_DIR))
    if not os.path.isdir(INSTALL_DIR):
        print("  (nothing installed -> this probe only tests OVERWRITE installs)")
        return 2

    # A sandboxed session cannot write to %LOCALAPPDATA%, so the installer it
    # launches would be refused before doing anything. Say so instead of
    # reporting a product failure: this probe needs a normal desktop session.
    try:
        probe = os.path.join(INSTALL_DIR, "_write_probe.txt")
        with open(probe, "w") as fh:
            fh.write("x")
        os.remove(probe)
        writable = True
    except OSError:
        writable = False
    if not writable:
        print("  SKIP  this session cannot write to %s" % INSTALL_DIR)
        print("        (the sandbox confines writes to the project folder; run this probe")
        print("         from a normal desktop session to exercise a real overwrite install)")
        print("        see tools/test_install_layout.py for the part that can be checked here")
        return 3

    log_before = len(log_tail(200))
    proc = subprocess.Popen([setup])
    hwnd = wait_for("FileRemarksInstallChoice", 20.0)
    if not check(hwnd is not None, "the choice window appeared"):
        proc.kill()
        return 1

    buttons = [(c, text_of(c)) for c in children(hwnd) if class_of(c) == "Button"]
    print("  buttons: %s" % [t for _, t in buttons])
    primary = None
    for child, label in buttons:
        if label in ("安装", "重新安装"):
            primary = child
            break
    if not check(primary is not None, "the 安装/重新安装 button exists"):
        user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
        proc.kill()
        return 1

    print("  clicking '%s' ..." % text_of(primary))
    user32.SendMessageW(primary, BM_CLICK, 0, 0)
    deadline = time.time() + 90
    while time.time() < deadline and proc.poll() is None:
        for w in windows():
            if text_of(w) and ("安装完成" in text_of(w) or "失败" in text_of(w)
                               or "无法" in text_of(w)):
                print("  dialog seen: %s" % text_of(w)[:120])
        time.sleep(0.3)
    rc = proc.poll()
    print("  installer exit code: %s" % rc)

    print("--- %s ---" % os.path.basename(LOG))
    for line in log_tail(16):
        print("   ", line)

    live = registered_dir()
    print("  registered copy : %s" % (live or "(registration not readable)"))
    check(live is not None, "the registration points at an installed directory")

    print("--- installed vs dist ---")
    same = True
    base = live or INSTALL_DIR
    for name in ("FileRemarksPropHandler.dll", "FileRemarksShellExt.dll",
                 "FileRemarksEditor.exe", "FileRemarksHotkey.exe"):
        a = sha16(os.path.join(base, name))
        b = sha16(os.path.join(DIST, name))
        ok = a == b
        same = same and ok
        print("   %-30s installed=%s dist=%s %s"
              % (name, a, b, "SAME" if ok else "DIFF"))
    check(same, "the overwrite install replaced every component with dist/")

    stale = [n for n in os.listdir(INSTALL_DIR) if n.endswith(".old")]
    print("   leftovers: %s" % (stale or "none"))

    print("\n--- verdict ---")
    if FAILS:
        print("  %d check(s) FAILED" % len(FAILS))
        return 1
    print("  ALL REINSTALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
