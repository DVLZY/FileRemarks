#!/usr/bin/env bash
# Build all FileRemarks native components with the portable MinGW-w64 toolchain.
# Components: property-handler DLL, context-menu DLL, editor EXE, logic self-test.
# Usage: tools/build_mingw.sh
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MINGW="$ROOT/tools/mingw64/bin"
OUT="$ROOT/build"
mkdir -p "$OUT"

# The portable toolchain is not part of the source tree (it is ~900 MB and
# only a build dependency). Use it when present, otherwise whatever g++ is
# on PATH -- CXX overrides both.
if [ -x "$MINGW/g++.exe" ]; then
    GPP="$MINGW/g++.exe"
else
    GPP="${CXX:-g++}"
    echo "      (toolchain: $GPP from PATH)"
fi
FLAGS="-std=c++17 -O2 -Wall -DUNICODE -D_UNICODE -mthreads -static -static-libgcc -static-libstdc++"
INCS="-I\"$ROOT/src\""
# Libraries must come AFTER the sources/objects: MinGW's ld discards a library
# that appears before its first unresolved symbol (this is what made GDI+ look
# "missing" during early experiments).
LIBS="-lole32 -lpropsys -lshlwapi -luuid -loleaut32 -ladvapi32 -lshell32 -lcomctl32 -lversion -lkernel32 -lgdi32 -luser32 -lz"

echo "[1/6] Building property handler DLL ..."
"$GPP" $FLAGS $INCS -shared "$ROOT/src/FileRemarksPropHandler.cpp" \
    "$ROOT/src/ooxml_meta.cpp" \
    -Wl,--kill-at -o "$OUT/FileRemarksPropHandler.dll" $LIBS
echo "      -> $OUT/FileRemarksPropHandler.dll"

echo "[2/6] Building context-menu DLL ..."
"$GPP" $FLAGS $INCS -shared "$ROOT/src/FileRemarksShellExt.cpp" \
    -Wl,--kill-at -o "$OUT/FileRemarksShellExt.dll" $LIBS
echo "      -> $OUT/FileRemarksShellExt.dll"

echo "[3/6] Building editor EXE ..."
"$GPP" $FLAGS $INCS "$ROOT/src/FileRemarksEditor.cpp" \
    -mwindows -o "$OUT/FileRemarksEditor.exe" $LIBS
echo "      -> $OUT/FileRemarksEditor.exe"

echo "[4/6] Building hotkey helper EXE ..."
"$GPP" $FLAGS $INCS "$ROOT/src/hotkey.cpp" \
    -mwindows -o "$OUT/FileRemarksHotkey.exe" $LIBS
echo "      -> $OUT/FileRemarksHotkey.exe"

echo "[5/6] Building logic self-test ..."
"$GPP" $FLAGS $INCS "$ROOT/src/test_prop.cpp" -o "$OUT/test_prop.exe" $LIBS
echo "      -> $OUT/test_prop.exe"

# Test-only DLLs: wrap internal functions of selfext.cpp so the real code can be
# exercised in-process from tools/*_ctypes.py (not shipped to users).
echo "[6/6] Building test wrappers ..."
"$GPP" $FLAGS $INCS -shared "$ROOT/src/selftest_extract.cpp" \
    -o "$OUT/selftest_extract.dll" $LIBS
"$GPP" $FLAGS $INCS -shared "$ROOT/src/selftest_install.cpp" \
    -o "$OUT/selftest_install.dll" $LIBS
"$GPP" $FLAGS $INCS -shared "$ROOT/src/selftest_native.cpp" \
    -o "$OUT/selftest_native.dll" $LIBS
"$GPP" $FLAGS $INCS -shared "$ROOT/src/selftest_columns.cpp" \
    -o "$OUT/selftest_columns.dll" $LIBS
"$GPP" $FLAGS $INCS -shared "$ROOT/src/selftest_installer_ui.cpp" \
    -o "$OUT/selftest_installer_ui.dll" $LIBS
"$GPP" $FLAGS $INCS -shared "$ROOT/src/selftest_hotkey.cpp" \
    -o "$OUT/selftest_hotkey.dll" $LIBS
# v1.18: the final result-box text and the parent/child marker handshake.
"$GPP" $FLAGS $INCS -shared "$ROOT/src/selftest_result.cpp" \
    -o "$OUT/selftest_result.dll" $LIBS
echo "      -> $OUT/selftest_extract.dll, $OUT/selftest_install.dll, $OUT/selftest_native.dll, $OUT/selftest_columns.dll, $OUT/selftest_installer_ui.dll, $OUT/selftest_hotkey.dll, $OUT/selftest_result.dll"

# Package a ready-to-ship folder: the four binaries.
# Only the top-level files are replaced; dist/releases/ holds every previously
# shipped installer and must survive a rebuild so old versions can be
# re-installed at any time.
DIST="$ROOT/dist"
mkdir -p "$DIST"
rm -f "$DIST/FileRemarksPropHandler.dll" "$DIST/FileRemarksShellExt.dll" \
      "$DIST/FileRemarksEditor.exe" "$DIST/FileRemarksHotkey.exe" \
      "$DIST/FileRemarks_Setup.exe" "$DIST/FileRemarksSetup.exe"
mkdir -p "$DIST/releases"
cp "$OUT/FileRemarksPropHandler.dll" "$DIST/"
cp "$OUT/FileRemarksShellExt.dll"    "$DIST/"
cp "$OUT/FileRemarksEditor.exe"      "$DIST/"
cp "$OUT/FileRemarksHotkey.exe"      "$DIST/"

# Build the single-file installer (native self-extractor with appended payload).
python "$ROOT/tools/build_installer.py"

# Name the installer after its own version, so versions never overwrite each
# other and the file name says what it installs.
VER="$(sed -n 's/.*#define FR_VERSION_TEXT *L"\([^"]*\)".*/\1/p' "$ROOT/src/version.h")"
if [ -z "$VER" ]; then
    echo "ERROR: could not read FR_VERSION_TEXT from src/version.h" >&2
    exit 1
fi
SETUP="$DIST/releases/FileRemarks_Setup_v${VER}.exe"
cp "$OUT/FileRemarks_Setup.exe" "$SETUP"
echo "      -> $SETUP  (双击运行，选择“安装/卸载”)"
echo "      -> $DIST/releases/ 里保留了之前所有版本的安装包："
ls -1 "$DIST/releases/" | sed 's/^/         /'

echo "BUILD OK  (v$VER)"
