// Shared NTFS Alternate Data Stream (ADS) I/O for the FileRemarks remark.
// The remark is stored per-file in a stream named ":remark" (UTF-8 text).
// Both the property handler, the editor and the self-test use these helpers
// so the storage logic lives in exactly one place.
#pragma once
#include <windows.h>
#include <string>

namespace fr {

inline std::wstring Utf8ToWstr(const std::string& s)
{
    if (s.empty()) return L"";
    int n = MultiByteToWideChar(CP_UTF8, 0, s.c_str(), (int)s.size(), nullptr, 0);
    std::wstring out(n, 0);
    MultiByteToWideChar(CP_UTF8, 0, s.c_str(), (int)s.size(), &out[0], n);
    return out;
}

inline std::string WstrToUtf8(const std::wstring& s)
{
    if (s.empty()) return "";
    int n = WideCharToMultiByte(CP_UTF8, 0, s.c_str(), (int)s.size(),
        nullptr, 0, nullptr, nullptr);
    std::string out(n, 0);
    WideCharToMultiByte(CP_UTF8, 0, s.c_str(), (int)s.size(), &out[0], n, nullptr, nullptr);
    return out;
}

// Read the ":remark" ADS. Returns false if the stream does not exist.
// On success, out holds the decoded text.
inline bool ReadRemark(const std::wstring& filePath, std::wstring& out)
{
    out.clear();
    std::wstring ads = filePath + L":remark";
    HANDLE h = CreateFileW(ads.c_str(), GENERIC_READ,
        FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
        nullptr, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (h == INVALID_HANDLE_VALUE) return false; // no remark yet
    DWORD size = GetFileSize(h, nullptr);
    bool ok = true;
    if (size != INVALID_FILE_SIZE && size > 0)
    {
        std::string buf(size, 0);
        DWORD rd = 0;
        if (ReadFile(h, buf.data(), size, &rd, nullptr) && rd > 0)
            out = Utf8ToWstr(std::string(buf.data(), rd));
        else
            ok = false;
    }
    CloseHandle(h);
    return ok;
}

// Write the ":remark" ADS. An empty remark clears (deletes) the stream.
inline bool WriteRemark(const std::wstring& filePath, const std::wstring& remark)
{
    std::wstring ads = filePath + L":remark";
    if (remark.empty())
    {
        // Clearing: delete the ADS stream. Setting attributes to NORMAL first
        // makes DeleteFileW reliably remove the stream on real NTFS.
        SetFileAttributesW(ads.c_str(), FILE_ATTRIBUTE_NORMAL);
        DeleteFileW(ads.c_str());
        return true;
    }
    HANDLE h = CreateFileW(ads.c_str(), GENERIC_WRITE, 0, nullptr,
        CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (h == INVALID_HANDLE_VALUE) return false;
    std::string u8 = WstrToUtf8(remark);
    bool ok = true;
    if (!u8.empty())
    {
        DWORD wr = 0;
        ok = (WriteFile(h, u8.data(), (DWORD)u8.size(), &wr, nullptr) != 0) &&
             (wr == (DWORD)u8.size());
    }
    CloseHandle(h);
    return ok;
}

} // namespace fr
