# -*- coding: utf-8 -*-
"""Check the editor window sizes itself around the file path it is given.

The editor measures the wrapped path before the window is created and grows the
file card (and therefore the window) to fit. This test proves that behaviour on
the real dist/FileRemarksEditor.exe:

  1. a short path gives a compact window;
  2. a much longer path gives a TALLER window, and the path control itself is
     taller than one line -- i.e. the path wrapped instead of being clipped;
  3. everything the user must see (path, remark box, status line) lies fully
     inside the client area, so no control is cut off by the frame.
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
WORK = os.path.join(ROOT, "build", "_editor_layout_test")

IDC_FILENAME = 101
IDC_REMARK = 102
IDC_STATUS = 103


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


class TEXTMETRICW(ctypes.Structure):
    _fields_ = [("tmHeight", c_int), ("tmAscent", c_int), ("tmDescent", c_int),
                ("tmInternalLeading", c_int), ("tmExternalLeading", c_int),
                ("tmAveCharWidth", c_int), ("tmMaxCharWidth", c_int),
                ("tmWeight", c_int), ("tmOverhang", c_int),
                ("tmDigitizedAspectX", c_int), ("tmDigitizedAspectY", c_int),
                ("tmFirstChar", ctypes.c_wchar), ("tmLastChar", ctypes.c_wchar),
                ("tmDefaultChar", ctypes.c_wchar), ("tmBreakChar", ctypes.c_wchar),
                ("tmItalic", ctypes.c_ubyte), ("tmUnderlined", ctypes.c_ubyte),
                ("tmStruckOut", ctypes.c_ubyte), ("tmPitchAndFamily", ctypes.c_ubyte),
                ("tmCharSet", ctypes.c_ubyte)]


WM_GETFONT = 0x0031


kernel32.CreateProcessW.argtypes = [
    c_wchar_p, c_wchar_p, c_void_p, c_void_p, c_int, c_uint32, c_void_p,
    c_wchar_p, ctypes.POINTER(STARTUPINFOW), ctypes.POINTER(PROCESS_INFORMATION)]
kernel32.CreateProcessW.restype = c_int
kernel32.CloseHandle.argtypes = [c_void_p]
kernel32.TerminateProcess.argtypes = [c_void_p, c_uint32]

user32.GetWindowThreadProcessId.argtypes = [c_void_p, ctypes.POINTER(c_uint32)]
user32.IsWindowVisible.argtypes = [c_void_p]
user32.GetWindowTextW.argtypes = [c_void_p, c_wchar_p, c_int]
user32.GetWindowTextW.restype = c_int
user32.GetDlgItem.argtypes = [c_void_p, c_int]
user32.GetDlgItem.restype = c_void_p
user32.SendMessageW.argtypes = [c_void_p, c_uint32, c_void_p, c_void_p]
user32.SendMessageW.restype = ctypes.c_ssize_t
user32.PostMessageW.argtypes = [c_void_p, c_uint32, c_void_p, c_void_p]
user32.PostMessageW.restype = c_int
user32.GetClientRect.argtypes = [c_void_p, ctypes.POINTER(RECT)]
user32.GetClientRect.restype = c_int
user32.GetWindowRect.argtypes = [c_void_p, ctypes.POINTER(RECT)]
user32.GetWindowRect.restype = c_int
user32.MapWindowPoints.argtypes = [c_void_p, c_void_p, ctypes.POINTER(RECT), c_uint32]
user32.MapWindowPoints.restype = c_int
# GetDC/ReleaseDC and the text metrics live in gdi32/user32 as noted below.
user32.GetDC.argtypes = [c_void_p]
user32.GetDC.restype = c_void_p
user32.ReleaseDC.argtypes = [c_void_p, c_void_p]
gdi32.SelectObject.argtypes = [c_void_p, c_void_p]
gdi32.SelectObject.restype = c_void_p
gdi32.GetTextMetricsW.argtypes = [c_void_p, ctypes.POINTER(TEXTMETRICW)]
gdi32.GetTextMetricsW.restype = c_int

WM_CLOSE = 0x0010
ENUM_CB = ctypes.WINFUNCTYPE(c_int, c_void_p, c_void_p)


def windows_of_pid(pid):
    found = []

    def cb(hwnd, lparam):
        p = c_uint32()
        user32.GetWindowThreadProcessId(hwnd, byref(p))
        if p.value == pid:
            found.append(hwnd)
        return 1

    user32.EnumWindows(ENUM_CB(cb), None)
    return found


def window_text(hwnd):
    buf = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(hwnd, buf, 512)
    return buf.value


def client_rect(hwnd):
    r = RECT()
    user32.GetClientRect(hwnd, byref(r))
    return r


def child_rect(hwnd, child):
    """Child rectangle in the parent's client coordinates."""
    r = RECT()
    user32.GetWindowRect(child, byref(r))
    user32.MapWindowPoints(None, hwnd, byref(r), 2)
    return r


