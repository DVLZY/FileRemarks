// In-process logic test for the FileRemarks remark storage.
// This exercises the exact ADS read/write path used by the property handler,
// without loading into Explorer. Build: tools/build_mingw.sh
#include <windows.h>
#include <cstdio>

#include "remark.h"
#include "remark_io.h"

int main()
{
    // Create a temp file on a real NTFS path.
    WCHAR tmpDir[MAX_PATH] = { 0 };
    GetTempPathW(MAX_PATH, tmpDir);
    WCHAR tmpFile[MAX_PATH] = { 0 };
    GetTempFileNameW(tmpDir, L"frm", 0, tmpFile);
    printf("Temp file: %ls\n", tmpFile);

    std::wstring path(tmpFile);
    // 1) Write a Chinese remark (UTF-8 round-trip).
    std::wstring remark = L"这是一个测试备注 - 用于记住文件用途 (v2)";
    bool bw = fr::WriteRemark(path, remark);
    printf("WriteRemark: %s\n", bw ? "OK" : "FAIL");

    // 2) Read it back, verify exact equality.
    std::wstring got;
    fr::ReadRemark(path, got);
    bool ok = (got == remark);
    printf("ReadRemark:  got=%ls\n", got.c_str());
    printf("Roundtrip:   %s\n", ok ? "PASS" : "FAIL");

    // 3) Empty remark clears the stream (file still exists, stream gone).
    fr::WriteRemark(path, L"");
    std::wstring got2;
    fr::ReadRemark(path, got2);
    bool cleared = got2.empty();
    printf("Clear remark: %s\n", cleared ? "PASS" : "FAIL");

    // 4) Verify ADS physically exists after a non-empty write.
    fr::WriteRemark(path, remark);
    std::wstring ads = path + FILEREMARKS_ADS_NAME;
    bool adsExists = GetFileAttributesW(ads.c_str()) != INVALID_FILE_ATTRIBUTES;
    printf("ADS exists after write: %s\n", adsExists ? "YES" : "NO");

    DeleteFileW(tmpFile);
    printf("\nRESULT: %s\n", (ok && cleared && adsExists) ? "ALL PASS" : "FAILURE");
    return (ok && cleared && adsExists) ? 0 : 1;
}
