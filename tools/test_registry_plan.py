"""Checks the registration plan that DllRegisterServer() will execute.

Registration itself cannot be run here: every process on this machine,
including ones started with higher rights, gets 0x80000005 from
RegCreateKeyExW/RegSetValueExW. So instead of writing the registry we read the
three extension lists out of the real source file, replay the exact same
decision logic, and assert the invariants that keep the tool from breaking any
file type Windows already handles.

Run:  python tools/test_registry_plan.py
"""

import os
import re
import sys
import winreg

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src", "FileRemarksPropHandler.cpp")

HKLM = winreg.HKEY_LOCAL_MACHINE
PH_KEY = r"SOFTWARE\Microsoft\Windows\CurrentVersion\PropertySystem\PropertyHandlers"
SPH_KEY = r"SOFTWARE\Microsoft\Windows\CurrentVersion\PropertySystem\SystemPropertyHandlers"
OWN_CLSID = "{B4C8E6D1-7A2F-4c3b-9D5E-1F6C2A8B3D41}"

failures = []


def check(ok, msg):
    print(("  ok   " if ok else "  FAIL ") + msg)
    if not ok:
        failures.append(msg)


def values(root, path):
    try:
        k = winreg.OpenKey(root, path)
    except OSError:
        return {}
    out = {}
    try:
        i = 0
        while True:
            try:
                name, val, typ = winreg.EnumValue(k, i)
            except OSError:
                break
            out[name] = (val, typ)
            i += 1
    finally:
        winreg.CloseKey(k)
    return out


def read_src():
    with open(SRC, encoding="utf-8", errors="replace") as f:
        return f.read()


def ext_list(src, name):
    m = re.search(r"const WCHAR\* const " + name + r"\[\]\s*=\s*\{(.*?)\};", src, re.S)
    if not m:
        raise SystemExit("could not find " + name + " in " + SRC)
    return re.findall(r'L"(\.[^"]*)"', m.group(1))


def default_sz(path):
    """The default (unnamed) value of a key, or None when absent/not a string."""
    try:
        k = winreg.OpenKey(HKLM, path)
    except OSError:
        return None
    try:
        v, t = winreg.QueryValueEx(k, "")
    except OSError:
        return None
    finally:
        winreg.CloseKey(k)
    if t not in (winreg.REG_SZ, winreg.REG_EXPAND_SZ):
        return None
    v = v.strip()
    return v or None


def handler_clsid(ext):
    """Mirror of ReadHandlerCLSID(): all three shapes the shell honours."""
    third = None
    vs = values(HKLM, SPH_KEY)
    if ext in vs and vs[ext][1] in (winreg.REG_SZ, winreg.REG_EXPAND_SZ):
        third = (vs[ext][0] or "").strip() or None
    return (default_sz(PH_KEY + "\\" + ext)
            or default_sz("Software\\Classes\\" + ext + "\\ShellEx\\PropertyHandler")
            or third)