# EM_* messages used to ask a multiline EDIT how much text it has and how much
# room it was given -- the only way to prove nothing is clipped.
EM_GETLINECOUNT = 0x00BA
EM_GETRECT = 0x00B2


def line_fit(path_box):
    """How many lines the path needs vs how many the control can display.

    Returns (needed, capacity). needed > capacity means the last lines are cut
    off -- exactly the bug this test guards against.
    """
    needed = user32.SendMessageW(path_box, EM_GETLINECOUNT, None, None)
    fr = RECT()
    user32.SendMessageW(path_box, EM_GETRECT, None, ctypes.cast(byref(fr), c_void_p))
    text_h = fr.bottom - fr.top
    # The path control uses the small font; one line of it is ~17 px at 96 DPI.
    # Derive the line height from the control's own font metrics instead of
    # hard-coding it, by measuring a known one-line box the same way.
    hdc = user32.GetDC(path_box)
    tm = TEXTMETRICW()
    old = gdi32.SelectObject(hdc, user32.SendMessageW(
        path_box, WM_GETFONT, None, None))
    gdi32.GetTextMetricsW(hdc, byref(tm))
    gdi32.SelectObject(hdc, old)
    user32.ReleaseDC(path_box, hdc)
    line_h = tm.tmHeight if tm.tmHeight > 0 else 17
    capacity = text_h // line_h if line_h else 0
    return needed, capacity


def launch(path):
    exe = os.path.join(ROOT, "dist", "FileRemarksEditor.exe")
    cmd = '"%s" "%s"' % (exe, path)
    si = STARTUPINFOW()
    si.cb = ctypes.sizeof(si)
    pi = PROCESS_INFORMATION()
    ok = kernel32.CreateProcessW(None, cmd, None, None, 0, 0, None, None,
                                 byref(si), byref(pi))
    if not ok:
        raise RuntimeError("CreateProcessW failed: %d" % ctypes.get_last_error())
    return pi


def kill(pi):
    kernel32.TerminateProcess(pi.hProcess, 0)
    kernel32.CloseHandle(pi.hThread)
    kernel32.CloseHandle(pi.hProcess)


