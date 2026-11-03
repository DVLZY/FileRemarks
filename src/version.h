#pragma once

// Single source of truth for the version number. The installer, the hotkey
// helper, the build scripts and the editor's footer all read it from here, so a
// release can never ship two numbers that disagree with each other. (The editor
// uses it only in the footer; its title bar shows the file name only.)
#define FR_VERSION_MAJOR 1
#define FR_VERSION_MINOR 22
#define FR_VERSION_PATCH 0
#define FR_VERSION_TEXT  L"1.22"
#define FR_VERSION_FULL  L"1.22.0.0"
#define FR_BUILD_TAG     L"v" FR_VERSION_TEXT L"  build 2026-11-03"
