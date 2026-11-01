// Test-only wrapper: exposes the REAL InstallFile() from selfext.cpp so the
// "target file is locked by a loaded DLL" path can be exercised in-process
// through ctypes (the sandbox forbids spawning native executables).
// Not part of the shipped product.
#include "selfext.cpp"

// --- install-layout helpers ------------------------------------------------
// These wrap the per-version directory logic so the probes can prove, without
// writing to %LOCALAPPDATA%, that a second install NEVER reuses (and therefore
// never has to overwrite) the directory of a copy that is already loaded.

extern "C" __declspec(dllexport)
int FrTestRoot(wchar_t* buf, int cap)
{
    std::wstring r = GetProgDir();
    int n = (int)r.size();
    if (n > cap - 1) n = cap - 1;
    for (int i = 0; i < n; ++i) buf[i] = r[i];
    buf[n] = 0;
    return n;
}

// Fresh (not yet existing) directory for a new install.
extern "C" __declspec(dllexport)
int FrTestFreshAppDir(wchar_t* buf, int cap)
{
    std::wstring r = MakeFreshAppDir();
    int n = (int)r.size();
    if (n > cap - 1) n = cap - 1;
    for (int i = 0; i < n; ++i) buf[i] = r[i];
    buf[n] = 0;
    return n;
}

// Create the directory MakeFreshAppDir() suggests; 1 on success.
extern "C" __declspec(dllexport)
int FrTestEnsureAppDir(wchar_t* buf, int cap)
{
    std::wstring root = GetProgDir();
    if (!EnsureDir(root)) return 0;
    std::wstring r = MakeFreshAppDir();
    if (!EnsureDir(r)) return 0;
    int n = (int)r.size();
    if (n > cap - 1) n = cap - 1;
    for (int i = 0; i < n; ++i) buf[i] = r[i];
    buf[n] = 0;
    return 1;
}

// Remove every app-* directory except `keep` ("" removes all).
extern "C" __declspec(dllexport)
void FrTestCleanupAppDirs(const wchar_t* keep)
{
    CleanupOldAppDirs(keep ? std::wstring(keep) : std::wstring());
}

// Number of directories CandidateDirs() reports (root + app-* + legacy).
extern "C" __declspec(dllexport)
int FrTestCandidateDirs()
{
    return (int)CandidateDirs().size();
}

// Returns 1 on success, 0 on failure; on failure writes the message to errBuf.
extern "C" __declspec(dllexport)
int FrTestInstall(const wchar_t* src, const wchar_t* dst, wchar_t* errBuf, int errCap)
{
    std::wstring err;
    bool ok = InstallFile(src, dst, err);
    if (!ok && errBuf && errCap > 0)
    {
        int n = (int)err.size();
        if (n > errCap - 1) n = errCap - 1;
        for (int i = 0; i < n; ++i) errBuf[i] = err[i];
        errBuf[n] = 0;
    }
    return ok ? 1 : 0;
}

// Returns the hex-formatted error code for a given value (sanity check of Hex()).
extern "C" __declspec(dllexport)
int FrTestHex(unsigned v, wchar_t* buf, int cap)
{
    std::wstring h = Hex((DWORD)v);
    int n = (int)h.size();
    if (n > cap - 1) n = cap - 1;
    for (int i = 0; i < n; ++i) buf[i] = h[i];
    buf[n] = 0;
    return n;
}

// The version string the installer would show for an already-installed copy,
// plus whether it considers a copy installed at all.
extern "C" __declspec(dllexport)
int FrTestInstalledVersion(wchar_t* buf, int cap)
{
    std::wstring v = InstalledVersion();
    int n = (int)v.size();
    if (n > cap - 1) n = cap - 1;
    for (int i = 0; i < n; ++i) buf[i] = v[i];
    buf[n] = 0;
    return n;
}

extern "C" __declspec(dllexport)
int FrTestIsInstalled()
{
    return IsInstalled() ? 1 : 0;
}

// The target version the installer advertises, so the test can assert the two
// sides differ and that the "current" side is not silently the same string.
extern "C" __declspec(dllexport)
int FrTestNewVersion(wchar_t* buf, int cap)
{
    std::wstring v = L"v" FR_VERSION_TEXT L"（本安装包）";
    int n = (int)v.size();
    if (n > cap - 1) n = cap - 1;
    for (int i = 0; i < n; ++i) buf[i] = v[i];
    buf[n] = 0;
    return n;
}
