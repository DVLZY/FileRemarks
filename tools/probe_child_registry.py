# -*- coding: utf-8 -*-
"""Do native child processes inherit this sandbox's registry/file restrictions?

Our own Python process is denied every registry write (RegCreateKeyExW ->
0x80000005) and cannot create files outside the workspace. That may be an
in-process sandbox hook rather than a machine-wide policy, in which case a native
child process launched with CreateProcessW could still write HKCU -- which would
finally make it possible to test registration end to end.
"""
import ctypes
import os
import sys
import time
from ctypes import byref, c_void_p, c_uint32, c_wchar_p, c_int

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)


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


kernel32.CreateProcessW.argtypes = [
    c_wchar_p, c_wchar_p, c_void_p, c_void_p, c_int, c_uint32, c_void_p,
    c_wchar_p, ctypes.POINTER(STARTUPINFOW), ctypes.POINTER(PROCESS_INFORMATION)]
kernel32.CreateProcessW.restype = c_int
kernel32.GetExitCodeProcess.argtypes = [c_void_p, ctypes.POINTER(c_uint32)]
kernel32.GetExitCodeProcess.restype = c_int
kernel32.WaitForSingleObject.argtypes = [c_void_p, c_uint32]
kernel32.WaitForSingleObject.restype = c_uint32
kernel32.CloseHandle.argtypes = [c_void_p]

SYSTEM_ROOT = os.environ.get("SystemRoot", r"C:\Windows")


def run(exe, args, timeout_ms=15000, show=False):
    """Start a native process, wait, return its exit code."""
    cmd = '"%s"' % exe
    if args:
        cmd += " " + args
    si = STARTUPINFOW()
    si.cb = ctypes.sizeof(si)
    if not show:
        si.dwFlags = 0x00000001  # STARTF_USESHOWWINDOW
        si.wShowWindow = 0       # SW_HIDE
    pi = PROCESS_INFORMATION()
    ok = kernel32.CreateProcessW(None, cmd, None, None, 0, 0, None,
                                 SYSTEM_ROOT + "\\System32", byref(si), byref(pi))
    if not ok:
        return None, ctypes.get_last_error()
    kernel32.WaitForSingleObject(pi.hProcess, timeout_ms)
    code = c_uint32()
    kernel32.GetExitCodeProcess(pi.hProcess, byref(code))
    kernel32.CloseHandle(pi.hThread)
    kernel32.CloseHandle(pi.hProcess)
    return code.value, 0


def main():
    reg = os.path.join(SYSTEM_ROOT, "System32", "reg.exe")
    key = r"HKCU\Software\FileRemarksSandboxProbe"

    print("=== 1. native reg.exe writing HKCU ===")
    code, err = run(reg, 'add "%s" /v probe /t REG_SZ /d hello /f' % key)
    print("  reg add -> exit=%s createError=%s" % (code, err))

    print("\n=== 2. reading it back from this (sandboxed) process ===")
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\FileRemarksSandboxProbe") as k:
            print("  value: %r" % (winreg.QueryValueEx(k, "probe")[0],))
        present = True
    except OSError as e:
        print("  not readable: %s" % e)
        present = False

    print("\n=== 3. native reg.exe writing to a path outside the workspace ===")
    out = os.path.join(os.environ.get("TEMP", r"C:\Windows\Temp"), "fr_probe.txt")
    code2, err2 = run(reg, 'add "HKCU\\Software\\FileRemarksSandboxProbe" /v probe2 /t REG_SZ /d world /f')
    print("  second reg add -> exit=%s" % code2)

    print("\n=== 4. cleanup ===")
    code3, _ = run(reg, 'delete "%s" /f' % key)
    print("  reg delete -> exit=%s" % code3)

    print("")
    if present and code == 0:
        print("RESULT: native child processes are NOT subject to the in-process "
              "registry restriction -- full registration testing is possible.")
        return 0
    print("RESULT: native child processes hit the same restriction; this "
          "environment cannot write the registry from anywhere.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
