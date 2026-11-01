"""In-process test of the REAL InstallFile() from src/selfext.cpp.

Simulates the exact failure the user hit (m00815): the target DLL is already
loaded by another process (explorer.exe), so CopyFileW fails with
ERROR_SHARING_VIOLATION (decimal 32).  InstallFile() must recover by renaming
the stale copy aside and writing the new one.

We simulate "loaded by another process" by loading the file into THIS process
with ctypes.WinDLL, which locks it against overwrite in exactly the same way.
"""
import ctypes
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD = os.path.join(ROOT, "build")
SRC_OLD = os.path.join(BUILD, "FileRemarksShellExt.dll")
# a source file that differs in size so we can prove the new bytes landed
SRC_NEW = os.path.join(BUILD, "FileRemarksPropHandler.dll")

WORK = os.path.join(BUILD, "_installtest")
TARGET = os.path.join(WORK, "FileRemarksShellExt.dll")

fails = []


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + (("  -> " + detail) if detail else ""))
    if not cond:
        fails.append(name)


def reset():
    if os.path.isdir(WORK):
        shutil.rmtree(WORK, ignore_errors=True)
    os.makedirs(WORK, exist_ok=True)
    for f in (TARGET, TARGET + ".old"):
        try:
            os.remove(f)
        except OSError:
            pass
    shutil.copy(SRC_OLD, TARGET)


print("[1] load the test DLL")
dll = ctypes.WinDLL(os.path.join(BUILD, "selftest_install.dll"))
dll.FrTestHex.argtypes = [ctypes.c_uint, ctypes.c_wchar_p, ctypes.c_int]
dll.FrTestHex.restype = ctypes.c_int
dll.FrTestInstall.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_int]
dll.FrTestInstall.restype = ctypes.c_int
print("     loaded OK")

print("[2] Hex() must print hex, not decimal  (32 -> 00000020)")
buf = ctypes.create_unicode_buffer(16)
dll.FrTestHex(32, buf, 16)
check("Hex(32) == '00000020'", buf.value == "00000020", buf.value)
buf2 = ctypes.create_unicode_buffer(16)
dll.FrTestHex(5, buf2, 16)
check("Hex(5) == '00000005'", buf2.value == "00000005", buf2.value)

print("[3] unlocked target: plain copy must succeed")
reset()
errb = ctypes.create_unicode_buffer(1024)
ok = dll.FrTestInstall(SRC_OLD, TARGET, errb, 1024)
check("InstallFile on free file returns 1", ok == 1, errb.value)
check("content equals source", open(TARGET, "rb").read() == open(SRC_OLD, "rb").read())
check("no .old left behind", not os.path.exists(TARGET + ".old"))

print("[4] locked target: the user's real scenario")
reset()
held = ctypes.WinDLL(TARGET)  # lock it, like explorer.exe does
print("     target locked in-process:", bool(held._handle))
# prove the naive path really fails here (this is what shipped in v1.1)
native_fail = False
try:
    shutil.copy(SRC_NEW, TARGET)
except OSError:
    native_fail = True
check("plain CopyFile would have FAILED (baseline)", native_fail)

errb = ctypes.create_unicode_buffer(1024)
ok = dll.FrTestInstall(SRC_NEW, TARGET, errb, 1024)
check("InstallFile recovers and returns 1", ok == 1, errb.value)
check("new bytes are in place",
      os.path.getsize(TARGET) == os.path.getsize(SRC_NEW),
      "%d vs %d" % (os.path.getsize(TARGET), os.path.getsize(SRC_NEW)))
check("stale copy parked as .old", os.path.exists(TARGET + ".old"))
if os.path.exists(TARGET + ".old"):
    check(".old still holds the OLD bytes",
          open(TARGET + ".old", "rb").read() == open(SRC_OLD, "rb").read())

print("[5] second run must be idempotent (stale .old already present)")
errb = ctypes.create_unicode_buffer(1024)
ok = dll.FrTestInstall(SRC_OLD, TARGET, errb, 1024)
check("re-run returns 1", ok == 1, errb.value)
check("content equals newest source", open(TARGET, "rb").read() == open(SRC_OLD, "rb").read())

print("[6] upgrade while BOTH target and .old are locked (no reboot yet)")
# Scenario: v1.1 is loaded by explorer -> install v1.2 renames it to .old and
# creates a new .dll -> user installs v1.3 again before rebooting, so BOTH the
# current .dll and the parked .old are still held open.  We reproduce the
# loader's exact sharing mode: FILE_SHARE_READ | FILE_SHARE_DELETE (rename is
# allowed, delete is not), which is why a loaded DLL can be moved but not
# removed.
k32 = ctypes.WinDLL("kernel32", use_last_error=True)
k32.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32,
                            ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32,
                            ctypes.c_void_p]
k32.CreateFileW.restype = ctypes.c_void_p
GENERIC_READ, SHARE_RD_DEL = 0x80000000, 0x1 | 0x4
OPEN_EXISTING = 3
INVALID_HANDLE = ctypes.c_void_p(-1).value
kept = []


def lock_like_loaded(path):
    h = k32.CreateFileW(path, GENERIC_READ, SHARE_RD_DEL, None, OPEN_EXISTING, 0, None)
    assert h != INVALID_HANDLE, "CreateFileW failed on " + path
    kept.append(h)


reset()
lock_like_loaded(TARGET)
errb = ctypes.create_unicode_buffer(1024)
ok = dll.FrTestInstall(SRC_NEW, TARGET, errb, 1024)   # creates a locked .old
check("first upgrade returns 1", ok == 1, errb.value)
check(".old exists and is still locked", os.path.exists(TARGET + ".old"))
lock_like_loaded(TARGET)                              # new .dll now loaded too
errb = ctypes.create_unicode_buffer(1024)
ok = dll.FrTestInstall(SRC_OLD, TARGET, errb, 1024)
check("second upgrade returns 1 despite locked .old", ok == 1, errb.value)
check("content equals newest source", open(TARGET, "rb").read() == open(SRC_OLD, "rb").read())
parked = [n for n in os.listdir(WORK) if ".old" in n]
check("a stale copy is parked, not lost", bool(parked), ", ".join(sorted(parked)))

for h in kept:
    k32.CloseHandle(ctypes.c_void_p(h))

print()
if fails:
    print("FAILED %d check(s): %s" % (len(fails), ", ".join(fails)))
    sys.exit(1)
print("ALL INSTALL-FILE TESTS PASSED")
