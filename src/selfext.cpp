// FileRemarks self-extracting installer / uninstaller (fully native, no .bat).
// ---------------------------------------------------------------------------
// A small native GUI program that carries the deployment files appended after
// its own image (see tools/build_installer.py). On launch it:
//   1. asks 安装/重新安装 or 卸载 (no elevation -- see below),
//   2. extracts the payload next to itself (or %TEMP%),
//   3. copies the files to %LOCALAPPDATA%\FileRemarks,
//   4. registers both shell extensions (LoadLibrary + DllRegisterServer), which
//      write under HKCU,
//   5. writes a per-user "应用和功能" uninstall entry,
//   6. cleans up the temp dir.
//
// /uninstall reverses steps 3-5 and schedules its own removal on reboot.
//
// No elevation, on purpose. Everything above lives inside the current user's
// profile, so no administrator token is ever needed -- and an installer that
// never requests one is never given SmartScreen's "发行者未知" warning, which
// Windows only raises when an unsigned executable asks to elevate.
//
// Everything is UTF-16 inside the program, so there is no .bat file and thus
// no ANSI/codepage problem on non-English Windows.
// ---------------------------------------------------------------------------

#include <windows.h>
#include <shellapi.h>
#include <shlobj.h>
#include <objbase.h>
#include <winver.h>
#include <string>
#include <vector>
#include <exception>

#include "theme.h"
#include "logo.h"
#include "installer_ui.h"

// Bump these whenever a release is made: the number is written to
// "Programs and Features" and compared with the installed copy at launch, so
// the dialog can say "v1.2 -> v1.3".
#include "version.h"
// The text of the final result box lives in its own header so the test suite
// can assert exactly what the user will read (v1.18: every action must report
// a result, including a cancelled choice and a silent /uninstall).
#include "result_msg.h"

// ---------------------------------------------------------------------------
// Small helpers
// ---------------------------------------------------------------------------

static void Msg(const std::wstring& text, bool error = false)
{
    MessageBoxW(nullptr, text.c_str(), L"FileRemarks 安装 " FR_BUILD_TAG,
        MB_OK | (error ? MB_ICONERROR : MB_ICONINFORMATION) | MB_SETFOREGROUND);
}

// Diagnostic log -> %TEMP%\FileRemarks_log.txt (UTF-8, appended).
static void Log(const std::wstring& s)
{
    WCHAR tmp[MAX_PATH] = { 0 };
    if (!GetTempPathW(MAX_PATH, tmp)) return;
    std::wstring p = std::wstring(tmp) + L"FileRemarks_log.txt";
    HANDLE h = CreateFileW(p.c_str(), FILE_APPEND_DATA, FILE_SHARE_READ, nullptr,
        OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (h == INVALID_HANDLE_VALUE) return;
    int n = WideCharToMultiByte(CP_UTF8, 0, s.c_str(), (int)s.size(), nullptr, 0, nullptr, nullptr);
    if (n > 0)
    {
        std::string u((size_t)n, '\0');
        WideCharToMultiByte(CP_UTF8, 0, s.c_str(), (int)s.size(), &u[0], n, nullptr, nullptr);
        DWORD wr = 0;
        WriteFile(h, u.data(), (DWORD)u.size(), &wr, nullptr);
    }
    DWORD wr = 0;
    WriteFile(h, "\r\n", 2, &wr, nullptr);
    CloseHandle(h);
}

static bool IsAdmin()
{
    BOOL ok = FALSE;
    HANDLE h = nullptr;
    if (OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &h))
    {
        TOKEN_ELEVATION te;
        DWORD sz = 0;
        if (GetTokenInformation(h, TokenElevation, &te, sizeof(te), &sz))
            ok = te.TokenIsElevated;
        CloseHandle(h);
    }
    return ok != FALSE;
}

static bool ReadAll(HANDLE h, LONGLONG offset, void* buf, DWORD count)
{
    LARGE_INTEGER li; li.QuadPart = offset;
    if (!SetFilePointerEx(h, li, nullptr, FILE_BEGIN)) return false;
    DWORD rd = 0;
    return (ReadFile(h, buf, count, &rd, nullptr) && rd == count);
}

static bool EnsureDir(const std::wstring& path)
{
    if (CreateDirectoryW(path.c_str(), nullptr)) return true;
    return GetLastError() == ERROR_ALREADY_EXISTS;
}

// Machine-wide install location.
//
// The 备注 column needs an HKLM registration. When Windows already ships a
// property handler for a type -- jpg, png, mp3, exe, ... -- an HKCU association
// naming another CLSID is simply ignored, and for .exe the built-in handler then
// fails with 0x80070715 and the column stays empty. Only an HKLM entry takes
// that slot, so the program lives next to the other machine-wide shell
// extensions and the installer asks for an administrator token once.
static std::wstring GetProgDir()
{
    // Test hook: the automated probes run inside a sandbox that denies writes
    // outside the project folder, so they point the install root at a
    // throw-away directory to exercise a real install. Unset in normal use.
    WCHAR over[MAX_PATH] = { 0 };
    if (GetEnvironmentVariableW(L"FR_REMARKS_ROOT", over, MAX_PATH) > 0 && over[0])
        return std::wstring(over);

    WCHAR pf[MAX_PATH] = { 0 };
    if (SUCCEEDED(SHGetFolderPathW(nullptr, CSIDL_PROGRAM_FILES, nullptr, 0, pf)))
        return std::wstring(pf) + L"\\FileRemarks";
    return std::wstring(L"C:\\Program Files\\FileRemarks");
}

// Where v1.9 - v1.15 installed the product: inside the current user's profile,
// with a per-user registration. Kept so an upgrade can find that install, tear
// it down and leave exactly one registration behind.
static std::wstring GetLegacyDir()
{
    WCHAR appdata[MAX_PATH] = { 0 };
    if (SUCCEEDED(SHGetFolderPathW(nullptr, CSIDL_LOCAL_APPDATA, nullptr, 0, appdata)))
        return std::wstring(appdata) + L"\\FileRemarks";
    return std::wstring();
}

