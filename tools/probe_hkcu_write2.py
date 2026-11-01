# -*- coding: utf-8 -*-
"""Can this sandbox write anywhere in HKCU? Needed to know whether the
column-default code can be verified end to end here or only on the user's box."""
import ctypes
import ctypes.wintypes as wt
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
HKEY_CURRENT_USER = 0x80000001


class SECURITY_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("nLength", wt.DWORD), ("lpSecurityDescriptor", wt.LPVOID),
                ("bInheritHandle", wt.BOOL)]


advapi32.RegCreateKeyExW.restype = ctypes.c_long
advapi32.RegCreateKeyExW.argtypes = [
    wt.HKEY, wt.LPCWSTR, wt.DWORD, wt.LPWSTR, wt.DWORD, wt.REGSAM,
    ctypes.POINTER(SECURITY_ATTRIBUTES), ctypes.POINTER(wt.HKEY),
    ctypes.POINTER(wt.DWORD),
]

CASES = [
    "Software\\FileRemarks\\Probe",
    "Software\\FileRemarks",
    "Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\FolderTypes\\{5c4f28b5-f869-4e84-8e60-f11db97c5cc7}\\TopViews\\{00000000-0000-0000-0000-000000000000}",
    "Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\FolderTypes\\{5c4f28b5-f869-4e84-8e60-f11db97c5cc7}\\TopViews",
]

for sub in CASES:
    hk = wt.HKEY()
    disp = wt.DWORD()
    rc = advapi32.RegCreateKeyExW(HKEY_CURRENT_USER, sub, 0, None, 0,
                                  wt.KEY_ALL_ACCESS, None, ctypes.byref(hk),
                                  ctypes.byref(disp))
    print("RC 0x%08X  %s" % (rc & 0xFFFFFFFF, sub))
    if rc == 0:
        advapi32.RegCloseKey(hk)
