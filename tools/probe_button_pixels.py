#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Diagnostic: what does the primary button actually contain pixel-wise?
import ctypes, ctypes.wintypes as wt, os, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD = os.path.join(ROOT, "build")
user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
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
user32.GetDC.restype = wt.HDC
user32.GetDC.argtypes = [H]
user32.ReleaseDC.restype = ctypes.c_int
user32.ReleaseDC.argtypes = [H, wt.HDC]
user32.RedrawWindow.restype = wt.BOOL
user32.RedrawWindow.argtypes = [H, ctypes.c_void_p, H, wt.UINT]
user32.GetClientRect.restype = wt.BOOL
user32.GetClientRect.argtypes = [H, ctypes.POINTER(wt.RECT)]
user32.IsWindow.restype = wt.BOOL
user32.IsWindow.argtypes = [H]
user32.PostMessageW.restype = wt.BOOL
user32.PostMessageW.argtypes = [H, wt.UINT, wt.WPARAM, wt.LPARAM]
gdi32.GetPixel.restype = DWORD
gdi32.GetPixel.argtypes = [wt.HDC, ctypes.c_int, ctypes.c_int]

ui = ctypes.WinDLL(os.path.join(BUILD, "selftest_installer_ui.dll"))
ui.FrTestStartChoice.restype = ctypes.c_int
ui.FrTestStartChoice.argtypes = [ctypes.c_int, wt.LPCWSTR, wt.LPCWSTR]
ui.FrTestWaitReady.restype = ctypes.c_int
ui.FrTestWaitReady.argtypes = []
ui.FrTestChoiceWindow.restype = H
ui.FrTestChoiceWindow.argtypes = []
ui.FrTestEndChoice.restype = ctypes.c_int
ui.FrTestEndChoice.argtypes = []

ui.FrTestStartChoice(1, "旧版本（未记录版本号）", "v1.4（本安装包）")
ui.FrTestWaitReady()
hwnd = ui.FrTestChoiceWindow()
time.sleep(0.4)
user32.RedrawWindow(hwnd, None, None, 0x0001 | 0x0100 | 0x0080)
time.sleep(0.3)

kids = []
@ctypes.WINFUNCTYPE(wt.BOOL, H, wt.LPARAM)
def cb(h, _l):
    kids.append(h)
    return True
user32.EnumChildWindows(hwnd, ctypes.cast(cb, ctypes.c_void_p), 0)

for h in kids:
    t = ctypes.create_unicode_buffer(128)
    user32.GetWindowTextW(h, t, 128)
    c = ctypes.create_unicode_buffer(128)
    user32.GetClassNameW(h, c, 128)
    r = wt.RECT()
    user32.GetClientRect(h, ctypes.byref(r))
    dc = user32.GetDC(h)
    px = []
    for yy in (2, 6, r.bottom // 2, r.bottom - 3):
        row = []
        for xx in (2, 6, r.right // 2, r.right - 3):
            v = gdi32.GetPixel(dc, xx, yy)
            row.append((v & 0xFF, (v >> 8) & 0xFF, (v >> 16) & 0xFF))
        px.append(row)
    user32.ReleaseDC(h, dc)
    print("%-6s %-8s size=%dx%d" % (c.value, t.value, r.right, r.bottom))
    for row in px:
        print("     ", row)

user32.PostMessageW(hwnd, 0x0010, 0, 0)
time.sleep(0.2)
print("end:", ui.FrTestEndChoice())
