// FileRemarks Property Handler
// ---------------------------------------------------------------------------
// A native Windows shell extension (in-process COM DLL) that adds a "备注"
// (Remark) column to File Explorer for files that have no system-owned
// property handler. The remark text is stored per-file in an NTFS Alternate
// Data Stream (ADS) named ":remark" (UTF-8), so it travels with the file when
// it is renamed or moved on the same volume.
//
// For file types that Windows already owns a property handler for (jpg, png,
// exe, ...) our handler *wraps* that original handler instead of replacing it:
// every native property is forwarded to it, and only the Remark key is added.
// The original handler CLSID is remembered under
//   HKLM\Software\FileRemarks\Original\.<ext>
// so uninstall restores the exact previous association.
//
// Implements:
//   * IPropertyStore            -> supplies the Remark value (the column)
//   * IInitializeWithItem       -> gets the file path from the IShellItem
//   * IInitializeWithFile       -> gets the file path directly
//   * IPropertyStoreCapabilities-> marks the property as writable
//
// Build: see tools/build_msvc.bat (MSVC) and tools/build_mingw.sh (MinGW).
// ---------------------------------------------------------------------------

#include <windows.h>
#include <shobjidl.h>
#include <propsys.h>
#include <propkey.h>
#include <shlwapi.h>
#include <strsafe.h>

#include <string>
#include <vector>

#include "remark.h"
#include "remark_io.h"
#include "shell_columns.h"

// Shared definitions (must be extern "C" so the editor/test link against them).
extern "C" const CLSID CLSID_FileRemarksPropHandler =
{ 0xb4c8e6d1, 0x7a2f, 0x4c3b, { 0x9d, 0x5e, 0x1f, 0x6c, 0x2a, 0x8b, 0x3d, 0x41 } };

// The property we publish. It is the built-in System.Comment -- Windows already
// describes it as "备注" (edit invitation "添加备注"), so Explorer's own 备注
// column is the one that shows our value and no custom schema is needed.
#define PKEY_FileRemark PKEY_Comment

static const WCHAR SZ_CLSID[] = L"{B4C8E6D1-7A2F-4c3b-9D5E-1F6C2A8B3D41}";

// Module lock counter for DllCanUnloadNow.
static volatile LONG g_cLocks = 0;
static void DllAddRef()  { InterlockedIncrement(&g_cLocks); }
static void DllRelease() { InterlockedDecrement(&g_cLocks); }

// Defined with the other registry helpers below; declared here because the
// handler needs it to find the handler it should forward to.
static bool RegGetSZ(HKEY hRoot, const WCHAR* subKey, const WCHAR* valueName,
                     WCHAR* out, DWORD cch);

// ----- Diagnostics ---------------------------------------------------------
// One line per process, written only when a handler is initialised through
// IInitializeWithStream. It exists so a report of "the 备注 column is empty" can
// be answered from a log file: the name Windows hands over decides whether the
// remark (an alternate data stream) can be found at all.
static bool g_streamNameLogged = false;

