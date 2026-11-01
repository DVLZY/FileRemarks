"""Prove the v1.9 installer never asks for elevation.

The whole point of the per-user redesign is that nothing calls `runas` any
more: no UAC prompt, and therefore no SmartScreen "发行者未知" dialog either
(Windows only runs that reputation check when an unsigned exe asks to elevate).

Three independent checks, all against the real shipped installer:

  1. the process we launch is NOT elevated, and stays that way -- if the old
     self-elevation code were still there, a second, elevated instance would
     appear with a different pid and an administrator token;
  2. the install choice window comes up from that same unelevated pid, which
     is only possible when no elevation step stands in front of it;
  3. no SmartScreen window appears while all this happens.

Window watching runs for the FULL duration and never breaks on the first
window: SmartScreen shows up after the launcher window, not before, and an
early exit is exactly how earlier probes produced false negatives.

Run:  python tools/probe_no_elevation.py
"""
import ctypes
import ctypes.wintypes as w
import os
import re
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
def newest_setup():
    """The newest versioned installer in dist/releases (never a fixed name, so a
    version bump cannot silently make this probe test an old build)."""
    d = os.path.join(ROOT, "dist", "releases")
    best = None
    for name in os.listdir(d):
        m = re.match(r"^FileRemarks_Setup_v(\d+(?:\.\d+)*)\.exe$", name)
        if not m:
            continue
        ver = tuple(int(x) for x in m.group(1).split("."))
        if best is None or ver > best[0]:
            best = (ver, os.path.join(d, name))
    return best[1] if best else None


SETUP = newest_setup()
WORK = os.path.join(ROOT, "build", "_no_elev")

WATCH = 18.0
POLL = 0.2

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
user32 = ctypes.WinDLL("user32", use_last_error=True)
advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PROCESS_QUERY_INFORMATION = 0x0400
TOKEN_QUERY = 0x0008
TokenElevation = 20
SEE_MASK_NOCLOSEPROCESS = 0x00000040


class STARTUPINFOW(ctypes.Structure):
    _fields_ = [("cb", w.DWORD), ("lpReserved", w.LPWSTR), ("lpDesktop", w.LPWSTR),
                ("lpTitle", w.LPWSTR), ("dwX", w.DWORD), ("dwY", w.DWORD),
                ("dwXSize", w.DWORD), ("dwYSize", w.DWORD),
                ("dwXCountChars", w.DWORD), ("dwYCountChars", w.DWORD),
                ("dwFillAttribute", w.DWORD), ("dwFlags", w.DWORD),
                ("wShowWindow", w.WORD), ("cbReserved2", w.WORD),
                ("lpReserved2", ctypes.c_void_p), ("hStdInput", w.HANDLE),
                ("hStdOutput", w.HANDLE), ("hStdError", w.HANDLE)]


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [("hProcess", w.HANDLE), ("hThread", w.HANDLE),
                ("dwProcessId", w.DWORD), ("dwThreadId", w.DWORD)]


def elevation_state(pid):
    """Return True when the process token is elevated, False when not, None if unknown."""
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return None
    try:
        tok = w.HANDLE()
        if not advapi32.OpenProcessToken(w.HANDLE(h), TOKEN_QUERY, ctypes.byref(tok)):
            return None
        try:
            info = ctypes.c_ulong(0)
            size = w.DWORD(ctypes.sizeof(info))
            if not advapi32.GetTokenInformation(tok, TokenElevation,
                                                ctypes.byref(info), size,
                                                ctypes.byref(size)):
                return None
            return bool(info.value)
        finally:
            kernel32.CloseHandle(tok)
    finally:
        kernel32.CloseHandle(h)


def image_of(pid):
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = w.DWORD(1024)
        if kernel32.QueryFullProcessImageNameW(w.HANDLE(h), 0, buf, ctypes.byref(size)):
            return os.path.basename(buf.value)
        return ""
    finally:
        kernel32.CloseHandle(h)


