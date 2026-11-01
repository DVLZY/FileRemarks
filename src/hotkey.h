// Ctrl+Alt+E: open the remark editor for the file selected in Explorer.
//
// Windows gives Explorer no way to add a shortcut of our own, so the only
// supported mechanism is a background program holding a system-wide hotkey
// (RegisterHotKey) and asking the shell what is selected. This header holds the
// whole implementation so both the real program (hotkey.cpp) and the automated
// test (selftest_hotkey.cpp) run the exact same code -- a test that re-implements
// the lookup would prove nothing about what ships.
//
// Why Ctrl+Alt+E and not a bare F8: RegisterHotKey takes the combination away
// from EVERY program on the machine, so a bare F8 would break F8 in browsers,
// Office and IDEs. A modified combination is the accepted way to claim a global
// shortcut. (The alternative, a keyboard hook that only reacts when Explorer is
// in front, needs no global claim but is far more invasive -- and antivirus
// software treats global hooks as suspicious, which this product must avoid.)

#pragma once

#ifndef MOD_NOREPEAT
#define MOD_NOREPEAT 0x4000
#endif

#include <windows.h>
#include <shlobj.h>
#include <shobjidl.h>
#include <servprov.h>
#include <exdisp.h>

#include <string>

namespace fr {
namespace hotkey {

// The single shortcut this product owns, as named constants so the test can
// assert the real values instead of hard-coding its own copies.
inline const UINT kModifiers = MOD_CONTROL | MOD_ALT | MOD_NOREPEAT;
inline const UINT kVirtualKey = 'E';
inline const int  kHotkeyId = 1;
inline const WCHAR* kWindowClass = L"FileRemarksHotkeyWnd";
inline const WCHAR* kWindowTitle = L"FileRemarks 快捷键";
inline const WCHAR* kMutexName = L"FileRemarksHotkeySingleton";
inline const WCHAR* kRunValueName = L"FileRemarksHotkey";

// Window message answered with the packed combination, so a test can prove the
// running process registered what this file says it did.
inline const UINT WM_QUERY_COMBO = WM_APP + 7;

// Modifier bits without MOD_NOREPEAT, packed as (modifiers << 16) | vk.
inline UINT PackedCombo()
{
    return ((kModifiers & ~MOD_NOREPEAT) << 16) | kVirtualKey;
}

// --- shell plumbing --------------------------------------------------------

// HWND behind a shell-window IDispatch (one per open Explorer window).
inline HWND WindowOf(IDispatch* disp)
{
    if (!disp) return nullptr;
    IWebBrowser2* browser = nullptr;
    HWND hwnd = nullptr;
    if (SUCCEEDED(disp->QueryInterface(IID_IWebBrowser2, (void**)&browser)) && browser)
    {
        SHANDLE_PTR value = 0;
        if (SUCCEEDED(browser->get_HWND(&value)))
            hwnd = (HWND)value;
        browser->Release();
    }
    return hwnd;
}

// The folder view of one Explorer window, reached the documented way:
// IServiceProvider -> SID_STopLevelBrowser -> IShellBrowser -> active IShellView.
inline IFolderView2* FolderViewOf(IDispatch* disp)
{
    if (!disp) return nullptr;
    IFolderView2* folderView = nullptr;
    IServiceProvider* provider = nullptr;
    if (SUCCEEDED(disp->QueryInterface(IID_IServiceProvider, (void**)&provider)) && provider)
    {
        IShellBrowser* browser = nullptr;
        if (SUCCEEDED(provider->QueryService(SID_STopLevelBrowser, IID_IShellBrowser,
                                             (void**)&browser)) && browser)
        {
            IShellView* view = nullptr;
            if (SUCCEEDED(browser->QueryActiveShellView(&view)) && view)
            {
                view->QueryInterface(IID_IFolderView2, (void**)&folderView);
                view->Release();
            }
            browser->Release();
        }
        provider->Release();
    }
    return folderView;
}

// Full file-system path of the first selected item, or an empty string.
//
// The product edits one file at a time by design, so when several items are
// selected only the first is used -- silently, because a dialog on every
// multi-selection would be intrusive.
inline std::wstring FirstSelectedPath(IFolderView2* folderView)
{
    if (!folderView) return std::wstring();

    std::wstring path;
    IShellItemArray* items = nullptr;
    if (FAILED(folderView->GetSelection(FALSE, &items)) || !items)
        return path;

    DWORD count = 0;
    if (SUCCEEDED(items->GetCount(&count)) && count > 0)
    {
        IShellItem* item = nullptr;
        if (SUCCEEDED(items->GetItemAt(0, &item)) && item)
        {
            PWSTR text = nullptr;
            if (SUCCEEDED(item->GetDisplayName(SIGDN_FILESYSPATH, &text)) && text)
            {
                path = text;
                CoTaskMemFree(text);
            }
            item->Release();
        }
    }
    items->Release();
    return path;
}

// Path of the file the user selected in the Explorer window that owns
// `foreground`. Empty when Explorer is not in front, nothing is selected, or the
// selection is not a file on disk (a virtual folder item has no path).
inline std::wstring SelectedPathForWindow(HWND foreground)
{
    if (!foreground) return std::wstring();
    const HWND root = GetAncestor(foreground, GA_ROOT);
    if (!root) return std::wstring();

    IShellWindows* windows = nullptr;
    if (FAILED(CoCreateInstance(CLSID_ShellWindows, nullptr, CLSCTX_ALL,
                                IID_IShellWindows, (void**)&windows)) || !windows)
        return std::wstring();

    IDispatch* matched = nullptr;
    IDispatch* only = nullptr;
    int visible = 0;

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

        const HWND hwnd = WindowOf(item);
        if (hwnd && IsWindowVisible(hwnd))
        {
            ++visible;
            if (!only)
            {
                only = item;
                only->AddRef();
            }
            if (GetAncestor(hwnd, GA_ROOT) == root && !matched)
            {
                matched = item;
                matched->AddRef();
            }
        }
        item->Release();

        if (matched) break;
    }
    windows->Release();

