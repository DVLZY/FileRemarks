# -*- coding: utf-8 -*-
"""Watch a launch and report EVERY new window, for a fixed full duration.

This is the instrument every earlier probe should have been: it never stops at
the first new window, so windows that appear seconds later are still reported.

Usage: python tools/watch_run.py <exe-to-launch> [seconds]

The SmartScreen dialog is a Windows.UI.Core.CoreWindow owned by explorer.exe, it
shows up several seconds after the launch, so a short watch misses it.
"""

import ctypes
import os
import sys
import time
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
WM_CLOSE = 0x0010


def say(*a):
    print(*a)
    sys.stdout.flush()


def image(pid):
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return ""
    b = ctypes.create_unicode_buffer(4096)
    n = ctypes.c_ulong(4096)
    ok = kernel32.QueryFullProcessImageNameW(h, 0, b, ctypes.byref(n))
    kernel32.CloseHandle(h)
    return os.path.basename(b.value) if ok else ""


def wtext(h):
    n = user32.GetWindowTextLengthW(h)
    b = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(h, b, n + 1)
    return b.value


def wclass(h):
    b = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(h, b, 256)
    return b.value


def wpid(h):
    p = wintypes.DWORD(0)
    user32.GetWindowThreadProcessId(h, ctypes.byref(p))
    return p.value


def wins():
    out = {}
    E = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def cb(h, _l):
        if user32.IsWindowVisible(h):
            out[h] = (wtext(h), wclass(h), wpid(h))
        return True

    user32.EnumWindows(E(cb), 0)
    return out


def main():
    exe = sys.argv[1]
    secs = float(sys.argv[2]) if len(sys.argv) > 2 else 25.0

    before = set(wins())
    si = ctypes.create_string_buffer(104)
    ctypes.memset(si, 0, 104)
    ctypes.cast(si, ctypes.POINTER(wintypes.DWORD))[0] = 104
    pi = ctypes.create_string_buffer(24)
    ctypes.memset(pi, 0, 24)
    ok = kernel32.CreateProcessW(exe, None, None, None, False, 0, None,
                                 os.path.dirname(exe), si, pi)
    say("launch %s -> %s" % (os.path.basename(exe), bool(ok)))

    seen = {}
    t0 = time.time()
    while time.time() - t0 < secs:
        for h, (t, c, p) in wins().items():
            if h in before or h in seen:
                continue
            seen[h] = (t, c, p)
            blob = (t + " " + c).lower()
            mark = ""
            if "smartscreen" in blob or "defender" in blob:
                mark = "   <<<<< SMARTSREEN PROMPT"
            say("[%5.1fs] class=%-32s caption=%-30s pid=%-6d img=%s%s" % (
                time.time() - t0, c, t[:30], p, image(p), mark))
        time.sleep(0.2)

    ss = [1 for (t, c, p) in seen.values()
          if "smartscreen" in (t + " " + c).lower() or "defender" in (t + " " + c).lower()]
    say("")
    say("new windows: %d   smart screen windows: %d" % (len(seen), len(ss)))

    for h in seen:
        user32.PostMessageW(h, WM_CLOSE, 0, 0)
    prog = ctypes.cast(pi, ctypes.POINTER(wintypes.HANDLE))[0] if ok else None
    if prog:
        kernel32.TerminateProcess(prog, 0)
        kernel32.CloseHandle(prog)
    return 0


if __name__ == "__main__":
    sys.exit(main())
