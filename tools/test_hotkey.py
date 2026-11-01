"""Verify the Shift+F2 shortcut helper (FileRemarksHotkey.exe).

What can be proven from this session, and what cannot:

  * PROVEN here -- the helper is a single-instance background process that
    really holds the shortcut Shift+F2, that it exposes the combination it
    registered, that a second launch exits instead of registering a duplicate,
    that WM_CLOSE stops it (which is what the uninstaller needs before it can
    delete the .exe), and that the same launch code opens the editor for a file.
  * NOT provable here -- the actual key press. A global hotkey is delivered by
    the window manager to whatever window has focus, and this session cannot
    own the foreground (`SetForegroundWindow`/`SetFocus` return 0 and
    `keybd_event` is ignored), so pressing Shift+F2 cannot be simulated.
    What the shortcut then does -- ask the shell for the selected item and open
    the editor -- is exercised directly through the shipped functions.

Run:  python tools/test_hotkey.py
"""
import ctypes
import ctypes.wintypes as w
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
HOTKEY = os.path.join(ROOT, "dist", "FileRemarksHotkey.exe")
DLL = os.path.join(ROOT, "build", "selftest_hotkey.dll")
WORK = os.path.join(ROOT, "build", "_hotkey_test")
TARGET = os.path.join(WORK, "快捷键测试.txt")

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
user32 = ctypes.WinDLL("user32", use_last_error=True)
ole32 = ctypes.WinDLL("ole32", use_last_error=True)

WM_APP = 0x8000
WM_QUERY_COMBO = WM_APP + 7
WM_CLOSE = 0x0010
MOD_ALT = 0x0001
MOD_SHIFT = 0x0004

fails = []


def check(ok, label, detail=""):
    print(("  PASS  " if ok else "  FAIL  ") + label + (("  [" + detail + "]") if detail else ""))
    if not ok:
        fails.append(label)
    return ok


def launch(exe, directory=None):
    """CreateProcessW: the only launch route that works from this sandbox."""
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = 0
    return subprocess.Popen([exe], cwd=directory or os.path.dirname(exe),
                            startupinfo=si, close_fds=True)


def wait_window(class_name, timeout=6.0):
    class_buf_len = 256
    deadline = time.time() + timeout
    while time.time() < deadline:
        hwnd = user32.FindWindowW(class_name, None)
        if hwnd:
            return hwnd
        time.sleep(0.05)
    return None


