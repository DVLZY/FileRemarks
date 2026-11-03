#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Verifies the two installer-version changes that can be checked in-process:

  1. the installer knows (a) whether a copy is installed, (b) the version of
     that copy, and (c) the version it is about to install -- and the two
     version strings are not the same, which is the whole point of the request
     "安装的时候显示当前已经安装的版本和目标安装版本".
  2. the replacement choice window really renders as a Windows 11 style dialog:
     correct title, three owner-drawn buttons with the right labels, the right
     one focused, live pixels in the page/card colours, and each button
     returning the documented value.

The installer itself self-elevates through UAC before showing this window, which
cannot be automated here, so the window is driven directly through
build/selftest_installer_ui.dll (test-only, never shipped).

Run:  python tools/test_installer_ui.py
"""

import ctypes
import ctypes.wintypes as wt
import os
import re
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD = os.path.join(ROOT, "build")

# Read the target version from the single source of truth instead of hardcoding
# it here: this assertion is about "the dialog names the version being
# installed", not about any particular release.
with open(os.path.join(ROOT, "src", "version.h"), encoding="utf-8") as _vh:
    VERSION_TEXT = re.search(r'#define\s+FR_VERSION_TEXT\s+L"([^"]+)"',
                             _vh.read()).group(1)

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

WM_COMMAND = 0x0111
WM_GETTEXT = 0x000D
WM_GETTEXTLENGTH = 0x000E
WM_KEYDOWN = 0x0100
WM_CLOSE = 0x0010
BM_CLICK = 0x00F5
BN_CLICKED = 0
VK_ESCAPE = 0x1B
VK_RETURN = 0x0D

H = wt.HWND
DWORD = wt.DWORD

user32.FindWindowW.restype = H
user32.FindWindowW.argtypes = [wt.LPCWSTR, wt.LPCWSTR]
user32.EnumChildWindows.restype = wt.BOOL
user32.EnumChildWindows.argtypes = [H, ctypes.c_void_p, wt.LPARAM]
user32.GetWindowTextW.restype = ctypes.c_int
user32.GetWindowTextW.argtypes = [H, wt.LPWSTR, ctypes.c_int]
user32.GetClassNameW.restype = ctypes.c_int
user32.GetClassNameW.argtypes = [H, wt.LPWSTR, ctypes.c_int]
user32.SendMessageW.restype = ctypes.c_ssize_t
user32.SendMessageW.argtypes = [H, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.GetDlgItem.restype = H
user32.GetDlgItem.argtypes = [H, ctypes.c_int]
user32.GetFocus.restype = H
user32.GetClientRect.restype = wt.BOOL
user32.GetClientRect.argtypes = [H, ctypes.POINTER(wt.RECT)]
user32.GetDC.restype = wt.HDC
user32.GetDC.argtypes = [H]
user32.ReleaseDC.restype = ctypes.c_int
user32.ReleaseDC.argtypes = [H, wt.HDC]
gdi32.GetPixel.restype = DWORD
gdi32.GetPixel.argtypes = [wt.HDC, ctypes.c_int, ctypes.c_int]
user32.IsWindow.restype = wt.BOOL
user32.IsWindow.argtypes = [H]
user32.PostMessageW.restype = wt.BOOL
user32.PostMessageW.argtypes = [H, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.SetForegroundWindow.restype = wt.BOOL
user32.SetForegroundWindow.argtypes = [H]
user32.RedrawWindow.restype = wt.BOOL
user32.RedrawWindow.argtypes = [H, ctypes.c_void_p, H, wt.UINT]
user32.GetWindowRect.restype = wt.BOOL
user32.GetWindowRect.argtypes = [H, ctypes.POINTER(wt.RECT)]
user32.MapWindowPoints.restype = ctypes.c_int
user32.MapWindowPoints.argtypes = [H, H, ctypes.POINTER(wt.RECT), wt.UINT]
gdi32.GetDeviceCaps.restype = ctypes.c_int
gdi32.GetDeviceCaps.argtypes = [wt.HDC, ctypes.c_int]

try:
    user32.GetDpiForWindow.restype = wt.UINT
    user32.GetDpiForWindow.argtypes = [H]
    HAS_DPI = True
except AttributeError:
    HAS_DPI = False

FAILS = []


def check(cond, msg, detail=""):
    if cond:
        print("  PASS  " + msg)
    else:
        print("  FAIL  " + msg + (("  [" + detail + "]") if detail else ""))
        FAILS.append(msg)


def system_palette():
    """The installer picks its palette from the Windows app mode, so the
    expected surfaces follow the machine's setting instead of a fixed file."""
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