static void DiagLog(const std::wstring& line)
{
    WCHAR temp[MAX_PATH] = { 0 };
    if (!GetTempPathW(ARRAYSIZE(temp), temp)) return;
    std::wstring path = temp;
    path += L"FileRemarks_propdiag.log";
    HANDLE h = CreateFileW(path.c_str(), FILE_APPEND_DATA,
                           FILE_SHARE_READ | FILE_SHARE_WRITE, nullptr,
                           OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (h == INVALID_HANDLE_VALUE) return;
    SYSTEMTIME t;
    GetLocalTime(&t);
    WCHAR stamp[64] = { 0 };
    StringCchPrintfW(stamp, ARRAYSIZE(stamp), L"[%02d:%02d:%02d] ", t.wHour,
                     t.wMinute, t.wSecond);
    std::wstring text = stamp + line;
    text.push_back(13);
    text.push_back(10);
    DWORD written = 0;
    WriteFile(h, text.c_str(), (DWORD)(text.size() * sizeof(WCHAR)), &written,
              nullptr);
    CloseHandle(h);
}

// ----- The property handler -----------------------------------------------
class CRemarkPropertyHandler
    : public IPropertyStore
    , public IInitializeWithItem
    , public IInitializeWithFile
    , public IInitializeWithStream
    , public IPropertyStoreCapabilities
{
private:
    long      m_cRef;
    IShellItem* m_psi;
    WCHAR     m_szPath[MAX_PATH];
    bool      m_fInit;
    bool      m_fRead;
    std::wstring m_remark;

    // The handler Windows originally used for this file type, if any. Every
    // property other than the Remark is forwarded to it, so taking over the
    // slot never costs the user their native columns (dimensions, EXIF, ...).
    IPropertyStore* m_pNative;

    // Set when a native value was edited through us, so Commit() forwards.
    bool m_fNativeDirty;

    // Creates and initialises the original handler named by `clsid` for the
    // current file. Failures are not fatal: we simply have nothing to forward.
    void LoadNative(REFCLSID clsid)
    {
        if (clsid == CLSID_FileRemarksPropHandler) return;

        IUnknown* punk = nullptr;
        if (FAILED(CoCreateInstance(clsid, nullptr, CLSCTX_INPROC_SERVER,
            IID_IUnknown, (void**)&punk)) || !punk)
            return;

        HRESULT hr = E_NOINTERFACE;

        IInitializeWithItem* pItem = nullptr;
        if (SUCCEEDED(punk->QueryInterface(IID_PPV_ARGS(&pItem))) && pItem)
        {
            hr = pItem->Initialize(m_psi, 0);
            pItem->Release();
        }
        else
        {
            IInitializeWithFile* pFile = nullptr;
            if (SUCCEEDED(punk->QueryInterface(IID_PPV_ARGS(&pFile))) && pFile)
            {
                hr = pFile->Initialize(m_szPath, 0);
                pFile->Release();
            }
            else
            {
                IInitializeWithStream* pStream = nullptr;
                if (SUCCEEDED(punk->QueryInterface(IID_PPV_ARGS(&pStream))) && pStream)
                {
                    IStream* strm = nullptr;
                    if (SUCCEEDED(SHCreateStreamOnFileEx(m_szPath, STGM_READ,
                        FILE_ATTRIBUTE_NORMAL, FALSE, nullptr, &strm)) && strm)
                    {
                        hr = pStream->Initialize(strm, 0);
                        strm->Release();
                    }
                    pStream->Release();
                }
            }
        }

        if (SUCCEEDED(hr))
        {
            IPropertyStore* ps = nullptr;
            if (SUCCEEDED(punk->QueryInterface(IID_PPV_ARGS(&ps))) && ps)
                m_pNative = ps;
        }
        punk->Release();
    }

    // Looks up the handler Windows itself associates with the file's type,
    // preferring the CLSID saved when we took the slot over.
    void FindNative()
    {
        if (m_pNative || !m_szPath[0]) return;

        const WCHAR* pdot = PathFindExtensionW(m_szPath);
        if (!pdot || !*pdot) return;

        WCHAR key[512];
        WCHAR szClsid[128];

        StringCchPrintfW(key, ARRAYSIZE(key),
            L"Software\\FileRemarks\\Original\\%s", pdot);
        if (RegGetSZ(HKEY_LOCAL_MACHINE, key, nullptr, szClsid, ARRAYSIZE(szClsid)) ||
            RegGetSZ(HKEY_CURRENT_USER, key, nullptr, szClsid, ARRAYSIZE(szClsid)))
        {
            CLSID c;
            if (SUCCEEDED(CLSIDFromString(szClsid, &c)))
            {
                LoadNative(c);
                if (m_pNative) return;
            }
        }

        StringCchPrintfW(key, ARRAYSIZE(key),
            L"Software\\Microsoft\\Windows\\CurrentVersion\\PropertySystem\\PropertyHandlers\\%s", pdot);
        if (RegGetSZ(HKEY_LOCAL_MACHINE, key, nullptr, szClsid, ARRAYSIZE(szClsid)) ||
            RegGetSZ(HKEY_CURRENT_USER, key, nullptr, szClsid, ARRAYSIZE(szClsid)))
        {
            CLSID c;
            if (SUCCEEDED(CLSIDFromString(szClsid, &c)))
                LoadNative(c);
        }
    }

    HRESULT ReadRemark()
    {
        m_fRead = true;
        m_remark.clear();
        if (!m_szPath[0]) return S_OK;
        std::wstring s;
        if (fr::ReadRemark(m_szPath, s))
            m_remark = s;
        return S_OK;
    }

    HRESULT WriteRemark(const std::wstring& s)
    {
        if (!m_szPath[0]) return E_FAIL;
        if (!fr::WriteRemark(m_szPath, s))
            return HRESULT_FROM_WIN32(GetLastError());
        m_remark = s;
        m_fRead = true;
        return S_OK;
    }

public:
    CRemarkPropertyHandler()
        : m_cRef(1), m_psi(nullptr), m_fInit(false), m_fRead(false),
          m_pNative(nullptr), m_fNativeDirty(false)
    {
        m_szPath[0] = 0;
        DllAddRef();
    }
    ~CRemarkPropertyHandler()
    {
        if (m_pNative) m_pNative->Release();
        if (m_psi) m_psi->Release();
        DllRelease();
    }

    // IUnknown
    IFACEMETHODIMP QueryInterface(REFIID riid, void** ppv)
    {
        static const QITAB qit[] = {
            QITABENT(CRemarkPropertyHandler, IPropertyStore),
            QITABENT(CRemarkPropertyHandler, IInitializeWithItem),
            QITABENT(CRemarkPropertyHandler, IInitializeWithFile),
            QITABENT(CRemarkPropertyHandler, IInitializeWithStream),
            QITABENT(CRemarkPropertyHandler, IPropertyStoreCapabilities),
            { 0 },
        };
        return QISearch(this, qit, riid, ppv);
    }
    IFACEMETHODIMP_(ULONG) AddRef()  { return InterlockedIncrement(&m_cRef); }
    IFACEMETHODIMP_(ULONG) Release()
    {
        ULONG c = InterlockedDecrement(&m_cRef);
        if (!c) delete this;
        return c;
    }

    // IInitializeWithItem
    IFACEMETHODIMP Initialize(IShellItem* psi, DWORD /*flags*/)
    {
        if (m_fInit) return HRESULT_FROM_WIN32(ERROR_ALREADY_INITIALIZED);
        if (!psi) return E_INVALIDARG;
        m_psi = psi;
        m_psi->AddRef();
        PWSTR psz = nullptr;
        if (SUCCEEDED(m_psi->GetDisplayName(SIGDN_FILESYSPATH, &psz)) && psz)
        {
            StringCchCopyW(m_szPath, ARRAYSIZE(m_szPath), psz);
            CoTaskMemFree(psz);
        }
        m_fInit = true;
        FindNative();
        return S_OK;
    }

    // IInitializeWithFile
    IFACEMETHODIMP Initialize(LPCWSTR pszFilePath, DWORD /*flags*/)
    {
        if (m_fInit) return HRESULT_FROM_WIN32(ERROR_ALREADY_INITIALIZED);
        if (!pszFilePath) return E_INVALIDARG;
        StringCchCopyW(m_szPath, ARRAYSIZE(m_szPath), pszFilePath);
        m_fInit = true;
        FindNative();
        return S_OK;
    }

    // IInitializeWithStream
    //
    // Windows hands property handlers a stream instead of a path whenever it
    // hosts them out of process (the surrogate exists so a buggy handler cannot
    // take the shell down with it), and -- as measured on this machine -- it
    // does exactly that for a handler registered under HKCU. Without this
    // method the store cannot be created at all and the 备注 column comes up
    // empty, so the stream is turned straight back into a path and everything
    // downstream stays identical to the other two initialisers.
    IFACEMETHODIMP Initialize(IStream* pStream, DWORD /*flags*/)
    {
        if (m_fInit) return HRESULT_FROM_WIN32(ERROR_ALREADY_INITIALIZED);
        if (!pStream) return E_INVALIDARG;
        STATSTG st = { 0 };
        HRESULT hr = pStream->Stat(&st, STATFLAG_DEFAULT);
        if (FAILED(hr)) return hr;
        if (st.pwcsName)
        {
            // The stat name is not guaranteed to be a full path: the stream this
            // process may be handed is built with CreateFile + the file name
            // only. Log what actually arrives (once per process) so a machine
            // that still shows an empty column can be diagnosed from the log
            // instead of guessed at, then make the best of it.
            if (!g_streamNameLogged)
            {
                g_streamNameLogged = true;
                std::wstring line = L"stream init name=";
                line += st.pwcsName;
                line += L" relative=";
                line += PathIsRelativeW(st.pwcsName) ? L"yes" : L"no";
                DiagLog(line);
            }
            WCHAR full[MAX_PATH * 2] = { 0 };
            if (!PathIsRelativeW(st.pwcsName) ||
                GetFullPathNameW(st.pwcsName, ARRAYSIZE(full), full, nullptr))
            {
                StringCchCopyW(m_szPath, ARRAYSIZE(m_szPath),
                               PathIsRelativeW(st.pwcsName) ? full : st.pwcsName);
            }
            else
            {
                StringCchCopyW(m_szPath, ARRAYSIZE(m_szPath), st.pwcsName);
            }
            CoTaskMemFree(st.pwcsName);
            st.pwcsName = nullptr;
        }
        m_fInit = true;
        FindNative();
        return S_OK;
    }

    // IPropertyStore
    // True when the wrapped handler already lists System.Comment among its own
    // keys (photo/Office handlers do). In that case we do not append a second
    // copy of the same key -- a store must not enumerate a key twice -- we just
    // override its value below.
    bool NativeHasComment()
    {
        if (!m_pNative) return false;
        DWORD c = 0;
        if (FAILED(m_pNative->GetCount(&c))) return false;
        for (DWORD i = 0; i < c; ++i)
        {
            PROPERTYKEY k;
            if (SUCCEEDED(m_pNative->GetAt(i, &k)) && k == PKEY_FileRemark)
                return true;
        }
        return false;
    }

    IFACEMETHODIMP GetCount(DWORD* c)
    {
        if (!c) return E_INVALIDARG;
        *c = 1;
        if (m_pNative)
        {
            DWORD cNative = 0;
            if (SUCCEEDED(m_pNative->GetCount(&cNative)))
                *c = cNative + (NativeHasComment() ? 0 : 1);
            else
                m_pNative->Release(), m_pNative = nullptr;
        }
        return S_OK;
    }
    IFACEMETHODIMP GetAt(DWORD i, PROPERTYKEY* pkey)
    {
        if (!pkey) return E_INVALIDARG;
        // With no native store the remark is all we have, so it is ours; with
        // one, it is ours only when the native side does not list it too.
        bool own = !m_pNative || !NativeHasComment();
        DWORD cNative = 0;
        if (m_pNative) m_pNative->GetCount(&cNative);
        if (i < cNative) return m_pNative->GetAt(i, pkey);
        if (!own || i != cNative) return E_INVALIDARG;
        *pkey = PKEY_FileRemark;
        return S_OK;
    }
    IFACEMETHODIMP GetValue(REFPROPERTYKEY key, PROPVARIANT* pv)
    {
        if (!pv) return E_INVALIDARG;
        PropVariantInit(pv);
        if (key != PKEY_FileRemark)
            return m_pNative ? m_pNative->GetValue(key, pv) : S_OK;
        if (!m_fRead) ReadRemark();
        // No remark of our own: a value the file itself carries (an image's
        // embedded comment, say) must still be shown, not blanked out.
        if (m_remark.empty() && m_pNative)
            return m_pNative->GetValue(key, pv);
        if (m_remark.empty()) return S_OK;
        size_t chars = m_remark.size() + 1;
        pv->vt = VT_LPWSTR;
        pv->pwszVal = (PWSTR)CoTaskMemAlloc(chars * sizeof(WCHAR));
        if (!pv->pwszVal) return E_OUTOFMEMORY;
        StringCchCopyW(pv->pwszVal, chars, m_remark.c_str());
        return S_OK;
    }
    IFACEMETHODIMP SetValue(REFPROPERTYKEY key, REFPROPVARIANT propvar)
    {
        // Every key the original handler knows is still editable through us, so
        // taking the slot over does not make any native column read-only.
        if (key != PKEY_FileRemark && m_pNative)
        {
            m_fNativeDirty = true;
            return m_pNative->SetValue(key, propvar);
        }
        if (key != PKEY_FileRemark)
            return HRESULT_FROM_WIN32(ERROR_NOT_SUPPORTED);
        if (propvar.vt == VT_LPWSTR || propvar.vt == VT_BSTR)
            m_remark = propvar.pwszVal ? propvar.pwszVal : L"";
        else if (propvar.vt == VT_EMPTY)
            m_remark.clear();
        else
            return S_FALSE;
        m_fRead = true;
        return S_OK;
    }
    IFACEMETHODIMP Commit()
    {
        if (!m_fInit) return E_FAIL;
        if (m_fNativeDirty && m_pNative)
        {
            HRESULT hrNative = m_pNative->Commit();
            m_fNativeDirty = false;
            if (FAILED(hrNative)) return hrNative;
        }
        return WriteRemark(m_remark);
    }

    // IPropertyStoreCapabilities
    IFACEMETHODIMP IsPropertyWritable(REFPROPERTYKEY key)
    {
        if (key == PKEY_FileRemark) return S_OK;
        if (m_pNative)
        {
            IPropertyStoreCapabilities* pNativeCap = nullptr;
            if (SUCCEEDED(m_pNative->QueryInterface(IID_PPV_ARGS(&pNativeCap))) && pNativeCap)
            {
                HRESULT hr = pNativeCap->IsPropertyWritable(key);
                pNativeCap->Release();
                return hr;
            }
        }
        return S_FALSE;
    }
};

// ----- Class factory ------------------------------------------------------
class CClassFactory : public IClassFactory
{
private:
    long m_cRef;
public:
    CClassFactory() : m_cRef(1) { DllAddRef(); }
    ~CClassFactory() { DllRelease(); }

    IFACEMETHODIMP QueryInterface(REFIID riid, void** ppv)
    {
        if (riid == IID_IUnknown || riid == IID_IClassFactory)
        {
            *ppv = this;
            AddRef();
            return S_OK;
        }
        *ppv = nullptr;
        return E_NOINTERFACE;
    }
    IFACEMETHODIMP_(ULONG) AddRef()  { return InterlockedIncrement(&m_cRef); }
    IFACEMETHODIMP_(ULONG) Release()
    {
        ULONG c = InterlockedDecrement(&m_cRef);
        if (!c) delete this;
        return c;
    }
    IFACEMETHODIMP CreateInstance(IUnknown* pUnkOuter, REFIID riid, void** ppv)
    {
        if (pUnkOuter) return CLASS_E_NOAGGREGATION;
        CRemarkPropertyHandler* p = new (std::nothrow) CRemarkPropertyHandler();
        if (!p) return E_OUTOFMEMORY;
        HRESULT hr = p->QueryInterface(riid, ppv);
        p->Release();
        return hr;
    }
    IFACEMETHODIMP LockServer(BOOL fLock)
    {
        if (fLock) DllAddRef(); else DllRelease();
        return S_OK;
    }
};

// ----- Registry helpers ---------------------------------------------------
static HRESULT RegSetSZ(HKEY hRoot, const WCHAR* subKey, const WCHAR* valueName, const WCHAR* data)
{
    HKEY hk = nullptr;
    DWORD disp = 0;
    HRESULT hr = HRESULT_FROM_WIN32(RegCreateKeyExW(hRoot, subKey, 0, nullptr,
        REG_OPTION_NON_VOLATILE, KEY_WRITE, nullptr, &hk, &disp));
    if (SUCCEEDED(hr))
    {
        hr = HRESULT_FROM_WIN32(RegSetValueExW(hk, valueName, 0, REG_SZ,
            (const BYTE*)data, (DWORD)((wcslen(data) + 1) * sizeof(WCHAR))));
        RegCloseKey(hk);
    }
    return hr;
}

static HRESULT RegSetDWORD(HKEY hRoot, const WCHAR* subKey, const WCHAR* valueName, DWORD data)
{
    HKEY hk = nullptr;
    DWORD disp = 0;
    HRESULT hr = HRESULT_FROM_WIN32(RegCreateKeyExW(hRoot, subKey, 0, nullptr,
        REG_OPTION_NON_VOLATILE, KEY_WRITE, nullptr, &hk, &disp));
    if (SUCCEEDED(hr))
    {
        hr = HRESULT_FROM_WIN32(RegSetValueExW(hk, valueName, 0, REG_DWORD,
            (const BYTE*)&data, sizeof(data)));
        RegCloseKey(hk);
    }
    return hr;
}

// Returns true when the string value equals `expected` (case-insensitive).
static bool RegSZEquals(HKEY hRoot, const WCHAR* subKey, const WCHAR* valueName, const WCHAR* expected)
{
    HKEY hk = nullptr;
    if (RegOpenKeyExW(hRoot, subKey, 0, KEY_READ, &hk) != ERROR_SUCCESS)
        return false;
    WCHAR buf[512] = { 0 };
    DWORD cb = sizeof(buf) - sizeof(WCHAR);
    DWORD type = 0;
    LONG rc = RegQueryValueExW(hk, valueName, nullptr, &type, (BYTE*)buf, &cb);
    RegCloseKey(hk);
    if (rc != ERROR_SUCCESS || (type != REG_SZ && type != REG_EXPAND_SZ))
        return false;
    buf[ARRAYSIZE(buf) - 1] = 0;
    return CompareStringOrdinal(buf, -1, expected, -1, TRUE) == CSTR_EQUAL;
}

// Reads a string value; returns false when absent or not a string.
static bool RegGetSZ(HKEY hRoot, const WCHAR* subKey, const WCHAR* valueName,
                     WCHAR* out, DWORD cch)
{
    if (!out || cch < 2) return false;
    out[0] = 0;
    HKEY hk = nullptr;
    if (RegOpenKeyExW(hRoot, subKey, 0, KEY_READ, &hk) != ERROR_SUCCESS)
        return false;
    DWORD cb = (cch - 1) * sizeof(WCHAR);
    DWORD type = 0;
    LONG rc = RegQueryValueExW(hk, valueName, nullptr, &type, (BYTE*)out, &cb);
    RegCloseKey(hk);
    if (rc != ERROR_SUCCESS || (type != REG_SZ && type != REG_EXPAND_SZ))
        return false;
    out[cch - 1] = 0;
    return true;
}

static HRESULT GetModulePath(WCHAR* out, DWORD cch)
{
    HMODULE hMod = nullptr;
    if (!GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS |
        GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
        (LPCWSTR)&CLSID_FileRemarksPropHandler, &hMod))
        return E_FAIL;
    DWORD n = GetModuleFileNameW(hMod, out, cch);
    if (!n || n >= cch) return E_FAIL;
    return S_OK;
}

