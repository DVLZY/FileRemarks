# -*- coding: utf-8 -*-
"""Probe: does the cue text really disappear, or does it stay painted behind
the typed text?

Typing one short character only repaints the small rectangle around it (that is
how the EDIT control optimises), so a cue painted across the whole first line
can survive to the right of the character. This probe types "a" and then counts
inked pixels in the *right* part of the box, where the character cannot reach but
the cue does.
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
WORK = os.path.join(ROOT, "build", "_overlap_test")
IDC_REMARK = 102


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
user32.EnumWindows.argtypes = [ctypes.WINFUNCTYPE(c_int, c_void_p, c_void_p), c_void_p]
gdi32.GetPixel.argtypes = [c_void_p, c_int, c_int]
gdi32.GetPixel.restype = c_uint32

ENUM_CB = ctypes.WINFUNCTYPE(c_int, c_void_p, c_void_p)


def windows_of_pid(pid):
    out = []

    def cb(hwnd, _lp):
        p = c_uint32()
        user32.GetWindowThreadProcessId(hwnd, byref(p))
        if p.value == pid and user32.IsWindowVisible(hwnd):
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
        w = windows_of_pid(pid)
        if w:
            return w[0]
        time.sleep(0.1)
    return None


def ink_columns(hwnd):
    """Inked pixels per 20px column band, sampled in-process over the whole box."""
    r = RECT()
    user32.GetClientRect(hwnd, byref(r))
    time.sleep(0.25)
    hdc = user32.GetDC(hwnd)
    bands = {}
    for y in range(0, r.bottom, 2):
        for x in range(0, r.right, 2):
            c = gdi32.GetPixel(hdc, x, y)
            rr, gg, bb = c & 0xFF, (c >> 8) & 0xFF, (c >> 16) & 0xFF
            if not (rr > 250 and gg > 250 and bb > 250):
                bands[x // 20] = bands.get(x // 20, 0) + 1
    user32.ReleaseDC(hwnd, hdc)
    return r.right, r.bottom, bands


def set_text(box, s):
    user32.SendMessageW(box, 0x000C, None,
                        ctypes.cast(c_wchar_p(s), c_void_p))
    time.sleep(0.25)


def type_chars(box, s):
    """Type through WM_CHAR, the way a real keystroke arrives.

    This matters: WM_SETTEXT repaints the whole control, so it hides the bug.
    A real keystroke only invalidates the rectangle around the inserted
    character, which is exactly the case where leftover cue text can survive.
    """
    for ch in s:
        user32.SendMessageW(box, 0x0102, ord(ch), 0x00000001)  # WM_CHAR
        time.sleep(0.05)
    time.sleep(0.3)


def get_text(box):
    n = user32.SendMessageW(box, 0x000E, None, None)
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.SendMessageW(box, 0x000D, n + 1, ctypes.cast(buf, c_void_p))
    return buf.value


def main():
    os.makedirs(WORK, exist_ok=True)
    target = os.path.join(WORK, "重叠测试.txt")
    open(target, "w", encoding="utf-8").write("x\n")
    try:
        os.remove(target + ":remark")
    except OSError:
        pass

    pi = launch(target)
    try:
        hwnd = wait_window(pi.dwProcessId)
        if not hwnd:
            print("FAIL: no window")
            return 1
        box = user32.GetDlgItem(hwnd, IDC_REMARK)
        if not box:
            print("FAIL: no remark control")
            return 1

        w, h, empty_bands = ink_columns(box)
        print("box %dx%d" % (w, h))
        print("empty   bands:", sorted(empty_bands.items()))

        type_chars(box, u"a")
        print("text after typing 'a': %r" % get_text(box))
        _w, _h, one_bands = ink_columns(box)
        print("typed 'a' bands:", sorted(one_bands.items()))

        # Every band that had ink when the box was empty, beyond the first two
        # 20px bands, can only be leftover cue text: one character is ~8px wide.
        leftover = {b: n for b, n in one_bands.items() if b >= 3}
        print("bands past the typed character:", sorted(leftover.items()))
        if leftover:
            print("  -> CUE TEXT IS STILL PAINTED (overlapping)")
        else:
            print("  -> cue text is gone (no overlap)")

        user32.PostMessageW(hwnd, 0x0010, None, None)
        time.sleep(0.5)
    finally:
        kernel32.TerminateProcess(pi.hProcess, 0)
    return 0


if __name__ == "__main__":
    sys.exit(main())
