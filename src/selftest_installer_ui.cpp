// Test-only wrapper: exposes the installer's choice window so it can be driven
// in-process from tools/test_installer_ui.py. The real installer self-elevates
// before showing this window, which is impossible to automate in this sandbox,
// so the window itself is tested directly instead. Never shipped to users.
//
// ShowChoice() runs its own message loop, so it is started on a worker thread
// (plain CreateThread, no winpthreads dependency); the wrapper publishes the
// window handle and the final choice.

#include <windows.h>
#include <string>

#include "installer_ui.h"

namespace {
struct Session {
    bool installed = false;
    std::wstring curVersion;
    std::wstring newVersion;
    int result = -1;            // -1 while running
    HANDLE thread = nullptr;
};

Session* g_session = nullptr;

DWORD WINAPI ThreadMain(LPVOID param)
{
    Session* s = (Session*)param;
    s->result = fr::ui::ShowChoice(s->installed, s->curVersion, s->newVersion,
                                   GetModuleHandleW(nullptr));
    return 0;
}
} // namespace

// Starts the choice window on a worker thread.
extern "C" __declspec(dllexport) int FrTestStartChoice(int installed,
                                                       const wchar_t* curVersion,
                                                       const wchar_t* newVersion)
{
    if (g_session) return 0;
    g_session = new Session();
    g_session->installed = installed != 0;
    g_session->curVersion = curVersion ? curVersion : L"";
    g_session->newVersion = newVersion ? newVersion : L"";
    g_session->thread = CreateThread(nullptr, 0, ThreadMain, g_session, 0, nullptr);
    return g_session->thread ? 1 : 0;
}

// How long the caller should wait for the window to appear, in milliseconds.
extern "C" __declspec(dllexport) int FrTestWaitReady()
{
    for (int i = 0; i < 200; ++i)
    {
        if (FindWindowW(L"FileRemarksInstallChoice", nullptr)) return 1;
        Sleep(25);
    }
    return 0;
}

// Window handle of the choice window, or 0 when it is not up yet.
extern "C" __declspec(dllexport) HWND FrTestChoiceWindow()
{
    return FindWindowW(L"FileRemarksInstallChoice", nullptr);
}

// 1 while the window is still running, 0 once a choice was made.
extern "C" __declspec(dllexport) int FrTestChoiceRunning()
{
    if (!g_session) return 0;
    return g_session->result < 0 ? 1 : 0;
}

// The choice that was made: 0 cancel, 1 install, 2 uninstall, -1 still running.
extern "C" __declspec(dllexport) int FrTestChoiceResult()
{
    if (!g_session) return -2;
    return g_session->result;
}

// Joins the worker thread and frees the session. Call once the choice is made.
extern "C" __declspec(dllexport) int FrTestEndChoice()
{
    if (!g_session) return -2;
    if (g_session->thread)
    {
        WaitForSingleObject(g_session->thread, 5000);
        CloseHandle(g_session->thread);
    }
    const int r = g_session->result;
    delete g_session;
    g_session = nullptr;
    return r;
}