// ----- Exported DLL entry points -----------------------------------------
STDAPI __declspec(dllexport) DllGetClassObject(REFCLSID rclsid, REFIID riid, void** ppv)
{
    if (rclsid != CLSID_FileRemarksPropHandler) return CLASS_E_CLASSNOTAVAILABLE;
    CClassFactory* pf = new (std::nothrow) CClassFactory();
    if (!pf) return E_OUTOFMEMORY;
    HRESULT hr = pf->QueryInterface(riid, ppv);
    pf->Release();
    return hr;
}

STDAPI __declspec(dllexport) DllCanUnloadNow()
{
    return (g_cLocks == 0) ? S_OK : S_FALSE;
}

// How many of the folder types we track currently expose the 备注 column, read
// straight back out of the registry. The installer calls this after registering
// so its final message can state the real number instead of assuming success --
// the old machine-wide build claimed the column was on while only two of six
// types had actually accepted the write.
STDAPI_(int) __declspec(dllexport) FileRemarksColumnCount()
{
    return fr::columns::CountEnabledFolderTypes();
}

// File types we try to attach the "备注" column to. Only extensions that
// Windows does NOT already own a property handler for are actually written,
// so the native Details/columns of jpg/png/doc/mp3/... keep working.
//
// This list is a convenience, not the limit of what works: registration also
// sets the wildcard fallback (see step 5), so an unlisted or custom extension
// still gets the column. Listing common ones explicitly just means their
// association is not dependent on wildcard resolution.
static const WCHAR* const kCandidateExts[] = {
    L".md", L".markdown", L".txt", L".log",
    L".py", L".pyw", L".ipynb",
    L".json", L".yaml", L".yml", L".toml", L".ini", L".cfg", L".conf", L".properties",
    L".c", L".h", L".cpp", L".hpp", L".cc", L".cs", L".js", L".ts", L".jsx", L".tsx",
    L".java", L".go", L".rs", L".rb", L".php", L".pl", L".lua", L".kt", L".swift",
    L".sh", L".bash", L".zsh", L".ps1", L".bat", L".cmd",
    L".sql", L".csv", L".xml", L".html", L".htm", L".css", L".scss",
    L".tex", L".bib", L".patch", L".diff", L".reg", L".gradle", L".dockerfile",
    L".sln", L".vcxproj", L".pro", L".cmake", L".make",
    L".rtf", L".odt", L".ods", L".odp",
    L".7z", L".rar", L".tar", L".gz",
    nullptr
};

