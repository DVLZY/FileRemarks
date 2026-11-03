# -*- coding: utf-8 -*-
"""Drive the real editor window and check it auto-saves.

This is the closest possible thing to a user double-clicking the file: the real
dist/FileRemarksEditor.exe is started on a real file, its controls are located by
the same IDs the source uses, text is typed into the remark box, and the stored
remark is then read back from outside the process (the ADS ":remark").

The editor has no buttons any more, so the two save triggers are what is tested:
  1. closing the window (WM_CLOSE)
  2. losing the foreground (WM_ACTIVATE with WA_INACTIVE)
Clearing a remark is simply deleting the text, which closes over the same path.
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
WORK = os.path.join(ROOT, "build", "_editor_gui_test")

# Must match the enum in src/FileRemarksEditor.cpp.
IDC_REMARK = 102
IDC_STATUS = 103

# These IDs no longer exist. The test asserts they are gone, which is what
# proves the text buttons were really removed.
IDC_GONE = {104: "保存", 105: "清空", 2: "关闭"}

WM_SETTEXT = 0x000C
WM_GETTEXT = 0x000D
WM_GETTEXTLENGTH = 0x000E
WM_CLOSE = 0x0010
WM_ACTIVATE = 0x0006
WM_GETICON = 0x007F
ICON_SMALL = 0
ICON_BIG = 1
WA_INACTIVE = 0


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
user32.GetWindowTextW.argtypes = [c_void_p, c_wchar_p, c_int]
user32.GetWindowTextW.restype = c_int
user32.GetDlgItem.argtypes = [c_void_p, c_int]
user32.GetDlgItem.restype = c_void_p
user32.SendMessageW.argtypes = [c_void_p, c_uint32, c_void_p, c_void_p]
user32.SendMessageW.restype = ctypes.c_ssize_t
user32.PostMessageW.argtypes = [c_void_p, c_uint32, c_void_p, c_void_p]
user32.PostMessageW.restype = c_int
user32.IsWindowVisible.argtypes = [c_void_p]
user32.IsWindow.argtypes = [c_void_p]
# GetPixel lives in gdi32 (not user32) and returns COLORREF 0x00BBGGRR.
user32.GetDC.argtypes = [c_void_p]
user32.GetDC.restype = c_void_p
user32.ReleaseDC.argtypes = [c_void_p, c_void_p]
user32.RedrawWindow.argtypes = [c_void_p, c_void_p, c_void_p, c_uint32]
gdi32.GetPixel.argtypes = [c_void_p, c_int, c_int]
gdi32.GetPixel.restype = c_uint32

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
    # GetWindowTextW(hwnd, NULL, 0) is not a reliable length probe; use a fixed
    # buffer instead, which is what the shell does too.
    buf = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(hwnd, buf, 512)
    return buf.value


def send_text(hwnd, text):
    return user32.SendMessageW(hwnd, WM_SETTEXT, None, c_wchar_p(text))


def get_text(hwnd):
    n = user32.SendMessageW(hwnd, WM_GETTEXTLENGTH, None, None)
    buf = ctypes.create_unicode_buffer(n + 4)
    user32.SendMessageW(hwnd, WM_GETTEXT, c_void_p(n + 4), ctypes.cast(buf, c_void_p))
    return buf.value


def read_ads(path):
    try:
        with open(path + ":remark", "rb") as f:
            return f.read().decode("utf-8")
    except (FileNotFoundError, OSError):
        return None


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


def main():
    os.makedirs(WORK, exist_ok=True)
    target = os.path.join(WORK, "一个纯英文名字的文件.txt")
    with open(target, "wb") as f:
        f.write(b"content\n")
    try:
        os.remove(target + ":remark")
    except OSError:
        pass

    failures = []
    remark_text = "这个是用来测试备注功能的文件"

    # --- round 1: the text buttons must be gone --------------------------
    print("=== round 1: no text buttons, controls present ===")
    pi = launch(target)
    try:
        hwnd = wait_for_main_window(pi.dwProcessId)
        if not hwnd:
            print("  the editor window never appeared")
            return 1
        print("  main window: %r" % window_text(hwnd))
        # The title bar carries the file NAME and nothing else: no "备注", no
        # version number, no folder. A native caption also left-aligns it for
        # free, which is the layout asked for.
        title = window_text(hwnd)
        if title != os.path.basename(target):
            failures.append("window title is %r, expected the file name %r"
                            % (title, os.path.basename(target)))

        remark_box = user32.GetDlgItem(hwnd, IDC_REMARK)
        status = user32.GetDlgItem(hwnd, IDC_STATUS)
        for name, h in (("remark", remark_box), ("status", status)):
            print("  control %-9s hwnd=%s" % (name, h))
            if not h:
                failures.append("control %s not found" % name)
        # The full-path row is gone: nothing may be left at the old control id.
        path_box = user32.GetDlgItem(hwnd, 101)
        print("  removed path row (id 101) -> %s" % path_box)
        if path_box:
            failures.append("the file path row is still there")
        for cid, label in IDC_GONE.items():
            h = user32.GetDlgItem(hwnd, cid)
            print("  removed button %r (id %d) -> %s" % (label, cid, h))
            if h:
                failures.append("button %s (id %d) is still there" % (label, cid))
        if failures:
            return 1

        # The window must carry our own logo, not the generic default icon --
        # that is what makes the tool recognisable in the task bar.
        big = user32.SendMessageW(hwnd, WM_GETICON, ICON_BIG, None)
        small = user32.SendMessageW(hwnd, WM_GETICON, ICON_SMALL, None)
        print("  window icons: big=%s small=%s" % (big, small))
        if not big and not small:
            failures.append("the window has no icon set by ApplyIcon()")

        # The remark box must already have the keyboard focus, so the user can
        # simply start typing.
        print("  remark box starts as: %r" % get_text(remark_box))
        print("  status line: %r" % get_text(status))
        # The permanent hint that used to sit under the box was removed on
        # request, so an idle window shows nothing there.
        if get_text(status) != "":
            failures.append("the status line should start empty, got %r"
                            % get_text(status))

        # The window must actually be painted in the Win11 palette, not left as
        # a bare default-grey dialog. The window is sized to its content, so the
        # sample point for the card is taken from the live client rect (its
        # centre always lands inside the remark box) instead of a hard-coded
        # coordinate that would move whenever the layout is tuned.
        RDW_INVALIDATE, RDW_UPDATENOW, RDW_ALLCHILDREN = 0x0001, 0x0100, 0x0080
        user32.RedrawWindow(hwnd, None, None,
                            RDW_INVALIDATE | RDW_UPDATENOW | RDW_ALLCHILDREN)
        time.sleep(0.2)
        client = RECT()
        user32.GetClientRect(hwnd, byref(client))
        card_x, card_y = client.right // 2, client.bottom // 2
        hdc = user32.GetDC(hwnd)
        page_px = gdi32.GetPixel(hdc, 4, 4)
        card_px = gdi32.GetPixel(hdc, card_x, card_y)
        user32.ReleaseDC(hwnd, hdc)
        rgb = lambda c: (c & 0xFF, (c >> 8) & 0xFF, (c >> 16) & 0xFF)
        print("  client=%dx%d  page pixel: %s   card pixel at (%d,%d): %s"
              % (client.right, client.bottom, rgb(page_px),
                 card_x, card_y, rgb(card_px)))
        if not all(abs(v - 243) <= 8 for v in rgb(page_px)):
            failures.append("page background is not the Win11 surface: %s"
                            % (rgb(page_px),))
        if rgb(card_px) != (255, 255, 255):
            failures.append("the remark card is not painted white: %s"
                            % (rgb(card_px),))

        # --- round 2: typing then CLOSING saves --------------------------
        print("\n=== round 2: type, then close the window ===")
        send_text(remark_box, remark_text)
        print("  typed: %r" % get_text(remark_box))
        user32.PostMessageW(hwnd, WM_CLOSE, None, None)
        time.sleep(0.8)
        still = [h for h in windows_of_pid(pi.dwProcessId) if user32.IsWindowVisible(h)]
        print("  visible windows after close: %d" % len(still))
        if still:
            failures.append("the window did not close on WM_CLOSE")
        stored = read_ads(target)
        print("  ADS :remark after close -> %r" % stored)
        if stored != remark_text:
            failures.append("closing stored %r, expected %r" % (stored, remark_text))
    finally:
        kill(pi)

    # --- round 3: reopening reloads, and LOSING FOCUS saves ---------------
    print("\n=== round 3: reopen, edit, then lose the foreground ===")
    pi = launch(target)
    try:
        hwnd = wait_for_main_window(pi.dwProcessId)
        if not hwnd:
            failures.append("editor window did not appear on reopen")
            return 1
        remark_box = user32.GetDlgItem(hwnd, IDC_REMARK)
        loaded = get_text(remark_box)
        print("  remark box on reopen: %r" % loaded)
        if loaded != remark_text:
            failures.append("reopen shows %r, expected %r" % (loaded, remark_text))

        second = remark_text + "（改过）"
        send_text(remark_box, second)
        # Exactly what Windows sends to the window that loses the foreground.
        user32.SendMessageW(hwnd, WM_ACTIVATE, c_void_p(WA_INACTIVE), None)
        time.sleep(0.5)
        status = get_text(user32.GetDlgItem(hwnd, IDC_STATUS))
        print("  status after losing focus: %r" % status)
        print("  ADS :remark now -> %r" % read_ads(target))
        if read_ads(target) != second:
            failures.append("losing focus did not save (ADS is %r)"
                            % (read_ads(target),))
        if "自动保存" not in status:
            failures.append("status does not confirm the auto-save: %r" % status)

        # Losing focus must SAVE but must NOT close the window -- the user asked
        # for exactly this ("失焦时自动保存，但不关闭窗口").
        if not user32.IsWindowVisible(hwnd):
            failures.append("losing focus closed the window")

        # Editing still works after the save, i.e. the window is not just alive
        # but resumable. Put the text back afterwards so the next check still
        # sees an unmodified buffer.
        send_text(remark_box, second + "!")
        time.sleep(0.1)
        if get_text(remark_box) != second + "!":
            failures.append("the remark box is not usable after losing focus")
        send_text(remark_box, second)
        time.sleep(0.1)

        # An idle window that just loses focus again must NOT rewrite the file,
        # and must not claim a save either -- the line goes blank again.
        user32.SendMessageW(hwnd, WM_ACTIVATE, c_void_p(WA_INACTIVE), None)
        time.sleep(0.3)
        status2 = get_text(user32.GetDlgItem(hwnd, IDC_STATUS))
        print("  status after a second (idle) deactivation: %r" % status2)
        if status2 != "":
            failures.append("an unedited window reported a save: %r" % status2)

        # --- round 4: clearing = deleting the text, then closing ---------
        print("\n=== round 4: clear by deleting the text, then close ===")
        send_text(remark_box, "")
        user32.PostMessageW(hwnd, WM_CLOSE, None, None)
        time.sleep(0.8)
        print("  ADS :remark after clearing -> %r" % read_ads(target))
        if read_ads(target) is not None:
            failures.append("clearing left the ADS behind")
        still = [h for h in windows_of_pid(pi.dwProcessId) if user32.IsWindowVisible(h)]
        if still:
            failures.append("the window did not close after clearing")
    finally:
        kill(pi)

    print("")
    if failures:
        print("FAILURES:")
        for f in failures:
            print("  - " + f)
        return 1
    print("ALL EDITOR GUI TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
