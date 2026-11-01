#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Diagnostic probe: why does GetWindowTextW return "" for the choice window?
import ctypes, ctypes.wintypes as wt, os, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD = os.path.join(ROOT, "build")
user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

H = wt.HWND
user32.FindWindowW.restype = H
user32.FindWindowW.argtypes = [wt.LPCWSTR, wt.LPCWSTR]
user32.GetWindowTextW.restype = ctypes.c_int
user32.GetWindowTextW.argtypes = [H, wt.LPWSTR, ctypes.c_int]
user32.SendMessageW.restype = ctypes.c_ssize_t
user32.SendMessageW.argtypes = [H, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.EnumChildWindows.restype = wt.BOOL
user32.EnumChildWindows.argtypes = [H, ctypes.c_void_p, wt.LPARAM]
user32.GetClassNameW.restype = ctypes.c_int
user32.GetClassNameW.argtypes = [H, wt.LPWSTR, ctypes.c_int]
user32.IsWindow.restype = wt.BOOL
user32.IsWindow.argtypes = [H]
user32.PostMessageW.restype = wt.BOOL
user32.PostMessageW.argtypes = [H, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.GetWindowThreadProcessId.restype = wt.DWORD
user32.GetWindowThreadProcessId.argtypes = [H, ctypes.POINTER(wt.DWORD)]
kernel32.GetCurrentThreadId.restype = wt.DWORD
kernel32.GetCurrentProcessId.restype = wt.DWORD

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
print("ready:", ui.FrTestWaitReady())
hwnd = ui.FrTestChoiceWindow()
print("hwnd:", hwnd, "is_window:", bool(user32.IsWindow(hwnd)))
time.sleep(0.3)

pid = wt.DWORD()
tid = user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
print("window pid=%d tid=%d ; python pid=%d tid=%d"
      % (pid.value, tid, kernel32.GetCurrentProcessId(), kernel32.GetCurrentThreadId()))

buf = ctypes.create_unicode_buffer(512)
n = user32.GetWindowTextW(hwnd, buf, 512)
print("GetWindowTextW ->", n, repr(buf.value))

buf2 = ctypes.create_unicode_buffer(512)
n2 = user32.SendMessageW(hwnd, 0x000D, wt.WPARAM(512), wt.LPARAM(ctypes.addressof(buf2)))
print("WM_GETTEXT ->", n2, repr(buf2.value))

l = user32.SendMessageW(hwnd, 0x000E, 0, 0)
print("WM_GETTEXTLENGTH ->", l)

kids = []
@ctypes.WINFUNCTYPE(wt.BOOL, H, wt.LPARAM)
def cb(h, _l):
    kids.append(h)
    return True
user32.EnumChildWindows(hwnd, ctypes.cast(cb, ctypes.c_void_p), 0)
for h in kids:
    cb2 = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(h, cb2, 256)
    tb = ctypes.create_unicode_buffer(256)
    user32.GetWindowTextW(h, tb, 256)
    tb2 = ctypes.create_unicode_buffer(256)
    user32.SendMessageW(h, 0x000D, wt.WPARAM(256), wt.LPARAM(ctypes.addressof(tb2)))
    print("child %s  GetWindowText=%r  WM_GETTEXT=%r" % (cb2.value, tb.value, tb2.value))

user32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE
time.sleep(0.3)
print("after close, is_window:", bool(user32.IsWindow(hwnd)))
print("end:", ui.FrTestEndChoice())
