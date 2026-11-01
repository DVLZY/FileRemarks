# -*- coding: utf-8 -*-
"""Check the cue text comes back when the box is emptied with real keystrokes.

test_placeholder.py empties the box with WM_SETTEXT, which repaints everything.
Backspace goes through WM_KEYDOWN, so this probe specifically covers that path:
type two characters, press Backspace twice, and the cue must be visible again.
"""
import ctypes
import os
import sys
import time
from ctypes import byref, c_void_p, c_uint32, c_wchar_p, c_int

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = os.path.join(ROOT, "build", "_cue_return")
IDC_REMARK = 102
WM_CHAR = 0x0102
WM_KEYDOWN = 0x0100
WM_GETTEXT = 0x000D
WM_GETTEXTLENGTH = 0x000E
WM_CLOSE = 0x0010
VK_BACK = 0x08


class STARTUPINFOW(ctypes.Structure):
    _fields_ = [
        ("cb", c_uint32), ("lpReserved", c_wchar_p), ("lpDesktop", c_wchar_p),
        ("lpTitle", c_wchar_p), ("dwX", c_uint32), ("dwY", c_uint32),
        ("dwXSize", c_uint32), ("dwYSize", c_uint32),
        ("dwXCountChars", c_uint32), ("dwYCountChars", c_uint32),
        ("dwFillAttribute", c_uint32), ("dwFlags", c_uint32),
        ("wShowWindow", ctypes.c_uint16), ("cbReserved2", ctypes.c_uint16),
        ("lpReserved2", c_void_p), ("hStdInput", c_void_p),
        ("hStdOutput", c_void_p), ("hStdError", c_void_p)]


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [("hProcess", c_void_p), ("hThread", c_void_p),
                ("dwProcessId", c_uint32), ("dwThreadId", c_uint32)]


class RECT(ctypes.Structure):
    _fields_ = [("left", c_int), ("top", c_int),
                ("right", c_int), ("bottom", c_int)]


kernel32.CreateProcessW.argtypes = [
    c_wchar_p, c_wchar_p, c_void_p, c_void_p, c_int, c_uint32, c_void_p,
    c_wchar_p, ctypes.POINTER(STARTUPINFOW), ctypes.POINTER(PROCESS_INFORMATION)]
kernel32.CreateProcessW.restype = c_int
kernel32.CloseHandle.argtypes = [c_void_p]
kernel32.TerminateProcess.argtypes = [c_void_p, c_uint32]
user32.GetWindowThreadProcessId.argtypes = [c_void_p, ctypes.POINTER(c_uint32)]
user32.GetDlgItem.argtypes = [c_void_p, c_int]
user32.GetDlgItem.restype = c_void_p
user32.SendMessageW.argtypes = [c_void_p, c_uint32, c_void_p, c_void_p]
user32.SendMessageW.restype = ctypes.c_ssize_t
user32.PostMessageW.argtypes = [c_void_p, c_uint32, c_void_p, c_void_p]
user32.GetClientRect.argtypes = [c_void_p, ctypes.POINTER(RECT)]
user32.GetDC.argtypes = [c_void_p]
user32.GetDC.restype = c_void_p
user32.ReleaseDC.argtypes = [c_void_p, c_void_p]
user32.RedrawWindow.argtypes = [c_void_p, c_void_p, c_void_p, c_uint32]
user32.EnumWindows.argtypes = [ctypes.WINFUNCTYPE(c_int, c_void_p, c_void_p),
                               c_void_p]
gdi32.GetPixel.argtypes = [c_void_p, c_int, c_int]
gdi32.GetPixel.restype = c_uint32

ENUM_CB = ctypes.WINFUNCTYPE(c_int, c_void_p, c_void_p)


def windows_of_pid(pid):
    out = []

    def cb(hwnd, _lp):
        p = c_uint32()
        user32.GetWindowThreadProcessId(hwnd, byref(p))
        if p.value == pid:
            out.append(hwnd)
        return 1

    user32.EnumWindows(ENUM_CB(cb), None)
    return out


