# -*- coding: utf-8 -*-
"""Does ELEVATION ALONE bring up the SmartScreen prompt?

Two series of identical launches, same watch window, same machine state:

  series ELEV   -> build/elev_probe.exe   (does nothing but ShellExecuteExW
                                           "runas" on itself, then exits)
  series PLAIN  -> dist/FileRemarksEditor.exe  (never requests elevation)

If the prompt shows up only in the ELEV series, the elevation request is the
trigger and a no-admin (per-user) install removes it without a certificate.

Both binaries get random trailing bytes first, so SmartScreen has never judged
these exact hashes before; without that, a cached "still run" verdict from an
earlier test would suppress the prompt and hide the real cause.
"""

import ctypes
import hashlib
import os
import random
import shutil
import sys
import time
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

ROOT = r"E:\AIAgent\DeepSeekHarness\Default\FileRemarks"
WORK = os.path.join(ROOT, "build", "_elev_series")
RUNS = 7
WATCH = 20.0
WM_CLOSE = 0x0010
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


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


def mint(src, name):
    """Copy `src` under a name SmartScreen has never seen, and strip any mark."""
    dst = os.path.join(WORK, name)
    shutil.copyfile(src, dst)
    try:
        os.remove(dst + ":Zone.Identifier")
    except OSError:
        pass
    with open(dst, "ab") as f:
        f.write(bytes(random.getrandbits(8) for _ in range(64)))
    with open(dst, "rb") as f:
        return dst, hashlib.sha256(f.read()).hexdigest()[:16]


def run_once(exe):
    before = set(wins())
    si = ctypes.create_string_buffer(104)
    ctypes.memset(si, 0, 104)
    ctypes.cast(si, ctypes.POINTER(wintypes.DWORD))[0] = 104
    pi = ctypes.create_string_buffer(24)
    ctypes.memset(pi, 0, 24)
    ok = kernel32.CreateProcessW(exe, None, None, None, False, 0, None,
                                 os.path.dirname(exe), si, pi)
    if not ok:
        return None, []

    seen = {}
    t0 = time.time()
    while time.time() - t0 < WATCH:
        for h, (t, c, p) in wins().items():
            if h in before or h in seen:
                continue
            seen[h] = (t, c, p)
            blob = (t + " " + c).lower()
            if "smartscreen" in blob or "defender" in blob:
                say("      [%4.1fs] SMARTSREEN  class=%s" % (time.time() - t0, c))
        time.sleep(0.2)

    prompts = [1 for (t, c, p) in seen.values()
               if "smartscreen" in (t + " " + c).lower()
               or "defender" in (t + " " + c).lower()]

    for h in seen:
        user32.PostMessageW(h, WM_CLOSE, 0, 0)
    time.sleep(0.8)
    prog = ctypes.cast(pi, ctypes.POINTER(wintypes.HANDLE))[0]
    if prog:
        kernel32.TerminateProcess(prog, 0)
        kernel32.CloseHandle(prog)
    time.sleep(0.8)
    return bool(prompts), [seen[h] for h in seen]


def series(label, src, tag):
    say("")
    say("#####################  %s  #####################" % label)
    hits = 0
    for i in range(1, RUNS + 1):
        exe, short = mint(src, "%s_%d.exe" % (tag, i))
        say("  run %d  (%s)%s" % (i, short, ""))
        prompt, windows = run_once(exe)
        if prompt is None:
            say("      launch failed")
            continue
        say("      windows: %s" % ", ".join(sorted({c for (_t, c, _p) in windows})))
        say("      -> %s" % ("PROMPT" if prompt else "clean"))
        hits += 1 if prompt else 0
    say("  %s: %d/%d runs showed the prompt" % (label, hits, RUNS))
    return hits


def main():
    os.makedirs(WORK, exist_ok=True)
    elev_hits = series("ELEVATING (elev_probe.exe -- does nothing but request admin)",
                       os.path.join(ROOT, "build", "elev_probe.exe"), "E")
    plain_hits = series("NON-ELEVATING (FileRemarksEditor.exe -- never requests admin)",
                        os.path.join(ROOT, "dist", "FileRemarksEditor.exe"), "P")

    say("")
    say("=================== verdict ===================")
    say("  elevating     : %d/%d runs prompted" % (elev_hits, RUNS))
    say("  non-elevating : %d/%d runs prompted" % (plain_hits, RUNS))
    if elev_hits and not plain_hits:
        say("  => CONFIRMED: requesting elevation is what raises 发行者未知.")
        say("     Fix: install per-user (no admin), so no runas, so no prompt --")
        say("     and no certificate purchase needed.")
    elif not elev_hits and not plain_hits:
        say("  => neither series prompted this time; the check is probabilistic.")
        say("     Repeat, or treat the installer's own elevation as the only")
        say("     structural difference and remove it anyway.")
    else:
        say("  => both prompted; elevation is not the sole trigger.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
