// Minimal probe: does requesting elevation alone (no installer logic at all)
// make Windows Defender SmartScreen raise "发行者未知"?
//
// Run with no arguments: it re-launches ITSELF with the "runas" verb -- the same
// call src/selfext.cpp makes -- then exits.  The elevated copy writes a marker
// file and exits, so nothing is installed and nothing is left running.
//
// If the smart screen dialog appears for this probe, elevation on an unsigned
// binary with no reputation is the trigger, independent of anything the real
// installer does.

#include <windows.h>
#include <shellapi.h>
#include <shlobj.h>
#include <string>

static void Marker(const wchar_t* what)
{
    wchar_t tmp[MAX_PATH] = { 0 };
    GetTempPathW(MAX_PATH, tmp);
    std::wstring path = std::wstring(tmp) + L"FileRemarks_elev_probe.txt";
    HANDLE h = CreateFileW(path.c_str(), FILE_APPEND_DATA, FILE_SHARE_READ,
                           nullptr, OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (h == INVALID_HANDLE_VALUE) return;
    std::wstring line = std::wstring(what) + (IsUserAnAdmin() ? L" [admin]" : L" [user]") + L"\r\n";    DWORD written = 0;
    WriteFile(h, line.c_str(), (DWORD)(line.size() * sizeof(wchar_t)), &written, nullptr);
    CloseHandle(h);
}

int WINAPI wWinMain(HINSTANCE, HINSTANCE, LPWSTR, int)
{
    int argc = 0;
    LPWSTR* argv = CommandLineToArgvW(GetCommandLineW(), &argc);
    bool relaunched = false;
    if (argv)
    {
        for (int i = 1; i < argc; ++i)
            if (lstrcmpiW(argv[i], L"/relaunched") == 0) relaunched = true;
        LocalFree(argv);
    }

    if (relaunched)
    {
        Marker(L"elevated instance started");
        return 0;
    }

    Marker(L"first instance started");

    wchar_t self[MAX_PATH] = { 0 };
    GetModuleFileNameW(nullptr, self, MAX_PATH);

    SHELLEXECUTEINFOW sei = { sizeof(sei) };
    sei.lpVerb = L"runas";
    sei.lpFile = self;
    sei.lpParameters = L"/relaunched";
    sei.nShow = SW_SHOWNORMAL;
    sei.fMask = SEE_MASK_NOCLOSEPROCESS;

    if (!ShellExecuteExW(&sei) || !sei.hProcess)
    {
        Marker(L"elevation request FAILED");
        return 1;
    }
    Marker(L"elevation request accepted");
    WaitForSingleObject(sei.hProcess, 60000);
    CloseHandle(sei.hProcess);
    return 0;
}
