"""Diagnostic probe: does the read-only path EDIT control fit its own text?

The editor sizes the path control from a DT_CALCRECT measurement made with a
plain DC.  An EDIT control wraps with its own algorithm (and its own internal
margins), so the two can disagree by a line -- which clips the tail of a long
path.  This probe compares the control's idea of its height with the height it
was actually given.
"""

import ctypes
import os
import subprocess
import time
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = os.path.join(ROOT, "build", "_probe_path_wrap")
IDC_FILENAME = 101

EM_GETLINECOUNT = 0x00BA
WM_GETFONT = 0x0031


class RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


class TEXTMETRICW(ctypes.Structure):
    _fields_ = [("tmHeight", ctypes.c_long), ("tmAscent", ctypes.c_long),
                ("tmDescent", ctypes.c_long), ("tmInternalLeading", ctypes.c_long),
                ("tmExternalLeading", ctypes.c_long), ("tmAveCharWidth", ctypes.c_long),
                ("tmMaxCharWidth", ctypes.c_long), ("tmWeight", ctypes.c_long),
                ("tmOverhang", ctypes.c_long), ("tmDigitizedAspectX", ctypes.c_long),
                ("tmDigitizedAspectY", ctypes.c_long), ("tmFirstChar", ctypes.c_wchar),
                ("tmLastChar", ctypes.c_wchar), ("tmDefaultChar", ctypes.c_wchar),
                ("tmBreakChar", ctypes.c_wchar), ("tmItalic", ctypes.c_byte),
                ("tmUnderlined", ctypes.c_byte), ("tmStruckOut", ctypes.c_byte),
                ("tmPitchAndFamily", ctypes.c_byte), ("tmCharSet", ctypes.c_byte)]


def make_path(name_len):
    d = WORK
    for i in range(4):
        d = os.path.join(d, "很长的目录名称_%02d" % i)
    os.makedirs(d, exist_ok=True)
    name = "a_very_long_english_file_name_to_force_wrapping_" + "x" * name_len + ".txt"
    p = os.path.join(d, name)
    with open(p, "w", encoding="utf-8") as f:
        f.write("x")
    return p


def find_window(pid, timeout=8.0):
    end = time.time() + timeout
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, lparam):
        wpid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(wpid))
        if wpid.value == pid and user32.IsWindowVisible(hwnd):
            cls = ctypes.create_unicode_buffer(64)
            user32.GetClassNameW(hwnd, cls, 64)
            if cls.value == "FileRemarksEditorWnd":
                found.append(hwnd)
                return False
        return True

    while time.time() < end:
        found.clear()
        user32.EnumWindows(cb, 0)
        if found:
            return found[0]
        time.sleep(0.1)
    return None


def main():
    path = make_path(40)
    print("path length: %d chars" % len(path))
    exe = os.path.join(ROOT, "dist", "FileRemarksEditor.exe")
    pi = subprocess.Popen('"%s" "%s"' % (exe, path), shell=False)
    try:
        hwnd = find_window(pi.pid)
        if not hwnd:
            print("no window")
            return 1
        time.sleep(0.4)
        box = user32.GetDlgItem(hwnd, IDC_FILENAME)
        if not box:
            print("no path control")
            return 1
        r = RECT()
        user32.GetClientRect(box, ctypes.byref(r))
        got_h = r.bottom
        lines = user32.SendMessageW(box, EM_GETLINECOUNT, 0, 0)
        font = user32.SendMessageW(box, WM_GETFONT, 0, 0)
        hdc = user32.GetDC(box)
        old = gdi32.SelectObject(hdc, font)
        tm = TEXTMETRICW()
        gdi32.GetTextMetricsW(hdc, ctypes.byref(tm))
        gdi32.SelectObject(hdc, old)
        user32.ReleaseDC(box, hdc)
        need = lines * tm.tmHeight
        print("control text      : %r" % (user32.SendMessageW(box, 0x000D, 0, 0),))
        print("lines reported    : %d" % lines)
        print("line height       : %d px" % tm.tmHeight)
        print("height it needs   : %d px" % need)
        print("height it was given: %d px" % got_h)
        print("fits              : %s" % ("YES" if got_h >= need else "NO -- clipped"))
        return 0 if got_h >= need else 2
    finally:
        pi.terminate()


if __name__ == "__main__":
    raise SystemExit(main())