// Where Windows looks for a property handler of a given type. All three shapes
// are honoured by Explorer on real machines:
//   SOFTWARE\Microsoft\Windows\CurrentVersion\PropertySystem\PropertyHandlers\.ext
//   SOFTWARE\Classes\.ext\ShellEx\PropertyHandler
//   SOFTWARE\Microsoft\Windows\CurrentVersion\PropertySystem\SystemPropertyHandlers
//      (a single key whose per-extension VALUES name the handler)
// Each is read per-user first and machine-wide second: the product registers
// under HKCU (it installs without admin), while the handler Windows ships for a
// type still lives in HKLM. Reading HKLM needs no elevated token.
static bool ReadHandlerCLSID(const WCHAR* ext, WCHAR* out, DWORD cch)
{
    WCHAR key[512];
    StringCchPrintfW(key, ARRAYSIZE(key),
        L"Software\\Microsoft\\Windows\\CurrentVersion\\PropertySystem\\PropertyHandlers\\%s", ext);
    if (RegGetSZ(HKEY_CURRENT_USER, key, nullptr, out, cch)) return true;
    if (RegGetSZ(HKEY_LOCAL_MACHINE, key, nullptr, out, cch)) return true;

    StringCchPrintfW(key, ARRAYSIZE(key),
        L"Software\\Classes\\%s\\ShellEx\\PropertyHandler", ext);
    if (RegGetSZ(HKEY_CURRENT_USER, key, nullptr, out, cch)) return true;
    if (RegGetSZ(HKEY_LOCAL_MACHINE, key, nullptr, out, cch)) return true;

    // The third shape stores the CLSID as a value named after the extension.
    const WCHAR* kSys = L"Software\\Microsoft\\Windows\\CurrentVersion\\PropertySystem\\SystemPropertyHandlers";
    if (RegGetSZ(HKEY_CURRENT_USER, kSys, ext, out, cch)) return true;
    return RegGetSZ(HKEY_LOCAL_MACHINE, kSys, ext, out, cch);
}

