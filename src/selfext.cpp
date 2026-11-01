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
#define FR_VERSION_MAJOR 1
#define FR_VERSION_MINOR 14
#define FR_VERSION_TEXT  L"1.14"
#define FR_VERSION_FULL  L"1.14.0.0"
#define FR_BUILD_TAG     L"v" FR_VERSION_TEXT L"  build 2026-11-01"

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

// Per-user install location.
//
// Installing under the current user's own profile is what keeps the whole
// program free of elevation: no administrator token is needed to create the
// folder, copy the files, or write the registration under HKCU. That matters
// beyond convenience -- an installer that never asks for elevation is never
// subjected to the SmartScreen "发行者未知" prompt, which Windows raises for an
// unsigned executable the moment it requests an elevated token. Per-user COM and
// shell registration is fully supported: HKCR is a merged view, so
// HKCU\Software\Classes\... simply takes precedence over the machine-wide keys.
static std::wstring GetProgDir()
{
    // Test hook: the automated probes run inside a sandbox that denies writes
    // outside the project folder, so they point the install root at a
    // throw-away directory to exercise a real install. Unset in normal use.
    WCHAR over[MAX_PATH] = { 0 };
    if (GetEnvironmentVariableW(L"FR_REMARKS_ROOT", over, MAX_PATH) > 0 && over[0])
        return std::wstring(over);

    WCHAR appdata[MAX_PATH] = { 0 };
    if (SUCCEEDED(SHGetFolderPathW(nullptr, CSIDL_LOCAL_APPDATA, nullptr, 0, appdata)))
        return std::wstring(appdata) + L"\\FileRemarks";
    return std::wstring(L"C:\\ProgramData\\FileRemarks");
}