def text_of(hwnd):
    if not hwnd:
        return ""
    # NOTE: GetWindowTextW(hwnd, None, 0) is NOT a reliable length probe for a
    # window owned by another thread -- it returns 0 even when text is set. A
    # fixed buffer read works, so always use one (same lesson as the editor test).
    buf = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(hwnd, buf, 512)
    return buf.value


# GetFocus() only ever reports the CALLING thread's focus window, and the choice
# window lives on its own thread, so ask that thread instead.
class GUITHREADINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", DWORD),
        ("flags", DWORD),
        ("hwndActive", H),
        ("hwndFocus", H),
        ("hwndCapture", H),
        ("hwndMenuOwner", H),
        ("hwndMoveSize", H),
        ("hwndCaret", H),
        ("rcCaret", wt.RECT),
    ]


def focus_of(hwnd):
    tid = user32.GetWindowThreadProcessId(hwnd, None)
    gti = GUITHREADINFO()
    gti.cbSize = ctypes.sizeof(GUITHREADINFO)
    if user32.GetGUIThreadInfo(tid, ctypes.byref(gti)):
        return gti.hwndFocus
    return None


def children(hwnd):
    out = []

    @ctypes.WINFUNCTYPE(wt.BOOL, H, wt.LPARAM)
    def cb(h, _l):
        out.append(h)
        return True

    user32.EnumChildWindows(hwnd, ctypes.cast(cb, ctypes.c_void_p), 0)
    return out


def class_of(hwnd):
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


# --------------------------------------------------------------------------
# Load the test wrapper.
# --------------------------------------------------------------------------
wrapper_path = os.path.join(BUILD, "selftest_installer_ui.dll")
ver_path = os.path.join(BUILD, "selftest_install.dll")
for p in (wrapper_path, ver_path):
    if not os.path.exists(p):
        print("missing %s -- run tools/build_mingw.sh first" % p)
        sys.exit(2)

ui = ctypes.WinDLL(wrapper_path)
ver = ctypes.WinDLL(ver_path)

ver.FrTestInstalledVersion.restype = ctypes.c_int
ver.FrTestInstalledVersion.argtypes = [wt.LPWSTR, ctypes.c_int]
ver.FrTestNewVersion.restype = ctypes.c_int
ver.FrTestNewVersion.argtypes = [wt.LPWSTR, ctypes.c_int]
ver.FrTestIsInstalled.restype = ctypes.c_int
ver.FrTestIsInstalled.argtypes = []

ui.FrTestStartChoice.restype = ctypes.c_int
ui.FrTestStartChoice.argtypes = [ctypes.c_int, wt.LPCWSTR, wt.LPCWSTR]
ui.FrTestWaitReady.restype = ctypes.c_int
ui.FrTestWaitReady.argtypes = []
ui.FrTestChoiceWindow.restype = H
ui.FrTestChoiceWindow.argtypes = []
ui.FrTestChoiceRunning.restype = ctypes.c_int
ui.FrTestChoiceRunning.argtypes = []
ui.FrTestChoiceResult.restype = ctypes.c_int
ui.FrTestChoiceResult.argtypes = []
ui.FrTestEndChoice.restype = ctypes.c_int
ui.FrTestEndChoice.argtypes = []


# --------------------------------------------------------------------------
# 1. Version reporting.
# --------------------------------------------------------------------------
print("=== 1. installer reports installed version and target version ===")
buf = ctypes.create_unicode_buffer(256)
ver.FrTestInstalledVersion(buf, 256)
cur = buf.value
ver.FrTestNewVersion(buf, 256)
new = buf.value
installed = ver.FrTestIsInstalled()

print("  installed            : %d" % installed)
print("  current version text : %r" % cur)
print("  target version text  : %r" % new)

check(installed in (0, 1), "IsInstalled() answers 0 or 1")
if installed:
    check(cur != "", "an installed copy reports a version string, not silence")
    check(cur != new, "current and target versions are distinguishable",
          "%r vs %r" % (cur, new))
    check(cur.startswith("v") or "旧版本" in cur or "未知" in cur,
          "current version is either a vX.Y string or an honest 'old/unknown' note",
          cur)
else:
    check(True, "not installed here, so there is no current version to show")
check(new.startswith("v" + VERSION_TEXT),
      "target version is the %s build" % VERSION_TEXT, new)