def wait_for_main_window(pid, timeout=8.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        for hwnd in windows_of_pid(pid):
            if user32.IsWindowVisible(hwnd) and window_text(hwnd).strip():
                return hwnd
        time.sleep(0.1)
    return None


def probe(path, label, failures):
    """Open the editor on `path` and report its measured geometry."""
    pi = launch(path)
    try:
        hwnd = wait_for_main_window(pi.dwProcessId)
        if not hwnd:
            failures.append("%s: the editor window never appeared" % label)
            return None
        client = client_rect(hwnd)
        path_box = user32.GetDlgItem(hwnd, IDC_FILENAME)
        remark = user32.GetDlgItem(hwnd, IDC_REMARK)
        status = user32.GetDlgItem(hwnd, IDC_STATUS)
        if not (path_box and remark and status):
            failures.append("%s: a control is missing" % label)
            return None
        boxes = {
            "path": child_rect(hwnd, path_box),
            "remark": child_rect(hwnd, remark),
            "status": child_rect(hwnd, status),
        }
        needed, capacity = line_fit(path_box)
        print("  %-8s client=%dx%d  pathH=%d remarkH=%d statusBottom=%d"
              % (label, client.right, client.bottom, 
                 boxes["path"].bottom - boxes["path"].top,
                 boxes["remark"].bottom - boxes["remark"].top,
                 boxes["status"].bottom))
        print("  %-8s path lines needed=%d capacity=%d" % (label, needed, capacity))
        # The one thing the user complained about: the file name must be shown in
        # full. If the control wrapped into more lines than it has room for, the
        # tail of the path is invisible.
        if needed > capacity:
            failures.append("%s: the path needs %d lines but the control only "
                            "shows %d -- the name is clipped"
                            % (label, needed, capacity))
        return client, boxes, needed
    finally:
        for h in windows_of_pid(pi.dwProcessId):
            user32.PostMessageW(h, WM_CLOSE, None, None)
        time.sleep(0.3)
        kill(pi)


def main():
    os.makedirs(WORK, exist_ok=True)

    short = os.path.join(WORK, "短名字.txt")
    with open(short, "wb") as f:
        f.write(b"x\n")

    # Deep enough that the path cannot possibly fit on one line in a 464px
    # dialog, but still under the 260-char MAX_PATH so the file can be created.
    deep = WORK
    for i in range(3):
        deep = os.path.join(deep, "目录%02d_%s" % (i, "abcdefghijklmnop" * 1))
    os.makedirs(deep, exist_ok=True)
    long_path = os.path.join(deep, "很长很长的一个文件名用来测试换行显示效果.txt")
    with open(long_path, "wb") as f:
        f.write(b"x\n")

    failures = []
    print("=== short path ===")
    a = probe(short, "short", failures)
    print("=== long path (%d chars) ===" % len(long_path))
    b = probe(long_path, "long", failures)

    if not a or not b:
        for f in failures:
            print("  - " + f)
        return 1

    (short_client, short_boxes, short_lines) = a
    (long_client, long_boxes, long_lines) = b

    # The window must be exactly as wide as the frozen client width at 96 DPI
    # (464), and the long path must not have made it wider -- it wraps instead.
    if short_client.right != long_client.right:
        failures.append("client width changed between short and long path: %d vs %d"
                        % (short_client.right, long_client.right))

    # A wrapped path makes the path control (and hence the window) taller. Both
    # paths here are absolute, so even the short one may wrap once; what matters
    # is that the much longer one wraps MORE. The line counts come from the edit
    # control itself (EM_GETLINECOUNT), so this does not depend on guessing a
    # font height from pixel sizes.
    short_path_h = short_boxes["path"].bottom - short_boxes["path"].top
    long_path_h = long_boxes["path"].bottom - long_boxes["path"].top
    print("  path control: short=%dpx/%d lines, long=%dpx/%d lines"
          % (short_path_h, short_lines, long_path_h, long_lines))
    if long_lines <= short_lines:
        failures.append("the long path reports %d lines vs %d for the short one "
                        "-- the control is not wrapping it" % (long_lines, short_lines))
    if long_client.bottom <= short_client.bottom:
        failures.append("the window did not grow for the long path "
                        "(%d vs %d)" % (long_client.bottom, short_client.bottom))

    # Nothing may stick out of the client area, for either size.
    for label, (client, boxes, _lines) in (("short", a), ("long", b)):
        for name, r in boxes.items():
            if r.left < 0 or r.top < 0 or r.right > client.right or r.bottom > client.bottom:
                failures.append("%s: the %s control (%d,%d,%d,%d) is outside the "
                                "client area (%d,%d)"
                                % (label, name, r.left, r.top, r.right, r.bottom,
                                   client.right, client.bottom))

    # The minimal layout: the path sits immediately to the right of the logo at
    # the very top of the window -- there is no "文件" label row above it and no
    # left-hand column reserved for one. 16+14 px of padding + a 24 px logo + 10 px
    # gap puts its left edge near x=64 at 96 DPI; a label row would push the top
    # down past 44.
    for label, (client, boxes, _lines) in (("short", a), ("long", b)):
        pr = boxes["path"]
        print("  %s path control at (%d,%d)" % (label, pr.left, pr.top))
        if pr.left > 80:
            failures.append("%s: the path starts at x=%d -- a label column is "
                            "still reserved to its left" % (label, pr.left))
        if pr.top > 40:
            failures.append("%s: the path starts at y=%d -- a label row is still "
                            "drawn above it" % (label, pr.top))

    # The status line must still be the last thing in the window, i.e. the
    # window is not taller than its content (no band of empty page).
    (client, boxes, _lines) = b
    gap = client.bottom - boxes["status"].bottom
    print("  empty space below the status line: %d px" % gap)
    if gap > 24:
        failures.append("the window leaves %d px of empty page below the status "
                        "line -- the measured height was not used" % gap)

    print("")
    if failures:
        print("FAILURES:")
        for f in failures:
            print("  - " + f)
        return 1
    print("ALL EDITOR LAYOUT TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
