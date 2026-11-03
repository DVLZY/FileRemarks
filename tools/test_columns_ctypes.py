# -*- coding: utf-8 -*-
"""Verify the default-column logic that install uses to show the 备注 column.

Registry writes are impossible in this environment, so the interesting part --
turning Explorer's ColumnList into one that also carries System.Comment -- is
tested as pure string logic through build/selftest_columns.dll, which wraps
fr::columns::BuildColumnList from src/shell_columns.h.

What must hold:
  * the entry appended is exactly ";0System.Comment"
  * the user's existing column order is preserved, ours goes last
  * a list that already has the column is left alone (install is idempotent)
  * a list ending in ';' does not produce an empty entry (Explorer would drop
    the whole list)
  * the real column list Windows ships for the Generic folder type works
"""
import ctypes
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DLL = os.path.join(ROOT, "build", "selftest_columns.dll")

# The value Windows 10 ships for FolderTypes\Generic\TopViews\{0000...}.
GENERIC = ("prop:0(34)System.ItemNameDisplay;0System.DateModified;"
           "0System.ItemTypeText;0System.Size;1System.DateCreated;"
           "1System.Author;1System.Keywords;1System.Title")

failures = []


def check(cond, msg):
    print("  %-5s %s" % ("ok" if cond else "FAIL", msg))
    if not cond:
        failures.append(msg)


def main():
    if not os.path.exists(DLL):
        print("missing %s -- run tools/build_mingw.sh first" % DLL)
        return 1
    lib = ctypes.WinDLL(DLL)
    WCHARP = ctypes.POINTER(ctypes.c_wchar)
    lib.FrTestBuildColumnList.argtypes = [ctypes.c_wchar_p, WCHARP, ctypes.c_int]
    lib.FrTestBuildColumnList.restype = ctypes.c_int
    lib.FrTestAlreadyHasComment.argtypes = [ctypes.c_wchar_p]
    lib.FrTestAlreadyHasComment.restype = ctypes.c_int
    lib.FrTestAppendLiteral.argtypes = [WCHARP, ctypes.c_int]
    lib.FrTestAppendLiteral.restype = ctypes.c_int

    buf = ctypes.create_unicode_buffer(4096)

    def build(src):
        buf.value = ""
        rc = lib.FrTestBuildColumnList(src, ctypes.cast(buf, WCHARP), 4096)
        return rc, buf.value

    print("=== the appended entry ===")
    lit = ctypes.create_unicode_buffer(64)
    lib.FrTestAppendLiteral(ctypes.cast(lit, WCHARP), 64)
    print("  append literal: %r" % lit.value)
    check(lit.value == ";0System.Comment",
          "the appended entry is ';0System.Comment' (got %r)" % lit.value)

    print("\n=== appending to a simple list ===")
    rc, out = build("prop:0(34)System.ItemNameDisplay;0System.Size")
    print("  in : %r" % "prop:0(34)System.ItemNameDisplay;0System.Size")
    print("  out: %r" % out)
    check(rc == 1, "a list without the column reports 'changed'")
    check(out.endswith(";0System.Comment"),
          "the entry is appended at the END (order preserved)")
    check(out.startswith("prop:0(34)System.ItemNameDisplay;0System.Size"),
          "the original list is preserved verbatim as a prefix")

    print("\n=== idempotency ===")
    rc2, out2 = build(out)
    check(rc2 == 0, "a list that already has the column reports 'nothing to change'")
    check(out2 == "", "no new value is produced the second time")
    check(lib.FrTestAlreadyHasComment(out) == 1,
          "AlreadyHasComment() sees the appended column")

    print("\n=== already present, in the middle ===")
    rc3, out3 = build("0System.Comment;0System.Size")
    check(rc3 == 0, "a list that starts with the column is left alone")
    check(lib.FrTestAlreadyHasComment("System.Comment") == 1,
          "AlreadyHasComment() matches it without the flag prefix")

    print("\n=== a trailing semicolon must not create an empty entry ===")
    rc4, out4 = build("0System.Size;")
    print("  out: %r" % out4)
    check(rc4 == 1, "a list ending in ';' is still changed")
    check(";;" not in out4,
          "no empty entry is produced (Explorer would drop the whole list)")
    check(out4 == "0System.Size;0System.Comment",
          "the trailing semicolon is normalised away (got %r)" % out4)

    print("\n=== several trailing semicolons ===")
    rc5, out5 = build("0System.Size;;; ")
    print("  out: %r" % out5)
    check(rc5 == 1, "a list with several trailing separators is still changed")
    check(";;" not in out5,
          "consecutive semicolons do not survive (got %r)" % out5)
    check(out5 == "0System.Size;0System.Comment",
          "all trailing separators are normalised away (got %r)" % out5)

    print("\n=== the real Generic folder type value ===")
    rc6, out6 = build(GENERIC)
    print("  in : %r" % GENERIC)
    print("  out: %r" % out6)
    check(rc6 == 1, "the real Windows value is changed")
    check(out6 == GENERIC + ";0System.Comment",
          "exactly the original value plus the new column")
    check(out6.count("System.Comment") == 1, "the column appears exactly once")

    # Every entry must still be well formed after the edit: a non-empty name
    # preceded by the "N" width flag. A stray empty entry would silently kill
    # the whole column list in Explorer.
    print("\n=== every entry is still well formed ===")
    entries = out6.split(";")
    print("  %d entries" % len(entries))
    empty = [i for i, e in enumerate(entries) if not e.strip()]
    check(not empty, "no empty entries (found at %r)" % empty)
    check(all(any(ch.isalpha() or ch == "." for ch in e) for e in entries),
          "every entry names a property")

    print("\n=== degenerate inputs ===")
    rc7, out7 = build("")
    check(rc7 == 0 and out7 == "", "an empty list is refused instead of patched")
    rc8, out8 = build("   ")
    print("  whitespace-only out: %r" % out8)
    check(rc8 == 0 and out8 == "",
          "a whitespace-only list is refused instead of patched")

    print("\n=== uninstall repairs the machine default an old release wrote ===")
    lib.FrTestStripComment.argtypes = [ctypes.c_wchar_p, WCHARP, ctypes.c_int]
    lib.FrTestStripComment.restype = ctypes.c_int

    def strip(src):
        buf.value = ""
        return lib.FrTestStripComment(src, ctypes.cast(buf, WCHARP), 4096), buf.value

    polluted = GENERIC + ";0System.Comment"
    rc9, out9 = strip(polluted)
    check(rc9 == 1, "the token is detected in a machine value")
    check(out9 == GENERIC,
          "the rest of the machine value is preserved exactly (got %r)" % out9[:60])
    rc10, out10 = strip(polluted.replace(";0System.Comment", ";0System.Comment;0System.Size"))
    check(rc10 == 1 and "System.Comment" not in out10,
          "a token that is not last is removed without leaving a broken list")
    rc11, _ = strip(GENERIC)
    check(rc11 == 0, "a value we never touched is left alone")

    print("")
    if failures:
        print("FAILURES:")
        for f in failures:
            print("  - " + f)
        return 1
    print("ALL COLUMN TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