static bool SystemOwnsHandler(const WCHAR* ext)
{
    WCHAR sz[128];
    return ReadHandlerCLSID(ext, sz, ARRAYSIZE(sz));
}

// Types Windows already has a property handler for, but whose handler exposes a
// plain IPropertyStore and can therefore be WRAPPED instead of replaced: our
// handler keeps every native value and only appends the "备注" key. This was
// measured with tools/test_chain_matrix.py on real files -- images/audio/video
// handlers initialise from a stream and exe/dll/sys from a file name, and all of
// them answer QueryInterface(IPropertyStore).
//
// Deliberately absent: .doc/.docx/.xls/.xlsx/.ppt/.pptx. The Office metadata
// handlers do not expose IPropertyStore, so taking their slot would hide the
// native Details columns -- those types keep their system handler and use only
// the right-click editor.
static const WCHAR* const kChainExts[] = {
    L".exe", L".dll", L".sys", L".ocx", L".cpl", L".scr",
    L".png", L".jpg", L".jpeg", L".jfif", L".gif", L".bmp", L".ico",
    L".tif", L".tiff", L".webp", L".dib", L".cur", L".ani", L".wmf", L".emf",
    L".mp3", L".mp4", L".m4a", L".wav", L".wma", L".avi", L".wmv",
    L".mov", L".mkv", L".flac", L".ogg", L".aac",
    nullptr
};

// Types we must NOT wrap (see kChainExts) but which the wildcard fallback could
// still capture. To keep their own Details columns we PIN them: the handler they
// use today is written into the per-extension class key, so the specific entry
// always answers before the wildcard. The value written is the CLSID Windows was
// already using, so nothing about these types changes.
static const WCHAR* const kPinExts[] = {
    L".doc", L".docx", L".docm", L".dotx", L".dotm",
    L".xls", L".xlsx", L".xlsm", L".xlsb", L".xltx", L".xltm",
    L".ppt", L".pptx", L".pptm", L".potx", L".potm",
    L".vsd", L".vsdx", L".accdt",
    // These get their handler from PropertySystem\SystemPropertyHandlers only,
    // so a wildcard association could otherwise take them over.
    L".appcontent-ms", L".library-ms", L".searchConnector-ms", L".settingcontent-ms",
    nullptr
};