// Format an error code the way Windows tools do (hex, not decimal).
static std::wstring Hex(DWORD v)
{
    static const WCHAR digits[] = L"0123456789ABCDEF";
    WCHAR buf[9] = { 0 };
    for (int i = 7; i >= 0; --i) { buf[i] = digits[v & 0xF]; v >>= 4; }
    return std::wstring(buf, 8);
}

// Copy src -> dst.
// If dst is in use (typical on a RE-install: Explorer has already loaded the
// shell-extension DLLs), Windows refuses to overwrite it with
// ERROR_SHARING_VIOLATION / ERROR_ACCESS_DENIED.  A loaded DLL cannot be
// overwritten, but it CAN be renamed, so move the stale copy to "<name>.old",
// write the fresh file, and schedule the stale one for deletion on reboot.
static bool InstallFile(const std::wstring& src, const std::wstring& dst, std::wstring& err)
{
    err.clear();
    if (CopyFileW(src.c_str(), dst.c_str(), FALSE)) return true;

    DWORD e = GetLastError();
    if (e != ERROR_SHARING_VIOLATION && e != ERROR_ACCESS_DENIED)
    {
        err = L"复制文件失败：" + dst + L"\n错误码 0x" + Hex(e);
        return false;
    }

    Log(L"locked, moving aside: " + dst + L" err=" + Hex(e));

    // Find a free ".old" name. A leftover from an earlier upgrade may itself
    // still be loaded (it was scheduled for deletion at reboot and the machine
    // has not rebooted yet), so try ".old", ".old1", ".old2", ...
    std::wstring old;
    bool gotFreeName = false;
    for (int i = 0; i < 16; ++i)
    {
        old = dst + L".old" + (i == 0 ? std::wstring() : std::to_wstring(i));
        if (GetFileAttributesW(old.c_str()) == INVALID_FILE_ATTRIBUTES)
        {
            gotFreeName = true;
            break;
        }
        if (DeleteFileW(old.c_str()))
        {
            gotFreeName = true;
            break; // stale copy was free after all
        }
    }
    if (!gotFreeName)
    {
        err = L"无法替换正在使用的文件（旧的备份文件也都无法删除）：\n" + dst +
              L"\n\n请先注销或重启电脑，再运行本安装程序。";
        return false;
    }
    if (!MoveFileExW(dst.c_str(), old.c_str(), MOVEFILE_REPLACE_EXISTING))
    {
        DWORD e2 = GetLastError();
        err = L"无法替换正在使用的文件：\n" + dst +
              L"\n\n错误码 0x" + Hex(e) + L" / 0x" + Hex(e2) +
              L"\n\n请先注销或重启电脑，再运行本安装程序。";
        return false;
    }
    if (!CopyFileW(src.c_str(), dst.c_str(), FALSE))
    {
        DWORD e3 = GetLastError();
        err = L"复制文件失败：" + dst + L"\n错误码 0x" + Hex(e3);
        return false;
    }
    if (!DeleteFileW(old.c_str()))
        MoveFileExW(old.c_str(), nullptr, MOVEFILE_DELAY_UNTIL_REBOOT);
    return true;
}

// Delete a file that may still be loaded; fall back to delete-at-reboot.
static void RemoveFileLazy(const std::wstring& p)
{
    if (GetFileAttributesW(p.c_str()) == INVALID_FILE_ATTRIBUTES) return;
    SetFileAttributesW(p.c_str(), FILE_ATTRIBUTE_NORMAL);
    if (!DeleteFileW(p.c_str()))
        MoveFileExW(p.c_str(), nullptr, MOVEFILE_DELAY_UNTIL_REBOOT);
}

static bool RegisterDll(const std::wstring& dllPath, std::wstring& err)
{
    err.clear();
    HMODULE lib = LoadLibraryW(dllPath.c_str());
    if (!lib)
    {
        DWORD e = GetLastError();
        Log(L"LoadLibrary FAILED " + dllPath + L" err=0x" + Hex(e));
        err = L"（LoadLibrary 失败，错误码 0x" + Hex(e) + L"）";
        return false;
    }
    typedef HRESULT (STDAPICALLTYPE *DllReg)(void);
    DllReg fn = (DllReg)GetProcAddress(lib, "DllRegisterServer");
    bool ok = false;
    if (fn)
    {
        HRESULT hr = fn();
        ok = SUCCEEDED(hr);
        if (!ok)
        {
            Log(L"DllRegisterServer " + dllPath + L" hr=0x" + Hex((DWORD)hr));
            err = L"（DllRegisterServer 失败，HRESULT 0x" + Hex((DWORD)hr) + L"）";
        }
    }
    else
    {
        Log(L"GetProcAddress(DllRegisterServer) failed " + dllPath);
        err = L"（该文件不是有效的扩展 DLL）";
    }
    FreeLibrary(lib);
    return ok;
}

static bool UnregisterDll(const std::wstring& dllPath)
{
    HMODULE lib = LoadLibraryW(dllPath.c_str());
    if (!lib) return true; // already gone is fine
    typedef HRESULT (STDAPICALLTYPE *DllReg)(void);
    DllReg fn = (DllReg)GetProcAddress(lib, "DllUnregisterServer");
    bool ok = true;
    if (fn) ok = SUCCEEDED(fn());
    FreeLibrary(lib);
    return ok;
}

// --- install layout --------------------------------------------------------
//
// The programs live in a per-version sub-directory:
//
//     %LOCALAPPDATA%\FileRemarks\app-1.14\FileRemarksPropHandler.dll
//     ...
//
// and the root holds only the uninstaller (FileRemarksSetup.exe). The reason is
// not tidiness: a property handler is loaded by explorer.exe, and a loaded image
// cannot be replaced -- measured on this machine, copying over the live DLL and
// renaming it both fail with ERROR_ACCESS_DENIED (0x5), because the image is
// mapped without FILE_SHARE_DELETE. Overwriting in place is therefore
// impossible, and "reinstall" used to fail with "无法替换正在使用的文件".
//
// Writing a NEW directory sidesteps that completely: nothing in use is touched,
// the registration is simply pointed at the new place, and the previous
// directory is deleted on the next boot (its DLL is still mapped until then).
static std::wstring MakeFreshAppDir()
{
    std::wstring base = GetProgDir() + L"\\app-" FR_VERSION_TEXT;
    std::wstring cand = base;
    for (int i = 2; i < 100; ++i)
    {
        if (GetFileAttributesW(cand.c_str()) == INVALID_FILE_ATTRIBUTES)
            return cand;
        WCHAR suffix[16] = { 0 };
        wsprintfW(suffix, L"-%d", i);
        cand = base + suffix;
    }
    return base;
}

