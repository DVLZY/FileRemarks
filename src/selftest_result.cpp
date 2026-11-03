// Test-only wrapper around the v1.18 result-box text (result_msg.h).
//
// The installer's message boxes cannot be driven from the sandbox (UAC), so the
// text the user will read is exposed here and asserted by
// tools/test_installer_result.py: success/partial/failed wording, the install
// path, the version, and the diagnostic-log path must all be present, and an
// uninstall must never be silent. Not part of the shipped product.
#include "selfext.cpp"

static int CopyOut(const std::wstring& s, wchar_t* buf, int cap)
{
    if (!buf || cap <= 0) return 0;
    int n = (int)s.size();
    if (n > cap - 1) n = cap - 1;
    for (int i = 0; i < n; ++i) buf[i] = s[i];
    buf[n] = 0;
    return n;
}

static std::vector<std::wstring> ToWarnings(const wchar_t* const* warnings,
                                            int count)
{
    std::vector<std::wstring> out;
    for (int i = 0; i < count; ++i)
        if (warnings && warnings[i]) out.emplace_back(warnings[i]);
    return out;
}

static fr::Action ToAction(int action)
{
    if (action == (int)fr::Action::Uninstall) return fr::Action::Uninstall;
    if (action == (int)fr::Action::Reinstall) return fr::Action::Reinstall;
    return fr::Action::Install;
}

extern "C" __declspec(dllexport)
int FrTestLogPath(wchar_t* buf, int cap)
{
    return CopyOut(fr::LogPath(), buf, cap);
}

// Returns the ResultKind; the box text is copied into buf.
extern "C" __declspec(dllexport)
int FrTestInstallResult(int reinstall, const wchar_t* dir, const wchar_t* version,
                        int columnTypes, int legacyRemains,
                        const wchar_t* const* warnings, int warningCount,
                        wchar_t* buf, int cap)
{
    const fr::ResultMessage m = fr::BuildInstallResult(
        reinstall != 0, dir ? std::wstring(dir) : std::wstring(),
        version ? std::wstring(version) : std::wstring(), columnTypes,
        legacyRemains != 0, ToWarnings(warnings, warningCount));
    CopyOut(m.text, buf, cap);
    return (int)m.kind;
}

extern "C" __declspec(dllexport)
int FrTestUninstallResult(const wchar_t* dir,
                          const wchar_t* const* warnings, int warningCount,
                          wchar_t* buf, int cap)
{
    const fr::ResultMessage m = fr::BuildUninstallResult(
        dir ? std::wstring(dir) : std::wstring(),
        ToWarnings(warnings, warningCount));
    CopyOut(m.text, buf, cap);
    return (int)m.kind;
}

extern "C" __declspec(dllexport)
int FrTestCancelResult(wchar_t* buf, int cap)
{
    const fr::ResultMessage m = fr::BuildCancelResult();
    CopyOut(m.text, buf, cap);
    return (int)m.kind;
}

extern "C" __declspec(dllexport)
int FrTestFailureResult(int action, const wchar_t* error, unsigned code,
                        wchar_t* buf, int cap)
{
    const fr::ResultMessage m = fr::BuildFailureResult(
        ToAction(action), error ? std::wstring(error) : std::wstring(),
        (DWORD)code);
    CopyOut(m.text, buf, cap);
    return (int)m.kind;
}

extern "C" __declspec(dllexport)
int FrTestNoResultResult(const wchar_t* logPath, int stillRunning,
                         unsigned exitCode, wchar_t* buf, int cap)
{
    const fr::ResultMessage m = fr::BuildNoResultResult(
        logPath ? std::wstring(logPath) : std::wstring(), stillRunning != 0,
        (DWORD)exitCode);
    CopyOut(m.text, buf, cap);
    return (int)m.kind;
}

// Marker round-trip: the outer instance decides "child already showed a result"
// from exactly this file.
extern "C" __declspec(dllexport)
int FrTestMarkerPath(wchar_t* buf, int cap)
{
    return CopyOut(fr::MakeResultMarkerPath(), buf, cap);
}

extern "C" __declspec(dllexport)
int FrTestWriteMarker(const wchar_t* path, int kind)
{
    return fr::WriteResultMarker(path ? std::wstring(path) : std::wstring(),
                                 (fr::ResultKind)kind) ? 1 : 0;
}

extern "C" __declspec(dllexport)
int FrTestMarkerExists(const wchar_t* path)
{
    return fr::ResultMarkerExists(path ? std::wstring(path) : std::wstring()) ? 1 : 0;
}

extern "C" __declspec(dllexport)
void FrTestDeleteMarker(const wchar_t* path)
{
    fr::DeleteResultMarker(path ? std::wstring(path) : std::wstring());
}
