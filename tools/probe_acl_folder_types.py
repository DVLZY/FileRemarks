# -*- coding: utf-8 -*-
"""Read-only: can the current user open each folder type's default-view key for
WRITE, and is System.Comment already in the live list?

Why this matters: v1.8 ran elevated and wrote HKLM. It stored a backup for all
six folder types (so ReadCurrentList() found a list for all six) but the live
ColumnList only ends up containing System.Comment for Music and Videos. The
remaining explanation is a write refusal on the other four view keys -- and the
ACLs earlier showed Generic's view key grants Users only ReadKey, while the
parent FolderTypes key does not. So measure the open-for-write result directly.

HKEY_LOCAL_MACHINE is 0x80000002, which does not fit a 32-bit c_void_p on 64-bit
Python's int->pointer conversion, hence the explicit c_void_p() wrapping.
"""
import ctypes
import sys
import winreg as wr
from ctypes import wintypes

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

VIEW = r"\TopViews\{00000000-0000-0000-0000-000000000000}"
FT = r"Software\Microsoft\Windows\CurrentVersion\Explorer\FolderTypes"

WANT = [
    ("{5c4f28b5-f869-4e84-8e60-f11db97c5cc7}", "Generic"),
    ("{7d49d726-3c21-4f05-99aa-fdc2c9474656}", "Documents"),
    ("{b3690e58-e961-423b-b687-386ebfd83239}", "Pictures"),
    ("{885a186e-a440-4ada-812b-db871b942259}", "Downloads"),
    ("{94d6ddcc-4a68-4175-a374-bd584a510b78}", "Music"),
    ("{5fa96407-7e77-483c-ac93-691d05850de8}", "Videos"),
]

advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
advapi32.RegOpenKeyExW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p,
                                   wintypes.DWORD, wintypes.DWORD,
                                   ctypes.POINTER(ctypes.c_void_p)]
advapi32.RegOpenKeyExW.restype = wintypes.LONG
advapi32.RegCloseKey.argtypes = [ctypes.c_void_p]

KEY_READ = 0x20019
KEY_WRITE = 0x20006
HKCU = ctypes.c_void_p(0x80000001)
HKLM = ctypes.c_void_p(0x80000002)


def can_open(root, path, access):
    hk = ctypes.c_void_p()
    rc = advapi32.RegOpenKeyExW(root, path, 0, access, ctypes.byref(hk))
    if rc == 0:
        advapi32.RegCloseKey(hk)
        return 0
    return rc


print("=" * 78)
print("RegOpenKeyExW with KEY_WRITE  (rc 0 = allowed)")
for guid, label in WANT:
    path = FT + "\\" + guid + VIEW
    for root, tag in ((HKLM, "HKLM"), (HKCU, "HKCU")):
        rw = can_open(root, path, KEY_WRITE)
        rd = can_open(root, path, KEY_READ)
        print("  %-4s %-10s read=%-9s write=%-9s"
              % (tag, label,
                 "OK" if rd == 0 else "rc0x%08X" % rd,
                 "OK" if rw == 0 else "DENIED rc0x%08X" % rw))

print()
print("=" * 78)
print("Parent FolderTypes key, for comparison")
for root, tag in ((HKLM, "HKLM"), (HKCU, "HKCU")):
    rw = can_open(root, FT, KEY_WRITE)
    print("  %-4s %-10s write=%s" % (tag, "FolderTypes",
                                     "OK" if rw == 0 else "DENIED rc0x%08X" % rw))

print()
print("=" * 78)
print("Live HKLM ColumnList vs our backup")
for guid, label in WANT:
    live = bak = None
    try:
        k = wr.OpenKey(wr.HKEY_LOCAL_MACHINE, FT + "\\" + guid + VIEW, 0, wr.KEY_READ)
        live = wr.QueryValueEx(k, "ColumnList")[0]
        wr.CloseKey(k)
    except OSError:
        pass
    try:
        k = wr.OpenKey(wr.HKEY_LOCAL_MACHINE,
                       r"Software\FileRemarks\ColumnList\%s" % guid, 0, wr.KEY_READ)
        for i in range(wr.QueryInfoKey(k)[1]):
            name, data, typ = wr.EnumValue(k, i)
            bak = data
        wr.CloseKey(k)
    except OSError:
        pass
    print("  %-10s live_len=%-4s backup_len=%-4s identical=%-5s comment_in_live=%s"
          % (label,
             len(live) if live else None,
             len(bak) if bak else None,
             (live == bak),
             ("System.Comment" in live) if live else None))