def launch(path):
    si = STARTUPINFOW()
    si.cb = ctypes.sizeof(si)
    si.dwFlags = 1
    si.wShowWindow = 1
    pi = PROCESS_INFORMATION()
    cmd = u'"%s" "%s"' % (os.path.join(ROOT, "dist", "FileRemarksEditor.exe"), path)
    if not kernel32.CreateProcessW(None, cmd, None, None, 0, 0, None, None,
                                   byref(si), byref(pi)):
        raise ctypes.WinError()
    return pi


def wait_window(pid, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        for h in windows_of_pid(pid):
            if user32.IsWindowVisible(h):
                return h
        time.sleep(0.1)
    return None


def get_text(hwnd):
    n = user32.SendMessageW(hwnd, WM_GETTEXTLENGTH, None, None)
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.SendMessageW(hwnd, WM_GETTEXT, n + 1, ctypes.cast(buf, c_void_p))
    return buf.value


def ink(hwnd):
    r = RECT()
    user32.GetClientRect(hwnd, byref(r))
    user32.RedrawWindow(hwnd, None, None, 0x0001 | 0x0100 | 0x0080)
    time.sleep(0.15)
    hdc = user32.GetDC(hwnd)
    n = 0
    for y in range(0, r.bottom, 2):
        for x in range(0, r.right, 2):
            c = gdi32.GetPixel(hdc, x, y)
            if not ((c & 0xFF) > 250 and ((c >> 8) & 0xFF) > 250
                    and ((c >> 16) & 0xFF) > 250):
                n += 1
    user32.ReleaseDC(hwnd, hdc)
    return n


def main():
    os.makedirs(WORK, exist_ok=True)
    target = os.path.join(WORK, "提示语回来测试.txt")
    with open(target, "w", encoding="utf-8") as f:
        f.write("probe\n")
    try:
        os.remove(target + ":remark")
    except OSError:
        pass

    failures = []
    pi = launch(target)
    try:
        hwnd = wait_window(pi.dwProcessId)
        if not hwnd:
            print("FAIL: editor window did not appear")
            return 1
        box = user32.GetDlgItem(hwnd, IDC_REMARK)
        if not box:
            print("FAIL: remark control not found")
            return 1

        empty_ink = ink(box)
        print("empty            ink=%d text=%r" % (empty_ink, get_text(box)))

        for ch in u"ab":
            user32.SendMessageW(box, WM_CHAR, c_void_p(ord(ch)), c_void_p(1))
            time.sleep(0.05)
        time.sleep(0.2)
        typed_ink = ink(box)
        print("typed 'ab'       ink=%d text=%r" % (typed_ink, get_text(box)))
        if get_text(box) != u"ab":
            failures.append("typing produced %r, expected 'ab'" % get_text(box))

        for _ in range(2):
            user32.SendMessageW(box, WM_KEYDOWN, c_void_p(VK_BACK), c_void_p(1))
            user32.SendMessageW(box, WM_CHAR, c_void_p(VK_BACK), c_void_p(1))
            time.sleep(0.05)
        time.sleep(0.25)
        back_ink = ink(box)
        print("after 2x Backsp   ink=%d text=%r" % (back_ink, get_text(box)))
        if get_text(box) != u"":
            failures.append("box is not empty after two Backspaces: %r"
                            % get_text(box))
        if back_ink < empty_ink * 0.8:
            failures.append("cue did not come back after Backspace "
                            "(ink %d, was %d when empty)"
                            % (back_ink, empty_ink))

        user32.PostMessageW(hwnd, WM_CLOSE, None, None)
        time.sleep(0.6)
    finally:
        kernel32.TerminateProcess(pi.hProcess, 0)
        kernel32.CloseHandle(pi.hProcess)
        kernel32.CloseHandle(pi.hThread)

    print()
    if failures:
        print("FAILURES:")
        for f in failures:
            print("  - %s" % f)
        return 1
    print("CUE RETURN PROBE PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
