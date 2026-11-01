// Test-only wrapper: exposes the REAL ExtractPayload() from selfext.cpp so it
// can be exercised in-process through ctypes (the sandbox forbids spawning
// native executables). Not part of the shipped product.
#include "selfext.cpp"

extern "C" __declspec(dllexport) int FrSelfTest(const wchar_t* exePath, const wchar_t* outDir)
{
    std::vector<std::wstring> files;
    std::wstring err = ExtractPayload(exePath, outDir, files);
    if (!err.empty()) return -1;
    return (int)files.size();
}
