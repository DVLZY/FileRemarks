#!/usr/bin/env python3
# Build a self-contained FileRemarks_Setup.exe: a small native self-extractor
# (selfext.cpp) with the 4 deployment files appended as a payload.
#
# Output: build/FileRemarks_Setup.exe  (single file, double-click to install)
#
# The self-extractor is a fully native Unicode GUI program: it self-elevates via
# UAC, asks 安装/卸载 with a standard MessageBox, extracts the payload next to
# itself (or %TEMP%), copies to Program Files, registers the shell extensions and
# writes the "Programs and Features" entry. There is no .bat anywhere.
# Pass --uninstall to build a variant that skips the dialog and uninstalls.

import os
import struct
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD = os.path.join(ROOT, "build")
DIST = os.path.join(ROOT, "dist")
MINGW = os.path.join(ROOT, "tools", "mingw64", "bin")
GPP = os.path.join(MINGW, "g++.exe")

FILES = [
    "FileRemarksPropHandler.dll",
    "FileRemarksShellExt.dll",
    "FileRemarksEditor.exe",
    "FileRemarksHotkey.exe",
]

MARKER = b"FRPKTEOF"


def build_selfext():
    out = os.path.join(BUILD, "selfext.obj.exe")
    # The self-extractor now paints its own Windows 11 style choice window
    # (src/installer_ui.h + src/theme.h), so it needs gdi32/comctl32, and it
    # reads the installed version through the version API (winver.h).
    # Libraries MUST come after the source: MinGW's ld discards a library that
    # appears before its first unresolved symbol.
    cmd = [
        GPP,
        "-std=c++17", "-O2", "-Wall", "-DUNICODE", "-D_UNICODE",
        "-mwindows", "-static", "-static-libgcc", "-static-libstdc++",
        "-I" + os.path.join(ROOT, "src"),
        os.path.join(ROOT, "src", "selfext.cpp"),
        "-o", out,
        "-lpropsys", "-lshell32", "-lole32", "-loleaut32", "-luuid",
        "-lcomctl32", "-ladvapi32", "-lgdi32", "-lversion", "-luser32", "-lkernel32",
    ]
    print("[*] Compiling self-extractor ...")
    subprocess.run(cmd, check=True)
    return out


def make_payload():
    payload = bytearray()
    payload += struct.pack("<I", len(FILES))
    for name in FILES:
        data = open(os.path.join(DIST, name), "rb").read()
        name_b = name.encode("utf-8")
        payload += struct.pack("<I", len(name_b))
        payload += name_b
        payload += struct.pack("<I", len(data))
        payload += data
    return bytes(payload)


def main():
    uninstall = "--uninstall" in sys.argv

    # Ensure build artifacts exist.
    missing = [f for f in FILES if not os.path.exists(os.path.join(DIST, f))]
    if missing:
        print("[!] Missing from dist/: ", missing)
        print("    Run tools/build_mingw.sh first (it populates dist/).")
        sys.exit(1)

    selfext = build_selfext()
    payload = make_payload()

    # Single combined installer: supports both install and uninstall in one exe.
    out_path = os.path.join(BUILD, "FileRemarks_Setup.exe")
    with open(selfext, "rb") as f:
        base = f.read()
    with open(out_path, "wb") as f:
        f.write(base)
        f.write(payload)
        f.write(MARKER)                       # 8 bytes
        f.write(struct.pack("<I", len(payload)))  # 4 bytes

    print(f"[+] Wrote {out_path}  ({os.path.getsize(out_path)} bytes)")

    # Sanity: parse the appended payload back and verify each file matches.
    with open(out_path, "rb") as f:
        blob = f.read()
    assert blob[-12:-4] == MARKER, "marker mismatch"
    plen = struct.unpack("<I", blob[-4:])[0]
    p = blob[-12 - plen:-12]
    cnt = struct.unpack("<I", p[:4])[0]
    off = 4
    ok = True
    for _ in range(cnt):
        nl = struct.unpack("<I", p[off:off + 4])[0]; off += 4
        nm = p[off:off + nl].decode("utf-8"); off += nl
        dl = struct.unpack("<I", p[off:off + 4])[0]; off += 4
        data = p[off:off + dl]; off += dl
        orig = open(os.path.join(DIST, nm), "rb").read()
        if data != orig:
            ok = False
            print(f"    [FAIL] {nm} payload mismatch")
    print("[+] Payload self-check:", "PASS" if ok else "FAIL")
    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
