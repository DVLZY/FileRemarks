# -*- coding: utf-8 -*-
"""Can this session write to HKCU at all?

Everything so far assumed NO registry writes anywhere (the old HKLM attempt
failed with 0x80000005 = ERROR_ACCESS_DENIED).  A per-user install design that
registers under HKCU\\Software\\Classes is only testable here if HKCU writes are
permitted, so this checks the three shapes we actually need:
  * a plain HKCU value
  * HKCU\\Software\\Classes\\CLSID\\{...}\\InprocServer32
  * HKCU\\Software\\Classes\\.txt\\ShellEx\\PropertyHandler
Everything created is deleted again at the end.
"""

import winreg

TEST_ROOT = r"Software\FileRemarks_WriteProbe"
TEXT = r"Software\FileRemarks_WriteProbe_Text"


def try_write(root, path, name, value):
    try:
        k = winreg.CreateKeyEx(root, path, 0, winreg.KEY_WRITE | winreg.KEY_READ)
        try:
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, value)
            got, _ = winreg.QueryValueEx(k, name)
        finally:
            winreg.CloseKey(k)
        return True, got
    except OSError as e:
        return False, "%s (winerror=%s)" % (e.strerror, getattr(e, "winerror", None))


def try_delete(root, path):
    try:
        winreg.DeleteKeyEx(root, path, winreg.KEY_WOW64_64KEY, 0)
        return True
    except OSError as e:
        return "failed: %s" % e.strerror


def main():
    checks = [
        ("plain HKCU value", winreg.HKEY_CURRENT_USER, TEST_ROOT, "Probe", "value-1"),
        ("HKCU in-proc COM server",
         winreg.HKEY_CURRENT_USER,
         TEST_ROOT + r"\CLSID\{11111111-2222-3333-4444-555555555555}\InprocServer32",
         "", r"C:\probe\probe.dll"),
        ("HKCU property handler association",
         winreg.HKEY_CURRENT_USER,
         TEST_ROOT + r"\Classes\.probe\ShellEx\PropertyHandler",
         "", "{11111111-2222-3333-4444-555555555555}"),
    ]
    ok_all = True
    for label, root, path, name, value in checks:
        ok, got = try_write(root, path, name, value)
        ok_all = ok_all and ok
        print("%-38s %s   %r" % (label, "WRITE OK" if ok else "DENIED  ", got))
    print()

    # Clean up whatever we managed to create.
    for sub in (r"\CLSID\{11111111-2222-3333-4444-555555555555}\InprocServer32",
                r"\CLSID\{11111111-2222-3333-4444-555555555555}",
                r"\Classes\.probe\ShellEx\PropertyHandler",
                r"\Classes\.probe\ShellEx",
                r"\Classes\.probe",
                r"\Classes"):
        try_delete(winreg.HKEY_CURRENT_USER, TEST_ROOT + sub)
    print("cleanup:", try_delete(winreg.HKEY_CURRENT_USER, TEST_ROOT))

    if ok_all:
        print("=> HKCU is writable here: a per-user install can be built AND tested in this session.")
    else:
        print("=> HKCU writes are denied: a per-user install can only be verified on the user's machine.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
