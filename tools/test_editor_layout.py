# -*- coding: utf-8 -*-
"""Check the editor window's geometry after the v1.17 simplification.

The window used to be sized around the wrapped file path. That row is gone: the
title bar now carries the file NAME and the window holds exactly one card. This
test proves the new contract on the real dist/FileRemarksEditor.exe:

  1. the window is the SAME size for a short name and for a very long, very deep
     path -- nothing is measured from the path any more;
  2. the title bar carries exactly the file name (no "备注", no version, no
     folder);
  3. the remark box sits inside the white card with a visible page margin, and
     the card is still white at the client centre;
  4. the status strip exists below the card and the bottom edge of the client is
     page background, i.e. nothing is clipped;
  5. the remark box has no vertical scrollbar;
  6. control id 101 (the removed full-path row) no longer exists.
"""
import ctypes
import os
import sys
import time
from ctypes import byref, c_void_p, c_uint32, c_wchar_p, c_int, c_ssize_t

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = os.path.join(ROOT, "build", "_editor_layout_test")

IDC_REMARK = 102
IDC_STATUS = 103
IDC_REMOVED_PATH = 101

WS_VSCROLL = 0x00200000
GWL_STYLE = -16
WM_GETICON = 0x007F
WM_CLOSE = 0x0010
RDW_INVALIDATE, RDW_UPDATENOW, RDW_ALLCHILDREN = 0x0001, 0x0100, 0x0080


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
user32.IsWindowVisible.argtypes = [c_void_p]
user32.GetWindowTextW.argtypes = [c_void_p, c_wchar_p, c_int]
user32.GetWindowTextW.restype = c_int
user32.GetDlgItem.argtypes = [c_void_p, c_int]
user32.GetDlgItem.restype = c_void_p
user32.GetClientRect.argtypes = [c_void_p, ctypes.POINTER(RECT)]
user32.GetClientRect.restype = c_int
user32.GetWindowRect.argtypes = [c_void_p, ctypes.POINTER(RECT)]
user32.GetWindowRect.restype = c_int
user32.MapWindowPoints.argtypes = [c_void_p, c_void_p, ctypes.POINTER(RECT), c_uint32]
user32.MapWindowPoints.restype = c_int
user32.GetWindowLongPtrW.argtypes = [c_void_p, c_int]
user32.GetWindowLongPtrW.restype = c_ssize_t
user32.GetDC.argtypes = [c_void_p]
user32.GetDC.restype = c_void_p
user32.ReleaseDC.argtypes = [c_void_p, c_void_p]
user32.RedrawWindow.argtypes = [c_void_p, c_void_p, c_void_p, c_uint32]
user32.PostMessageW.argtypes = [c_void_p, c_uint32, c_void_p, c_void_p]
gdi32.GetPixel.argtypes = [c_void_p, c_int, c_int]
gdi32.GetPixel.restype = c_uint32

ENUM_CB = ctypes.WINFUNCTYPE(c_int, c_void_p, c_void_p)
failures = []


def check(cond, label, detail=""):
    print("  %s %s%s" % ("PASS" if cond else "FAIL", label,
                         "" if not detail else "  [%s]" % detail))
    if not cond:
        failures.append(label)


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


def child_rect(hwnd, child):
    """Child rectangle in the parent's client coordinates."""
    r = RECT()
    user32.GetWindowRect(child, byref(r))
    user32.MapWindowPoints(None, hwnd, byref(r), 2)
    return r


def launch(path):
    exe = os.path.join(ROOT, "dist", "FileRemarksEditor.exe")
    cmd = '"%s" "%s"' % (exe, path)
    si = STARTUPINFOW()
    si.cb = ctypes.sizeof(si)
    pi = PROCESS_INFORMATION()
    ok = kernel32.CreateProcessW(None, cmd, None, None, False, 0, None,
                                 os.path.dirname(exe), byref(si), byref(pi))
    if not ok:
        return None, None
    return pi, pi.dwProcessId


