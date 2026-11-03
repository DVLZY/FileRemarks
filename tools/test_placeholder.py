# -*- coding: utf-8 -*-
"""Check that an empty remark box really shows the cue text "在这输入备注...".

The cue is only painted (never stored), so the only honest way to check it is to
look at the pixels: count non-white pixels inside the remark control while it is
empty, then repeat after typing real text and after clearing it again. A working
placeholder inks the box when empty, and the typed text must never contain the
cue -- that is what proves the cue is painted and not stored.
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
WORK = os.path.join(ROOT, "build", "_placeholder_test")

IDC_REMARK = 102
WM_SETTEXT = 0x000C
WM_GETTEXT = 0x000D
WM_CLOSE = 0x0010
WM_CHAR = 0x0102
WM_KEYDOWN = 0x0100
WM_SETTEXT = 0x000C
EM_SETSEL = 0x00B1
EM_GETLINECOUNT = 0x00BA
EM_GETFIRSTVISIBLELINE = 0x00CE
EM_SCROLLCARET = 0x00B7
GWL_STYLE = -16
WS_VSCROLL = 0x00200000
VK_BACK = 0x08
SW_SHOWNORMAL = 1


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
user32.GetWindowLongPtrW.argtypes = [c_void_p, c_int]
user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
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
    si.wShowWindow = SW_SHOWNORMAL
    pi = PROCESS_INFORMATION()
    cmd = u'"%s" "%s"' % (os.path.join(ROOT, "dist", "FileRemarksEditor.exe"), path)
    ok = kernel32.CreateProcessW(None, cmd, None, None, 0, 0, None, None,
                                 byref(si), byref(pi))
    if not ok:
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
    n = user32.SendMessageW(hwnd, WM_GETTEXT + 1, None, None)  # WM_GETTEXTLENGTH
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.SendMessageW(hwnd, WM_GETTEXT, n + 1, ctypes.cast(buf, c_void_p))
    return buf.value


def ink(hwnd):
    """Count non-white pixels in a control, and return (count, w, h)."""
    r = RECT()
    user32.GetClientRect(hwnd, byref(r))
    user32.RedrawWindow(hwnd, None, None, 0x0001 | 0x0100 | 0x0080)
    time.sleep(0.15)
    hdc = user32.GetDC(hwnd)
    n = 0
    for y in range(0, r.bottom, 2):
        for x in range(0, r.right, 2):
            c = gdi32.GetPixel(hdc, x, y)
            rr = c & 0xFF
            gg = (c >> 8) & 0xFF
            bb = (c >> 16) & 0xFF
            if not (rr > 250 and gg > 250 and bb > 250):
                n += 1
    user32.ReleaseDC(hwnd, hdc)
    return n, r.right, r.bottom


def ink_columns(hwnd, band=20):
    """Count non-white pixels per `band`-wide column strip.

    One typed character is only ~8 px wide, so ink showing up several bands to
    the right of it can only be cue text that was left behind on screen.
    """
    r = RECT()
    user32.GetClientRect(hwnd, byref(r))
    user32.RedrawWindow(hwnd, None, None, 0x0001 | 0x0100 | 0x0080)
    time.sleep(0.15)
    hdc = user32.GetDC(hwnd)
    counts = {}
    for y in range(0, r.bottom, 2):
        for x in range(0, r.right, 2):
            c = gdi32.GetPixel(hdc, x, y)
            if not ((c & 0xFF) > 250 and ((c >> 8) & 0xFF) > 250
                    and ((c >> 16) & 0xFF) > 250):
                counts[x // band] = counts.get(x // band, 0) + 1
    user32.ReleaseDC(hwnd, hdc)
    return sorted(counts.items())


def type_chars(box, text):
    """Type through WM_CHAR, i.e. the same path a real keystroke takes."""
    for ch in text:
        user32.SendMessageW(box, WM_CHAR, c_void_p(ord(ch)), c_void_p(1))
        time.sleep(0.05)


def main():
    os.makedirs(WORK, exist_ok=True)
    target = os.path.join(WORK, "空的备注测试文件.txt")
    with open(target, "w", encoding="utf-8") as f:
        f.write("probe\n")
    # Make sure the remark is empty so the cue must appear.
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

        text = get_text(box)
        empty_ink, w, h = ink(box)
        print("=== empty box ===")
        print("  stored text: %r" % text)
        print("  control size: %dx%d" % (w, h))
        print("  non-white pixels: %d" % empty_ink)
        if text != "":
            failures.append("box should start empty, got %r" % text)
        if empty_ink < 30:
            failures.append("no cue text painted in the empty box (%d inked "
                            "pixels); the placeholder is missing" % empty_ink)

        # Type real text: the cue must be gone and must NOT be part of the value.
        user32.SendMessageW(box, WM_SETTEXT, None,
                            ctypes.cast(ctypes.c_wchar_p(u"这里是我自己写的备注"), c_void_p))
        time.sleep(0.2)
        typed = get_text(box)
        filled_ink, _, _ = ink(box)
        print("=== filled box ===")
        print("  stored text: %r" % typed)
        print("  non-white pixels: %d" % filled_ink)
        if typed != u"这里是我自己写的备注":
            failures.append("typed text came back as %r" % typed)
        if u"在这输入备注" in typed:
            failures.append("the cue text leaked into the control's value")

        # Clearing again must bring the cue back.
        user32.SendMessageW(box, WM_SETTEXT, None,
                            ctypes.cast(ctypes.c_wchar_p(u""), c_void_p))
        time.sleep(0.2)
        again_ink, _, _ = ink(box)
        print("=== cleared box ===")
        print("  non-white pixels: %d" % again_ink)
        if again_ink < 30:
            failures.append("clearing the box did not bring the cue back "
                            "(%d inked pixels)" % again_ink)

        # Real keystrokes: the cue must be wiped, not left lying under the text.
        # WM_SETTEXT above repaints the whole control anyway, so it can never
        # catch this; only WM_CHAR takes the path that exposes stale cue pixels.
        empty_cols = ink_columns(box)
        type_chars(box, u"a")
        time.sleep(0.2)
        typed_now = get_text(box)
        typed_cols = dict(ink_columns(box))
        # One character is ~8 px wide, so anything beyond the first 20 px band
        # can only be cue text that was not erased.
        leftover = sorted(c for c in typed_cols if c > 0)
        print("=== real keystroke ===")
        print("  stored text: %r" % typed_now)
        print("  empty   bands: %s" % empty_cols)
        print("  typed   bands: %s" % sorted(typed_cols.items()))
        print("  bands still inked past the character: %s" % leftover)
        if typed_now != u"a":
            failures.append("a single keystroke produced %r, expected 'a'"
                            % typed_now)
        if leftover:
            failures.append("cue text is still painted after the first keystroke "
                            "(ink in bands %s); the hint overlaps the typed text"
                            % leftover)

        # And deleting the last character again must bring the cue back, all via
        # the keystroke path.
        user32.SendMessageW(box, WM_KEYDOWN, c_void_p(VK_BACK), c_void_p(1))
        user32.SendMessageW(box, WM_CHAR, c_void_p(VK_BACK), c_void_p(1))
        time.sleep(0.25)
        back_text = get_text(box)
        back_ink, _, _ = ink(box)
        print("=== after Backspace ===")
        print("  stored text: %r" % back_text)
        print("  non-white pixels: %d (empty box was %d)" % (back_ink, empty_ink))
        if back_text != u"":
            failures.append("Backspace left %r in the box" % back_text)
        if back_ink < empty_ink * 0.8:
            failures.append("cue did not come back after the box was emptied with "
                            "Backspace (%d vs %d pixels)" % (back_ink, empty_ink))

        # --- no scrollbar, but the caret still scrolls into view ------------
        # The vertical scrollbar was removed on request. A multiline EDIT keeps
        # the caret visible by scrolling its own contents, which is what makes
        # that acceptable -- prove it here rather than assuming it.
        print("=== no scrollbar, caret still scrolls ===")
        style = user32.GetWindowLongPtrW(box, GWL_STYLE)
        print("  remark box style: 0x%08x" % style)
        if style & WS_VSCROLL:
            failures.append("the remark box still asks for a vertical scrollbar")

        many = "\r\n".join("第 %02d 行的备注内容" % i for i in range(1, 41))
        user32.SendMessageW(box, WM_SETTEXT, None,
                            ctypes.cast(c_wchar_p(many), c_void_p))
        user32.SendMessageW(box, EM_SETSEL, c_void_p(0x7FFFFFFF), c_void_p(0x7FFFFFFF))
        # EM_SETSEL only moves the caret; EM_SCROLLCARET is what brings it
        # into view, and it is what an insertion does implicitly.
        user32.SendMessageW(box, EM_SCROLLCARET, None, None)
        time.sleep(0.3)
        lines = user32.SendMessageW(box, EM_GETLINECOUNT, None, None)
        first = user32.SendMessageW(box, EM_GETFIRSTVISIBLELINE, None, None)
        print("  lines in box: %d   first visible line: %d" % (lines, first))
        if lines < 40:
            failures.append("the box did not take the 40-line text (%d lines)"
                            % lines)
        if first <= 0:
            failures.append("the view did not scroll to the caret (first visible "
                            "line is %d)" % first)

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
    print("ALL PLACEHOLDER CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
