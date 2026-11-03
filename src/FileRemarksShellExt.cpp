// FileRemarks Shell Context-Menu Extension
// ---------------------------------------------------------------------------
// Adds a "编辑备注" (Edit Remark) entry to the Explorer right-click menu of ANY
// file. Selecting it launches FileRemarksEditor.exe (next to this DLL) for the
// chosen file. Registered under HKEY_CLASSES_ROOT\*\shellex\ContextMenuHandlers.
//
// Implements IContextMenu + IShellExtInit. Explorer creates the object via
// DllGetClassObject, then calls IShellExtInit::Initialize with the IDataObject
// of the selected file(s); we capture the first file's path there.
// ---------------------------------------------------------------------------

#include <windows.h>
#include <shlobj.h>
#include <shlwapi.h>
#include <strsafe.h>
#include <string>

#include "logo.h"

// {6F3A1B2C-9D4E-4c7b-8A1F-2E5B6C7D8E90}
static const CLSID CLSID_FileRemarksContextMenu =
{ 0x6f3a1b2c, 0x9d4e, 0x4c7b, { 0x8a, 0x1f, 0x2e, 0x5b, 0x6c, 0x7d, 0x8e, 0x90 } };

static const WCHAR SZ_CM_CLSID[] = L"{6F3A1B2C-9D4E-4c7b-8A1F-2E5B6C7D8E90}";

// Module lock counter.
static volatile LONG g_cLocks = 0;
static void DllAddRef()  { InterlockedIncrement(&g_cLocks); }
static void DllRelease() { InterlockedDecrement(&g_cLocks); }

// Menu bitmap for the "编辑备注" entry.
//
// A menu does NOT copy the bitmap handed to it through MENUITEMINFO; it draws
// whatever HBITMAP is still alive when the menu is shown. The menu can outlive
// this COM object (Explorer may release us first), so the bitmap is owned by the
// module and kept for the process lifetime -- creating it once also avoids
// re-rasterising the artwork on every right-click.
static HBITMAP g_hMenuLogo = nullptr;

static HBITMAP GetMenuLogo()
{
    if (g_hMenuLogo) return g_hMenuLogo;

    // Menu bitmaps are 16x16 at 96 dpi; scale with the monitor DPI so the icon
    // is not blurry on a high-DPI display.
    int px = 16;
    HDC hdc = GetDC(nullptr);
    if (hdc)
    {
        int dpi = GetDeviceCaps(hdc, LOGPIXELSX);
        ReleaseDC(nullptr, hdc);
        if (dpi > 0) px = MulDiv(16, dpi, 96);
    }
    if (px < 16) px = 16;
    if (px > 32) px = 32;
    g_hMenuLogo = fr::logo::CreateLogoBitmap(px);
    return g_hMenuLogo;
}

