# -*- coding: utf-8 -*-
"""Overwrite-install layout test ("覆盖安装" must never need a reboot).

The failure this guards against, reported from a real machine:

    无法替换正在使用的文件：
    C:\\Users\\<user>\\AppData\\Local\\FileRemarks\\FileRemarksPropHandler.dll
    错误码 0x00000005 / 0x00000005

The property handler is loaded by explorer.exe, so the copy that is in use
cannot be replaced -- and the old "rename it to .old and write the new one"
trick does not help either. v1.14 therefore never installs into the folder of a
running copy: every install gets a brand-new directory
(%LOCALAPPDATA%\\FileRemarks\\app-1.14, app-1.14-2, ...), the registration is
pointed at it, and the previous directory is deleted on the next boot.

This test drives the REAL layout functions from selfext.cpp through the
selftest DLL, with FR_REMARKS_ROOT pointed at a throw-away directory (the
sandbox denies writes to %LOCALAPPDATA%), and asserts the property that makes
the fix work: a second install never lands in a directory that already exists.

    python tools/test_install_layout.py
"""
import ctypes
import os
import re
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD = os.path.join(ROOT, "build")
WORK = os.path.join(BUILD, "_layout_test")
DLL = os.path.join(BUILD, "selftest_install.dll")
# The directory name carries the version, so read it from the source instead of
# hard-coding it: a version bump used to turn this suite red for no reason.
_VER = re.search(r'#define FR_VERSION_TEXT\s+L"([^"]+)"',
                 open(os.path.join(ROOT, 'src', 'version.h'),
                      encoding='utf-8').read()).group(1)
VERSION_DIR = 'app-%s' % _VER

FAILS = []


def check(ok, what, detail=""):
    print("  %s  %s%s" % ("PASS" if ok else "FAIL", what,
                          ("  [%s]" % detail) if detail else ""))
    if not ok:
        FAILS.append(what)
    return ok


def main():
    if not os.path.exists(DLL):
        print("missing %s -- run tools\\build_mingw.sh first" % DLL)
        return 2
    if os.path.isdir(WORK):
        shutil.rmtree(WORK, ignore_errors=True)
    os.makedirs(WORK)

    # The override is read on every GetProgDir() call, so setting it here is
    # enough -- no subprocess, no registry.
    os.environ["FR_REMARKS_ROOT"] = WORK

    lib = ctypes.WinDLL(DLL)
    buf = ctypes.create_unicode_buffer(512)

    lib.FrTestRoot.argtypes = [ctypes.c_wchar_p, ctypes.c_int]
    lib.FrTestFreshAppDir.argtypes = [ctypes.c_wchar_p, ctypes.c_int]
    lib.FrTestEnsureAppDir.argtypes = [ctypes.c_wchar_p, ctypes.c_int]
    lib.FrTestEnsureAppDir.restype = ctypes.c_int
    lib.FrTestCleanupAppDirs.argtypes = [ctypes.c_wchar_p]
    lib.FrTestCleanupAppDirs.restype = None
    lib.FrTestCandidateDirs.restype = ctypes.c_int

    lib.FrTestRoot(buf, 512)
    check(buf.value == WORK, "the install root honours the test override", buf.value)

    lib.FrTestFreshAppDir(buf, 512)
    first = buf.value
    check(os.path.basename(first) == VERSION_DIR,
          "a fresh install targets app-<version>", os.path.basename(first))

    check(lib.FrTestEnsureAppDir(buf, 512) == 1, "the fresh directory is created")
    created = buf.value
    check(created == first, "the created directory is the one that was planned",
          os.path.basename(created))
    check(os.path.isdir(created), "the directory exists on disk")

    # Pretend the copy inside it is the one Explorer has loaded: put a marker in
    # the folder. A reinstall must leave this folder completely alone.
    marker = os.path.join(created, "FileRemarksPropHandler.dll")
    with open(marker, "wb") as fh:
        fh.write(b"MZ loaded-copy-marker")
    stamp = os.path.getmtime(marker)

    lib.FrTestFreshAppDir(buf, 512)
    second = buf.value
    check(second != created, "a second install picks a DIFFERENT directory",
          os.path.basename(second))
    check(os.path.basename(second).startswith(VERSION_DIR + "-"),
          "the second directory carries a numeric suffix", os.path.basename(second))
    check(not os.path.isdir(second),
          "the second directory does not exist yet (nothing to overwrite)")

    check(lib.FrTestEnsureAppDir(buf, 512) == 1, "the second directory is created")
    check(buf.value == second, "the second install used the directory it planned",
          os.path.basename(buf.value))

    check(lib.FrTestEnsureAppDir(buf, 512) == 1, "a third install succeeds")
    third = buf.value
    check(third not in (created, second), "a third install picks yet another directory",
          os.path.basename(third))

    check(os.path.getmtime(marker) == stamp and os.path.getsize(marker) == 21,
          "the already-installed copy is untouched by later installs")

    before = lib.FrTestCandidateDirs()
    check(before >= 4, "CandidateDirs() sees root + the three app dirs",
          "%d directories" % before)

    lib.FrTestCleanupAppDirs(third)
    check(os.path.isdir(third), "cleanup keeps the directory just installed")
    check(not os.path.isdir(created), "cleanup removes an older app directory")
    check(not os.path.isdir(second), "cleanup removes every older app directory")

    lib.FrTestCleanupAppDirs("")
    left = [d for d in os.listdir(WORK) if d.startswith("app-")]
    check(left == [], "uninstall layout removes all app directories", str(left))

    print()
    if FAILS:
        print("--- verdict ---")
        print("  %d check(s) FAILED" % len(FAILS))
        return 1
    print("ALL INSTALL-LAYOUT CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