def wait_gone(class_name, timeout=6.0):
    """True once no window of `class_name` exists any more."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not user32.FindWindowW(class_name, None):
            return True
        time.sleep(0.05)
    return False


def kill_stale_helpers():
    """Terminate any helper left over from an earlier run or install.

    Needed because the window class is global: a stale instance from a previous
    version would answer FindWindow first and the checks below would describe
    the OLD process (its combination, its WM_CLOSE behaviour) instead of the
    binary under test.
    """
    for _ in range(60):
        hwnd = user32.FindWindowW("FileRemarksHotkeyWnd", None)
        if not hwnd:
            return True
        pid = pid_of_window(hwnd)
        handle = kernel32.OpenProcess(0x0001, False, pid)  # PROCESS_TERMINATE
        if handle:
            kernel32.TerminateProcess(handle, 0)
            kernel32.CloseHandle(handle)
        time.sleep(0.1)
    return False


def pid_of_window(hwnd):
    pid = w.DWORD(0)
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def main():
    print("=== shortcut helper ===")
    for name, path in (("dist/FileRemarksHotkey.exe", HOTKEY), ("build/selftest_hotkey.dll", DLL)):
        if not check(os.path.isfile(path), name + " exists"):
            return 1

    check(kill_stale_helpers(), "no helper from an earlier run is still resident")

    os.makedirs(WORK, exist_ok=True)
    with open(TARGET, "w", encoding="utf-8") as handle:
        handle.write("x")

    # --- the combination in code -------------------------------------------
    dll = ctypes.WinDLL(DLL)
    dll.FrTestPackedCombo.restype = ctypes.c_uint
    combo = dll.FrTestPackedCombo()
    expected = (MOD_SHIFT << 16) | 0x71  # VK_F2
    check(combo == expected, "shortcut is Shift+F2",
          "0x%08X vs 0x%08X" % (combo, expected))

    # --- the running helper -------------------------------------------------
    # Start from an empty trace file so the check below can only pass on a line
    # this run wrote.
    log_path = os.path.join(os.environ.get("TEMP", ""), "FileRemarks_hotkey.log")
    if os.path.isfile(log_path):
        os.remove(log_path)

    first = launch(HOTKEY)
    hwnd = wait_window("FileRemarksHotkeyWnd", 6.0)
    if not check(hwnd is not None, "helper window is up (so the hotkey registered)"):
        first.kill()
        return 1

    hotkey_pid = pid_of_window(hwnd)

    # "I pressed it and nothing happened" must be answerable after the fact.
    traced = ""
    deadline = time.time() + 3.0
    while time.time() < deadline and not traced:
        if os.path.isfile(log_path):
            with open(log_path, encoding="utf-8", errors="replace") as handle:
                traced = handle.read()
        if "helper started" not in traced:
            time.sleep(0.05)
    check("helper started" in traced,
          r"the helper leaves a trace in %TEMP%\FileRemarks_hotkey.log", repr(traced.strip()[:60]))

    # The process reports the combination it actually registered; this is what
    # ties the running binary to the constants above.
    asked = user32.SendMessageW(hwnd, WM_QUERY_COMBO, 0, 0) & 0xFFFFFFFF
    check(asked == expected, "running helper holds Shift+F2", "0x%08X" % asked)

    # --- single instance ----------------------------------------------------
    second = launch(HOTKEY)
    try:
        code = second.wait(timeout=6.0)
        exited = True
    except subprocess.TimeoutExpired:
        exited = False
        second.kill()
    check(exited, "a second launch exits instead of sitting in memory",
          "exit=%s" % (code if exited else "still running"))
    check(user32.FindWindowW("FileRemarksHotkeyWnd", None) is not None,
          "the first instance is still the one holding the shortcut")

    # --- the action the shortcut performs -----------------------------------
    dll.FrTestLaunchIn.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
    dll.FrTestLaunchIn.restype = ctypes.c_int
    opened = dll.FrTestLaunchIn(os.path.join(ROOT, "dist"), TARGET)
    check(bool(opened), "the shipped launch code starts the editor for a file")

    editor_hwnd = None
    deadline = time.time() + 8.0
    while time.time() < deadline and not editor_hwnd:
        found = []
        user32.EnumWindows(
            ctypes.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)(
                lambda h, l: (found.append(h), True)[1]), 0)
        for h in found:
            buf = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(h, buf, 256)
            if buf.value == "FileRemarksEditorWnd":
                editor_hwnd = h
                break
        time.sleep(0.05)
    if check(editor_hwnd is not None, "an editor window appeared for that file"):
        user32.PostMessageW(editor_hwnd, WM_CLOSE, 0, 0)
        time.sleep(0.6)

    # --- selection lookup with nothing usable ------------------------------
    ole32.CoInitialize(None)
    dll.FrTestSelectedPath.argtypes = [ctypes.c_void_p]
    dll.FrTestSelectedPath.restype = ctypes.c_wchar_p
    empty = dll.FrTestSelectedPath(None)
    check(not empty, "no window means no selection (never a stale path)", repr(empty))

    # The foreground window here is this console/python, not Explorer, so the
    # lookup must decline instead of guessing.
    foreground = user32.GetForegroundWindow()
    other = dll.FrTestSelectedPath(ctypes.c_void_p(foreground))
    check(not other, "a non-Explorer window yields no path", repr(other))
    ole32.CoUninitialize()

    # --- stopping it (the uninstaller's route) ------------------------------
    user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
    check(wait_gone("FileRemarksHotkeyWnd", 6.0),
          "WM_CLOSE removes the helper window (the uninstaller's stop route)")

    exited = False
    code = None
    try:
        code = first.wait(timeout=6.0)
        exited = True
    except subprocess.TimeoutExpired:
        first.kill()
    check(exited, "the helper process really ends (a running .exe cannot be deleted)",
          "exit=%s" % (code if exited else "still running"))

    print()
    if fails:
        print("FAILED: %d check(s) -- %s" % (len(fails), "; ".join(fails)))
        return 1
    print("ALL HOTKEY CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
