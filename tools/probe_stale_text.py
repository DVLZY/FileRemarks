"""Reproduces "deleted remark text still visible but not selectable" (bug report).

The symptom -- the characters are gone from the control (they can no longer be
selected) but their pixels are still on screen -- means the control painted the
shorter text WITHOUT wiping the background underneath.

Oracle for "is what I see correct?": a FRESH window given the same final value
through WM_SETTEXT renders the ground truth. Comparing ink against that
reference isolates stale pixels from legitimate ones.

Scenarios
  S1  backspace a whole line          (incremental delete)
  S2  select everything + Delete key  (bulk delete, as most users do it)
  S3  long text that scrolls, then select all + Delete  (scrolled viewport)
  S4  select a middle chunk + Delete  (delete from the middle)

Run:  python tools/probe_stale_text.py
"""

import ctypes
import os
import subprocess
import sys
import time
from ctypes import wintypes

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EDITOR = os.path.join(ROOT, "dist", "FileRemarksEditor.exe")
# Optional override so the same probe can be pointed at an installed copy:
#   python tools/probe_stale_text.py "C:\Program Files\FileRemarks\FileRemarksEditor.exe"
if len(sys.argv) > 1:
    EDITOR = sys.argv[1]
WORK = os.path.join(ROOT, "build", "_stale_text")

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

IDC_REMARK = 102
WM_SETTEXT = 0x000C
WM_GETTEXT = 0x000D
WM_GETTEXTLENGTH = 0x000E
WM_CLOSE = 0x0010
WM_KEYDOWN = 0x0100
WM_CHAR = 0x0102
WM_CLEAR = 0x0303
EM_SETSEL = 0x00B1
EM_GETRECT = 0x00B2
VK_BACK = 0x08
VK_DELETE = 0x2E
RDW_INVALIDATE, RDW_ERASE, RDW_UPDATENOW = 0x0001, 0x0004, 0x0100

_send = user32.SendMessageW
_send.restype = ctypes.c_ssize_t
_send.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
# Text / struct arguments need a pointer-typed LPARAM; ctypes keeps argtypes per
# binding, not per call, so this is a second binding of the same function.
_send_ptr = ctypes.WinDLL("user32", use_last_error=True).SendMessageW
_send_ptr.restype = ctypes.c_ssize_t
_send_ptr.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, ctypes.c_void_p]

user32.GetDlgItem.restype = wintypes.HWND
user32.GetDlgItem.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetClientRect.restype = wintypes.BOOL
user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.GetDC.restype = wintypes.HDC
user32.GetDC.argtypes = [wintypes.HWND]
user32.ReleaseDC.restype = ctypes.c_int
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
user32.RedrawWindow.restype = wintypes.BOOL
user32.RedrawWindow.argtypes = [wintypes.HWND, ctypes.c_void_p, wintypes.HANDLE,
                                wintypes.UINT]
user32.PostMessageW.restype = wintypes.BOOL
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM,
                                wintypes.LPARAM]
user32.IsWindowVisible.restype = wintypes.BOOL
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND,
                                            ctypes.POINTER(wintypes.DWORD)]
user32.EnumWindows.restype = wintypes.BOOL
user32.EnumWindows.argtypes = [ctypes.c_void_p, wintypes.LPARAM]
gdi32.GetPixel.restype = wintypes.DWORD
gdi32.GetPixel.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]

WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

FAILS = []


def check(cond, msg, detail=""):
    if cond:
        print("  PASS  " + msg)
    else:
        print("  FAIL  " + msg + (("  [" + detail + "]") if detail else ""))
        FAILS.append(msg)


def get_text(box):
    n = _send(box, WM_GETTEXTLENGTH, 0, 0)
    buf = ctypes.create_unicode_buffer(n + 2)
    _send_ptr(box, WM_GETTEXT, n + 1, ctypes.byref(buf))
    return buf.value


def set_text(box, s):
    _send_ptr(box, WM_SETTEXT, 0, ctypes.c_wchar_p(s))


