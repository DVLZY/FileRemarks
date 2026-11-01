// Test wrapper for src/hotkey.h: exports the shortcuts and launch helper so
// tools/test_hotkey.py can exercise the real code from Python instead of
// re-implementing it.

#include "hotkey.h"

#include <objbase.h>

#include <string>

static std::wstring g_lastPath;

// (modifiers << 16) | virtual key, without MOD_NOREPEAT.
extern "C" __declspec(dllexport) unsigned int FrTestPackedCombo()
{
    return fr::hotkey::PackedCombo();
}

// Path of the first selected item in the Explorer window that owns `hwnd`.
// Returns an empty string when there is no selection or `hwnd` is not an
// Explorer window. The caller must have COM initialised (the test does).
extern "C" __declspec(dllexport) const wchar_t* FrTestSelectedPath(void* hwnd)
{
    g_lastPath = fr::hotkey::SelectedPathForWindow((HWND)hwnd);
    return g_lastPath.c_str();
}

// Number of items in the folder view of the Explorer window that owns `hwnd`.
// Proves the IShellWindows -> IShellBrowser -> IFolderView2 chain reaches a real
// window (a count > 0 cannot come from a failed lookup), which is what makes an
// empty selection a meaningful "nothing is selected" rather than a broken path.
extern "C" __declspec(dllexport) int FrTestViewItemCount(void* hwnd)
{
    if (!hwnd) return -1;

    const HWND root = GetAncestor((HWND)hwnd, GA_ROOT);
    if (!root) return -1;

    IShellWindows* windows = nullptr;
    if (FAILED(CoCreateInstance(CLSID_ShellWindows, nullptr, CLSCTX_ALL,
                                IID_IShellWindows, (void**)&windows)) || !windows)
        return -1;

    int count = -1;
    long total = 0;
    windows->get_Count(&total);
    for (long i = 0; i < total; ++i)
    {
        VARIANT index;
        VariantInit(&index);
        index.vt = VT_I4;
        index.lVal = i;

        IDispatch* item = nullptr;
        if (FAILED(windows->Item(index, &item)) || !item)
            continue;

        const HWND window = fr::hotkey::WindowOf(item);
        if (window && GetAncestor(window, GA_ROOT) == root)
        {
            IFolderView2* view = fr::hotkey::FolderViewOf(item);
            if (view)
            {
                int items = 0;
                if (SUCCEEDED(view->ItemCount(SVGIO_ALLVIEW, &items)))
                    count = items;
                view->Release();
            }
            item->Release();
            break;
        }
        item->Release();
    }
    windows->Release();
    return count;
}

// Diagnostic: one line per shell window, so a failing lookup can be explained
// instead of guessed at. Format: "n=<count>|<hwnd>=<root>|<hwnd>=<root>|..."
extern "C" __declspec(dllexport) int FrTestDumpShellWindows(wchar_t* buffer, int cch)
{
    if (!buffer || cch <= 0) return 0;
    buffer[0] = 0;

    IShellWindows* windows = nullptr;
    if (FAILED(CoCreateInstance(CLSID_ShellWindows, nullptr, CLSCTX_ALL,
                                IID_IShellWindows, (void**)&windows)) || !windows)
        return 0;

    std::wstring out;
    long total = 0;
    windows->get_Count(&total);
    out += L"n=" + std::to_wstring(total);
    for (long i = 0; i < total; ++i)
    {
        VARIANT index;
        VariantInit(&index);
        index.vt = VT_I4;
        index.lVal = i;

        IDispatch* item = nullptr;
        if (FAILED(windows->Item(index, &item)) || !item)
        {
            out += L"|missing";
            continue;
        }
        const HWND window = fr::hotkey::WindowOf(item);
        IFolderView2* view = fr::hotkey::FolderViewOf(item);
        int items = -1;
        if (view)
        {
            view->ItemCount(SVGIO_ALLVIEW, &items);
            view->Release();
        }
        wchar_t piece[128];
        _snwprintf(piece, 128, L"|w=%llu root=%llu viewItems=%d",
                   (unsigned long long)(ULONG_PTR)window,
                   (unsigned long long)(ULONG_PTR)GetAncestor(window, GA_ROOT),
                   items);
        out += piece;
        item->Release();
    }
    windows->Release();

    if ((int)out.size() + 1 > cch) out.resize(cch - 1);
    wmemcpy(buffer, out.c_str(), out.size() + 1);
    return (int)out.size();
}

// Start the editor for `path` using the shipped launch code; 1 on success.
// The folder is passed in because inside a test process GetModuleFileNameW
// reports the host executable, not the folder the editor lives in.
extern "C" __declspec(dllexport) int FrTestLaunchIn(const wchar_t* dir, const wchar_t* path)
{
    if (!dir || !path) return 0;
    return fr::hotkey::LaunchEditorIn(std::wstring(dir), std::wstring(path)) ? 1 : 0;
}