// Delete a directory and everything in it, deferring to the next boot whatever
// cannot go now (the previous version's DLL is still mapped by explorer).
static void RemoveDirLazy(const std::wstring& dir)
{
    WIN32_FIND_DATAW fd;
    HANDLE h = FindFirstFileW((dir + L"\\*").c_str(), &fd);
    if (h != INVALID_HANDLE_VALUE)
    {
        do
        {
            if (wcscmp(fd.cFileName, L".") == 0 || wcscmp(fd.cFileName, L"..") == 0)
                continue;
            RemoveFileLazy(dir + L"\\" + fd.cFileName);
        } while (FindNextFileW(h, &fd));
        FindClose(h);
    }
    if (!RemoveDirectoryW(dir.c_str()))
        MoveFileExW(dir.c_str(), nullptr, MOVEFILE_DELAY_UNTIL_REBOOT);
}

// Remove every app-* directory except the one just installed. An empty `keep`
// removes all of them, which is what uninstall wants.
static void CleanupOldAppDirs(const std::wstring& keep)
{
    WIN32_FIND_DATAW fd;
    HANDLE h = FindFirstFileW((GetProgDir() + L"\\app-*").c_str(), &fd);
    if (h == INVALID_HANDLE_VALUE) return;
    do
    {
        if (!(fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY)) continue;
        std::wstring dir = GetProgDir() + L"\\" + fd.cFileName;
        if (!keep.empty() && _wcsicmp(dir.c_str(), keep.c_str()) == 0) continue;
        RemoveDirLazy(dir);
    } while (FindNextFileW(h, &fd));
    FindClose(h);
}

// Directories that may hold an installed copy: the root (the flat layout used up
// to v1.13), every per-version app-* directory, and a machine-wide install left
// behind by builds up to v1.8.
static std::vector<std::wstring> CandidateDirs()
{
    std::vector<std::wstring> dirs;
    dirs.push_back(GetProgDir());
    WIN32_FIND_DATAW fd;
    HANDLE h = FindFirstFileW((GetProgDir() + L"\\app-*").c_str(), &fd);
    if (h != INVALID_HANDLE_VALUE)
    {
        do
        {
            if (fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY)
                dirs.push_back(GetProgDir() + L"\\" + fd.cFileName);
        } while (FindNextFileW(h, &fd));
        FindClose(h);
    }
    std::wstring legacy = GetLegacyDir();
    if (!legacy.empty()) dirs.push_back(legacy);
    return dirs;
}

// Set by DoInstall so the success message can ask the DLL that was just
// registered, instead of guessing where it went.
static std::wstring g_lastAppDir;

// Asks the property handler DLL how many of the six folder types really show the
// 备注 column right now. Returns -1 when it cannot be asked.
//
// Why not just assume success: the number is read back out of the registry by
// the DLL itself, so the message shown to the user can only claim what is
// actually there. The previous machine-wide build reported the column as
// enabled while only two of the six folder types had accepted the write.
static int QueryColumnCount(const std::wstring& dllPath)
{
    HMODULE lib = LoadLibraryW(dllPath.c_str());
    if (!lib) return -1;
    typedef int (STDAPICALLTYPE *ColumnCount)(void);
    ColumnCount fn = (ColumnCount)GetProcAddress(lib, "FileRemarksColumnCount");
    const int n = fn ? fn() : -1;
    FreeLibrary(lib);
    return n;
}

// --- Shift+F2 helper -------------------------------------------------------
// FileRemarksHotkey.exe holds the system-wide shortcut and has to be running
// for it to work. It is registered for auto-start under HKCU\...\Run (no
// elevation needed) and started immediately after installing, otherwise the
// shortcut would only start working after a reboot.
static void StopHotkey()
{
    HWND hwnd = FindWindowW(L"FileRemarksHotkeyWnd", nullptr);
    if (!hwnd) return;
    PostMessageW(hwnd, WM_CLOSE, 0, 0);
    // Wait for it to go away: the uninstaller cannot delete a running .exe, and
    // a re-install must replace it before the new copy starts.
    for (int i = 0; i < 50; ++i)
    {
        Sleep(100);
        if (!IsWindow(hwnd)) return;
    }
    Log(L"hotkey helper did not exit");
}

static bool WriteRunEntry(const std::wstring& exePath)
{
    HKEY hk = nullptr;
    LONG r = RegCreateKeyExW(HKEY_CURRENT_USER,
        L"Software\\Microsoft\\Windows\\CurrentVersion\\Run",
        0, nullptr, REG_OPTION_NON_VOLATILE, KEY_WRITE, nullptr, &hk, nullptr);
    if (r != ERROR_SUCCESS) return false;
    const std::wstring quoted = L"\"" + exePath + L"\"";
    r = RegSetValueExW(hk, L"FileRemarksHotkey", 0, REG_SZ,
        (const BYTE*)quoted.c_str(), (DWORD)((quoted.size() + 1) * sizeof(WCHAR)));
    RegCloseKey(hk);
    return r == ERROR_SUCCESS;
}

static void RemoveRunEntry()
{
    HKEY hk = nullptr;
    if (RegOpenKeyExW(HKEY_CURRENT_USER,
            L"Software\\Microsoft\\Windows\\CurrentVersion\\Run",
            0, KEY_WRITE, &hk) != ERROR_SUCCESS)
        return;
    RegDeleteValueW(hk, L"FileRemarksHotkey");
    RegCloseKey(hk);
}