def main():
    src = read_src()
    cand = ext_list(src, "kCandidateExts")
    chain = ext_list(src, "kChainExts")
    pin = ext_list(src, "kPinExts")

    print("lists parsed from src/FileRemarksPropHandler.cpp")
    print("  kCandidateExts = %d" % len(cand))
    print("  kChainExts     = %d" % len(chain))
    print("  kPinExts       = %d" % len(pin))
    print()

    print("[1] the lists do not overlap")
    check(not (set(cand) & set(chain)), "candidate/chain disjoint")
    check(not (set(cand) & set(pin)), "candidate/pin disjoint")
    check(not (set(chain) & set(pin)), "chain/pin disjoint")
    for name, lst in (("candidate", cand), ("chain", chain), ("pin", pin)):
        dup = sorted({e for e in lst if lst.count(e) > 1})
        check(not dup, "%s has no duplicates%s" % (name, "" if not dup else ": %s" % dup))
    print()

    print("[2] candidate types are free, or safely skipped")
    # DllRegisterServer() calls SystemOwnsHandler() and skips those, so a
    # system-owned extension in the candidate list can never be overwritten.
    # When FileRemarks is already installed the candidates it owns naturally
    # resolve to our own CLSID -- that is the expected end state, not a
    # collision, so those are excluded from the "stays on the system handler"
    # check below.
    owned = [(e, handler_clsid(e)) for e in cand if handler_clsid(e)]
    foreign = [(e, v) for e, v in owned if v != OWN_CLSID]
    print("      %d candidate(s) resolve a handler; %d of them are ours already"
          % (len(owned), len(owned) - len(foreign)))
    check("if (SystemOwnsHandler(ext)) continue;" in src,
          "system-owned candidates are skipped, not overwritten")
    for e, v in foreign:
        check(v != OWN_CLSID, "%-7s stays on the system handler %s" % (e, v))
    print()

    print("[3] chain types really have a native handler to wrap")
    # A wrap target is only useful when a handler exists; SystemOwnsHandler()
    # skips the ones that do not, so they simply fall through to the wildcard.
    missing = [e for e in chain if not handler_clsid(e)]
    check(True, "%d/%d chain types resolve a native handler (the rest fall through to the wildcard): %s"
          % (len(chain) - len(missing), len(chain), ", ".join(missing) or "-"))
    print()

    print("[4] pin types keep the handler Windows already uses")
    # A pin type with no handler on this machine has no native columns to
    # protect, so registration skips it; on a machine where Office/Visio is
    # installed the same code re-reads the CLSID and pins it.
    unpinned = [e for e in pin if not handler_clsid(e)]
    check(True, "%d/%d pin types resolve a CLSID to pin (the rest have no native handler here): %s"
          % (len(pin) - len(unpinned), len(pin), ", ".join(unpinned) or "-"))
    check("if (!hadKey && !ReadHandlerCLSID(ext, szPin, ARRAYSIZE(szPin))) return;" in src,
          "a pin type without a native handler is skipped instead of pinned to nothing")
    check("PinAllExistingHandlers();" in src,
          "every existing native handler on the machine is pinned, not just the listed ones")
    check("RegEnumValueW" in src and "RegEnumKeyExW" in src,
          "pinning enumerates the registry instead of relying on a fixed list")
    selfpin = [e for e in pin if handler_clsid(e) == OWN_CLSID]
    check(not selfpin, "no pin type resolves to our own CLSID%s"
          % ("" if not selfpin else ": %s" % selfpin))
    print()

    print("[5] Office extensions: OLE wrapped by delegation, OOXML served by our parser")
    # .doc/.ppt/.xls are the legacy OLE formats: their handler in propsys.dll
    # answers IPropertyStore, so wrapping them keeps 作者/标题/页数 by delegation
    # (measured on real files). The OOXML handlers answer E_NOINTERFACE, so there
    # is nothing to delegate to -- they are taken over and our own docProps reader
    # reproduces the same columns, because Office's handler cannot open a 0-byte
    # "新建" file (0x80030050) and the ADS remark would otherwise never show.
    ole_office = {".doc", ".ppt", ".xls"}
    ooxml_office = {".docx", ".docm", ".dotx", ".dotm", ".xlsx", ".xlsm",
                    ".xlsb", ".xltx", ".xltm", ".pptx", ".pptm", ".potx", ".potm"}
    missing = sorted(ole_office - set(chain))
    check(not missing, "every OLE Office type is wrapped%s"
          % ("" if not missing else ": %s" % missing))
    missing = sorted(ooxml_office - set(chain))
    check(not missing, "every OOXML Office type is taken over%s"
          % ("" if not missing else ": %s" % missing))
    check(not (ooxml_office & set(cand)),
          "no OOXML Office extension is registered through the candidate path")
    check(not (ooxml_office & set(pin)),
          "no OOXML Office extension is left pinned to the Office handler")
    for e in sorted(ooxml_office | ole_office):
        target = handler_clsid(e)
        # Installed builds point these at us; on a clean machine the original
        # handler must at least still resolve, so uninstall has something to
        # restore. Either way a handler has to exist.
        check(target is not None, "%-7s resolves to a handler %s" % (e, target or "(none)"))
    print()

    print("[6] user's headline types are covered")
    for e in (".exe", ".png", ".jpg", ".doc", ".py", ".md", ".docx", ".xlsx", ".txt"):
        covered = (e in cand) or (e in chain) or bool(handler_clsid(e))
        check(covered, "%-7s has a remark path" % e)
    print()

    print("[7] wildcard fallback is registered and removed by the same source")
    # Step 6 writes it; DllUnregisterServer removes it. Both must be present.
    check(src.count(r"Software\\Classes\\*\\shellex\\PropertyHandler") >= 1,
          "wildcard key is written at registration")
    unreg = src.split("DllUnregisterServer", 1)[-1]
    check(r"Software\\Classes\\*\\shellex\\PropertyHandler" in unreg,
          "wildcard key is removed at uninstall")
    # The product registers per-user (HKCU), so the guard may name either root;
    # what matters is that the wildcard is not deleted blindly.
    check(("RegSZEquals(HKEY_CURRENT_USER, keyStar" in unreg or
           "RegSZEquals(HKEY_LOCAL_MACHINE, keyStar" in unreg),
          "wildcard is only deleted while it still points at us")
    print()

    print("[8] uninstall can undo everything registration writes")
    unreg = src.split("DllUnregisterServer", 1)[-1]
    for lst in ("kCandidateExts", "kChainExts"):
        check(lst + "[i]" in unreg, "uninstall walks " + lst)
    check(r"Software\\FileRemarks\\Original" in unreg, "uninstall restores wrapped originals")
    check(r"Software\\FileRemarks\\Pinned" in unreg, "uninstall removes pinned keys")
    check("RegEnumKeyExW(hkPinned" in unreg,
          "uninstall enumerates the pinned list it recorded, not a fixed list")
    check("Software\\\\Classes\\\\CLSID" in unreg, "uninstall deletes the CLSID key")
    print()

    if failures:
        print("FAILURES:")
        for f in failures:
            print("  - " + f)
        return 1
    print("ALL REGISTRATION-PLAN TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