def class_of(hwnd):
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def caption_of(hwnd):
    buf = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(hwnd, buf, 512)
    return buf.value


def visible_windows():
    out = []

    @ctypes.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
    def cb(hwnd, _lp):
        if user32.IsWindowVisible(hwnd):
            pid = w.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            out.append((hwnd, pid.value, class_of(hwnd), caption_of(hwnd)))
        return True

    user32.EnumWindows(cb, 0)
    return out


def main():
    os.makedirs(WORK, exist_ok=True)
    local = os.path.join(WORK, os.path.basename(SETUP))
    with open(SETUP, "rb") as f:
        data = f.read()
    with open(local, "wb") as f:
        f.write(data)
    # A copy of a file we have never launched keeps SmartScreen from short-circuiting.
    print("installer : %s (%d bytes)" % (os.path.basename(local), len(data)))

    si = STARTUPINFOW()
    si.cb = ctypes.sizeof(si)
    pi = PROCESS_INFORMATION()
    cmd = ctypes.create_unicode_buffer('"%s"' % local)
    ok = kernel32.CreateProcessW(local, cmd, None, None, False, 0, None,
                                 WORK, ctypes.byref(si), ctypes.byref(pi))
    print("launch ->", bool(ok))
    if not ok:
        print("could not launch")
        return 1

    root_pid = pi.dwProcessId
    root_elev = elevation_state(root_pid)
    print("launched pid=%d elevated=%s" % (root_pid, root_elev))

    seen = set()
    choice = []
    smart = []
    elevated_instances = []
    deadline = time.time() + WATCH
    while time.time() < deadline:
        for hwnd, pid, cls, cap in visible_windows():
            if hwnd in seen:
                continue
            seen.add(hwnd)
            if pid <= 4:
                continue
            if "smart" in cap.lower() or "smart" in cls.lower() or \
                    "defender" in cls.lower() or "defender" in cap.lower():
                smart.append((pid, cls, cap))
                print("  !! SMARTSREEN pid=%d class=%s caption=%s" % (pid, cls, cap))
                continue
            if cls == "FileRemarksInstallChoice":
                choice.append((pid, cap))
                print("  install window pid=%d caption=%s elevated=%s"
                      % (pid, cap, elevation_state(pid)))
            elif cls in ("Static", "#32770", "ProxyModalWindow", "ApplicationFrameWindow"):
                print("  window pid=%d class=%s caption=%s img=%s"
                      % (pid, cls, cap, image_of(pid)))
        # Any *new* process running our installer must not have an admin token.
        for hwnd, pid, cls, cap in list(visible_windows()):
            if "FileRemarks" in image_of(pid) and pid != root_pid:
                if elevation_state(pid) and pid not in elevated_instances:
                    elevated_instances.append(pid)
        time.sleep(POLL)

    # Close whatever is still open so nothing gets installed.
    for hwnd, pid, cls, cap in visible_windows():
        if pid == root_pid or "FileRemarks" in image_of(pid):
            user32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE
    time.sleep(0.6)
    kernel32.TerminateProcess(pi.hProcess, 0)
    kernel32.CloseHandle(pi.hThread)
    kernel32.CloseHandle(pi.hProcess)

    print()
    failures = []
    if root_elev:
        failures.append("the installer itself started elevated")
    if not choice:
        failures.append("no install window came from the unelevated pid")
    elif any(p != root_pid for p, _c in choice):
        failures.append("the install window belongs to a different (elevated) instance")
    if smart:
        failures.append("SmartScreen appeared")
    if elevated_instances:
        failures.append("a second, elevated instance of the installer appeared")
    if failures:
        print("FAILURES:")
        for f in failures:
            print("  - " + f)
        return 1
    print("installer pid %d is unelevated, the window came from it, "
          "no UAC, no SmartScreen" % root_pid)
    print("ALL NO-ELEVATION CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