// Saves the handler Windows currently uses for `ext` so the wrapper can forward
// to it, and so uninstall can put it back exactly as it was.
static void SaveOriginalHandler(const WCHAR* ext)
{
    WCHAR szOrig[128] = { 0 };
    if (!ReadHandlerCLSID(ext, szOrig, ARRAYSIZE(szOrig))) return;
    if (CompareStringOrdinal(szOrig, -1, SZ_CLSID, -1, TRUE) == CSTR_EQUAL)
        return; // already ours, keep what we saved earlier

    WCHAR key[512];
    StringCchPrintfW(key, ARRAYSIZE(key), L"Software\\FileRemarks\\Original\\%s", ext);
    RegSetSZ(HKEY_CURRENT_USER, key, nullptr, szOrig);
}

// Raises the resolution priority of the handler `ext` already uses by writing it
// into the per-extension class key, which outranks the wildcard fallback. The
// CLSID written is the one already in effect, so nothing about the type changes
// for the user -- we only make the per-type choice explicit, so registering our
// wildcard can never darken a type Windows already knows how to describe.
//
// Types served by our own handler resolve to SZ_CLSID here and are skipped, so
// calling this for every known extension is safe and idempotent.
static void PinOneExtension(const WCHAR* ext)
{
    if (!ext || ext[0] != L'.') return;

    WCHAR szPin[128] = { 0 };
    if (!ReadHandlerCLSID(ext, szPin, ARRAYSIZE(szPin))) return;
    if (CompareStringOrdinal(szPin, -1, SZ_CLSID, -1, TRUE) == CSTR_EQUAL) return;

    WCHAR key[512];
    StringCchPrintfW(key, ARRAYSIZE(key),
        L"Software\\Classes\\%s\\ShellEx\\PropertyHandler", ext);
    RegSetSZ(HKEY_CURRENT_USER, key, nullptr, szPin);

    // Remember what we wrote so uninstall can take the key back out again, but
    // only while it still holds our value (see DllUnregisterServer).
    StringCchPrintfW(key, ARRAYSIZE(key), L"Software\\FileRemarks\\Pinned\\%s", ext);
    RegSetSZ(HKEY_CURRENT_USER, key, nullptr, szPin);
}

// Pins the handler of every file type on this machine that has one, whichever of
// the three shapes registered it. Enumerating instead of hard-coding a list is
// what makes the wildcard fallback safe on machines we have never seen: Office,
// Visio, Photoshop, archive tools, anything that ships its own metadata handler
// is found here and keeps its columns.
static void PinAllExistingHandlers()
{
    WCHAR key[512];
    WCHAR name[256];

    // Both roots are enumerated: a per-user install writes everything under HKCU,
    // while the handlers Windows ships for a type live in HKLM. Reading HKLM does
    // not need an elevated token.
    static HKEY const kRoots[2] = { HKEY_CURRENT_USER, HKEY_LOCAL_MACHINE };

    for (int r = 0; r < 2; ++r)
    {
        const HKEY root = kRoots[r];

        // (a) PropertySystem\PropertyHandlers\.ext  (the documented per-type key).
        StringCchPrintfW(key, ARRAYSIZE(key),
            L"Software\\Microsoft\\Windows\\CurrentVersion\\PropertySystem\\PropertyHandlers");
        HKEY hk = nullptr;
        if (RegOpenKeyExW(root, key, 0, KEY_READ, &hk) == ERROR_SUCCESS)
        {
            for (DWORD i = 0; ; ++i)
            {
                DWORD cch = ARRAYSIZE(name);
                if (RegEnumKeyExW(hk, i, name, &cch, nullptr, nullptr, nullptr, nullptr) != ERROR_SUCCESS)
                    break;
                PinOneExtension(name);
            }
            RegCloseKey(hk);
        }

        // (b) SystemPropertyHandlers: one key whose VALUES are named after the type.
        StringCchPrintfW(key, ARRAYSIZE(key),
            L"Software\\Microsoft\\Windows\\CurrentVersion\\PropertySystem\\SystemPropertyHandlers");
        if (RegOpenKeyExW(root, key, 0, KEY_READ, &hk) == ERROR_SUCCESS)
        {
            for (DWORD i = 0; ; ++i)
            {
                DWORD cch = ARRAYSIZE(name);
                if (RegEnumValueW(hk, i, name, &cch, nullptr, nullptr, nullptr, nullptr) != ERROR_SUCCESS)
                    break;
                PinOneExtension(name);
            }
            RegCloseKey(hk);
        }

        // (c) Software\Classes\.ext\ShellEx\PropertyHandler  (what Office writes).
        if (RegOpenKeyExW(root, L"Software\\Classes", 0, KEY_READ, &hk) == ERROR_SUCCESS)
        {
            for (DWORD i = 0; ; ++i)
            {
                DWORD cch = ARRAYSIZE(name);
                if (RegEnumKeyExW(hk, i, name, &cch, nullptr, nullptr, nullptr, nullptr) != ERROR_SUCCESS)
                    break;
                if (name[0] != L'.' || name[1] == 0) continue;

                WCHAR probe[512];
                StringCchPrintfW(probe, ARRAYSIZE(probe),
                    L"Software\\Classes\\%s\\ShellEx\\PropertyHandler", name);
                HKEY hSub = nullptr;
                if (RegOpenKeyExW(root, probe, 0, KEY_READ, &hSub) == ERROR_SUCCESS)
                {
                    RegCloseKey(hSub);
                    PinOneExtension(name);
                }
            }
            RegCloseKey(hk);
        }
    }
}