    // The window the hotkey was pressed in normally matches by handle. The
    // single-window fallback covers shells that report the browser window under
    // a different top-level handle than the one that owns focus.
    IDispatch* chosen = matched ? matched : (visible == 1 ? only : nullptr);

    std::wstring path;
    if (chosen)
    {
        IFolderView2* folderView = FolderViewOf(chosen);
        if (folderView)
        {
            path = FirstSelectedPath(folderView);
            folderView->Release();
        }
    }
    if (only) only->Release();
    if (matched) matched->Release();
    return path;
}

// Folder this program lives in, which is where the editor is installed next to
// it. Taken from the executable (not the calling module) because the helper is
// the process that owns the shortcut.
inline std::wstring ModuleDir()
{
    WCHAR self[MAX_PATH] = { 0 };
    if (!GetModuleFileNameW(nullptr, self, MAX_PATH)) return std::wstring();
    std::wstring dir(self);
    const size_t slash = dir.find_last_of(L"\\/");
    if (slash == std::wstring::npos) return std::wstring();
    dir.resize(slash);
    return dir;
}

// --- diagnostics -----------------------------------------------------------

// %TEMP%\FileRemarks_hotkey.log, append-only, one line per event.
//
// The shortcut has no window to show an error in, so "I pressed it and nothing
// happened" would otherwise be unexplainable. Three lines cover every case:
// the helper started, the shortcut fired, and what it resolved.
inline std::wstring LogPath()
{
    WCHAR tmp[MAX_PATH] = { 0 };
    if (!GetTempPathW(MAX_PATH, tmp)) return std::wstring();
    return std::wstring(tmp) + L"FileRemarks_hotkey.log";
}

inline void TraceLog(const std::wstring& text)
{
    const std::wstring path = LogPath();
    if (path.empty()) return;

    SYSTEMTIME st;
    GetLocalTime(&st);
    WCHAR stamp[32] = { 0 };
    swprintf(stamp, 32, L"[%02d:%02d:%02d] ", st.wHour, st.wMinute, st.wSecond);

    std::string utf8;
    const std::wstring line = std::wstring(stamp) + text + L"\r\n";
    const int need = WideCharToMultiByte(CP_UTF8, 0, line.c_str(), (int)line.size(),
                                         nullptr, 0, nullptr, nullptr);
    if (need <= 0) return;
    utf8.resize((size_t)need);
    WideCharToMultiByte(CP_UTF8, 0, line.c_str(), (int)line.size(), &utf8[0], need,
                        nullptr, nullptr);

    HANDLE file = CreateFileW(path.c_str(), FILE_APPEND_DATA,
                              FILE_SHARE_READ | FILE_SHARE_WRITE, nullptr,
                              OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (file == INVALID_HANDLE_VALUE) return;
    DWORD written = 0;
    WriteFile(file, utf8.data(), (DWORD)utf8.size(), &written, nullptr);
    CloseHandle(file);
}

// --- start the editor ------------------------------------------------------

inline bool LaunchEditorIn(const std::wstring& dir, const std::wstring& filePath)
{
    if (filePath.empty() || dir.empty()) return false;

    const std::wstring exe = dir + L"\\FileRemarksEditor.exe";
    if (GetFileAttributesW(exe.c_str()) == INVALID_FILE_ATTRIBUTES) return false;

    std::wstring command = L"\"" + exe + L"\" \"" + filePath + L"\"";
    STARTUPINFOW startup = { sizeof(startup) };
    PROCESS_INFORMATION process = { 0 };
    if (!CreateProcessW(exe.c_str(), &command[0], nullptr, nullptr, FALSE, 0,
                        nullptr, dir.c_str(), &startup, &process))
        return false;

    CloseHandle(process.hThread);
    CloseHandle(process.hProcess);
    return true;
}

inline bool LaunchEditor(const std::wstring& filePath)
{
    return LaunchEditorIn(ModuleDir(), filePath);
}

} // namespace hotkey
} // namespace fr