def wait_for_main_window(pid, timeout=8.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        for h in windows_of_pid(pid):
            if user32.IsWindowVisible(h) and user32.GetDlgItem(h, IDC_REMARK):
                return h
        time.sleep(0.1)
    return None


def kill(pi):
    if pi and pi.hProcess:
        kernel32.TerminateProcess(pi.hProcess, 1)
        kernel32.CloseHandle(pi.hProcess)


def rgb(c):
    return (c & 0xFF, (c >> 8) & 0xFF, (c >> 16) & 0xFF)


def probe(path, label):
    """Open the editor on `path` and measure the window."""
    pi, pid = launch(path)
    if not pi:
        failures.append("%s: could not start the editor" % label)
        return None
    out = {"label": label, "hwnd": None}
    try:
        hwnd = wait_for_main_window(pid)
        if not hwnd:
            failures.append("%s: the editor window never appeared" % label)
            return None
        out["hwnd"] = hwnd

        user32.RedrawWindow(hwnd, None, None,
                            RDW_INVALIDATE | RDW_UPDATENOW | RDW_ALLCHILDREN)
        time.sleep(0.25)

        client = RECT()
        user32.GetClientRect(hwnd, byref(client))
        out["client"] = client
        out["title"] = window_text(hwnd)

        remark = user32.GetDlgItem(hwnd, IDC_REMARK)
        status = user32.GetDlgItem(hwnd, IDC_STATUS)
        out["remark"] = child_rect(hwnd, remark) if remark else None
        out["status"] = child_rect(hwnd, status) if status else None
        out["remark_style"] = user32.GetWindowLongPtrW(remark, GWL_STYLE)
        out["status_hwnd"] = status
        out["removed_path"] = user32.GetDlgItem(hwnd, IDC_REMOVED_PATH)

        hdc = user32.GetDC(hwnd)
        out["page_px"] = rgb(gdi32.GetPixel(hdc, 4, 4))
        # Sample the card in the strip between the remark box and the status row.
        # The client centre belongs to the EDIT control, and a window DC is
        # clipped by WS_CLIPCHILDREN, so GetPixel there returns CLR_INVALID
        # (0xFFFFFFFF) instead of a colour.
        card_y = (out["remark"].bottom + out["status"].top) // 2
        out["card_px"] = rgb(gdi32.GetPixel(hdc, client.right // 2, card_y))
        out["bottom_px"] = rgb(gdi32.GetPixel(hdc, client.right // 2,
                                              client.bottom - 2))
        user32.ReleaseDC(hwnd, hdc)

        print("  %-6s client=%dx%d  title=%r" % (label, client.right,
                                                 client.bottom, out["title"]))
        if out["remark"]:
            r = out["remark"]
            print("  %-6s remark box=(%d,%d)-(%d,%d)  status bottom=%d"
                  % (label, r.left, r.top, r.right, r.bottom,
                     out["status"].bottom if out["status"] else -1))
        return out
    finally:
        if out["hwnd"]:
            user32.PostMessageW(out["hwnd"], WM_CLOSE, None, None)
        time.sleep(0.2)
        kill(pi)


def system_palette():
    """The editor picks its palette from the Windows app mode, so the expected
    surface and card colours depend on the machine's setting rather than being
    fixed at the light values."""
    import winreg
    light = 1
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
            light, _ = winreg.QueryValueEx(k, "AppsUseLightTheme")
    except OSError:
        pass
    if light == 0:
        return (32, 32, 32), (43, 43, 43)
    return (243, 243, 243), (255, 255, 255)


def main():
    page_rgb, card_rgb = system_palette()
    print("=== the editor window after the v1.17 simplification ===")
    if not os.path.isdir(WORK):
        os.makedirs(WORK)

    short = os.path.join(WORK, "短名字.txt")
    open(short, "w").close()

    deep = WORK
    for i in range(7):
        deep = os.path.join(deep, "目录%02d_%s" % (i, "abcdefghijklmnop"))
        if not os.path.isdir(deep):
            os.makedirs(deep)
    long_path = os.path.join(deep, "很长很长的一个文件名用来测试标题栏省略效果.txt")
    open(long_path, "w").close()

    a = probe(short, "short")
    b = probe(long_path, "long")
    if not (a and b):
        return 1

    print("\n=== 1. the window no longer depends on the path ===")
    check((a["client"].right, a["client"].bottom) ==
          (b["client"].right, b["client"].bottom),
          "a deep path does not resize the window",
          "%dx%d vs %dx%d" % (a["client"].right, a["client"].bottom,
                              b["client"].right, b["client"].bottom))

    print("\n=== 2. the title bar carries the file name, nothing else ===")
    check(a["title"] == os.path.basename(short),
          "short name is the whole title", a["title"])
    check(b["title"] == os.path.basename(long_path),
          "long name is the whole title (the caption elides it, the text stays)",
          b["title"])
    for bad in ("备注", "v1.", "\\", "/"):
        check(bad not in a["title"], "title has no %r" % bad, a["title"])

    print("\n=== 3. one white card with a page margin ===")
    for item in (a, b):
        lab, c, r = item["label"], item["client"], item["remark"]
        check(r is not None, "%s: the remark box exists" % lab)
        if not r:
            continue
        check(r.left >= 20 and r.top >= 18,
              "%s: the box keeps a page margin on the left/top" % lab,
              "(%d,%d)" % (r.left, r.top))
        check(r.right <= c.right - 20 and r.bottom <= c.bottom - 20,
              "%s: the box is fully inside the client" % lab,
              "(%d,%d) in %dx%d" % (r.right, r.bottom, c.right, c.bottom))
        check(item["page_px"] == page_rgb,
              "%s: the page background is the Win11 surface" % lab,
              str(item["page_px"]))
        check(item["card_px"] == card_rgb,
              "%s: the card is painted in the surface colour" % lab,
              str(item["card_px"]))

    print("\n=== 4. the status strip sits under the card, bottom is not clipped ===")
    for item in (a, b):
        lab, st = item["label"], item["status"]
        check(st is not None, "%s: the status strip exists" % lab)
        if not st:
            continue
        check(st.top >= item["remark"].bottom,
              "%s: the strip starts below the box" % lab,
              "%d vs %d" % (st.top, item["remark"].bottom))
        check(st.bottom <= item["client"].bottom,
              "%s: the strip is inside the client" % lab,
              "%d in %d" % (st.bottom, item["client"].bottom))
        check(item["bottom_px"] == page_rgb,
              "%s: the last row is page background, nothing is cut off" % lab,
              str(item["bottom_px"]))

    print("\n=== 5. no scrollbar, no leftover path row ===")
    for item in (a, b):
        lab = item["label"]
        check(item["remark_style"] is not None and
              not (item["remark_style"] & WS_VSCROLL),
              "%s: the remark box has no vertical scrollbar" % lab,
              "style=0x%08x" % (item["remark_style"] or 0))
        check(not item["removed_path"],
              "%s: control id 101 (the removed path row) is gone" % lab)

    print("\n--- verdict ---")
    if failures:
        print("%d check(s) FAILED" % len(failures))
        for f in failures:
            print("  - %s" % f)
        return 1
    print("ALL EDITOR LAYOUT CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
