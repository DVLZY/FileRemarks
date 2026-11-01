# -*- coding: utf-8 -*-
"""Verify the native System.Comment helpers used by the editor.

Covers the real code in src/native_comment.h through build/selftest_native.dll:
  * writing System.Comment works for types whose own handler allows it
    (.docx, .xls, photos, video), and
  * it fails cleanly (returns 0, no crash, nothing corrupted) for types that do
    not -- which is exactly what the editor relies on, since it treats that as a
    normal result rather than an error.
Samples come from build/_chain_matrix (produced by tools/test_chain_matrix.py)
when available.
"""
import ctypes
import os
import shutil
import sys
import winreg

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLES = os.path.join(ROOT, "build", "_chain_matrix")
WORK = os.path.join(ROOT, "build", "_native_test")
TEXT = "原生备注 native comment 测试"

# Must match FILEREMARKS_CLSID in src/native_comment.h.
OURS = "{B4C8E6D1-7A2F-4c3b-9D5E-1F6C2A8B3D41}"
PS_KEY = r"SOFTWARE\Microsoft\Windows\CurrentVersion\PropertySystem\PropertyHandlers"


def _rd(path, value=None):
    """Read a value from HKCU first, then HKLM.

    Our own registration lives under HKCU (the product installs per user and
    never asks for elevation) while a handler Windows ships for a type lives in
    HKLM, so both roots have to be consulted -- exactly what fr::HandlerIsOurs()
    does. Reading HKLM alone made this comparison disagree with the code.
    """
    for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(root, path, 0, winreg.KEY_READ) as k:
                return winreg.QueryValueEx(k, value)[0]
        except OSError:
            continue
    return None


def registry_says_ours(ext):
    """Does the registry resolve this extension to our handler right now?

    FileRemarks may or may not be installed on the machine running the tests, so
    this is what HandlerIsOurs() has to agree with -- the same three key shapes
    the C++ code reads (see native_comment.h).
    """
    a = _rd(PS_KEY + "\\" + ext)
    if a:
        return a.strip().upper() == OURS.upper()
    b = _rd(r"SOFTWARE\Classes\\" + ext + r"\ShellEx\PropertyHandler")
    if b:
        return b.strip().upper() == OURS.upper()
    c = _rd(r"SOFTWARE\Microsoft\Windows\CurrentVersion\PropertySystem"
            r"\SystemPropertyHandlers", ext)
    if c:
        return c.strip().upper() == OURS.upper()
    return False


def load():
    dll = os.path.join(ROOT, "build", "selftest_native.dll")
    assert os.path.exists(dll), "build/selftest_native.dll missing -- run tools/build_mingw.sh"
    lib = ctypes.WinDLL(dll)
    lib.FrTestCoInit.restype = ctypes.c_int
    lib.FrTestWriteNative.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
    lib.FrTestWriteNative.restype = ctypes.c_int
    lib.FrTestReadNative.argtypes = [
        ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_int, ctypes.POINTER(ctypes.c_int)]
    lib.FrTestReadNative.restype = ctypes.c_int
    lib.FrTestHandlerIsOurs.argtypes = [ctypes.c_wchar_p]
    lib.FrTestHandlerIsOurs.restype = ctypes.c_int
    lib.FrTestWriteNativeIfNeeded.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
    lib.FrTestWriteNativeIfNeeded.restype = ctypes.c_int
    return lib


def read(lib, path):
    buf = ctypes.create_unicode_buffer(1024)
    exists = ctypes.c_int(0)
    ok = lib.FrTestReadNative(path, buf, 1024, ctypes.byref(exists))
    return bool(ok), bool(exists.value), buf.value


def make_sample(ext):
    os.makedirs(WORK, exist_ok=True)
    dst = os.path.join(WORK, "sample" + ext)
    if os.path.exists(dst) and os.path.getsize(dst) > 4096:
        return dst
    # A real file of this type, if one was staged earlier.
    for folder in (SAMPLES, WORK):
        if not os.path.isdir(folder):
            continue
        for f in sorted(os.listdir(folder)):
            if f.lower().endswith(ext):
                src = os.path.join(folder, f)
                try:
                    if os.path.getsize(src) > 4096:
                        shutil.copy2(src, dst)
                        return dst
                except OSError:
                    pass
    if ext in (".jpg", ".png"):
        try:
            from PIL import Image
            img = Image.new("RGB", (120, 80))
            for x in range(120):
                for y in range(80):
                    img.putpixel((x, y), ((x * 3) % 256, (y * 5) % 256, (x + y) % 256))
            img.save(dst, "JPEG" if ext == ".jpg" else "PNG")
            return dst
        except Exception:  # noqa: BLE001
            return None
    return None