STDAPI __declspec(dllexport) DllRegisterServer()
{
    WCHAR dllPath[MAX_PATH] = { 0 };
    if (FAILED(GetModulePath(dllPath, ARRAYSIZE(dllPath)))) return E_FAIL;

    // 1) CLSID registration (documented shape).
    WCHAR keyCls[MAX_PATH];
    StringCchPrintfW(keyCls, ARRAYSIZE(keyCls), L"Software\\Classes\\CLSID\\%s", SZ_CLSID);
    HRESULT hr = RegSetSZ(HKEY_CURRENT_USER, keyCls, nullptr, L"FileRemarks Property Handler");
    if (FAILED(hr)) return hr;

    // We do not implement IInitializeWithStream, so the shell must keep us out
    // of the isolated surrogate host.
    hr = RegSetDWORD(HKEY_CURRENT_USER, keyCls, L"DisableProcessIsolation", 1);
    if (FAILED(hr)) return hr;
    // Commit() is the only write path; the shell need not wrap us in a
    // transaction.
    hr = RegSetDWORD(HKEY_CURRENT_USER, keyCls, L"ManualSafeSave", 1);
    if (FAILED(hr)) return hr;

    WCHAR keyInproc[MAX_PATH];
    StringCchPrintfW(keyInproc, ARRAYSIZE(keyInproc), L"Software\\Classes\\CLSID\\%s\\InprocServer32", SZ_CLSID);
    hr = RegSetSZ(HKEY_CURRENT_USER, keyInproc, nullptr, dllPath);
    if (FAILED(hr)) return hr;
    hr = RegSetSZ(HKEY_CURRENT_USER, keyInproc, L"ThreadingModel", L"Both");
    if (FAILED(hr)) return hr;

    // 2) No property schema is registered: the value is published under
    //    System.Comment, which Windows already describes as "备注".

    // 3) Per-extension association, but ONLY where it is safe: never take a
    //    type away from a handler Windows already installed, otherwise that
    //    type would lose its own Details/columns.
    HRESULT hrFirstFail = S_OK;
    for (int i = 0; kCandidateExts[i]; ++i)
    {
        const WCHAR* ext = kCandidateExts[i];
        if (SystemOwnsHandler(ext)) continue;

        StringCchPrintfW(keyInproc, ARRAYSIZE(keyInproc),
            L"Software\\Classes\\%s\\ShellEx\\PropertyHandler", ext);
        HRESULT h1 = RegSetSZ(HKEY_CURRENT_USER, keyInproc, nullptr, SZ_CLSID);

        StringCchPrintfW(keyInproc, ARRAYSIZE(keyInproc),
            L"Software\\Microsoft\\Windows\\CurrentVersion\\PropertySystem\\PropertyHandlers\\%s", ext);
        HRESULT h2 = RegSetSZ(HKEY_CURRENT_USER, keyInproc, nullptr, SZ_CLSID);

        if (SUCCEEDED(h1) && FAILED(h2)) h1 = h2;
        if (FAILED(h1) && SUCCEEDED(hrFirstFail)) hrFirstFail = h1;
    }

    // 4) Types Windows already owns a handler for, but where that handler can be
    //    wrapped (see kChainExts). The original CLSID is remembered first, then
    //    the association is switched to us; we forward every native property.
    for (int i = 0; kChainExts[i]; ++i)
    {
        const WCHAR* ext = kChainExts[i];
        SaveOriginalHandler(ext);

        StringCchPrintfW(keyInproc, ARRAYSIZE(keyInproc),
            L"Software\\Classes\\%s\\ShellEx\\PropertyHandler", ext);
        HRESULT h1 = RegSetSZ(HKEY_CURRENT_USER, keyInproc, nullptr, SZ_CLSID);

        StringCchPrintfW(keyInproc, ARRAYSIZE(keyInproc),
            L"Software\\Microsoft\\Windows\\CurrentVersion\\PropertySystem\\PropertyHandlers\\%s", ext);
        HRESULT h2 = RegSetSZ(HKEY_CURRENT_USER, keyInproc, nullptr, SZ_CLSID);

        if (SUCCEEDED(h1) && FAILED(h2)) h1 = h2;
        if (FAILED(h1) && SUCCEEDED(hrFirstFail)) hrFirstFail = h1;
    }

    // 5) Every other type that Windows already describes gets pinned to the
    //    handler it already uses, so the wildcard in step 6 cannot capture it
    //    and hide its Details columns. Two sources, both needed:
    //      a) a fixed list of well-known unwrappable types (Office & friends),
    //         which also covers a type whose handler has not been registered
    //         yet at the moment we run;
    //      b) an enumeration of every type this machine actually has a handler
    //         for, so third-party handlers (Office add-ins, archive tools,
    //         photo editors) are protected without us knowing their names.
    for (int i = 0; kPinExts[i]; ++i)
        PinOneExtension(kPinExts[i]);
    PinAllExistingHandlers();

    // 6) Wildcard fallback, so files whose type nobody listed above -- custom
    //    extensions, .zip, .pdf, .iso, whatever the user happens to have -- still
    //    get the 备注 column. This is additive: a per-extension association
    //    always takes precedence, so every type handled in steps 3-5 keeps the
    //    handler chosen there, and Office keeps the system handler it had.
    hr = RegSetSZ(HKEY_CURRENT_USER, L"Software\\Classes\\*\\shellex\\PropertyHandler",
                  nullptr, SZ_CLSID);
    if (FAILED(hr) && SUCCEEDED(hrFirstFail)) hrFirstFail = hr;

    // 7) Turn the 备注 column on in Explorer's default views, so it is visible
    //    right after installation instead of having to be added by hand. The
    //    original column list of each folder type is saved first, so uninstall
    //    restores it exactly. A failure here is not fatal: the extension still
    //    works, the user would just add the column manually.
    fr::columns::EnableCommentColumn();

    return hrFirstFail;
}

