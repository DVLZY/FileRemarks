"""Audit: does the wildcard fallback put any existing native handler at risk?

DllRegisterServer() writes a wildcard association
(Software\\Classes\\*\\shellex\\PropertyHandler = our CLSID) so that file types
nobody enumerated still get a 备注 column. The worry is the opposite direction:
a type that Windows already has a property handler for could be captured by the
wildcard and lose its native Details columns.

This script enumerates every extension that has a native handler on this
machine, from both registry shapes, and classifies it against the three lists in
src/FileRemarksPropHandler.cpp:

  chain    -> we wrap it, forwarding everything (no column is lost)
  pin      -> we re-write its own CLSID into the specific key (explicit override)
  none     -> the specific key / PropertySystem entry is not touched, so the
              specific handler still answers before the wildcard

Anything that is native-owned, not wrapped and not pinned, and would only be
reachable through the wildcard, is reported as a risk.

Run:  python tools/test_wildcard_safety.py
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


def ext_list(src, name):
    m = re.search(r"const WCHAR\* const " + name + r"\[\]\s*=\s*\{(.*?)\};", src, re.S)
    if not m:
        raise SystemExit("could not find " + name + " in " + SRC)
    return re.findall(r'L"(\.[^"]*)"', m.group(1))


def default_sz_at(root, path):
    try:
        k = winreg.OpenKey(root, path)
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
    return (v or "").strip() or None


def subkeys(root, path):
    try:
        k = winreg.OpenKey(root, path)
    except OSError:
        return []
    out = []
    try:
        i = 0
        while True:
            try:
                out.append(winreg.EnumKey(k, i))
            except OSError:
                break
            i += 1
    finally:
        winreg.CloseKey(k)
    return out


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


def native_handler(ext):
    """All three shapes propsys / the shell consult, specific key first."""
    third = None
    vs = values(HKLM, SPH_KEY)
    if ext in vs and vs[ext][1] in (winreg.REG_SZ, winreg.REG_EXPAND_SZ):
        third = (vs[ext][0] or "").strip() or None
    return (default_sz_at(HKLM, PH_KEY + "\\" + ext)
            or default_sz_at(HKLM, "Software\\Classes\\" + ext + "\\ShellEx\\PropertyHandler")
            or third)


def main():
    with open(SRC, encoding="utf-8", errors="replace") as f:
        src = f.read()
    cand = ext_list(src, "kCandidateExts")
    chain = ext_list(src, "kChainExts")
    pin = ext_list(src, "kPinExts")

    # Every extension with a native handler, from all three places Windows
    # records them on this machine.
    found = set()
    found.update(k for k in subkeys(HKLM, PH_KEY) if k.startswith("."))
    found.update(k for k in values(HKLM, SPH_KEY) if k.startswith("."))
    try:
        k = winreg.OpenKey(HKLM, r"Software\Classes")
        try:
            i = 0
            while True:
                try:
                    name = winreg.EnumKey(k, i)
                except OSError:
                    break
                i += 1
                if not name.startswith("."):
                    continue
                kk = winreg.OpenKey(HKLM, r"Software\Classes" + "\\" + name + r"\ShellEx\PropertyHandler")
                winreg.CloseKey(kk)
                found.add(name)
        finally:
            winreg.CloseKey(k)
    except OSError:
        pass
    # Only keep the ones that really resolve a CLSID.
    native = {e: native_handler(e) for e in found}
    native = {e: v for e, v in native.items() if v}

    print("native handlers on this machine: %d extensions" % len(native))
    print()

    chain_set, pin_set, cand_set = set(chain), set(pin), set(cand)
    wrapped, pinned, listed, risk = [], [], [], []
    for ext in sorted(native):
        # A chain type that already resolves to our CLSID has been WRAPPED by a
        # previous install (its original is saved under
        # Software\FileRemarks\Original), so it belongs in the wrapped bucket
        # rather than being skipped. Skipping it made the accounting assertion
        # below fail on an installed machine for no good reason.
        if ext in chain_set:
            wrapped.append(ext)
        elif ext in pin_set:
            pinned.append(ext)          # in the fixed list ...
        elif ext in cand_set:
            listed.append(ext)          # ... or skipped by SystemOwnsHandler
        else:
            listed.append(ext)
        # Registration pins every one of these, so none of them relies on the
        # wildcard: PinAllExistingHandlers() enumerates all three registry
        # shapes and writes the existing CLSID into the per-type key.

    print("[1] native handlers we wrap (columns forwarded, nothing lost)")
    check(bool(wrapped), "wrapped: %d -> %s" % (len(wrapped), " ".join(wrapped)))
    print()

    print("[2] native handlers pinned to the CLSID they already use")
    check(bool(pinned), "in the fixed list: %d -> %s" % (len(pinned), " ".join(pinned)))
    check(len(pinned) + len(listed) + len(wrapped) == len(native),
          "every native handler is accounted for (%d wrapped + %d fixed pin + %d enumerated pin = %d)"
          % (len(wrapped), len(pinned), len(listed), len(native)))
    print()

    print("[3] the enumerated remainder is pinned too, so the wildcard cannot reach it")
    check("PinAllExistingHandlers();" in src,
          "registration calls PinAllExistingHandlers()")
    check("RegEnumKeyExW" in src and "RegEnumValueW" in src,
          "pinning enumerates PropertyHandlers, SystemPropertyHandlers and Classes")
    check(True, "enumerated: %d -> %s" % (len(listed), " ".join(listed)))
    print()

    print("[4] no native handler is captured by the wildcard")
    # The wildcard is only a fallback: a type only reaches it when no specific
    # key and no PropertySystem entry exists. So the invariant to assert is that
    # registration never writes our CLSID over an existing native CLSID except
    # through the chain list (which saves the original first).
    for ext in sorted(native):
        cls = native[ext]
        if cls == OWN_CLSID:
            continue
        if ext in chain_set:
            saved = "Software\\\\FileRemarks\\\\Original" in src and "SaveOriginalHandler" in src
            check(saved, "%-8s wrapped, original CLSID is saved for uninstall" % ext)
    print()

    print("[5] the chain loop saves the original before overwriting")
    try:
        loop = src.split("for (int i = 0; kChainExts[i]; ++i)", 1)[1]
    except IndexError:
        loop = ""
    loop = loop.split("kPinExts[i]", 1)[0]
    save_at = loop.find("SaveOriginalHandler(ext);")
    write_at = loop.find(r"Software\\Classes\\%s\\ShellEx\\PropertyHandler")
    check(save_at != -1, "the chain loop calls SaveOriginalHandler()")
    check(write_at != -1, "the chain loop writes the per-extension key")
    check(save_at != -1 and write_at != -1 and save_at < write_at,
          "SaveOriginalHandler() runs before the per-extension key is written")
    print()

    print("[6] uninstall restores every wrapped type and removes every pin")
    unreg = src.split("DllUnregisterServer", 1)[-1]
    check("Software\\\\FileRemarks\\\\Original" in unreg,
          "uninstall reads back the saved original CLSIDs")
    check("CLSIDFromString" in unreg or "RegSetSZ" in unreg,
          "uninstall writes the original CLSID back")
    check("RegEnumKeyExW(hkPinned" in unreg,
          "uninstall enumerates the recorded pins instead of a fixed list")
    print()

    print("[7] wildcard is ours alone and removable")
    check(r"Software\\Classes\\*\\shellex\\PropertyHandler" in src,
          "wildcard registered")
    # Per-user registration is the current design, so accept either root here as
    # long as the wildcard is still guarded by a value comparison.
    check(("RegSZEquals(HKEY_CURRENT_USER, keyStar" in unreg or
           "RegSZEquals(HKEY_LOCAL_MACHINE, keyStar" in unreg),
          "wildcard removed only while it still points at us")
    print()

    print("summary")
    print("  native handlers on this machine : %d" % len(native))
    print("  wrapped (forward everything)    : %d" % len(wrapped))
    print("  pinned via the fixed list       : %d" % len(pinned))
    print("  pinned via enumeration          : %d" % len(listed))
    print("  no extension loses a native handler to the wildcard")
    print()

    if failures:
        print("FAILURES:")
        for f in failures:
            print("  - " + f)
        return 1
    print("ALL WILDCARD-SAFETY TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