static void StartHotkey(const std::wstring& dir)
{
    const std::wstring exe = dir + L"\\FileRemarksHotkey.exe";
    if (GetFileAttributesW(exe.c_str()) == INVALID_FILE_ATTRIBUTES) return;
    std::wstring command = L"\"" + exe + L"\"";
    STARTUPINFOW si = { sizeof(si) };
    PROCESS_INFORMATION pi = { 0 };
    if (CreateProcessW(exe.c_str(), &command[0], nullptr, nullptr, FALSE, 0,
                       nullptr, dir.c_str(), &si, &pi))
    {
        CloseHandle(pi.hThread);
        CloseHandle(pi.hProcess);
        Log(L"hotkey helper started");
    }
    else
    {
        Log(L"hotkey helper failed to start err=" + Hex(GetLastError()));
    }
}

// Writes the "应用和功能" entry for the current user. Returns false when any
// value could not be written, so the v1.18 result box can say the install is
// only partial instead of silently claiming a clean success.
static bool WriteUninstallEntry(const std::wstring& setupExe)
{
    // Per-user entry: appears in "应用和功能" for this user, and uninstall needs
    // no elevation because everything it removes is inside the user's profile.
    HKEY hk = nullptr;
    LONG r = RegCreateKeyExW(HKEY_CURRENT_USER,
        L"Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\FileRemarks",
        0, nullptr, REG_OPTION_NON_VOLATILE, KEY_WRITE, nullptr, &hk, nullptr);
    if (r != ERROR_SUCCESS)
    {
        Log(L"RegCreateKeyEx(Uninstall) failed " + std::to_wstring(r));
        return false;
    }
    bool ok = true;
    auto setSz = [&](LPCWSTR name, const std::wstring& v) {
        if (RegSetValueExW(hk, name, 0, REG_SZ, (const BYTE*)v.c_str(),
                (DWORD)((v.size() + 1) * sizeof(WCHAR))) != ERROR_SUCCESS)
        {
            Log(L"RegSetValueEx(Uninstall) failed: " + std::wstring(name));
            ok = false;
        }
    };
    std::wstring us = L"\"" + setupExe + L"\" /uninstall";
    setSz(L"DisplayName", L"FileRemarks");
    setSz(L"DisplayVersion", FR_VERSION_FULL);
    setSz(L"DisplayIcon", GetProgDir() + L"\\FileRemarksEditor.exe");
    setSz(L"Publisher", L"FileRemarks");
    setSz(L"InstallLocation", GetProgDir());
    setSz(L"UninstallString", us);
    DWORD one = 1;
    if (RegSetValueExW(hk, L"NoModify", 0, REG_DWORD, (const BYTE*)&one,
                       sizeof(one)) != ERROR_SUCCESS)
        ok = false;
    if (RegSetValueExW(hk, L"NoRepair", 0, REG_DWORD, (const BYTE*)&one,
                       sizeof(one)) != ERROR_SUCCESS)
        ok = false;
    DWORD v = ((DWORD)FR_VERSION_MAJOR << 16) | (DWORD)FR_VERSION_MINOR;
    if (RegSetValueExW(hk, L"VersionMajor", 0, REG_DWORD, (const BYTE*)&v,
                       sizeof(v)) != ERROR_SUCCESS)
        ok = false;
    RegCloseKey(hk);
    return ok;
}

// False only when the key exists and could not be deleted; "already absent"
// counts as success for an uninstall.
static bool RemoveUninstallEntry()
{
    const LONG r = RegDeleteTreeW(HKEY_CURRENT_USER,
        L"Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\FileRemarks");
    if (r == ERROR_SUCCESS || r == ERROR_FILE_NOT_FOUND) return true;
    Log(L"RegDeleteTree(Uninstall) failed " + std::to_wstring(r));
    return false;
}

// ---------------------------------------------------------------------------
// Payload: [u32 count] then per file: [u32 nameLen][name][u32 dataLen][data]
// Tail:    "FRPKTEOF" (8 bytes) + [u32 payloadLen LE]
// ---------------------------------------------------------------------------

