// Test-only wrapper: exposes the native System.Comment helpers so they can be
// exercised in-process from tools/test_native_comment_ctypes.py.
// Not shipped to users.

#include <windows.h>
#include <objbase.h>
#include <string>

#include "remark_io.h"
#include "native_comment.h"

extern "C" __declspec(dllexport)
int FrTestWriteNative(const wchar_t* filePath, const wchar_t* text)
{
    return fr::WriteNativeComment(std::wstring(filePath), std::wstring(text)) ? 1 : 0;
}

extern "C" __declspec(dllexport)
int FrTestReadNative(const wchar_t* filePath, wchar_t* outBuf, int cap, int* exists)
{
    std::wstring value;
    bool present = false;
    bool ok = fr::ReadNativeComment(std::wstring(filePath), value, present);
    if (exists) *exists = present ? 1 : 0;
    if (outBuf && cap > 0)
    {
        int n = (int)value.size();
        if (n > cap - 1) n = cap - 1;
        if (n > 0) memcpy(outBuf, value.c_str(), n * sizeof(wchar_t));
        outBuf[n] = 0;
    }
    return ok ? 1 : 0;
}

extern "C" __declspec(dllexport)
int FrTestCoInit()
{
    HRESULT hr = CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED);
    return (int)(hr & 0xFFFFFFFF);
}

extern "C" __declspec(dllexport)
int FrTestHandlerIsOurs(const wchar_t* filePath)
{
    return fr::HandlerIsOurs(std::wstring(filePath)) ? 1 : 0;
}

extern "C" __declspec(dllexport)
int FrTestWriteNativeIfNeeded(const wchar_t* filePath, const wchar_t* text)
{
    return fr::WriteNativeCommentIfNeeded(std::wstring(filePath), std::wstring(text)) ? 1 : 0;
}
