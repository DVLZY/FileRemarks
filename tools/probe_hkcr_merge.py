"""Does the merged HKCR view expose associations that live only in HKCU?

v1.9 registers everything per-user. The shell resolves handlers through HKCR, a
merged view of HKLM\\Software\\Classes and HKCU\\Software\\Classes. If HKCR shows an
entry that exists ONLY under HKCU, then a per-user PropertyHandler association is
visible to Explorer exactly like a machine-wide one.

This machine already has two HKCU-only context-menu handlers
(CloudStation.SyncFolderContextMenu, QuarkAI.ContextMenu), so the merge can be
observed without writing anything.

Read-only. Usage:  python tools/probe_hkcr_merge.py
"""
import winreg

HKCR = winreg.HKEY_CLASSES_ROOT
HKCU = winreg.HKEY_CURRENT_USER
HKLM = winreg.HKEY_LOCAL_MACHINE


def subkeys(root, path):
    try:
        k = winreg.OpenKey(root, path)
    except OSError:
        return []
    out = []
    i = 0
    while True:
        try:
            out.append(winreg.EnumKey(k, i))
        except OSError:
            break
        i += 1
    winreg.CloseKey(k)
    return out


def value(root, path, name=""):
    try:
        k = winreg.OpenKey(root, path)
    except OSError:
        return None
    try:
        return winreg.QueryValueEx(k, name)[0]
    except OSError:
        return None
    finally:
        winreg.CloseKey(k)


def main():
    print("HKCR merge visibility (read-only)")
    print("=" * 60)
    ok = True

    # 1) An association that exists only in HKCU: is it visible through HKCR?
    print()
    print("1) HKCU-only context-menu handlers, as seen through HKCR")
    star = r"*\shellex\ContextMenuHandlers"
    cu = subkeys(HKCU, "Software\\Classes\\" + star)
    lm = subkeys(HKLM, "Software\\Classes\\" + star)
    cr = subkeys(HKCR, star)
    for name in ["CloudStation.SyncFolderContextMenu", "QuarkAI.ContextMenu"]:
        in_cu = name in cu
        in_lm = name in lm
        in_cr = name in cr
        verdict = "HKCR sees it" if in_cr else "hkcr does NOT see it"
        print("   %-38s HKCU=%-5s HKLM=%-5s HKCR=%-5s  -> %s"
              % (name, in_cu, in_lm, in_cr, verdict))
        if in_cu and not in_lm and not in_cr:
            ok = False

    print()
    print("   HKCR subkey count: %d   HKCU-only entries in HKCR: %d"
          % (len(cr), len([n for n in cu if n not in lm and n in cr])))

    # 2) Would a per-user PropertyHandler association be readable the same way?
    print()
    print("2) the property-handler shape, per sample extension")
    for ext in [".txt", ".md", ".py", ".jpg", ".exe", ".docx"]:
        shape = r"%s\ShellEx\PropertyHandler" % ext
        cr_v = value(HKCR, shape, "")
        cu_v = value(HKCU, "Software\\Classes\\" + shape, "")
        lm_v = value(HKLM, "Software\\Classes\\" + shape, "")
        src = []
        if cu_v:
            src.append("HKCU")
        if lm_v:
            src.append("HKLM")
        print("   %-7s HKCR=%-44s  (HKCU=%s HKLM=%s)"
              % (ext, cr_v, bool(cu_v), bool(lm_v)))

    # 3) and the wildcard shape the installer also writes
    print()
    print("3) wildcard property handler")
    wshape = r"*\shellex\PropertyHandler"
    print("   HKCR = %s" % value(HKCR, wshape, ""))
    print("   HKCU = %s" % value(HKCU, "Software\\Classes\\" + wshape, ""))
    print("   HKLM = %s" % value(HKLM, "Software\\Classes\\" + wshape, ""))

    # 4) legacy PropSys shape, both hives and HKCR-merged view
    print()
    print("4) PropertySystem\\PropertyHandlers (the second shape v1.9 writes)")
    p = r"Software\Microsoft\Windows\CurrentVersion\PropertySystem\PropertyHandlers"
    for name, root in (("HKCU", HKCU), ("HKLM", HKLM)):
        print("   %-4s key=%s .txt=%s" % (name, bool(subkeys(root, p)),
                                          value(root, p + r"\.txt", "")))

    print()
    print("VERDICT:", "HKCR merges HKCU associations -> per-user registration reaches Explorer"
          if ok else "*** HKCR does NOT expose HKCU-only entries here -- per-user shape unproven ***")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