static std::wstring ExtractPayload(const std::wstring& self, const std::wstring& dir,
                                   std::vector<std::wstring>& outFiles)
{
    HANDLE h = CreateFileW(self.c_str(), GENERIC_READ, FILE_SHARE_READ, nullptr,
        OPEN_EXISTING, 0, nullptr);
    if (h == INVALID_HANDLE_VALUE) return L"无法读取安装程序自身。";
    LARGE_INTEGER fsize;
    if (!GetFileSizeEx(h, &fsize)) { CloseHandle(h); return L"无法获取文件大小。"; }

    const int TAIL = 12;
    if (fsize.QuadPart < TAIL + 8) { CloseHandle(h); return L"安装包已损坏（文件太小）。"; }

    BYTE tail[TAIL] = { 0 };
    if (!ReadAll(h, fsize.QuadPart - TAIL, tail, TAIL))
    { CloseHandle(h); return L"读取安装包失败。"; }
    if (memcmp(tail, "FRPKTEOF", 8) != 0)
    { CloseHandle(h); return L"这不是有效的 FileRemarks 安装包（缺少数据标记）。\n请重新下载完整的 FileRemarks_Setup.exe。"; }

    DWORD payloadLen = *(DWORD*)(tail + 8);
    if (payloadLen < 4 || ((LONGLONG)payloadLen + TAIL) > fsize.QuadPart)
    { CloseHandle(h); return L"安装包数据长度异常。"; }

    std::vector<BYTE> payload(payloadLen);
    if (!ReadAll(h, fsize.QuadPart - TAIL - payloadLen, payload.data(), payloadLen))
    { CloseHandle(h); return L"读取安装数据失败。"; }
    CloseHandle(h);

    if (!EnsureDir(dir)) return L"无法创建解压目录：" + dir;

    size_t pos = 0;
    auto need = [&](size_t n) { return pos + n <= payload.size(); };
    auto rd32 = [&](DWORD& v) {
        if (!need(4)) return false;
        v = *(DWORD*)(payload.data() + pos);
        pos += 4;
        return true;
    };

    DWORD count = 0;
    if (!rd32(count) || count == 0 || count > 64) return L"安装包数据损坏（文件数量）。";

    for (DWORD i = 0; i < count; ++i)
    {
        DWORD nameLen = 0;
        if (!rd32(nameLen) || nameLen == 0 || nameLen > 260 || !need(nameLen))
            return L"安装包数据损坏（文件名）。";
        std::string name((const char*)(payload.data() + pos), nameLen);
        pos += nameLen;

        DWORD dataLen = 0;
        if (!rd32(dataLen) || !need(dataLen))
            return L"安装包数据损坏（文件内容）。";

        std::wstring outPath = dir + L"\\" + std::wstring(name.begin(), name.end());
        HANDLE oh = CreateFileW(outPath.c_str(), GENERIC_WRITE, 0, nullptr,
            CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
        if (oh == INVALID_HANDLE_VALUE)
            return L"写入临时文件失败：" + outPath + L"\n错误码 0x" +
                   Hex(GetLastError());

        DWORD wr = 0;
        BOOL ok = WriteFile(oh, payload.data() + pos, dataLen, &wr, nullptr);
        CloseHandle(oh);
        if (!ok || wr != dataLen) return L"写入临时文件不完整：" + outPath;

        pos += dataLen;
        outFiles.push_back(outPath);
    }
    return L"";
}

// ---------------------------------------------------------------------------
// Install / uninstall
// ---------------------------------------------------------------------------

// Removes what a per-user build (v1.9 - v1.15) left behind: its HKCU
// registration, the HKCU uninstall entry and the program copies. Two
// registrations naming different DLLs is exactly the state that blanked the
// 备注 column, so an upgrade must never leave the old one in place.
static void CleanupLegacyUserInstall()
{
    const std::wstring legacy = GetLegacyDir();
    if (legacy.empty() || legacy == GetProgDir()) return;
    if (GetFileAttributesW(legacy.c_str()) == INVALID_FILE_ATTRIBUTES) return;

    Log(L"legacy per-user install found: " + legacy);

    std::vector<std::wstring> dirs;
    dirs.push_back(legacy);
    WIN32_FIND_DATAW fd = { 0 };
    HANDLE h = FindFirstFileW((legacy + L"\\app-*").c_str(), &fd);
    if (h != INVALID_HANDLE_VALUE)
    {
        do { dirs.push_back(legacy + L"\\" + fd.cFileName); } while (FindNextFileW(h, &fd));
        FindClose(h);
    }

    // Unregistering through the old DLL is what removes the HKCU associations,
    // the CLSID keys and the column bookkeeping: it knows every key it wrote.
    for (const auto& d : dirs)
    {
        UnregisterDll(d + L"\\FileRemarksPropHandler.dll");
        UnregisterDll(d + L"\\FileRemarksShellExt.dll");
    }
    RegDeleteTreeW(HKEY_CURRENT_USER,
        L"Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\FileRemarks");

    for (const auto& d : dirs)
        RemoveDirLazy(d);
    if (!RemoveDirectoryW(legacy.c_str()))
        MoveFileExW(legacy.c_str(), nullptr, MOVEFILE_DELAY_UNTIL_REBOOT);
    Log(L"legacy per-user install removed");
}

// `warnings` collects everything that did not work but does not stop the
// install. They are reported in the final result box (v1.18) instead of being
// written only to the log, so "installed, but the column/hotkey did not
// register" cannot look like a clean success.
static std::wstring DoInstall(const std::vector<std::wstring>& files,
                              std::vector<std::wstring>& warnings)
{
    // An upgrade from a per-user build has to be torn down first, or the two
    // registrations fight over the same file types (see CleanupLegacyUserInstall).
    StopHotkey();
    CleanupLegacyUserInstall();

    const std::wstring root = GetProgDir();
    if (!EnsureDir(root))
        return L"无法创建安装目录：" + root + L"\n请确认该目录可写。";

    // A brand-new directory per install, so nothing that Explorer has loaded is
    // ever overwritten -- see the comment above MakeFreshAppDir.
    std::wstring dst = MakeFreshAppDir();
    if (!EnsureDir(dst))
        return L"无法创建安装目录：" + dst + L"\n请确认该目录可写。";
    g_lastAppDir = dst;
    for (const auto& f : files)
    {
        std::wstring name = f.substr(f.find_last_of(L"\\/") + 1);
        std::wstring err;
        if (!InstallFile(f, dst + L"\\" + name, err))
            return err + L"\n\n来源：" + f;
    }

    // Copy THIS installer as the uninstaller (it may itself be running, so a
    // plain overwrite of an old copy could fail; InstallFile handles that).
    {
        const std::wstring selfDst = root + L"\\FileRemarksSetup.exe";
        WCHAR self[MAX_PATH] = { 0 };
        GetModuleFileNameW(nullptr, self, MAX_PATH);
        // Re-installing THROUGH the installed copy means source == destination.
        // CopyFileW rejects that with ERROR_SHARING_VIOLATION (0x20), and
        // InstallFile's "rename it aside first" recovery would then move away the
        // very file it was about to copy from. Skipping it is correct: the copy
        // that is running already IS the uninstaller.
        if (_wcsicmp(self, selfDst.c_str()) != 0)
        {
            std::wstring err;
            if (!InstallFile(self, selfDst, err))
            {
                // Without this copy "应用和功能" cannot uninstall later, so the
                // user must be told even though the product itself works.
                Log(L"installer copy failed: " + err); // not fatal
                warnings.push_back(L"安装程序副本没有写入，卸载后目录可能残留（详见日志）");
            }
        }
    }

    std::wstring rerr;
    if (!RegisterDll(dst + L"\\FileRemarksPropHandler.dll", rerr))
        return L"注册“备注列”属性处理器失败。\n" + rerr + L"\n请检查 " + dst +
               L"\\FileRemarksPropHandler.dll 是否被安全软件拦截。";
    if (!RegisterDll(dst + L"\\FileRemarksShellExt.dll", rerr))
        return L"注册右键菜单失败。\n" + rerr + L"\n请检查 " + dst +
               L"\\FileRemarksShellExt.dll 是否被安全软件拦截。";

    if (!WriteUninstallEntry(root + L"\\FileRemarksSetup.exe"))
        warnings.push_back(L"“应用和功能”里没有写入卸载条目，卸载时可能找不到本软件");

    // Install or restart the Shift+F2 helper so the shortcut works straight
    // away. A failure here is worth a log line and a warning, but not a failed
    // install: the editor and the 备注 column work without it.
    StopHotkey();
    if (!WriteRunEntry(dst + L"\\FileRemarksHotkey.exe"))
    {
        Log(L"auto-start entry failed");
        warnings.push_back(L"开机启动项没有写入，重启电脑后 Shift+F2 需要先运行一次程序");
    }
    StartHotkey(dst);

    // The previous version's folder is still mapped by explorer.exe, so its
    // files are removed on the next boot; the registration already points here.
    CleanupOldAppDirs(dst);

    return L"";
}

// `warnings` reports registrations that could not be removed. The uninstall
// still returns "" (err means "stopped, this did not complete"), but the result
// box must say it was only partial rather than claim a clean removal.
static std::wstring DoUninstall(std::vector<std::wstring>& warnings)
{
    const std::wstring dst = GetProgDir();

    // Stop the shortcut helper before touching the files: a running .exe cannot
    // be deleted, and leaving it alive would keep a hotkey that does nothing.
    StopHotkey();
    RemoveRunEntry();

    // Unregister every copy that could be the registered one: the flat layout
    // used up to v1.13 sits in the root, newer installs sit in app-* folders.
    int unregisterFailed = 0;
    for (const auto& dir : CandidateDirs())
    {
        if (!UnregisterDll(dir + L"\\FileRemarksPropHandler.dll")) ++unregisterFailed;
        if (!UnregisterDll(dir + L"\\FileRemarksShellExt.dll")) ++unregisterFailed;
    }
    if (unregisterFailed > 0)
        warnings.push_back(L"有 " + std::to_wstring(unregisterFailed) +
                           L" 个登记项没有卸载成功，重启后“备注”列可能仍然显示（详见日志）");
    if (!RemoveUninstallEntry())
        warnings.push_back(L"“应用和功能”里的卸载条目没有移除");

    // Whole per-version folders, plus the files of a pre-v1.14 flat install.
    CleanupOldAppDirs(std::wstring());

    // The files are usually still loaded by explorer.exe, so a plain delete
    // fails; RemoveFileLazy defers those to the next reboot.
    RemoveFileLazy(dst + L"\\FileRemarksEditor.exe");
    RemoveFileLazy(dst + L"\\FileRemarksHotkey.exe");
    RemoveFileLazy(dst + L"\\FileRemarksPropHandler.dll");
    RemoveFileLazy(dst + L"\\FileRemarksShellExt.dll");

    // Only the copy that lives inside the install directory belongs to us.
    // (An earlier build also scheduled the setup file the user launched from
    // Downloads for deletion at the next boot, which silently removed a file
    // the user still owns.)
    RemoveFileLazy(dst + L"\\FileRemarksSetup.exe");
    if (!RemoveDirectoryW(dst.c_str()))
        MoveFileExW(dst.c_str(), nullptr, MOVEFILE_DELAY_UNTIL_REBOOT);

    // Also clear a per-user install left by v1.9 - v1.15, if one is still there.
    CleanupLegacyUserInstall();
    return L"";
}

// True when a per-user install from v1.9 - v1.15 is still present (its files
// cannot be deleted while explorer.exe maps them, so it lingers until reboot).
static bool LegacyInstalled()
{
    HKEY hk = nullptr;
    if (RegOpenKeyExW(HKEY_CURRENT_USER,
            L"Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\FileRemarks",
            0, KEY_READ, &hk) == ERROR_SUCCESS)
    {
        RegCloseKey(hk);
        return true;
    }
    std::wstring legacy = GetLegacyDir();
    return !legacy.empty() &&
        GetFileAttributesW((legacy + L"\\FileRemarksPropHandler.dll").c_str())
            != INVALID_FILE_ATTRIBUTES;
}

static bool IsInstalled()
{
    // Our own per-user entry first, then the machine-wide one left behind by
    // builds up to v1.8, so upgrading from an old build still shows "installed".
    static const HKEY kRoots[2] = { HKEY_CURRENT_USER, HKEY_LOCAL_MACHINE };
    for (int i = 0; i < 2; ++i)
    {
        HKEY hk;
        if (RegOpenKeyExW(kRoots[i],
                L"Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\FileRemarks",
                0, KEY_READ, &hk) == ERROR_SUCCESS)
        {
            RegCloseKey(hk);
            return true;
        }
    }

    for (const auto& dir : CandidateDirs())
    {
        if (GetFileAttributesW((dir + L"\\FileRemarksPropHandler.dll").c_str())
            != INVALID_FILE_ATTRIBUTES)
            return true;
    }

    std::wstring legacy = GetLegacyDir();
    if (!legacy.empty() &&
        GetFileAttributesW((legacy + L"\\FileRemarksPropHandler.dll").c_str())
        != INVALID_FILE_ATTRIBUTES)
        return true;
    return false;
}

// Version of the copy that is already installed, for the "current -> new" line.
// Prefers the ARP entry we write ourselves; falls back to the version resource
// of the installed DLL.
//
// Builds up to v1.3 all wrote the same placeholder "1.0", so that value means
// "an older build that did not record its version" -- showing "v1.0" there
// would be a lie, so it is reported as such instead.
static std::wstring InstalledVersion()
{
    static const HKEY kRoots[2] = { HKEY_CURRENT_USER, HKEY_LOCAL_MACHINE };
    for (int i = 0; i < 2; ++i)
    {
        HKEY hk;
        if (RegOpenKeyExW(kRoots[i],
                L"Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\FileRemarks",
                0, KEY_READ, &hk) != ERROR_SUCCESS)
            continue;

        WCHAR buf[128] = { 0 };
        DWORD cb = sizeof(buf) - sizeof(WCHAR);
        DWORD type = 0;
        std::wstring v;
        if (RegQueryValueExW(hk, L"DisplayVersion", nullptr, &type,
                (LPBYTE)buf, &cb) == ERROR_SUCCESS && type == REG_SZ && buf[0])
            v = buf;
        RegCloseKey(hk);
        if (v == L"1.0")
            return L"旧版本（未记录版本号）";
        if (!v.empty())
            return L"v" + v;
    }

    // Fall back to the file version of an installed handler DLL.
    const std::vector<std::wstring> dirs = CandidateDirs();
    for (size_t i = 0; i < dirs.size(); ++i)
    {
        if (dirs[i].empty()) continue;
        std::wstring dll = dirs[i] + L"\\FileRemarksPropHandler.dll";
        DWORD dummy = 0;
        DWORD size = GetFileVersionInfoSizeW(dll.c_str(), &dummy);
        if (!size) continue;
        std::vector<BYTE> data(size);
        if (!GetFileVersionInfoW(dll.c_str(), 0, size, data.data())) continue;
        VS_FIXEDFILEINFO* fi = nullptr;
        UINT len = 0;
        if (VerQueryValueW(data.data(), L"\\", (LPVOID*)&fi, &len) && fi &&
            fi->dwSignature == 0xFEEF04BD)
        {
            WCHAR buf[64] = { 0 };
            wsprintfW(buf, L"v%u.%u", HIWORD(fi->dwFileVersionMS),
                      LOWORD(fi->dwFileVersionMS));
            return buf;
        }
    }
    return L"未知";
}

// ---------------------------------------------------------------------------
// The result box (v1.18)
// ---------------------------------------------------------------------------

// Set from /result=<path> when this process is the elevated child. The outer
// instance watches the same file to know the child already reported.
static std::wstring g_resultMarkerPath;

// Show the outcome of an install/uninstall/cancel. Every path ends here, so the
// user never gets a silently closed window: the choice dialog is closed by
// accident more often than not, and an elevated child's box belongs to another
// process (the outer one cannot show it).
static void ShowResult(const fr::ResultMessage& m)
{
    Log(L"RESULT " + std::wstring(fr::KindName(m.kind)) + L": " + m.text);
    // Written BEFORE the box: the parent must never observe "child finished
    // without a result" while this box is actually on screen.
    fr::WriteResultMarker(g_resultMarkerPath, m.kind);
    UINT icon = MB_ICONINFORMATION;
    if (m.kind == fr::ResultKind::Failed) icon = MB_ICONERROR;
    else if (m.kind == fr::ResultKind::Partial) icon = MB_ICONWARNING;
    MessageBoxW(nullptr, m.text.c_str(), L"FileRemarks " FR_VERSION_FULL,
                MB_OK | icon | MB_SETFOREGROUND | MB_TOPMOST);
}

// ---------------------------------------------------------------------------
// Entry point
// ---------------------------------------------------------------------------

int WINAPI WinMain(HINSTANCE, HINSTANCE, LPSTR, int)
{
    CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED);

    int argc = 0;
    LPWSTR* argv = CommandLineToArgvW(GetCommandLineW(), &argc);
    bool uninstall = false, silent = false, elevated = false;
    for (int i = 1; argv && i < argc; ++i)
    {
        std::wstring a = argv[i];
        if (a == L"/uninstall") { uninstall = true; silent = true; }
        if (a == L"/elevated") elevated = true;
        // The elevated child reports back through this marker so the outer
        // instance can keep its mouth shut instead of showing a second box.
        if (a.rfind(L"/result=", 0) == 0) g_resultMarkerPath = a.substr(8);
    }
    if (argv) LocalFree(argv);

    Log(L"=== start admin=" + std::to_wstring(IsAdmin() ? 1 : 0) +
        L" silent=" + std::to_wstring(silent ? 1 : 0) +
        L" uninstall=" + std::to_wstring(uninstall ? 1 : 0));

    // ---- Elevate, because the 备注 column needs a machine-wide registration. ----
    //
    // Property-handler associations are not an HKCU-first lookup: when Windows
    // already ships a handler for a type (jpg, png, mp3, exe, ...), a per-user
    // association naming another CLSID is ignored, and for .exe the built-in
    // handler then fails with 0x80070715 and the column comes up empty. Only an
    // HKLM entry takes that slot, and HKLM needs a token.
    //
    // Known cost: Windows runs its SmartScreen reputation check on an unsigned
    // executable exactly when it asks to elevate, so this build may show
    // 发行者未知 once per install. That dialog cannot be avoided without a
    // purchased code-signing certificate, and it is the price of a column that
    // works for every file type.
    if (!IsAdmin() && !elevated)
    {
        WCHAR self[MAX_PATH] = { 0 };
        if (GetModuleFileNameW(nullptr, self, MAX_PATH) == 0)
        {
            Msg(L"无法获取安装程序路径。", true);
            CoUninitialize();
            return 1;
        }
        // The elevated child writes a marker right before its own result box;
        // this instance waits for the child and only speaks when nothing was
        // reported (child killed, blocked by security software, crash).
        const std::wstring childMarker = fr::MakeResultMarkerPath();
        std::wstring params = L"/elevated";
        if (uninstall) params += L" /uninstall";
        if (!childMarker.empty())
            params += L" /result:\"" + childMarker + L"\"";
        SHELLEXECUTEINFOW sei = { sizeof(sei) };
        sei.lpVerb = L"runas";
        sei.lpFile = self;
        sei.lpParameters = params.c_str();
        sei.nShow = SW_SHOWNORMAL;
        sei.fMask = SEE_MASK_NOCLOSEPROCESS;
        if (!ShellExecuteExW(&sei) || !sei.hProcess)
        {
            const DWORD elevateErr = GetLastError();
            Log(L"elevate FAILED err=" + std::to_wstring(elevateErr));
            // Cancelling the UAC prompt is a normal outcome, not a failure of
            // the install: saying "需要管理员权限" there would leave the user
            // wondering what happened, since they had just said no.
            if (elevateErr == ERROR_CANCELLED)
                Msg(L"已取消：UAC 提权被取消，没有安装或卸载任何内容。"
                    L"\n\n如仍要继续，请重新运行本程序，并在 UAC 提示中点“是”。",
                    true);
            else
                Msg(L"需要管理员权限才能安装。"
                    L"\n\n“备注”列必须登记在机器范围内（HKLM）：Windows 对 exe、jpg、png、mp3"
                    L"这些自带属性处理器的类型只认这项登记，只登记到当前用户的话，这些类型的"
                    L"备注列会是空的。" L"\n\n请在提示 UAC 时点“是”。"
                    L"\n（错误码 0x" + Hex(elevateErr) + L"）",
                    true);
            CoUninitialize();
            return 1;
        }
        // A machine that runs an on-access scanner can make a first run take a
        // long time; waiting far longer costs nothing because the box only shows
        // up if the child really failed to report.
        const DWORD wait = WaitForSingleObject(sei.hProcess, 45 * 60 * 1000);
        DWORD code = 0;
        GetExitCodeProcess(sei.hProcess, &code);
        CloseHandle(sei.hProcess);
        Log(L"elevated run finished code=" + std::to_wstring(code) +
            L" wait=" + std::to_wstring(wait));
        if (fr::ResultMarkerExists(childMarker))
        {
            // The child reported; a second box here would be exactly the
            // confusion this release exists to remove.
            Log(L"child reported a result, outer instance stays silent");
            fr::DeleteResultMarker(childMarker);
        }
        else
        {
            Log(L"child left no result marker, showing fallback box (code=" +
                std::to_wstring(code) + L")");
            ShowResult(fr::BuildNoResultResult(fr::LogPath(), wait == WAIT_TIMEOUT, code));
        }
        CoUninitialize();
        return 0;
    }

    // ---- Ask what to do, showing the installed version against this one. ----
    // Everything the final box needs, captured before the action runs: after a
    // successful re-install IsInstalled() is true, so "was it installed
    // before?" cannot be answered afterwards.
    const bool wasInstalled = IsInstalled();
    const bool legacyWasInstalled = LegacyInstalled();
    std::vector<std::wstring> warnings;

    bool doUninstall = uninstall;
    std::wstring installedVersion;
    if (!silent)
    {
        bool installed = wasInstalled;
        if (installed) installedVersion = InstalledVersion();
        Log(L"choice dialog (installed=" + std::to_wstring(installed ? 1 : 0) +
            L", version=" + installedVersion + L", new=v" FR_VERSION_TEXT L")");

        const int choice = fr::ui::ShowChoice(installed, installedVersion,
                                              L"v" FR_VERSION_TEXT L"（本安装包）",
                                              GetModuleHandleW(nullptr));
        Log(L"choice=" + std::to_wstring(choice));

        // Closing the window is a real outcome and must say so: previously it
        // returned silently and looked like the installer had hung or failed.
        if (choice == fr::ui::kChoiceCancel)
        {
            Log(L"cancelled");
            ShowResult(fr::BuildCancelResult());
            CoUninitialize();
            return 3; // cancelled: nothing was changed
        }
        doUninstall = (choice == fr::ui::kChoiceUninstall);
    }

    Log(doUninstall ? L"action=uninstall" : L"action=install");

    // 0 = 完成，1 = 失败，2 = 部分完成，3 = 已取消. The elevated child returns
    // it so the outer instance can at least distinguish "nothing was reported"
    // from "it really failed" (see BuildNoResultResult).
    int exitCode = 0;
    try
    {
        std::wstring err;
        if (doUninstall)
        {
            err = DoUninstall(warnings);
            if (err.empty())
            {
                Log(L"uninstall OK");
                const fr::ResultMessage m =
                    fr::BuildUninstallResult(GetProgDir(), warnings);
                exitCode = m.kind == fr::ResultKind::Ok ? 0 : 2;
                ShowResult(m);
            }
        }
        else
        {
            WCHAR self[MAX_PATH] = { 0 };
            GetModuleFileNameW(nullptr, self, MAX_PATH);
            std::wstring selfPath(self);
            std::wstring base = selfPath.substr(0, selfPath.find_last_of(L"\\/"));
            std::wstring dir = base + L"\\FileRemarks_files";
            if (!EnsureDir(dir))
            {
                WCHAR tmp[MAX_PATH] = { 0 };
                GetTempPathW(MAX_PATH, tmp);
                dir = std::wstring(tmp) + L"FileRemarks";
                EnsureDir(dir);
            }

            std::vector<std::wstring> files;
            err = ExtractPayload(selfPath, dir, files);
            Log(L"extract -> " + std::to_wstring(files.size()) + L" files, err=" + err);

            if (err.empty()) err = DoInstall(files, warnings);

            for (auto& f : files) DeleteFileW(f.c_str());
            RemoveDirectoryW(dir.c_str());

            if (err.empty())
            {
                Log(L"install OK");

                // Ask the property handler how many folder types really show the
                // 备注 column now, instead of assuming the registration worked.
                const std::wstring asked = g_lastAppDir.empty() ? GetProgDir() : g_lastAppDir;
                const int cols = QueryColumnCount(asked + L"\\FileRemarksPropHandler.dll");
                Log(L"column types enabled=" + std::to_wstring(cols));

                // The box names the directory and version, so a re-install into
                // a fresh app-<ver> folder is visible and not a guess.
                const fr::ResultMessage m = fr::BuildInstallResult(
                    wasInstalled, asked, FR_VERSION_FULL, cols,
                    legacyWasInstalled, warnings);
                exitCode = m.kind == fr::ResultKind::Ok ? 0 : 2;
                ShowResult(m);
            }
        }

        if (!err.empty())
        {
            Log(L"FAILED: " + err);
            exitCode = 1;
            ShowResult(fr::BuildFailureResult(
                doUninstall ? fr::Action::Uninstall : fr::Action::Install, err));
        }
    }
    catch (...)
    {
        Log(L"EXCEPTION thrown");
        exitCode = 1;
        ShowResult(fr::BuildFailureResult(
            doUninstall ? fr::Action::Uninstall : fr::Action::Install,
            L"安装程序内部错误（已记录日志）。"));
    }

    CoUninitialize();
    return exitCode;
}