STDAPI __declspec(dllexport) DllUnregisterServer()
{
    // Undo the default-column change first: it is the one piece of state that
    // lives outside our own keys, and the user never asked us to touch it
    // permanently.
    fr::columns::DisableCommentColumn();

    // Remove only the associations that point at us, so a handler that was
    // registered later by something else is left untouched.
    WCHAR key[512];
    for (int i = 0; kCandidateExts[i]; ++i)
    {
        StringCchPrintfW(key, ARRAYSIZE(key),
            L"Software\\Classes\\%s\\ShellEx\\PropertyHandler", kCandidateExts[i]);
        if (RegSZEquals(HKEY_CURRENT_USER, key, nullptr, SZ_CLSID))
            RegDeleteKeyW(HKEY_CURRENT_USER, key);

        StringCchPrintfW(key, ARRAYSIZE(key),
            L"Software\\Microsoft\\Windows\\CurrentVersion\\PropertySystem\\PropertyHandlers\\%s", kCandidateExts[i]);
        if (RegSZEquals(HKEY_CURRENT_USER, key, nullptr, SZ_CLSID))
            RegDeleteKeyW(HKEY_CURRENT_USER, key);
    }

    // Types we wrapped: put the handler Windows had before back in place, so the
    // file type behaves exactly as it did before installation.
    for (int i = 0; kChainExts[i]; ++i)
    {
        const WCHAR* ext = kChainExts[i];

        StringCchPrintfW(key, ARRAYSIZE(key), L"Software\\FileRemarks\\Original\\%s", ext);
        WCHAR szOrig[128] = { 0 };
        bool haveOrig = RegGetSZ(HKEY_CURRENT_USER, key, nullptr, szOrig, ARRAYSIZE(szOrig));

        WCHAR keyEx[512];
        StringCchPrintfW(keyEx, ARRAYSIZE(keyEx),
            L"Software\\Classes\\%s\\ShellEx\\PropertyHandler", ext);
        if (RegSZEquals(HKEY_CURRENT_USER, keyEx, nullptr, SZ_CLSID))
        {
            if (haveOrig)
                RegSetSZ(HKEY_CURRENT_USER, keyEx, nullptr, szOrig);
            else
                RegDeleteKeyW(HKEY_CURRENT_USER, keyEx);
        }

        StringCchPrintfW(keyEx, ARRAYSIZE(keyEx),
            L"Software\\Microsoft\\Windows\\CurrentVersion\\PropertySystem\\PropertyHandlers\\%s", ext);
        if (RegSZEquals(HKEY_CURRENT_USER, keyEx, nullptr, SZ_CLSID))
        {
            if (haveOrig)
                RegSetSZ(HKEY_CURRENT_USER, keyEx, nullptr, szOrig);
            else
                RegDeleteKeyW(HKEY_CURRENT_USER, keyEx);
        }

        RegDeleteKeyW(HKEY_CURRENT_USER, key);
    }
    RegDeleteTreeW(HKEY_CURRENT_USER, L"Software\\FileRemarks\\Original");

    // Undo the pinning from step 5 of registration. The pinned keys are read
    // back from our own bookkeeping rather than from a hard-coded list, because
    // registration pins every type this machine happens to have a handler for.
    // The per-extension key only ever held a copy of what was already in effect,
    // so deleting it restores the original resolution order.
    WCHAR keyPinned[512];
    StringCchPrintfW(keyPinned, ARRAYSIZE(keyPinned), L"Software\\FileRemarks\\Pinned");
    HKEY hkPinned = nullptr;
    if (RegOpenKeyExW(HKEY_CURRENT_USER, keyPinned, 0, KEY_READ, &hkPinned) == ERROR_SUCCESS)
    {
        WCHAR name[256];
        for (DWORD i = 0; ; ++i)
        {
            DWORD cch = ARRAYSIZE(name);
            if (RegEnumKeyExW(hkPinned, i, name, &cch, nullptr, nullptr, nullptr, nullptr) != ERROR_SUCCESS)
                break;

            WCHAR keyPin[512];
            StringCchPrintfW(keyPin, ARRAYSIZE(keyPin), L"Software\\FileRemarks\\Pinned\\%s", name);
            WCHAR szPin[128] = { 0 };
            bool havePin = RegGetSZ(HKEY_CURRENT_USER, keyPin, nullptr, szPin, ARRAYSIZE(szPin));

            WCHAR keyEx[512];
            StringCchPrintfW(keyEx, ARRAYSIZE(keyEx),
                L"Software\\Classes\\%s\\ShellEx\\PropertyHandler", name);
            // Only delete while the key still holds the value we pinned; if
            // Office or the OS rewrote it in the meantime, leave their value.
            if (havePin && RegSZEquals(HKEY_CURRENT_USER, keyEx, nullptr, szPin))
                RegDeleteKeyW(HKEY_CURRENT_USER, keyEx);
        }
        RegCloseKey(hkPinned);
    }
    RegDeleteTreeW(HKEY_CURRENT_USER, L"Software\\FileRemarks");

    // The wildcard fallback from step 6 of registration. Only removed when it
    // still points at us.
    WCHAR keyStar[MAX_PATH];
    StringCchPrintfW(keyStar, ARRAYSIZE(keyStar),
        L"Software\\Classes\\*\\shellex\\PropertyHandler");
    if (RegSZEquals(HKEY_CURRENT_USER, keyStar, nullptr, SZ_CLSID))
        RegDeleteKeyW(HKEY_CURRENT_USER, keyStar);

    WCHAR keyCls[MAX_PATH];
    StringCchPrintfW(keyCls, ARRAYSIZE(keyCls), L"Software\\Classes\\CLSID\\%s", SZ_CLSID);
    RegDeleteTreeW(HKEY_CURRENT_USER, keyCls);

    return S_OK;
}

BOOL APIENTRY DllMain(HMODULE hModule, DWORD dwReason, LPVOID /*lpReserved*/)
{
    if (dwReason == DLL_PROCESS_ATTACH)
        DisableThreadLibraryCalls(hModule);
    return TRUE;
}