class CRemarkContextMenu
    : public IContextMenu
    , public IShellExtInit
{
private:
    long        m_cRef;
    std::wstring m_file;

    void CaptureFile(IDataObject* pdtobj)
    {
        m_file.clear();
        if (!pdtobj) return;
        FORMATETC fe = { CF_HDROP, nullptr, DVASPECT_CONTENT, -1, TYMED_HGLOBAL };
        STGMEDIUM stm = { 0 };
        if (FAILED(pdtobj->GetData(&fe, &stm))) return;
        HDROP hDrop = (HDROP)GlobalLock(stm.hGlobal);
        if (hDrop)
        {
            WCHAR buf[MAX_PATH] = { 0 };
            if (DragQueryFileW(hDrop, 0, buf, ARRAYSIZE(buf)) && buf[0])
                m_file = buf;
            GlobalUnlock(stm.hGlobal);
        }
        ReleaseStgMedium(&stm);
    }

public:
    CRemarkContextMenu() : m_cRef(1) { DllAddRef(); }
    ~CRemarkContextMenu() { DllRelease(); }

    // IUnknown
    IFACEMETHODIMP QueryInterface(REFIID riid, void** ppv)
    {
        static const QITAB qit[] = {
            QITABENT(CRemarkContextMenu, IContextMenu),
            QITABENT(CRemarkContextMenu, IShellExtInit),
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

    // IShellExtInit
    IFACEMETHODIMP Initialize(PCIDLIST_ABSOLUTE, IDataObject* pdtobj, HKEY)
    {
        CaptureFile(pdtobj);
        return S_OK;
    }

    // IContextMenu
    IFACEMETHODIMP QueryContextMenu(HMENU hMenu, UINT indexMenu, UINT idCmdFirst,
                                    UINT /*idCmdLast*/, UINT uFlags)
    {
        if (uFlags & CMF_DEFAULTONLY) return MAKE_HRESULT(SEVERITY_SUCCESS, 0, 0);
        if (m_file.empty()) return MAKE_HRESULT(SEVERITY_SUCCESS, 0, 0);

        MENUITEMINFOW mii = { sizeof(mii) };
        mii.fMask = MIIM_ID | MIIM_STRING | MIIM_STATE;
        mii.wID = idCmdFirst + 0;
        mii.dwTypeData = (LPWSTR)L"编辑备注";
        mii.fState = MFS_ENABLED;

        // Put our logo in front of the text. A menu bitmap is drawn to the left
        // of the string, which is exactly the placement we want; if the bitmap
        // cannot be created the entry still works, just without the picture.
        HBITMAP hLogo = GetMenuLogo();
        if (hLogo)
        {
            mii.fMask |= MIIM_BITMAP;
            mii.hbmpItem = hLogo;
        }

        if (InsertMenuItemW(hMenu, indexMenu, TRUE, &mii))
            return MAKE_HRESULT(SEVERITY_SUCCESS, 0, 1); // 1 command added
        return E_FAIL;
    }

    IFACEMETHODIMP InvokeCommand(LPCMINVOKECOMMANDINFO pici)
    {
        if (HIWORD(pici->lpVerb) != 0) return E_INVALIDARG; // string verb not used
        if (LOWORD(pici->lpVerb) != 0) return E_INVALIDARG; // our command id is 0
        if (m_file.empty()) return E_FAIL;

        // Locate the editor EXE next to this DLL.
        WCHAR dllPath[MAX_PATH] = { 0 };
        HMODULE hMod = nullptr;
        if (!GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS |
            GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
            (LPCWSTR)&CLSID_FileRemarksContextMenu, &hMod))
            return E_FAIL;
        GetModuleFileNameW(hMod, dllPath, ARRAYSIZE(dllPath));
        PWSTR pName = PathFindFileNameW(dllPath);
        if (pName) StringCchCopyW(pName, ARRAYSIZE(dllPath) - (pName - dllPath),
            L"FileRemarksEditor.exe");

        std::wstring cmd = L"\"" + std::wstring(dllPath) + L"\" \"" + m_file + L"\"";
        STARTUPINFOW si = { sizeof(si) };
        PROCESS_INFORMATION pi = { 0 };
        if (CreateProcessW(nullptr, &cmd[0], nullptr, nullptr, FALSE, 0,
            nullptr, nullptr, &si, &pi))
        {
            CloseHandle(pi.hThread);
            CloseHandle(pi.hProcess);
            return S_OK;
        }
        return HRESULT_FROM_WIN32(GetLastError());
    }

    // NOTE: MinGW-w64's shobjidl.h declares the ANSI vtable form
    // (CHAR* pszName), while the Windows SDK declares the UNICODE form
    // (LPWSTR pszName) when UNICODE is defined. We select the matching
    // signature so the code compiles with both toolchains.
    //
    // The caller's buffer format follows uType, not the declared signature, so
    // the MinGW branch still answers the W requests: Explorer asks with
    // GCS_HELPTEXTW once the extension is registered as Unicode-capable, and
    // returning E_NOTIMPL there would just mean no status-bar hint.
#ifdef __MINGW32__
    IFACEMETHODIMP GetCommandString(UINT_PTR idCmd, UINT uType, UINT*, CHAR* pszName, UINT cchMax)
    {
        if (idCmd != 0) return E_INVALIDARG;
        if (!pszName) return E_INVALIDARG;
        if (uType == GCS_HELPTEXTA)
        {
            WideCharToMultiByte(CP_ACP, 0, L"为这个文件添加或编辑备注", -1,
                pszName, (int)cchMax, nullptr, nullptr);
            return S_OK;
        }
        if (uType == GCS_HELPTEXTW)
        {
            StringCchCopyW((LPWSTR)pszName, cchMax, L"为这个文件添加或编辑备注");
            return S_OK;
        }
        if (uType == GCS_VERBA)
        {
            lstrcpynA(pszName, "editremark", (int)cchMax);
            return S_OK;
        }
        if (uType == GCS_VERBW)
        {
            StringCchCopyW((LPWSTR)pszName, cchMax, L"editremark");
            return S_OK;
        }
        if (uType == GCS_VALIDATEA || uType == GCS_VALIDATEW)
            return S_OK;
        return E_NOTIMPL;
    }
#else
    IFACEMETHODIMP GetCommandString(UINT_PTR idCmd, UINT uType, UINT*, LPWSTR pszName, UINT cchMax)
    {
        if (idCmd != 0) return E_INVALIDARG;
        if (!pszName) return E_INVALIDARG;
        if (uType == GCS_HELPTEXTW)
        {
            StringCchCopyW(pszName, cchMax, L"为这个文件添加或编辑备注");
            return S_OK;
        }
        if (uType == GCS_VERBW)
        {
            StringCchCopyW(pszName, cchMax, L"editremark");
            return S_OK;
        }
        // The buffer format follows uType, not this declaration: for the A
        // forms cchMax counts bytes and the buffer holds narrow characters.
        if (uType == GCS_HELPTEXTA)
        {
            WideCharToMultiByte(CP_ACP, 0, L"为这个文件添加或编辑备注", -1,
                (CHAR*)pszName, (int)cchMax, nullptr, nullptr);
            return S_OK;
        }
        if (uType == GCS_VERBA)
        {
            lstrcpynA((CHAR*)pszName, "editremark", (int)cchMax);
            return S_OK;
        }
        if (uType == GCS_VALIDATEW || uType == GCS_VALIDATEA)
            return S_OK;
        return E_NOTIMPL;
    }
#endif
};

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
            *ppv = this; AddRef(); return S_OK;
        }
        *ppv = nullptr; return E_NOINTERFACE;
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
        CRemarkContextMenu* p = new (std::nothrow) CRemarkContextMenu();
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