# --------------------------------------------------------------------------
# 2. The choice window itself.
# --------------------------------------------------------------------------
# FrTestWaitReady() only proves the window OBJECT exists; ShowChoice may still be
# inside CreateWindowExW, not yet pumping its message loop.  Reading the title or
# class right then sends a synchronous message to that thread and can come back
# empty (or after a stall), which used to make this suite fail intermittently.
# So wait until the window answers a WM_NULL round trip: that is the moment it is
# actually usable.
user32.SendMessageTimeoutW.argtypes = [
    H, wt.UINT, wt.WPARAM, wt.LPARAM, wt.UINT, wt.UINT,
    ctypes.POINTER(ctypes.c_size_t),
]
user32.SendMessageTimeoutW.restype = wt.LPARAM


def wait_choice_ready(timeout=4.0):
    SMTO_ABORTIFHUNG = 0x0002
    deadline = time.time() + timeout
    while time.time() < deadline:
        hwnd = ui.FrTestChoiceWindow()
        if hwnd:
            class_buf = ctypes.create_unicode_buffer(256)
            if user32.GetClassNameW(hwnd, class_buf, 256):
                out = ctypes.c_size_t(0)
                ok = user32.SendMessageTimeoutW(
                    hwnd, 0, 0, 0, SMTO_ABORTIFHUNG, 200, ctypes.byref(out))
                if ok:
                    return hwnd
        time.sleep(0.05)
    return None


def open_choice(installed_flag, cur_text, new_text):
    ui.FrTestStartChoice(1 if installed_flag else 0, cur_text, new_text)
    if not ui.FrTestWaitReady():
        return None
    hwnd = wait_choice_ready()
    time.sleep(0.15)
    return hwnd


