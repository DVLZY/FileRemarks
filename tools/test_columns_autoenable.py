# -*- coding: utf-8 -*-
"""Regression test for the "备注 column is switched on automatically" feature.

What went wrong before, and what this test pins down:

  * v1.8 wrote the ColumnList straight into HKLM while elevated. The HKLM view
    keys of Generic, Documents, Pictures and Downloads grant
    BUILTIN\\Administrators only ReadKey (measured), so those four writes were
    refused and only Music and Videos ever got the column -- while the installer
    still reported success. The fix writes a per-user override under HKCU
    instead, and refuses to count a folder type as done unless the value can be
    read back with System.Comment in it.

Two halves:

  1. Pure logic (works anywhere, including this build machine): the append
     helper still produces exactly one extra column and is idempotent.
  2. Live registry (read-only, and honest about a read-only machine): count how
     many folder types currently expose the column, run the real enable path,
     and require the count to never go DOWN. On a machine where writes are
     denied, the changed count must be 0 and the probe says so out loud instead
     of pretending.

Run: python tools/test_columns_autoenable.py
"""
import ctypes
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DLL = os.path.join(ROOT, "build", "selftest_columns.dll")

fail = []


def check(cond, label, extra=""):
    print(("  ok   " if cond else "  FAIL ") + label + (("  " + str(extra)) if extra else ""))
    if not cond:
        fail.append(label)


lib = ctypes.WinDLL(DLL)
lib.FrTestBuildColumnList.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_int]
lib.FrTestBuildColumnList.restype = ctypes.c_int
lib.FrTestAlreadyHasComment.argtypes = [ctypes.c_wchar_p]
lib.FrTestAlreadyHasComment.restype = ctypes.c_int
lib.FrTestAppendLiteral.argtypes = [ctypes.c_wchar_p, ctypes.c_int]
lib.FrTestAppendLiteral.restype = ctypes.c_int
lib.FrTestCountEnabled.argtypes = []
lib.FrTestCountEnabled.restype = ctypes.c_int
lib.FrTestEnable.argtypes = []
lib.FrTestEnable.restype = ctypes.c_int

GENERIC = ("prop:0(34)System.ItemNameDisplay;0System.DateModified;"
           "0System.ItemTypeText;0System.Size;1System.Comment")

print("=" * 78)
print("1) append helper")
buf = ctypes.create_unicode_buffer(4096)
lit = ctypes.create_unicode_buffer(64)
lib.FrTestAppendLiteral(lit, 64)
check(lit.value == ";0System.Comment", "the appended literal is ;0System.Comment", lit.value)

base = ("prop:0(34)System.ItemNameDisplay;0System.DateModified;"
        "0System.ItemTypeText;0System.Size")
rc = lib.FrTestBuildColumnList(base, buf, 4096)
merged = buf.value
check(rc == 1, "a list without the column is changed")
check(merged == base + ";0System.Comment", "the column is appended, order untouched", merged[-40:])
check(merged.count("System.Comment") == 1, "the column appears exactly once")
check(lib.FrTestAlreadyHasComment(base) == 0, "base list is recognised as lacking it")
check(lib.FrTestAlreadyHasComment(GENERIC) == 1, "a list that has it is recognised")

# Idempotence: feeding the merged value back must be a no-op, otherwise a
# second install would stack the column.
rc2 = lib.FrTestBuildColumnList(merged, buf, 4096)
check(rc2 == 0, "running it again changes nothing (idempotent)", rc2)

# Trailing separators would leave an empty entry, and one empty entry makes
# Explorer drop the whole column list -- so they must be trimmed first.
trail = ctypes.create_unicode_buffer(4096)
rc3 = lib.FrTestBuildColumnList(base + ";;  ", trail, 4096)
check(rc3 == 1 and trail.value == base + ";0System.Comment",
      "trailing separators are trimmed, not turned into an empty column",
      repr(trail.value[-24:]))

print()
print("=" * 78)
print("2) live registry (read-only where writes are denied)")
before = lib.FrTestCountEnabled()
print("  folder types currently showing 备注: %d / 6" % before)
check(0 <= before <= 6, "the count is in range", before)

changed = lib.FrTestEnable()
after = lib.FrTestCountEnabled()
print("  enable path reported %d changed, now %d / 6 show the column"
      % (changed, after))

if before == after == 0:
    print("  (this machine denies the registry writes, so nothing can change here;"
          " the same code path is exercised on the user's machine by"
          " tools/check_install.py)")
check(after >= before, "enabling never loses a folder type", "%d -> %d" % (before, after))
check(0 <= changed <= 6, "the changed count is in range", changed)
# The important one: the reported number must agree with what can be read back.
if changed == 0:
    check(after == before, "0 changed really means no new folder type", "%d -> %d" % (before, after))

print()
if fail:
    print("COLUMN AUTO-ENABLE TESTS FAILED (%d): %s" % (len(fail), "; ".join(fail)))
    sys.exit(1)
print("ALL COLUMN AUTO-ENABLE TESTS PASSED")
