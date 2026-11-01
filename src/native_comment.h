// Reading/writing the remark through the property system as well as the ADS.
//
// The remark has two possible homes:
//   * the :remark ADS -- always available, works for every file type;
//   * the built-in System.Comment property -- what Explorer's "备注" column
//     shows, but only writable for file types whose own property handler
//     supports writing it (Word/Excel/PowerPoint metadata, photos, video).
//
// Types our own property handler owns get the column from the ADS, so there is
// no reason to touch the file's own metadata (that would rewrite the bytes of
// an image or a video for nothing). Types we deliberately do NOT take over --
// Office documents above all, because their metadata handler does not expose
// IPropertyStore and replacing it would hide the native Details columns -- only
// get the column when the value is written natively. So: ADS always, native
// value only when our handler is not the one serving the type.
#pragma once

#include <shobjidl.h>
#include <propsys.h>
#include <propkey.h>
#include <propvarutil.h>

namespace fr
{
    // CLSID of FileRemarksPropHandler; must match src/FileRemarksPropHandler.cpp.
    const WCHAR FILEREMARKS_CLSID[] = L"{B4C8E6D1-7A2F-4c3b-9D5E-1F6C2A8B3D41}";

    // SHGetPropertyStoreFromParsingName rejects a relative path outright
    // (E_INVALIDARG), so always hand it an absolute one.
    inline std::wstring FullPath(const std::wstring& path)
    {
        WCHAR buf[MAX_PATH * 2];
        DWORD n = GetFullPathNameW(path.c_str(), ARRAYSIZE(buf), buf, nullptr);
        if (n == 0 || n >= ARRAYSIZE(buf)) return path;
        return std::wstring(buf, n);
    }

    // True when our own property handler is the one registered for this file
    // type, i.e. when Explorer reads the 备注 column from our ADS-backed store.
    inline bool HandlerIsOurs(const std::wstring& path)
    {
        const WCHAR* dot = wcsrchr(path.c_str(), L'.');
        if (!dot) return false;
        std::wstring ext(dot);

        // Both shapes Explorer consults for a per-type handler.
        std::wstring sub1 = std::wstring(
            L"SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\PropertySystem\\PropertyHandlers\\") + ext;
        std::wstring sub2 = std::wstring(L"SOFTWARE\\Classes\\") + ext + L"\\ShellEx\\PropertyHandler";

        // Our own entries live under HKCU (per-user install), while a handler
        // Windows ships for a type lives in HKLM, so both roots must be checked.
        const HKEY kRoots[] = { HKEY_CURRENT_USER, HKEY_LOCAL_MACHINE };

        for (int r = 0; r < 2; ++r)
        {
            for (const std::wstring* sub : { &sub1, &sub2 })
            {
                HKEY hk = nullptr;
                if (RegOpenKeyExW(kRoots[r], sub->c_str(), 0, KEY_READ, &hk) != ERROR_SUCCESS)
                    continue;
                WCHAR value[256] = { 0 };
                DWORD cb = sizeof(value) - sizeof(WCHAR);
                DWORD type = 0;
                LONG rc = RegQueryValueExW(hk, nullptr, nullptr, &type,
                    reinterpret_cast<LPBYTE>(value), &cb);
                RegCloseKey(hk);
                if (rc == ERROR_SUCCESS && type == REG_SZ &&
                    CompareStringOrdinal(value, -1, FILEREMARKS_CLSID, -1, TRUE) == CSTR_EQUAL)
                    return true;
            }

            // Third shape: one key holding a value named after the extension.
            HKEY hk = nullptr;
            if (RegOpenKeyExW(kRoots[r],
                L"SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\PropertySystem\\SystemPropertyHandlers",
                0, KEY_READ, &hk) == ERROR_SUCCESS)
            {
                WCHAR value[256] = { 0 };
                DWORD cb = sizeof(value) - sizeof(WCHAR);
                DWORD type = 0;
                LONG rc = RegQueryValueExW(hk, ext.c_str(), nullptr, &type,
                    reinterpret_cast<LPBYTE>(value), &cb);
                RegCloseKey(hk);
                if (rc == ERROR_SUCCESS && type == REG_SZ &&
                    CompareStringOrdinal(value, -1, FILEREMARKS_CLSID, -1, TRUE) == CSTR_EQUAL)
                    return true;
            }
        }
        return false;
    }

    // Reads System.Comment. `exists` tells whether the property was present and
    // non-empty; the return value reports whether the store could be opened.
    inline bool ReadNativeComment(const std::wstring& path, std::wstring& out, bool& exists)
    {
        out.clear();
        exists = false;
        std::wstring full = FullPath(path);
        IPropertyStore* ps = nullptr;
        HRESULT hr = SHGetPropertyStoreFromParsingName(full.c_str(), nullptr,
            GPS_DEFAULT, IID_PPV_ARGS(&ps));
        if (FAILED(hr) || !ps) return false;

        PROPVARIANT pv;
        PropVariantInit(&pv);
        hr = ps->GetValue(PKEY_Comment, &pv);
        bool ok = SUCCEEDED(hr);
        if (ok && pv.vt == VT_LPWSTR && pv.pwszVal && *pv.pwszVal)
        {
            out.assign(pv.pwszVal);
            exists = true;
        }
        PropVariantClear(&pv);
        ps->Release();
        return ok;
    }

    // Writes System.Comment. Returns false when this file type does not allow
    // it -- a completely normal outcome, not an error the user needs to see.
    inline bool WriteNativeComment(const std::wstring& path, const std::wstring& text)
    {
        std::wstring full = FullPath(path);
        IPropertyStore* ps = nullptr;
        HRESULT hr = SHGetPropertyStoreFromParsingName(full.c_str(), nullptr,
            GPS_READWRITE, IID_PPV_ARGS(&ps));
        if (FAILED(hr) || !ps) return false;

        PROPVARIANT pv;
        PropVariantInit(&pv);
        if (text.empty())
            pv.vt = VT_EMPTY;
        else
            hr = InitPropVariantFromString(text.c_str(), &pv);
        if (SUCCEEDED(hr)) hr = ps->SetValue(PKEY_Comment, pv);
        if (SUCCEEDED(hr)) hr = ps->Commit();
        PropVariantClear(&pv);
        ps->Release();
        return SUCCEEDED(hr);
    }

    // Only for types whose column our handler does not serve; see the note at
    // the top of this file.
    inline bool WriteNativeCommentIfNeeded(const std::wstring& path, const std::wstring& text)
    {
        if (HandlerIsOurs(path)) return true;   // ADS is enough, leave the file alone
        return WriteNativeComment(path, text);
    }
}
