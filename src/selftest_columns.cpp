// Test-only wrapper around the default-column logic in shell_columns.h
// ---------------------------------------------------------------------------
// fr::columns::BuildColumnList is pure string manipulation, so it can be
// verified without touching HKLM -- which matters here because this build
// machine denies every registry write. tools/test_columns_ctypes.py loads this
// DLL and drives it.
// ---------------------------------------------------------------------------

#include "shell_columns.h"

using namespace fr;

extern "C" __declspec(dllexport)
int FrTestBuildColumnList(const wchar_t* list, wchar_t* out, int cap)
{
    if (!out || cap <= 0) return -1;
    out[0] = 0;
    WCHAR* merged = columns::BuildColumnList(list);
    if (!merged) return 0;            // nothing to change (already present / empty)
    wcsncpy(out, merged, (size_t)cap - 1);
    out[cap - 1] = 0;
    delete[] merged;
    return 1;
}

extern "C" __declspec(dllexport)
int FrTestAlreadyHasComment(const wchar_t* list)
{
    return columns::AlreadyHasComment(list) ? 1 : 0;
}

// The exact value Windows ships for the Generic folder type, so the test can
// check the real-world input instead of only hand-written strings.
extern "C" __declspec(dllexport)
int FrTestAppendLiteral(wchar_t* out, int cap)
{
    if (!out || cap <= 0) return -1;
    out[0] = 0;
    StringCchCopyW(out, (size_t)cap, columns::SZ_APPEND);
    return 1;
}

// How many of the six tracked folder types currently advertise the 备注 column.
// Read-only, so it works even where the registry is read-only.
extern "C" __declspec(dllexport)
int FrTestCountEnabled()
{
    return columns::CountEnabledFolderTypes();
}

// Runs the real enable path and returns how many types it actually changed.
// On this build machine every write is denied, so the honest answer is 0 -- and
// 0 must not be confused with "it worked silently": EnableCommentColumn() only
// counts a type after reading the value back and finding our column in it.
extern "C" __declspec(dllexport)
int FrTestEnable()
{
    return columns::EnableCommentColumn();
}

// Uninstall repair: strip the token an older release appended to the machine
// default, leaving everything else byte for byte. Returns 1 when it changed.
extern "C" __declspec(dllexport)
int FrTestStripComment(const wchar_t* list, wchar_t* out, int cap)
{
    if (!out || cap <= 0) return -1;
    out[0] = 0;
    return columns::StripAppendedComment(list, out, (size_t)cap) ? 1 : 0;
}