def wait_window(pid, timeout=8.0):
    end = time.time() + timeout
    while time.time() < end:
        found = []

        def cb(h, _l, found=found, pid=pid):
            tid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(h, ctypes.byref(tid))
            if tid.value == pid and user32.IsWindowVisible(h):
                found.append(h)
            return True

        user32.EnumWindows(WNDENUMPROC(cb), 0)
        if found:
            time.sleep(0.4)
            return found[0]
        time.sleep(0.1)
    return None


def ink(box, stride=2):
    rc = wintypes.RECT()
    user32.GetClientRect(box, ctypes.byref(rc))
    hdc = user32.GetDC(box)
    count = 0
    for y in range(0, rc.bottom, stride):
        for x in range(0, rc.right, stride):
            c = gdi32.GetPixel(hdc, x, y) & 0xFFFFFF
            r, g, b = c & 0xFF, (c >> 8) & 0xFF, (c >> 16) & 0xFF
            if not (r > 240 and g > 240 and b > 240):
                count += 1
    user32.ReleaseDC(box, hdc)
    return count


class Session:
    """One editor window, driven from a test thread."""

    def __init__(self, target):
        self.proc = subprocess.Popen([EDITOR, target])
        self.hwnd = wait_window(self.proc.pid)
        self.box = user32.GetDlgItem(self.hwnd, IDC_REMARK) if self.hwnd else None

    def ok(self):
        return bool(self.hwnd and self.box)

    def redraw(self):
        user32.RedrawWindow(self.box, None, None, RDW_INVALIDATE | RDW_UPDATENOW)
        time.sleep(0.35)

    def close(self):
        if self.hwnd:
            user32.PostMessageW(self.hwnd, WM_CLOSE, 0, 0)
            time.sleep(0.4)
        try:
            self.proc.kill()
        except Exception:
            pass
        time.sleep(0.2)


def reference_ink(target, value):
    """Ground truth: a fresh window whose content is exactly `value`."""
    s = Session(target)
    if not s.ok():
        raise SystemExit("editor did not start")
    try:
        set_text(s.box, value)
        s.redraw()
        got = get_text(s.box)
        if got != value:
            raise SystemExit("reference setup failed: %r != %r" % (got, value))
        return ink(s.box)
    finally:
        s.close()


def repaint_delta(box):
    """How much ink survives a full repaint?

    A correct window shows what the control would draw from scratch, so forcing
    RDW_ERASE|RDW_INVALIDATE must not change the picture. Any ink that vanishes
    only after that repaint was stale: the control had already forgotten the
    text but the screen still showed it. This needs no reference render, so it
    works for cases where the surviving text differs from a clean re-render
    (a single character deleted out of a word, for instance).
    """
    before = ink(box)
    user32.RedrawWindow(box, None, None,
                        RDW_INVALIDATE | RDW_ERASE | RDW_UPDATENOW)
    time.sleep(0.35)
    after = ink(box)
    return before, after


def scenario(name, target, setup_text, final_text, mutate):
    print("\n--- %s ---" % name)
    s = Session(target)
    if not s.ok():
        check(False, "%s: editor did not start" % name)
        return
    try:
        set_text(s.box, setup_text)
        s.redraw()
        if get_text(s.box) != setup_text:
            check(False, "%s: setup text not applied" % name)
            return
        mutate(s.box)
        # The shell repaints whatever region the control claims changed; force
        # nothing here, so a stale region stays stale and is visible below.
        time.sleep(0.4)
        value = get_text(s.box)
        seen = ink(s.box)
        before, after = repaint_delta(s.box)
    finally:
        s.close()

    ref = reference_ink(target, final_text)
    print("  value after delete: %r" % value)
    print("  ink: after-delete=%d   ground-truth render=%d" % (seen, ref))
    check(before - after <= 12,
          "%s: a forced repaint does not erase anything" % name,
          "ink %d before repaint vs %d after (%d stale pixels)"
          % (before, after, before - after))
    check(value == final_text, "%s: the control's value is the remaining text" % name,
          "got %r" % value)
    allowed = int(ref * 1.12) + 10
    check(seen <= allowed,
          "%s: no leftover pixels from the deleted text" % name,
          "ink %d vs %d (limit %d)" % (seen, ref, allowed))