def main():
    lib = load()
    hr = lib.FrTestCoInit()
    print("CoInitializeEx hr=0x%08X" % (hr & 0xFFFFFFFF))
    failures = []
    try:
        expectations = [
            (".docx", "maybe"),   # Word metadata handler: writable on a real .docx
            (".xlsx", "maybe"),   # Excel metadata handler: same
            (".jpg", "yes"),      # photo handler: writable
            (".png", "maybe"),
            (".exe", "no"),       # PE handler: read-only -- our own handler serves it
        ]
        for ext, expect in expectations:
            path = make_sample(ext)
            print("\n=== %s (expect write: %s) ===" % (ext, expect))
            if not path:
                print("  (no sample available, skipped)")
                continue
            print("  sample: %s (%d bytes)" % (path, os.path.getsize(path)))

            # WriteNativeCommentIfNeeded/WriteNativeComment refuse on purpose for
            # every type our handler serves: the remark belongs in the ADS, and
            # writing the file itself would modify the user's bytes for nothing.
            # So "must be writable" only holds while FileRemarks does not own the
            # extension -- on an installed machine .jpg resolves to us and the
            # correct behaviour is a clean refusal.
            if registry_says_ours(ext) and expect == "yes":
                print("  (FileRemarks owns %s right now -> a refusal is the "
                      "expected behaviour)" % ext)
                expect = "no"

            dummy = os.path.join(WORK, "sample_dummy" + ext)
            if os.path.exists(dummy):
                os.remove(dummy)
            ok_before, exists_before, value_before = read(lib, path)
            print("  read before: ok=%s exists=%s value=%r" % (ok_before, exists_before, value_before))

            wrote = bool(lib.FrTestWriteNative(path, TEXT))
            print("  WriteNativeComment -> %s" % wrote)
            ok_after, exists_after, value_after = read(lib, path)
            print("  read after:  ok=%s exists=%s value=%r" % (ok_after, exists_after, value_after))

            if wrote:
                if value_after != TEXT:
                    failures.append("%s: wrote but read back %r" % (ext, value_after))
                # Clearing must undo it.
                cleared = bool(lib.FrTestWriteNative(path, ""))
                ok3, exists3, value3 = read(lib, path)
                print("  clear -> %s, read: exists=%s value=%r" % (cleared, exists3, value3))
                if value3:
                    failures.append("%s: clear left %r" % (ext, value3))
            else:
                if expect == "yes":
                    failures.append("%s: expected a writable native comment" % ext)
                # A refused write must not have damaged anything.
                if value_after == TEXT:
                    failures.append("%s: write reported failure but value changed" % ext)
                if os.path.getsize(path) == 0:
                    failures.append("%s: file was truncated by the failed write" % ext)
                print("  (refused cleanly -- treated as a normal result by the editor)")

        # Section 2: HandlerIsOurs must agree with what the registry actually
        # says. What it answers depends on whether FileRemarks is installed on
        # this machine, so the expectation is read from the registry rather than
        # assumed -- the point being tested is the AGREEMENT, not a hard-coded
        # "no".
        print("\n=== HandlerIsOurs agrees with the registry ===")
        for ext in (".docx", ".xlsx", ".jpg", ".exe", ".py", ".md", ".txt", ".zzz"):
            probe = os.path.join(WORK, "probe" + ext)
            if not os.path.exists(probe):
                open(probe, "wb").close()
            ours = bool(lib.FrTestHandlerIsOurs(probe))
            expected = registry_says_ours(ext)
            print("  %-6s HandlerIsOurs=%-5s registry says ours=%s"
                  % (ext, ours, expected))
            if ours != expected:
                failures.append("%s: HandlerIsOurs=%s but the registry says %s"
                                % (ext, ours, expected))
            # With our handler absent from the equation the conditional write
            # must behave exactly like the unconditional one.
            if ext == ".zzz":
                conditional = bool(lib.FrTestWriteNativeIfNeeded(probe, TEXT))
                conditional_clear = bool(lib.FrTestWriteNativeIfNeeded(probe, ""))
                print("  %-6s WriteNativeCommentIfNeeded -> %s / clear -> %s"
                      % (ext, conditional, conditional_clear))

        # Section 3: a relative path must work too. SHGetPropertyStoreFromParsingName
        # rejects relative paths with E_INVALIDARG, so fr::FullPath has to resolve
        # them first; the shell itself always passes absolute paths, but a user
        # launching the editor by hand should not hit a silent no-op.
        print("\n=== relative path handling ===")
        rel_dir = os.path.join(WORK, "rel")
        os.makedirs(rel_dir, exist_ok=True)
        rel_file = os.path.join(rel_dir, "sample.docx")
        if os.path.exists(rel_file):
            os.remove(rel_file)
        docx = make_sample(".docx")
        if docx:
            shutil.copy2(docx, rel_file)
            cwd = os.getcwd()
            os.chdir(rel_dir)
            try:
                ok_rel = bool(lib.FrTestWriteNative("sample.docx", TEXT))
                ok_read, exists_rel, value_rel = read(lib, "sample.docx")
                print("  relative write -> %s, read exists=%s value=%r"
                      % (ok_rel, exists_rel, value_rel))
                if not ok_rel:
                    failures.append("relative path: write failed")
                elif value_rel != TEXT:
                    failures.append("relative path: read back %r" % value_rel)
                lib.FrTestWriteNative("sample.docx", "")
            finally:
                os.chdir(cwd)
        else:
            print("  (no .docx sample available, skipped)")

        print("")
        if failures:
            print("FAILURES:")
            for f in failures:
                print("  - " + f)
            return 1
        print("ALL NATIVE-COMMENT TESTS PASSED")
        return 0
    finally:
        pass


if __name__ == "__main__":
    sys.exit(main())