// Where builds up to v1.8 installed the product (machine-wide, needs admin).
// Only used to report "an older version is still registered" and to show its
// version number in the dialog.
static std::wstring GetLegacyDir()
{
    WCHAR pf[MAX_PATH] = { 0 };
    if (SUCCEEDED(SHGetFolderPathW(nullptr, CSIDL_PROGRAM_FILES, nullptr, 0, pf)))
        return std::wstring(pf) + L"\\FileRemarks";
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

static void WriteUninstallEntry(const std::wstring& setupExe)
{
    // Per-user entry: appears in "应用和功能" for this user, and uninstall needs
    // no elevation because everything it removes is inside the user's profile.
    HKEY hk = nullptr;
    LONG r = RegCreateKeyExW(HKEY_CURRENT_USER,
        L"Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\FileRemarks",
        0, nullptr, REG_OPTION_NON_VOLATILE, KEY_WRITE, nullptr, &hk, nullptr);
    if (r != ERROR_SUCCESS) { Log(L"RegCreateKeyEx(Uninstall) failed " + std::to_wstring(r)); return; }
    auto setSz = [&](LPCWSTR name, const std::wstring& v) {
        RegSetValueExW(hk, name, 0, REG_SZ, (const BYTE*)v.c_str(),
            (DWORD)((v.size() + 1) * sizeof(WCHAR)));
    };
    std::wstring us = L"\"" + setupExe + L"\" /uninstall";
    setSz(L"DisplayName", L"FileRemarks");
    setSz(L"DisplayVersion", FR_VERSION_FULL);
    setSz(L"DisplayIcon", GetProgDir() + L"\\FileRemarksEditor.exe");
    setSz(L"Publisher", L"FileRemarks");
    setSz(L"InstallLocation", GetProgDir());
    setSz(L"UninstallString", us);
    DWORD one = 1;
    RegSetValueExW(hk, L"NoModify", 0, REG_DWORD, (const BYTE*)&one, sizeof(one));
    RegSetValueExW(hk, L"NoRepair", 0, REG_DWORD, (const BYTE*)&one, sizeof(one));
    DWORD v = ((DWORD)FR_VERSION_MAJOR << 16) | (DWORD)FR_VERSION_MINOR;
    RegSetValueExW(hk, L"VersionMajor", 0, REG_DWORD, (const BYTE*)&v, sizeof(v));
    RegCloseKey(hk);
}

static void RemoveUninstallEntry()
{
    RegDeleteTreeW(HKEY_CURRENT_USER,
        L"Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\FileRemarks");
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

static std::wstring DoInstall(const std::vector<std::wstring>& files)
{
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
        WCHAR self[MAX_PATH] = { 0 };
        GetModuleFileNameW(nullptr, self, MAX_PATH);
        std::wstring err;
        if (!InstallFile(self, root + L"\\FileRemarksSetup.exe", err))
            Log(L"installer copy failed: " + err); // not fatal
    }

    std::wstring rerr;
    if (!RegisterDll(dst + L"\\FileRemarksPropHandler.dll", rerr))
        return L"注册“备注列”属性处理器失败。\n" + rerr + L"\n请检查 " + dst +
               L"\\FileRemarksPropHandler.dll 是否被安全软件拦截。";
    if (!RegisterDll(dst + L"\\FileRemarksShellExt.dll", rerr))
        return L"注册右键菜单失败。\n" + rerr + L"\n请检查 " + dst +
               L"\\FileRemarksShellExt.dll 是否被安全软件拦截。";

    WriteUninstallEntry(root + L"\\FileRemarksSetup.exe");

    // Install or restart the Shift+F2 helper so the shortcut works straight
    // away. A failure here is worth a log line but not a failed install: the
    // editor and the 备注 column work without it.
    StopHotkey();
    if (!WriteRunEntry(dst + L"\\FileRemarksHotkey.exe"))
        Log(L"auto-start entry failed");
    StartHotkey(dst);

    // The previous version's folder is still mapped by explorer.exe, so its
    // files are removed on the next boot; the registration already points here.
    CleanupOldAppDirs(dst);

    return L"";
}

static std::wstring DoUninstall()
{
    const std::wstring dst = GetProgDir();

    // Stop the shortcut helper before touching the files: a running .exe cannot
    // be deleted, and leaving it alive would keep a hotkey that does nothing.
    StopHotkey();
    RemoveRunEntry();

    // Unregister every copy that could be the registered one: the flat layout
    // used up to v1.13 sits in the root, newer installs sit in app-* folders.
    for (const auto& dir : CandidateDirs())
    {
        UnregisterDll(dir + L"\\FileRemarksPropHandler.dll");
        UnregisterDll(dir + L"\\FileRemarksShellExt.dll");
    }
    RemoveUninstallEntry();

    // Whole per-version folders, plus the files of a pre-v1.14 flat install.
    CleanupOldAppDirs(std::wstring());

    // The files are usually still loaded by explorer.exe, so a plain delete
    // fails; RemoveFileLazy defers those to the next reboot.
    RemoveFileLazy(dst + L"\\FileRemarksEditor.exe");
    RemoveFileLazy(dst + L"\\FileRemarksHotkey.exe");
    RemoveFileLazy(dst + L"\\FileRemarksPropHandler.dll");
    RemoveFileLazy(dst + L"\\FileRemarksShellExt.dll");

    WCHAR self[MAX_PATH] = { 0 };
    GetModuleFileNameW(nullptr, self, MAX_PATH);
    RemoveFileLazy(dst + L"\\FileRemarksSetup.exe");
    if (std::wstring(self) != dst + L"\\FileRemarksSetup.exe")
        MoveFileExW(self, nullptr, MOVEFILE_DELAY_UNTIL_REBOOT);
    if (!RemoveDirectoryW(dst.c_str()))
        MoveFileExW(dst.c_str(), nullptr, MOVEFILE_DELAY_UNTIL_REBOOT);

    // Best effort: also clear what builds up to v1.8 left machine-wide. Without
    // an elevated token those writes and deletes are simply refused, which is
    // why every call here ignores its result -- the per-user state above is the
    // one that decides whether the product is gone.
    std::wstring legacy = GetLegacyDir();
    if (!legacy.empty() && legacy != dst)
    {
        UnregisterDll(legacy + L"\\FileRemarksPropHandler.dll");
        UnregisterDll(legacy + L"\\FileRemarksShellExt.dll");
        RegDeleteTreeW(HKEY_LOCAL_MACHINE,
            L"Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\FileRemarks");
        RemoveFileLazy(legacy + L"\\FileRemarksEditor.exe");
        RemoveFileLazy(legacy + L"\\FileRemarksPropHandler.dll");
        RemoveFileLazy(legacy + L"\\FileRemarksShellExt.dll");
        RemoveFileLazy(legacy + L"\\FileRemarksSetup.exe");
        RemoveDirectoryW(legacy.c_str());
    }
    return L"";
}

// True when a machine-wide install from a build up to v1.8 is still present.
static bool LegacyInstalled()
{
    HKEY hk = nullptr;
    if (RegOpenKeyExW(HKEY_LOCAL_MACHINE,
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
// Entry point
// ---------------------------------------------------------------------------

int WINAPI WinMain(HINSTANCE, HINSTANCE, LPSTR, int)
{
    CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED);

    int argc = 0;
    LPWSTR* argv = CommandLineToArgvW(GetCommandLineW(), &argc);
    bool uninstall = false, silent = false;
    for (int i = 1; argv && i < argc; ++i)
    {
        std::wstring a = argv[i];
        if (a == L"/uninstall") { uninstall = true; silent = true; }
    }
    if (argv) LocalFree(argv);

    Log(L"=== start admin=" + std::to_wstring(IsAdmin() ? 1 : 0) +
        L" silent=" + std::to_wstring(silent ? 1 : 0) +
        L" uninstall=" + std::to_wstring(uninstall ? 1 : 0));

    // ---- No elevation, deliberately. ----
    // Everything this program touches lives in the current user's profile: the
    // per-user install folder, the HKCU registration and the HKCU uninstall
    // entry. Requesting an administrator token would add nothing except a UAC
    // prompt and, worse, SmartScreen's "发行者未知" warning -- Windows runs that
    // reputation check on an unsigned executable precisely when it asks to
    // elevate, which is the dialog this build exists to remove.

    // ---- Ask what to do, showing the installed version against this one. ----
    bool doUninstall = uninstall;
    std::wstring installedVersion;
    if (!silent)
    {
        bool installed = IsInstalled();
        if (installed) installedVersion = InstalledVersion();
        Log(L"choice dialog (installed=" + std::to_wstring(installed ? 1 : 0) +
            L", version=" + installedVersion + L", new=v" FR_VERSION_TEXT L")");

        const int choice = fr::ui::ShowChoice(installed, installedVersion,
                                              L"v" FR_VERSION_TEXT L"（本安装包）",
                                              GetModuleHandleW(nullptr));
        Log(L"choice=" + std::to_wstring(choice));

        if (choice == fr::ui::kChoiceCancel) { Log(L"cancelled"); CoUninitialize(); return 0; }
        doUninstall = (choice == fr::ui::kChoiceUninstall);
    }

    Log(doUninstall ? L"action=uninstall" : L"action=install");

    try
    {
        std::wstring err;
        if (doUninstall)
        {
            err = DoUninstall();
            if (err.empty())
            {
                Log(L"uninstall OK");
                Msg(L"已卸载。\n重启“资源管理器”或注销后生效（安装目录将在下次重启时清除）。");
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

            if (err.empty()) err = DoInstall(files);

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

                std::wstring msg =
                    L"安装完成！\n\n在任意文件上点右键 -> “编辑备注” 即可使用。\n"
                    L"也可以先选中一个文件，按 Shift+F2 直接打开备注。\n";
                if (cols >= 6)
                    msg += L"资源管理器里的“备注”列也已经默认打开。\n";
                else if (cols > 0)
                    msg += L"资源管理器里的“备注”列已经打开（" + std::to_wstring(cols) +
                           L" 种文件夹类型，其余的可手动添加）。\n";
                else
                    msg += L"“备注”列没能自动打开，可以在资源管理器里右键列标题手动勾选“备注”。\n";
                msg += L"\n首次使用请重启“资源管理器”或注销重登录。";
                // An older machine-wide build can still be lying around in
                // Program Files; this user-scoped registration supersedes it, so
                // nothing is broken, but telling the user keeps it unsurprising.
                if (LegacyInstalled())
                    msg += L"\n\n旧版本留下的 C:\\Program Files\\FileRemarks 目录已经不再使用，"
                           L"想清理的话需要管理员权限删除它。";
                Msg(msg);
            }
        }

        if (!err.empty())
        {
            Log(L"FAILED: " + err);
            Msg(err + L"\n\n（诊断日志：%TEMP%\\FileRemarks_log.txt）", true);
        }
    }
    catch (...)
    {
        Log(L"EXCEPTION thrown");
        Msg(L"安装程序内部错误（已记录日志）。\n\n诊断日志：%TEMP%\\FileRemarks_log.txt", true);
    }

    CoUninitialize();
    return 0;
}