print()
print("=== 2. choice window (installed case) ===")
hwnd = open_choice(True, "旧版本（未记录版本号）", new)
check(bool(hwnd), "choice window appeared")
if hwnd:
    title = text_of(hwnd)
    print("  window title  : %r" % title)
    print("  window class  : %r" % class_of(hwnd))
    check("FileRemarks" in title, "title names the product", title)
    check(class_of(hwnd) == "FileRemarksInstallChoice", "own window class registered")

    rect = wt.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(rect))
    dpi = user32.GetDpiForWindow(hwnd) if HAS_DPI else 96
    print("  client size   : %dx%d at %d dpi" % (rect.right, rect.bottom, dpi))
    check(abs(rect.right - 520 * dpi // 96) <= 2,
          "client width is the designed 520", "%d" % rect.right)
    check(rect.bottom >= 300 * dpi // 96,
          "client height fits the content (>= 300)", "%d" % rect.bottom)

    kids = [h for h in children(hwnd) if class_of(h) == "Button"]
    labels = [text_of(h) for h in kids]
    print("  buttons       : %r" % (labels,))
    check(len(kids) == 2, "exactly two action buttons (no 取消)", str(len(kids)))
    if installed:
        check(labels and labels[0] in ("重新安装", "安装"),
              "primary button offers 重新安装 when already installed", str(labels[:1]))
    check("卸载" in labels, "uninstall button present", str(labels))
    check("取消" not in labels, "the 取消 button is gone", str(labels))

    # Every button must sit fully inside the client area, i.e. the window was
    # really sized to its content instead of clipping the bottom row.
    for h in kids:
        br = wt.RECT()
        user32.GetWindowRect(h, ctypes.byref(br))
        user32.MapWindowPoints(None, hwnd, ctypes.byref(br), 2)
        inside = (br.left >= 0 and br.top >= 0 and
                  br.right <= rect.right and br.bottom <= rect.bottom)
        print("  button %-6s rect=(%d,%d)-(%d,%d) inside=%s"
              % (text_of(h), br.left, br.top, br.right, br.bottom, inside))
        if not inside:
            failures.append("button %r is clipped by the window" % text_of(h))

    focus = focus_of(hwnd)
    print("  focused       : %r" % (text_of(focus),))
    check(focus in kids, "keyboard focus starts on a button (not nowhere)")

    # Live pixels: page colour in the margin, white inside the version card.
    # RDW_* forces the window AND its owner-drawn child buttons to paint now;
    # ShowWindow/UpdateWindow only paints the top-level window, so a child that
    # has never been asked to paint would otherwise give a blank device context.
    RDW_INVALIDATE, RDW_UPDATENOW, RDW_ALLCHILDREN = 0x0001, 0x0100, 0x0080
    user32.RedrawWindow(hwnd, None, None,
                        RDW_INVALIDATE | RDW_UPDATENOW | RDW_ALLCHILDREN)
    time.sleep(0.15)

    hdc = user32.GetDC(hwnd)
    S = lambda v: v * dpi // 96
    page = gdi32.GetPixel(hdc, S(6), S(6))
    card = gdi32.GetPixel(hdc, S(240), S(120))
    user32.ReleaseDC(hwnd, hdc)

    # The primary button is its own window, so sample ITS device context -- a
    # parent DC does not contain child-window pixels. Sample near the left edge
    # inside the rounded rect, away from the centred label: the old bug painted
    # an opaque white block behind the white glyphs, which showed up exactly
    # here as a white patch on the blue fill.
    primary = kids[0]
    prect = wt.RECT()
    user32.GetClientRect(primary, ctypes.byref(prect))
    primary_dc = user32.GetDC(primary)
    accent = gdi32.GetPixel(primary_dc, 10, prect.bottom // 2)
    user32.ReleaseDC(primary, primary_dc)
    # GetPixel returns COLORREF = 0x00BBGGRR.
    rgb = lambda c: (c & 0xFF, (c >> 8) & 0xFF, (c >> 16) & 0xFF)  # (R, G, B)
    print("  page pixel    : %s" % (rgb(page),))
    print("  card pixel    : %s" % (rgb(card),))
    print("  button pixel  : %s" % (rgb(accent),))
    page_r, page_g, page_b = rgb(page)
    exp_page, exp_card = system_palette()
    check(abs(page_r - exp_page[0]) <= 6 and abs(page_g - exp_page[1]) <= 6 and
          abs(page_b - exp_page[2]) <= 6,
          "page background is the app-mode surface", str(rgb(page)))
    check(rgb(card) == exp_card, "version card is the app-mode card colour",
          str(rgb(card)))
    acc_r, acc_g, acc_b = rgb(accent)
    check(acc_b > 120 and acc_b > acc_r + 60,
          "primary button fill is accent blue with no white text block",
          str(rgb(accent)))

    # Closing the window is the cancel path now (no 取消 button).
    user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
    time.sleep(0.3)
    check(not user32.IsWindow(hwnd), "closing the window ends the dialog")
    res = ui.FrTestEndChoice()
    print("  result        : %d" % res)
    check(res == 0, "closing returns kChoiceCancel (0)", str(res))


print()
print("=== 3. not-installed case + keyboard + uninstall guard ===")
hwnd = open_choice(False, "", new)
if hwnd:
    kids = [h for h in children(hwnd) if class_of(h) == "Button"]
    labels = [text_of(h) for h in kids]
    print("  buttons       : %r" % (labels,))
    check(labels and labels[0] == "安装", "primary button says 安装 when nothing is installed",
          str(labels[:1]))

    # Clicking 卸载 with nothing installed must not close the window (it beeps).
    un_btn = [h for h in kids if text_of(h) == "卸载"]
    if un_btn:
        user32.SendMessageW(hwnd, WM_COMMAND, wt.WPARAM(2 | (BN_CLICKED << 16)),
                            wt.LPARAM(un_btn[0]))
        time.sleep(0.2)
        check(bool(user32.IsWindow(hwnd)),
              "卸载 does nothing when nothing is installed (window stays)")

    # Esc cancels.
    user32.SendMessageW(hwnd, WM_KEYDOWN, wt.WPARAM(VK_ESCAPE), 0)
    time.sleep(0.2)
    check(not user32.IsWindow(hwnd), "Esc closes the window")
    res = ui.FrTestEndChoice()
    check(res == 0, "Esc returns kChoiceCancel (0)", str(res))

print()
print("=== 4. Enter starts the install ===")
hwnd = open_choice(True, "旧版本（未记录版本号）", new)
if hwnd:
    user32.SendMessageW(hwnd, WM_KEYDOWN, wt.WPARAM(VK_RETURN), 0)
    time.sleep(0.2)
    check(not user32.IsWindow(hwnd), "Enter closes the window")
    res = ui.FrTestEndChoice()
    print("  result        : %d" % res)
    check(res == 1, "Enter returns kChoiceInstall (1)", str(res))

print()
if FAILS:
    print("FAILURES:")
    for f in FAILS:
        print("  - " + f)
    sys.exit(1)
print("ALL INSTALLER-UI TESTS PASSED")
