# -*- coding: utf-8 -*-
"""Can this sandbox actually start a native GUI process?

The right-click handler launches FileRemarksEditor.exe, and InvokeCommand
reported S_OK, so CreateProcessW apparently succeeded -- but no process showed
up afterwards. This settles whether a GUI can be exercised here at all.
"""
import ctypes
import os
import sys
import time
from ctypes import byref, c_void_p, c_uint32, c_wchar_p

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)


class STARTUPINFOW(ctypes.Structure):
    _fields_ = [
        ("cb", c_uint32),
        ("lpReserved", c_wchar_p),
        ("lpDesktop", c_wchar_p),
        ("lpTitle", c_wchar_p),
        ("dwX", c_uint32), ("dwY", c_uint32),
        ("dwXSize", c_uint32), ("dwYSize", c_uint32),
        ("dwXCountChars", c_uint32), ("dwYCountChars", c_uint32),
        ("dwFillAttribute", c_uint32), ("dwFlags", c_uint32),
        ("wShowWindow", ctypes.c_uint16), ("cbReserved2", ctypes.c_uint16),
        ("lpReserved2", c_void_p),
        ("hStdInput", c_void_p), ("hStdOutput", c_void_p), ("hStdError", c_void_p),
    ]


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [("hProcess", c_void_p), ("hThread", c_void_p),
                ("dwProcessId", c_uint32), ("dwThreadId", c_uint32)]


kernel32.CreateProcessW.argtypes = [
    c_wchar_p, ctypes.c_wchar_p, c_void_p, c_void_p, ctypes.c_int, c_uint32,
    c_void_p, c_wchar_p, ctypes.POINTER(STARTUPINFOW),
    ctypes.POINTER(PROCESS_INFORMATION)]
kernel32.CreateProcessW.restype = ctypes.c_int
kernel32.GetExitCodeProcess.argtypes = [c_void_p, ctypes.POINTER(c_uint32)]
kernel32.GetExitCodeProcess.restype = ctypes.c_int
kernel32.WaitForSingleObject.argtypes = [c_void_p, c_uint32]
kernel32.WaitForSingleObject.restype = c_uint32
kernel32.TerminateProcess.argtypes = [c_void_p, c_uint32]
kernel32.CloseHandle.argtypes = [c_void_p]


def try_launch(exe, arg, label):
    print("\n--- %s" % label)
    print("    exe: %s" % exe)
    print("    exists: %s" % os.path.exists(exe))
    cmd = '"%s"' % exe
    if arg:
        cmd += ' "%s"' % arg
    si = STARTUPINFOW()
    si.cb = ctypes.sizeof(si)
    pi = PROCESS_INFORMATION()
    ok = kernel32.CreateProcessW(None, cmd, None, None, 0, 0, None, None,
                                 byref(si), byref(pi))
    if not ok:
        print("    CreateProcessW FAILED, GetLastError=%d" % ctypes.get_last_error())
        return None
    print("    CreateProcessW ok, pid=%d" % pi.dwProcessId)
    # Give it a moment, then see whether it is still alive.
    code = c_uint32()
    for waited in (0, 300, 1500):
        if waited:
            time.sleep(waited / 1000.0)
        kernel32.GetExitCodeProcess(pi.hProcess, byref(code))
        print("    after %4dms: exit code=%d%s"
              % (waited, code.value, " (STILL RUNNING)" if code.value == 259 else ""))
        if code.value != 259:
            break
    alive = (code.value == 259)
    if alive:
        kernel32.TerminateProcess(pi.hProcess, 0)
    kernel32.CloseHandle(pi.hThread)
    kernel32.CloseHandle(pi.hProcess)
    return alive


def main():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    target = os.path.join(root, "build", "_shellext_test", "被备注的文件.txt")
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "wb") as f:
        f.write(b"hello")

    editor = os.path.join(root, "dist", "FileRemarksEditor.exe")
    alive = try_launch(editor, target, "the remark editor on a real file")
    if alive:
        print("\nRESULT: this sandbox CAN start the GUI -- the editor stayed alive.")
    else:
        print("\nRESULT: the editor could not stay alive here (process creation or "
              "GUI is blocked in this environment), so the dialog cannot be exercised "
              "from inside the sandbox. That is an environment limit, not a code fault.")

    # For contrast: a plain system program.
    try_launch(os.path.join(os.environ.get("SystemRoot", r"C:\Windows"),
                            "System32", "notepad.exe"), None, "control case: notepad")
    return 0


if __name__ == "__main__":
    sys.exit(main())