LINE1 = "abcdefghij"
LINE2 = "klmnopqrst"


def main():
    print("stale-text probe (deleted text still drawn, not selectable)")
    print("=" * 66)
    if not os.path.exists(EDITOR):
        print("missing %s -- run tools/build_mingw.sh first" % EDITOR)
        return 2
    os.makedirs(WORK, exist_ok=True)
    target = os.path.join(WORK, "样例文件.txt")
    with open(target, "w", encoding="utf-8") as f:
        f.write("x")
    try:
        os.remove(target + ":remark")
    except OSError:
        pass

    two = LINE1 + "\r\n" + LINE2

    # S1: incremental delete with Backspace.
    def s1(box):
        _send(box, EM_SETSEL, len(two), len(two))
        # Only WM_CHAR: an EDIT deletes on the character message, so also
        # sending WM_KEYDOWN for the same key would delete twice. Backspace
        # exactly as many times as needed, re-reading the value each time so the
        # scenario never deletes a character it should have kept.
        for _ in range(len(two) + 4):
            if get_text(box) == LINE1:
                break
            _send(box, WM_CHAR, VK_BACK, 0x000E0001)

    scenario("S1 backspace a whole line", target, two, LINE1, s1)

    # S2: select everything, press Delete.
    def s2(box):
        _send(box, EM_SETSEL, 0, -1)
        _send(box, WM_KEYDOWN, VK_DELETE, 0x00530001)

    scenario("S2 select all + Delete", target, two, "", s2)

    # S3: text long enough to scroll, then select all + Delete.
    long_text = "\r\n".join("%02d line %s" % (i, "x" * 30) for i in range(24))
    def s3(box):
        _send(box, EM_SETSEL, 0, -1)
        _send(box, WM_KEYDOWN, VK_DELETE, 0x00530001)

    scenario("S3 scrolled text, select all + Delete", target, long_text, "", s3)

    # S4: delete a chunk out of the middle.
    def s4(box):
        _send(box, EM_SETSEL, len(LINE1) + 2, len(two))
        _send(box, WM_KEYDOWN, VK_DELETE, 0x00530001)

    scenario("S4 delete from the middle", target, two, LINE1 + "\r\n", s4)

    print("\n--- verdict ---")
    # S5: select a chunk in the middle, press Backspace instead of Delete.
    def s5(box):
        _send(box, EM_SETSEL, len(LINE1) + 2, len(two))
        _send(box, WM_CHAR, VK_BACK, 0x000E0001)

    scenario("S5 select the tail + Backspace", target, two, two[:len(LINE1) + 2], s5)

    # S6: select everything and type one replacement character over it.
    def s6(box):
        _send(box, EM_SETSEL, 0, -1)
        _send(box, WM_CHAR, ord("Z"), 0x002A0001)

    scenario("S6 select all + type over", target, two, "Z", s6)

    # S7: shorten a scrolled multi-line text so the box shrinks its line count.
    def s7(box):
        set_text(box, "only one line left")

    scenario("S7 long text replaced by one short line", target, long_text,
             "only one line left", s7)

    # S8: delete a single character out of the middle of a word.
    def s8(box):
        _send(box, EM_SETSEL, 3, 4)          # the "d" of abcdefghij
        _send(box, WM_KEYDOWN, VK_DELETE, 0x00530001)

    scenario("S8 delete one character mid-word", target, "abcdefghij",
             "abcefghij", s8)

    # S9: scrolled to the bottom, then delete a few characters at the caret.
    def s9(box):
        _send(box, EM_SETSEL, len(long_text), len(long_text))
        for _ in range(6):
            _send(box, WM_CHAR, VK_BACK, 0x000E0001)

    scenario("S9 scrolled, backspace at the end", target, long_text,
             long_text[:-6], s9)

    if FAILS:
        print("  %d stale-text check(s) FAILED" % len(FAILS))
        return 1
    print("  all scenarios erased the deleted text")
    return 0


if __name__ == "__main__":
    sys.exit(main())
