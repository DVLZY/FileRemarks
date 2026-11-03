// Text of the installer's final "what happened" box.
// ---------------------------------------------------------------------------
// v1.18 exists because a re-install / uninstall could finish without telling
// the user anything: the old flow only spoke on success (and stayed silent when
// the choice window was closed), while the elevated child process left the
// outer one with no result at all. Every path now builds one ResultMessage
// here, shows it, and writes the same text to the diagnostic log.
//
// The builders are pure string functions on purpose: tools/test_installer_result.py
// asserts what the user will actually read through a ctypes wrapper, without
// driving MessageBox (which cannot be automated in the sandbox) or UAC.
// ---------------------------------------------------------------------------
#pragma once

#include <windows.h>
#include <string>
#include <vector>

namespace fr {

enum class ResultKind { Ok = 0, Partial = 1, Failed = 2 };

// Which action the box describes, so a failure can be titled 安装失败 or
// 卸载失败 instead of one generic wording.
enum class Action { Install = 0, Reinstall = 1, Uninstall = 2 };

struct ResultMessage
{
    ResultKind kind = ResultKind::Ok;
    std::wstring text;
};

inline const WCHAR* KindName(ResultKind k)
{
    switch (k)
    {
    case ResultKind::Partial: return L"partial";
    case ResultKind::Failed:  return L"failed";
    default:                  return L"ok";
    }
}

// Windows-style error code, uppercase 8 hex digits (same shape as Hex() in
// selfext.cpp; kept local so the header stands on its own in the test DLL).
inline std::wstring FormatHex(DWORD v)
{
    static const WCHAR digits[] = L"0123456789ABCDEF";
    WCHAR buf[9] = { 0 };
    for (int i = 7; i >= 0; --i) { buf[i] = digits[v & 0xF]; v >>= 4; }
    return std::wstring(buf, 8);
}

// Where Log() writes: %TEMP%\FileRemarks_log.txt. Every result box names it, so
// "查看日志" never leaves the user guessing which file to open.
inline std::wstring LogPath()
{
    WCHAR tmp[MAX_PATH] = { 0 };
    if (!GetTempPathW(MAX_PATH, tmp)) return L"%TEMP%\\FileRemarks_log.txt";
    return std::wstring(tmp) + L"FileRemarks_log.txt";
}

// A single list of everything that did not go as planned. An install/uninstall
// with entries here is reported as Partial rather than Ok: the box must never
// claim a clean success while a registry write silently failed.
inline std::wstring WarningBlock(const std::vector<std::wstring>& warnings)
{
    if (warnings.empty()) return std::wstring();
    std::wstring s = L"\r\n以下项目没能完成（不影响主要功能，但请留意）：\r\n";
    for (size_t i = 0; i < warnings.size(); ++i)
        s += L"  - " + warnings[i] + L"\r\n";
    return s;
}

// What to say about the 备注 column, based on the number of folder types the
// registered handler reports. Never promises more than the DLL read back.
inline std::wstring ColumnNote(int columnTypes)
{
    if (columnTypes >= 6)
        return L"资源管理器里的“备注”列已经设为默认列。\r\n";
    if (columnTypes > 0)
        return L"资源管理器里的“备注”列已经设为默认列（" + std::to_wstring(columnTypes) +
               L" 种文件夹类型，其余可手动添加）。\r\n";
    return L"“备注”列没能自动打开，可以在资源管理器里右键列标题手动勾选“备注”。\r\n";
}

inline ResultMessage BuildInstallResult(bool reinstall,
                                        const std::wstring& installDir,
                                        const std::wstring& versionFull,
                                        int columnTypes,
                                        bool legacyRemains,
                                        const std::vector<std::wstring>& warnings)
{
    ResultMessage m;
    m.kind = warnings.empty() ? ResultKind::Ok : ResultKind::Partial;
    m.text = reinstall ? L"已重新安装到 " : L"已安装到 ";
    m.text += installDir + L"（版本 " + versionFull + L"）";
    if (!warnings.empty()) m.text += L" —— 部分项目未完成";
    m.text += L"\r\n\r\n";
    m.text += L"在任意文件上点右键 → “编辑备注”；也可以选中文件按 Shift+F2。\r\n";
    m.text += ColumnNote(columnTypes);
    // Explorer keeps a saved view per folder the user has already opened, and
    // that saved layout wins over the default. Saying so here is cheaper than
    // letting the user think the install failed.
    m.text += L"已经打开过的文件夹会保留原来的列设置；重启“资源管理器”后，"
              L"新打开的窗口就会带上“备注”列。\r\n";
    if (legacyRemains)
        m.text += L"\r\n旧版本（v1.9 - v1.15）留下的用户目录已经不再使用，重启后会自动删除。\r\n";
    m.text += WarningBlock(warnings);
    m.text += L"\r\n诊断日志：" + LogPath();
    return m;
}

inline ResultMessage BuildUninstallResult(const std::wstring& installDir,
                                          const std::vector<std::wstring>& warnings)
{
    ResultMessage m;
    m.kind = warnings.empty() ? ResultKind::Ok : ResultKind::Partial;
    m.text = warnings.empty() ? L"已卸载完成。" : L"已卸载，但部分项目没有完全移除。";
    m.text += L"\r\n\r\n已移除：右键菜单、“备注”列登记、开机启动项，"
              L"以及“应用和功能”里的卸载条目。\r\n";
    if (!installDir.empty())
    {
        m.text += L"\r\n安装目录：" + installDir + L"\r\n";
        m.text += L"（程序文件通常还被资源管理器占用，会在下次重启时自动删除。）\r\n";
    }
    m.text += L"\r\n重启“资源管理器”或注销后生效。\r\n";
    m.text += WarningBlock(warnings);
    m.text += L"\r\n诊断日志：" + LogPath();
    return m;
}

inline ResultMessage BuildCancelResult()
{
    ResultMessage m;
    m.kind = ResultKind::Ok;
    m.text = L"已取消，未做任何更改。\r\n\r\n"
             L"右键菜单和“备注”列都保持原样。\r\n"
             L"如需继续，请重新运行安装程序。\r\n\r\n"
             L"诊断日志：" + LogPath();
    return m;
}

inline ResultMessage BuildFailureResult(Action action, const std::wstring& error,
                                        DWORD code = 0)
{
    ResultMessage m;
    m.kind = ResultKind::Failed;
    m.text = action == Action::Uninstall ? L"卸载失败。\r\n\r\n" : L"安装失败。\r\n\r\n";
    m.text += error;
    if (code != 0)
        m.text += L"\r\n\r\n错误码 0x" + FormatHex(code);
    m.text += L"\r\n\r\n诊断日志：" + LogPath();
    m.text += L"\r\n如果反复失败，请把这份日志发给作者。";
    return m;
}

// Used by the outer (non-elevated) instance: it cannot see the elevated child's
// message box, so it waits for a result marker file. No marker after the child
// exits means nothing was reported and this box takes over.
inline ResultMessage BuildNoResultResult(const std::wstring& logPath, bool stillRunning,
                                        DWORD exitCode = 0)
{
    ResultMessage m;
    m.kind = ResultKind::Failed;
    m.text = stillRunning
        ? L"安装程序仍在运行，但很久没有返回结果。"
        : L"安装程序已经退出，但没能确认操作结果。";
    m.text += L"\r\n\r\n可能是被安全软件拦截，或者安装程序提前结束了。"
              L"\r\n请先看完当前打开的窗口；如果已经没有任何窗口，请查看诊断日志：\r\n\r\n";
    m.text += logPath.empty() ? LogPath() : logPath;
    // The child reports its own outcome through the marker; this exit code is
    // only the last hint when even that did not happen.
    if (!stillRunning && exitCode != 0)
        m.text += L"\r\n\r\n（安装程序退出码 " + std::to_wstring(exitCode) + L"）";
    m.text += L"\r\n\r\n如果“应用和功能”里的版本没有变化，请重新运行安装程序。";
    return m;
}

// --- parent/child handshake -------------------------------------------------
// The elevated child writes this marker immediately BEFORE its result box, so
// the marker means "the child has something to say": the outer instance must
// stay quiet and let the child's box be the single result the user sees.
inline std::wstring MakeResultMarkerPath()
{
    WCHAR tmp[MAX_PATH] = { 0 };
    if (!GetTempPathW(MAX_PATH, tmp)) return std::wstring();
    WCHAR name[64] = { 0 };
    wsprintfW(name, L"FileRemarks_result_%lu.txt",
              (unsigned long)GetCurrentProcessId());
    return std::wstring(tmp) + name;
}

inline bool WriteResultMarker(const std::wstring& path, ResultKind kind)
{
    if (path.empty()) return false;
    HANDLE h = CreateFileW(path.c_str(), GENERIC_WRITE, FILE_SHARE_READ, nullptr,
                           CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (h == INVALID_HANDLE_VALUE) return false;
    const std::wstring line = std::wstring(L"kind=") + KindName(kind) + L"\r\n";
    const int n = WideCharToMultiByte(CP_UTF8, 0, line.c_str(), (int)line.size(),
                                      nullptr, 0, nullptr, nullptr);
    bool ok = false;
    if (n > 0)
    {
        std::string u((size_t)n, '\0');
        WideCharToMultiByte(CP_UTF8, 0, line.c_str(), (int)line.size(), &u[0], n,
                            nullptr, nullptr);
        DWORD written = 0;
        ok = WriteFile(h, u.data(), (DWORD)u.size(), &written, nullptr) &&
             written == u.size();
    }
    CloseHandle(h);
    return ok;
}

inline bool ResultMarkerExists(const std::wstring& path)
{
    return !path.empty() &&
           GetFileAttributesW(path.c_str()) != INVALID_FILE_ATTRIBUTES;
}

inline void DeleteResultMarker(const std::wstring& path)
{
    if (!path.empty()) DeleteFileW(path.c_str());
}

} // namespace fr
