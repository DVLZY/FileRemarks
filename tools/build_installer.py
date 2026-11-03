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
import re
import struct
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD = os.path.join(ROOT, "build")
DIST = os.path.join(ROOT, "dist")
MINGW = os.path.join(ROOT, "tools", "mingw64", "bin")
GPP = os.path.join(MINGW, "g++.exe")
WINDRES = os.path.join(MINGW, "windres.exe")

FILES = [
    "FileRemarksPropHandler.dll",
    "FileRemarksShellExt.dll",
    "FileRemarksEditor.exe",
    "FileRemarksHotkey.exe",
]

MARKER = b"FRPKTEOF"


def read_version():
    """Return (1, 18, 0, 0, "1.18.0.0") from src/version.h.

    The resource compiled below is what Explorer's "详情" tab and the UAC prompt
    show as 文件版本; it must come from the same header the installer prints,
    otherwise the setup exe and its own result box disagree.
    """
    with open(os.path.join(ROOT, "src", "version.h"), encoding="utf-8") as f:
        text = f.read()

    def one(name):
        m = re.search(r'#define\s+' + name + r'\s+L?"([^"]+)"', text)
        if not m:
            raise SystemExit("cannot read %s from src/version.h" % name)
        return m.group(1)

    full = one("FR_VERSION_FULL")
    parts = [int(p) for p in full.split(".")]
    if len(parts) != 4:
        raise SystemExit("FR_VERSION_FULL must be a.b.c.d, got %r" % full)
    return parts + [full]


def build_version_resource():
    a, b, c, d, full = read_version()
    rc = os.path.join(BUILD, "_selfext_version.rc")
    obj = os.path.join(BUILD, "_selfext_version.o")
    with open(rc, "w", encoding="utf-8") as f:
        f.write('''1 VERSIONINFO
FILEVERSION %d,%d,%d,%d
PRODUCTVERSION %d,%d,%d,%d
FILEFLAGSMASK 0x3fL
FILEFLAGS 0x0L
FILEOS 0x40004L
FILETYPE 0x1L
FILESUBTYPE 0x0L
BEGIN
  BLOCK "StringFileInfo"
  BEGIN
    BLOCK "080404b0"
    BEGIN
      VALUE "CompanyName", "FileRemarks"
      VALUE "FileDescription", "FileRemarks 安装程序"
      VALUE "FileVersion", "%s"
      VALUE "InternalName", "FileRemarks_Setup"
      VALUE "OriginalFilename", "FileRemarks_Setup.exe"
      VALUE "ProductName", "FileRemarks"
      VALUE "ProductVersion", "%s"
    END
  END
  BLOCK "VarFileInfo"
  BEGIN
    VALUE "Translation", 0x804, 1200
  END
END
''' % (a, b, c, d, a, b, c, d, full, full))
    subprocess.run([WINDRES, "--codepage=65001",
                    "-I" + os.path.join(ROOT, "src"),
                    "-o", obj, rc], check=True)
    return obj


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
    print("[*] Compiling self-extractor (version resource from src/version.h) ...")
    version_obj = build_version_resource()
    cmd.insert(cmd.index("-o"), version_obj)
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