extern "C" BOOL WINAPI DllMain(HINSTANCE, DWORD dwReason, LPVOID)
{
    if (dwReason == DLL_PROCESS_ATTACH)
        DisableThreadLibraryCalls((HINSTANCE)GetModuleHandleW(nullptr));
    return TRUE;
}

STDAPI __declspec(dllexport) DllGetClassObject(REFCLSID rclsid, REFIID riid, void** ppv)
{
    if (rclsid != CLSID_FileRemarksContextMenu) return CLASS_E_CLASSNOTAVAILABLE;
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

// Registry helpers.
//
// The association is written to the user's hive and, when this process happens
// to be elevated, to the machine hive too. Shell associations are looked up with
// HKCU first, but the property handler this DLL is installed next to is not, so
// writing both keeps the two halves of the product in the same place.
static void RegDeleteSZUser(const WCHAR* subKey, const WCHAR* valueName)
{
    HKEY hk = nullptr;
    if (RegOpenKeyExW(HKEY_CURRENT_USER, subKey, 0, KEY_SET_VALUE, &hk) == ERROR_SUCCESS)
    {
        RegDeleteValueW(hk, valueName);
        RegCloseKey(hk);
    }
}

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
    if (hRoot == HKEY_LOCAL_MACHINE)
        RegDeleteSZUser(subKey, valueName);
    return hr;
}

