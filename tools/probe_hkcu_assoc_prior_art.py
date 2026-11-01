"""Does Windows honour property-handler registrations that live in HKCU?

Why this matters
----------------
v1.9 installs per-user (no elevation -> no UAC -> no SmartScreen). That means the
property-handler associations are written under HKCU\\Software\\Classes instead of
HKLM\\Software\\Classes. HKCR is documented as a merged view where HKCU wins for
the current user, but the build sandbox refuses ALL registry writes (winerror 5),
so the round trip cannot be tested here directly.

What CAN be checked is prior art: does this machine already have shell
associations that exist ONLY under HKCU and are ABSENT under HKLM? If real
software does that and its features work, HKCU is a supported shape.

Read-only. Usage:  python tools/probe_hkcu_assoc_prior_art.py
"""
import winreg

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
    print("HKCU association prior art (read-only)")
    print("=" * 60)

    print()
    print("1) per-user CLSID registrations (in-proc COM servers)")
    clsid_root = r"Software\Classes\CLSID"
    classes = subkeys(HKCU, clsid_root)
    inproc = 0
    for c in classes:
        dll = value(HKCU, clsid_root + "\\" + c + "\\InprocServer32", "")
        if dll:
            inproc += 1
            if inproc <= 6:
                print("   %s -> %s" % (c, dll))
    print("   HKCU CLSID keys: %d, of which in-proc servers: %d" % (len(classes), inproc))

    print()
    print("2) property-handler associations under HKCU only")
    found = 0
    for ext in subkeys(HKCU, r"Software\Classes"):
        if not ext.startswith("."):
            continue
        p = r"Software\Classes\%s\ShellEx\PropertyHandler" % ext
        cu = value(HKCU, p, "")
        lm = value(HKLM, p, "")
        if cu and not lm:
            found += 1
            print("   %-14s HKCU only -> %s" % (ext, cu))
    print("   HKCU-only property handlers: %d" % found)

    print()
    print("3) any ShellEx handler shape under HKCU\\Software\\Classes\\*")
    star = subkeys(HKCU, r"Software\Classes\*\shellex")
    print("   subkeys: %s" % (star if star else "(none)"))
    for s in star:
        ours_cu = subkeys(HKCU, r"Software\Classes\*\shellex\%s" % s)
        ours_lm = subkeys(HKLM, r"Software\Classes\*\shellex\%s" % s)
        print("   %-24s HKCU=%s HKLM=%s" % (s, ours_cu, ours_lm))

    print()
    print("4) PropertySystem\\PropertyHandlers root, both hives")
    for name, root in (("HKCU", HKCU), ("HKLM", HKLM)):
        p = r"Software\Microsoft\Windows\CurrentVersion\PropertySystem\PropertyHandlers"
        print("   %-4s exists=%s entries=%s"
              % (name, value(root, p, "") is not None or bool(subkeys(root, p)),
                 subkeys(root, p)[:8]))

    print()
    print("Reading:    section 1 proves per-user COM servers are normal on this box.")
    print("            section 2/3 show whether shell ASSOCIATIONS also live in HKCU.")
    print("            section 4 shows whether the v1.9 PropSys shape even exists per-user.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
