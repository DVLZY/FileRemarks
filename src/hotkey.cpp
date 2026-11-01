// FileRemarksHotkey.exe -- background helper for the Shift+F2 shortcut.
//
// Starts with Windows (the installer writes HKCU\...\Run), holds the hotkey and
// does nothing else. It shows no window and no tray icon: the product's whole
// point is to stay out of the way, and a background process whose only job is to
// open a dialog when asked does not need a face.
//
// Closing the hidden window (WM_CLOSE) stops it, which is how the uninstaller
// releases the .exe before deleting it.

#include "hotkey.h"

#include <objbase.h>

namespace {

// Probe before claiming the shortcut: no point owning a window if the
// combination is already taken by another program.
bool HotkeyAvailable()
{
    if (!RegisterHotKey(nullptr, fr::hotkey::kHotkeyId, fr::hotkey::kModifiers,
                        fr::hotkey::kVirtualKey))
        return false;
    UnregisterHotKey(nullptr, fr::hotkey::kHotkeyId);
    return true;
}

// Resolve and open. Called from WM_HOTKEY, i.e. while the user holds the keys in
// whatever window is in front.
void OpenEditorForSelection()
{
    const HWND foreground = GetForegroundWindow();
    const std::wstring path = fr::hotkey::SelectedPathForWindow(foreground);
    if (path.empty())
    {
        // Nothing selected (or a virtual item with no path): stay silent, the
        // user simply pressed the keys with nothing to edit -- but leave a
        // trace, because otherwise this looks identical to a broken shortcut.
        fr::hotkey::TraceLog(L"hotkey fired: foreground=" +
                             std::to_wstring((unsigned long long)(ULONG_PTR)foreground) +
                             L" selection=none");
        return;
    }
    const bool ok = fr::hotkey::LaunchEditor(path);
    fr::hotkey::TraceLog(L"hotkey fired: file=" + path +
                         (ok ? L" launch=ok" : L" launch=FAILED"));
}

LRESULT CALLBACK WndProc(HWND hWnd, UINT msg, WPARAM wParam, LPARAM lParam)
{
    switch (msg)
    {
    case WM_HOTKEY:
        if (wParam == (WPARAM)fr::hotkey::kHotkeyId)
            OpenEditorForSelection();
        return 0;

    case fr::hotkey::WM_QUERY_COMBO:
        // Lets the automated test prove the running process holds the shortcut
        // this source file promises.
        return (LRESULT)fr::hotkey::PackedCombo();

    case WM_CLOSE:
        DestroyWindow(hWnd);
        return 0;

    case WM_DESTROY:
        UnregisterHotKey(hWnd, fr::hotkey::kHotkeyId);
        PostQuitMessage(0);
        return 0;
    }
    return DefWindowProcW(hWnd, msg, wParam, lParam);
}

} // namespace

int WINAPI WinMain(HINSTANCE hInst, HINSTANCE, LPSTR, int)
{
    // One instance only: a second copy would fail to register the same hotkey
    // anyway and would just sit in memory.
    HANDLE mutex = CreateMutexW(nullptr, FALSE, fr::hotkey::kMutexName);
    if (mutex && GetLastError() == ERROR_ALREADY_EXISTS)
        return 0;

    if (FAILED(CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED)))
        return 1;

    if (!HotkeyAvailable())
    {
        fr::hotkey::TraceLog(L"helper exiting: Shift+F2 is taken by another program");
        CoUninitialize();
        return 0; // another program owns Shift+F2 -- nothing to do
    }

    WNDCLASSEXW wc = { sizeof(wc) };
    wc.lpfnWndProc = WndProc;
    wc.hInstance = hInst;
    wc.lpszClassName = fr::hotkey::kWindowClass;
    if (!RegisterClassExW(&wc))
    {
        CoUninitialize();
        return 1;
    }

    HWND hWnd = CreateWindowExW(WS_EX_TOOLWINDOW, fr::hotkey::kWindowClass,
                                fr::hotkey::kWindowTitle, WS_POPUP,
                                0, 0, 0, 0, nullptr, nullptr, hInst, nullptr);
    if (!hWnd)
    {
        CoUninitialize();
        return 1;
    }

    // Bind the shortcut to the window, so WM_HOTKEY arrives with a handle the
    // uninstaller can also reach.
    if (!RegisterHotKey(hWnd, fr::hotkey::kHotkeyId, fr::hotkey::kModifiers,
                        fr::hotkey::kVirtualKey))
    {
        DestroyWindow(hWnd);
        CoUninitialize();
        return 0;
    }

    fr::hotkey::TraceLog(L"helper started, shortcut=Shift+F2");

    MSG msg;
    while (GetMessageW(&msg, nullptr, 0, 0) > 0)
    {
        TranslateMessage(&msg);
        DispatchMessageW(&msg);
    }

    if (mutex) CloseHandle(mutex);
    CoUninitialize();
    return 0;
}