static LONG RegDeleteTreeBoth(HKEY hRoot, const WCHAR* subKey)
{
    LONG e = RegDeleteTreeW(hRoot, subKey);
    RegDeleteTreeW(hRoot == HKEY_LOCAL_MACHINE ? HKEY_CURRENT_USER : HKEY_LOCAL_MACHINE, subKey);
    return e;
}

static HRESULT GetModulePath(WCHAR* out, DWORD cch)
{
    HMODULE hMod = nullptr;
    if (!GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS |
        GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
        (LPCWSTR)&CLSID_FileRemarksContextMenu, &hMod))
        return E_FAIL;
    DWORD n = GetModuleFileNameW(hMod, out, cch);
    if (!n || n >= cch) return E_FAIL;
    return S_OK;
}

STDAPI __declspec(dllexport) DllRegisterServer()
{
    WCHAR dllPath[MAX_PATH] = { 0 };
    if (FAILED(GetModulePath(dllPath, ARRAYSIZE(dllPath)))) return E_FAIL;

    // Machine-wide registration: the installer runs elevated and puts the DLL in
    // Program Files, so the menu entry is written next to the other shell
    // extensions and is found no matter which user is logged on.
    //
    // Every step is checked: a registration that silently half-succeeds is the
    // worst outcome, because the menu entry would just never appear.
    WCHAR keyCls[MAX_PATH];
    StringCchPrintfW(keyCls, ARRAYSIZE(keyCls), L"Software\\Classes\\CLSID\\%s", SZ_CM_CLSID);
    HRESULT hr = RegSetSZ(HKEY_LOCAL_MACHINE, keyCls, nullptr, L"FileRemarks Context Menu");
    if (FAILED(hr)) return hr;

    WCHAR keyInproc[MAX_PATH];
    StringCchPrintfW(keyInproc, ARRAYSIZE(keyInproc),
        L"Software\\Classes\\CLSID\\%s\\InprocServer32", SZ_CM_CLSID);
    hr = RegSetSZ(HKEY_LOCAL_MACHINE, keyInproc, nullptr, dllPath);
    if (FAILED(hr)) return hr;
    hr = RegSetSZ(HKEY_LOCAL_MACHINE, keyInproc, L"ThreadingModel", L"Apartment");
    if (FAILED(hr)) return hr;

    WCHAR keyCM[MAX_PATH];
    StringCchPrintfW(keyCM, ARRAYSIZE(keyCM),
        L"Software\\Classes\\*\\shellex\\ContextMenuHandlers\\FileRemarks");
    hr = RegSetSZ(HKEY_LOCAL_MACHINE, keyCM, nullptr, SZ_CM_CLSID);
    if (FAILED(hr)) return hr;

    // Remove the HKCU copies written by v1.9 - v1.15: a stale per-user CLSID
    // pointing at a deleted DLL is worse than no entry at all.
    RegDeleteTreeW(HKEY_CURRENT_USER, keyCls);
    RegDeleteTreeW(HKEY_CURRENT_USER, keyCM);

    return S_OK;
}

STDAPI __declspec(dllexport) DllUnregisterServer()
{
    HRESULT hrFirst = S_OK;

    WCHAR keyCM[MAX_PATH];
    StringCchPrintfW(keyCM, ARRAYSIZE(keyCM),
        L"Software\\Classes\\*\\shellex\\ContextMenuHandlers\\FileRemarks");
    LONG e = RegDeleteTreeBoth(HKEY_LOCAL_MACHINE, keyCM);
    if (e != ERROR_SUCCESS && e != ERROR_FILE_NOT_FOUND) hrFirst = HRESULT_FROM_WIN32(e);

    WCHAR keyCls[MAX_PATH];
    StringCchPrintfW(keyCls, ARRAYSIZE(keyCls), L"Software\\Classes\\CLSID\\%s", SZ_CM_CLSID);
    e = RegDeleteTreeBoth(HKEY_LOCAL_MACHINE, keyCls);
    if (e != ERROR_SUCCESS && e != ERROR_FILE_NOT_FOUND && SUCCEEDED(hrFirst))
        hrFirst = HRESULT_FROM_WIN32(e);

    return hrFirst;
}
