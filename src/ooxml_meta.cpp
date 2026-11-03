#include "ooxml_meta.h"

#include <zlib.h>

#include <string>
#include <vector>
#include <cstdio>
#include <cstring>
#include <cwchar>
#include <cctype>
#include <cstdlib>

namespace {

// A ZIP central-directory entry, reduced to what we need.
struct ZipEntry
{
    DWORD method;
    DWORD compSize;
    DWORD localOff;
    bool found;
};

WORD ReadU16(const BYTE* p) { return (WORD)(p[0] | (p[1] << 8)); }
DWORD ReadU32(const BYTE* p)
{
    return (DWORD)p[0] | ((DWORD)p[1] << 8) | ((DWORD)p[2] << 16) | ((DWORD)p[3] << 24);
}

bool ReadAt(HANDLE h, LONGLONG off, void* buf, DWORD cb)
{
    LARGE_INTEGER li;
    li.QuadPart = off;
    if (!SetFilePointerEx(h, li, nullptr, FILE_BEGIN)) return false;
    DWORD got = 0;
    if (!ReadFile(h, buf, cb, &got, nullptr)) return false;
    return got == cb;
}

bool NameMatches(const char* name, WORD len, const char* wanted)
{
    const size_t wlen = strlen(wanted);
    if (len < wlen) return false;
    const char* tail = name + (len - wlen);
    for (size_t i = 0; i < wlen; ++i)
    {
        char a = tail[i], b = wanted[i];
        if (a >= 'A' && a <= 'Z') a = (char)(a - 'A' + 'a');
        if (b >= 'A' && b <= 'Z') b = (char)(b - 'A' + 'a');
        if (a != b) return false;
    }
    return true;
}

// Locates the end-of-central-directory record and reads the directory itself.
bool ReadCentralDirectory(HANDLE h, LONGLONG size, std::vector<BYTE>* cd)
{
    if (size < 22) return false;

    DWORD tailLen = size < 66000 ? (DWORD)size : 66000;
    std::vector<BYTE> tail(tailLen);
    if (!ReadAt(h, size - tailLen, tail.data(), tailLen)) return false;

    for (int i = (int)tailLen - 22; i >= 0; --i)
    {
        const BYTE* p = &tail[(size_t)i];
        if (ReadU32(p) != 0x06054b50u) continue;

        DWORD cdSize = ReadU32(p + 12);
        DWORD cdOff  = ReadU32(p + 16);
        // ZIP64 markers mean a package we do not support; the caller falls back
        // to an ADS-only remark, which is harmless.
        if (cdSize == 0 || cdSize == 0xFFFFFFFFu || cdOff == 0xFFFFFFFFu) continue;
        if (cdSize > 8 * 1024 * 1024) continue;
        if ((LONGLONG)cdOff + (LONGLONG)cdSize > size) continue;

        cd->resize(cdSize);
        return ReadAt(h, cdOff, cd->data(), cdSize);
    }
    return false;
}

bool FindEntries(const std::vector<BYTE>& cd, ZipEntry* core, ZipEntry* app)
{
    size_t p = 0;
    while (p + 46 <= cd.size())
    {
        const BYTE* e = &cd[p];
        if (ReadU32(e) != 0x02014b50u) break;

        WORD nameLen    = ReadU16(e + 28);
        WORD extraLen   = ReadU16(e + 30);
        WORD commentLen = ReadU16(e + 32);
        if (p + 46 + nameLen > cd.size()) break;

        const char* name = (const char*)(e + 46);
        ZipEntry* target = nullptr;
        if (NameMatches(name, nameLen, "docProps/core.xml")) target = core;
        else if (NameMatches(name, nameLen, "docProps/app.xml")) target = app;

        if (target)
        {
            target->method   = ReadU16(e + 10);
            target->compSize = ReadU32(e + 20);
            target->localOff = ReadU32(e + 42);
            // A package may put docProps/app.xml first, whose local header then
            // sits at offset 0 -- so presence cannot be inferred from the offset.
            target->found    = true;
        }
        p += 46 + nameLen + extraLen + commentLen;
    }
    return core->found || app->found;
}

// Reads one entry's bytes, inflating raw DEFLATE when the package compressed it.
bool ReadEntry(HANDLE h, const ZipEntry& e, std::string* out)
{
    BYTE lh[30] = { 0 };
    if (!ReadAt(h, e.localOff, lh, 30)) return false;
    if (ReadU32(lh) != 0x04034b50u) return false;

    WORD nameLen  = ReadU16(lh + 26);
    WORD extraLen = ReadU16(lh + 28);
    LONGLONG dataOff = (LONGLONG)e.localOff + 30 + (LONGLONG)nameLen + extraLen;
    if (e.compSize == 0 || e.compSize > 4 * 1024 * 1024) return false;

    std::vector<BYTE> raw(e.compSize);
    if (!ReadAt(h, dataOff, raw.data(), e.compSize)) return false;

    if (e.method == 0)
    {
        out->assign((const char*)raw.data(), raw.size());
        return true;
    }
    if (e.method != 8) return false;   // anything else (bzip2, LZMA, ...) unsupported

    static const DWORD kCap = 1024 * 1024;
    out->assign(kCap, 0);
    z_stream zs;
    memset(&zs, 0, sizeof(zs));
    zs.next_in  = raw.data();
    zs.avail_in = e.compSize;
    zs.next_out = (Bytef*)&out->operator[](0);
    zs.avail_out = kCap;
    if (inflateInit2(&zs, -MAX_WBITS) != Z_OK) return false;
    const int rc = inflate(&zs, Z_FINISH);
    const DWORD produced = kCap - zs.avail_out;
    inflateEnd(&zs);
    if (rc != Z_STREAM_END) return false;
    out->resize(produced);
    return true;
}

// --- the small XML reader ------------------------------------------------
// The two parts are machine-generated and flat (one text value per element,
// no nesting inside the values), so a tag scanner is enough. It is deliberately
// forgiving: unknown elements are ignored, a malformed tail simply ends the scan.

std::string LocalName(const std::string& tag)
{
    const size_t colon = tag.find(':');
    return colon == std::string::npos ? tag : tag.substr(colon + 1);
}

// Returns the text of the first <prefix:local>...</prefix:local> element.
bool XmlText(const std::string& xml, const char* local, std::string* text)
{
    size_t pos = 0;
    while ((pos = xml.find('<', pos)) != std::string::npos)
    {
        const size_t close = xml.find('>', pos + 1);
        if (close == std::string::npos) return false;

        std::string tag = xml.substr(pos + 1, close - pos - 1);
        const bool selfClosing = !tag.empty() && tag[tag.size() - 1] == '/';
        const size_t space = tag.find_first_of(" \t\r\n/");
        if (space != std::string::npos) tag.resize(space);

        if (LocalName(tag) != local)
        {
            pos = close + 1;
            continue;
        }
        if (selfClosing)
        {
            text->clear();
            return true;
        }

        const size_t contentStart = close + 1;
        size_t scan = contentStart;
        while ((scan = xml.find("</", scan)) != std::string::npos)
        {
            const size_t end = xml.find('>', scan + 2);
            if (end == std::string::npos) return false;
            std::string endTag = xml.substr(scan + 2, end - scan - 2);
            const size_t sp = endTag.find_first_of(" \t\r\n");
            if (sp != std::string::npos) endTag.resize(sp);
            if (LocalName(endTag) == local)
            {
                *text = xml.substr(contentStart, scan - contentStart);
                return true;
            }
            scan = end + 1;
        }
        return false;
    }
    return false;
}

// Entities the two parts actually use, plus numeric escapes for safety.
std::string Unescape(const std::string& in)
{
    std::string out;
    out.reserve(in.size());
    for (size_t i = 0; i < in.size(); ++i)
    {
        if (in[i] != '&') { out.push_back(in[i]); continue; }

        const size_t semi = in.find(';', i + 1);
        if (semi == std::string::npos || semi - i > 10) { out.push_back(in[i]); continue; }

        const std::string ent = in.substr(i + 1, semi - i - 1);
        if (ent == "amp") out.push_back('&');
        else if (ent == "lt") out.push_back('<');
        else if (ent == "gt") out.push_back('>');
        else if (ent == "quot") out.push_back('"');
        else if (ent == "apos") out.push_back('\'');
        else if (ent.size() > 1 && ent[0] == '#')
        {
            const bool hex = ent[1] == 'x' || ent[1] == 'X';
            const unsigned code = (unsigned)strtoul(ent.c_str() + (hex ? 2 : 1), nullptr, hex ? 16 : 10);
            if (code < 0x80) { out.push_back((char)code); }
            else
            {
                // Outside ASCII: decode through UTF-8 so the wide conversion works.
                char buf[5] = { 0 };
                if (code < 0x800) { buf[0] = (char)(0xC0 | (code >> 6)); buf[1] = (char)(0x80 | (code & 0x3F)); }
                else if (code < 0x10000)
                {
                    buf[0] = (char)(0xE0 | (code >> 12));
                    buf[1] = (char)(0x80 | ((code >> 6) & 0x3F));
                    buf[2] = (char)(0x80 | (code & 0x3F));
                }
                else
                {
                    buf[0] = (char)(0xF0 | (code >> 18));
                    buf[1] = (char)(0x80 | ((code >> 12) & 0x3F));
                    buf[2] = (char)(0x80 | ((code >> 6) & 0x3F));
                    buf[3] = (char)(0x80 | (code & 0x3F));
                }
                out += buf;
            }
        }
        else { out += in.substr(i, semi - i + 1); }
        i = semi;
    }
    return out;
}

std::wstring ToWide(const std::string& utf8)
{
    if (utf8.empty()) return std::wstring();
    const int n = MultiByteToWideChar(CP_UTF8, 0, utf8.c_str(), (int)utf8.size(), nullptr, 0);
    if (n <= 0) return std::wstring();
    std::wstring w((size_t)n, 0);
    MultiByteToWideChar(CP_UTF8, 0, utf8.c_str(), (int)utf8.size(), &w[0], n);
    return w;
}

// Reads a text element and trims the markup some producers leave inside.
bool ReadText(const std::string& xml, const char* local, std::wstring* out)
{
    std::string raw;
    if (!XmlText(xml, local, &raw)) return false;
    const size_t lt = raw.find('<');      // e.g. <vt:lpwstr>...</vt:lpwstr>
    if (lt != std::string::npos) raw.resize(lt);
    raw = Unescape(raw);
    // Trim leading/trailing whitespace, which some writers add for readability.
    while (!raw.empty() && (raw[0] == ' ' || raw[0] == '\t' || raw[0] == '\r' || raw[0] == '\n'))
        raw.erase(0, 1);
    while (!raw.empty() && (isspace((unsigned char)raw[raw.size() - 1])))
        raw.erase(raw.size() - 1);
    *out = ToWide(raw);
    return true;
}

bool ReadUnsigned(const std::string& xml, const char* local, unsigned long long* out)
{
    std::wstring text;
    if (!ReadText(xml, local, &text) || text.empty()) return false;
    wchar_t* end = nullptr;
    const unsigned long long v = _wcstoui64(text.c_str(), &end, 10);
    if (!end || *end != 0) return false;
    *out = v;
    return true;
}

// "2023-11-01T05:26:00Z" (optionally with fractions). Office stores UTC; the
// value is returned as-is so Explorer formats it the same way Office did.
bool ReadW3CDate(const std::string& xml, const char* local, FILETIME* out)
{
    std::wstring text;
    if (!ReadText(xml, local, &text)) return false;
    int y = 0, mo = 0, d = 0, hh = 0, mi = 0, ss = 0;
    if (swscanf(text.c_str(), L"%4d-%2d-%2dT%2d:%2d:%2d", &y, &mo, &d, &hh, &mi, &ss) < 3)
        return false;
    SYSTEMTIME st;
    memset(&st, 0, sizeof(st));
    st.wYear = (WORD)y; st.wMonth = (WORD)mo; st.wDay = (WORD)d;
    st.wHour = (WORD)hh; st.wMinute = (WORD)mi; st.wSecond = (WORD)ss;
    return SystemTimeToFileTime(&st, out) != FALSE;
}

const WCHAR* ContentTypeFor(const WCHAR* ext)
{
    static const struct { const WCHAR* ext; const WCHAR* type; } kMap[] = {
        { L".docx", L"application/vnd.openxmlformats-officedocument.wordprocessingml.document" },
        { L".docm", L"application/vnd.ms-word.document.macroEnabled.12" },
        { L".dotx", L"application/vnd.openxmlformats-officedocument.wordprocessingml.template" },
        { L".dotm", L"application/vnd.ms-word.template.macroEnabled.12" },
        { L".pptx", L"application/vnd.openxmlformats-officedocument.presentationml.presentation" },
        { L".pptm", L"application/vnd.ms-powerpoint.presentation.macroEnabled.12" },
        { L".potx", L"application/vnd.openxmlformats-officedocument.presentationml.template" },
        { L".potm", L"application/vnd.ms-powerpoint.template.macroEnabled.12" },
        { L".xlsx", L"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" },
        { L".xlsm", L"application/vnd.ms-excel.sheet.macroEnabled.12" },
        { L".xlsb", L"application/vnd.ms-excel.sheet.binary.macroEnabled.12" },
        { L".xltx", L"application/vnd.openxmlformats-officedocument.spreadsheetml.template" },
        { L".xltm", L"application/vnd.ms-excel.template.macroEnabled.12" },
    };
    for (size_t i = 0; i < ARRAYSIZE(kMap); ++i)
        if (_wcsicmp(ext, kMap[i].ext) == 0) return kMap[i].type;
    return nullptr;
}

} // namespace

namespace fr {
namespace ooxml {

void Meta::Clear()
{
    for (size_t i = 0; i < values.size(); ++i)
        PropVariantClear(&values[i].var);
    values.clear();
    description.clear();
    ok = false;
}

void Meta::AddString(REFPROPERTYKEY key, const std::wstring& text)
{
    if (text.empty()) return;
    for (size_t i = 0; i < values.size(); ++i)
        if (values[i].key == key) return;

    PROPVARIANT v;
    PropVariantInit(&v);
    v.vt = VT_LPWSTR;
    v.pwszVal = (PWSTR)CoTaskMemAlloc((text.size() + 1) * sizeof(WCHAR));
    if (!v.pwszVal) return;
    wcscpy(v.pwszVal, text.c_str());
    Value item = { key, v };
    values.push_back(item);
}

void Meta::AddUInt32(REFPROPERTYKEY key, unsigned value)
{
    for (size_t i = 0; i < values.size(); ++i)
        if (values[i].key == key) return;
    PROPVARIANT v;
    PropVariantInit(&v);
    v.vt = VT_UI4;
    v.ulVal = value;
    Value item = { key, v };
    values.push_back(item);
}

void Meta::AddUInt64(REFPROPERTYKEY key, unsigned long long value)
{
    for (size_t i = 0; i < values.size(); ++i)
        if (values[i].key == key) return;
    PROPVARIANT v;
    PropVariantInit(&v);
    v.vt = VT_UI8;
    v.uhVal.QuadPart = value;
    Value item = { key, v };
    values.push_back(item);
}

void Meta::AddFileTime(REFPROPERTYKEY key, const FILETIME& ft)
{
    for (size_t i = 0; i < values.size(); ++i)
        if (values[i].key == key) return;
    PROPVARIANT v;
    PropVariantInit(&v);
    v.vt = VT_FILETIME;
    v.filetime = ft;
    Value item = { key, v };
    values.push_back(item);
}

bool IsOoxmlExtension(const WCHAR* ext)
{
    if (!ext) return false;
    static const WCHAR* const kExts[] = {
        L".docx", L".docm", L".dotx", L".dotm",
        L".pptx", L".pptm", L".potx", L".potm",
        L".xlsx", L".xlsm", L".xlsb", L".xltx", L".xltm",
        nullptr
    };
    for (int i = 0; kExts[i]; ++i)
        if (_wcsicmp(ext, kExts[i]) == 0) return true;
    return false;
}

bool Read(const WCHAR* path, Meta* out)
{
    if (!path || !out) return false;
    out->Clear();

    // Shared access on purpose: an open Word/Excel document keeps the package
    // file open, and Explorer must still be able to read its properties.
    HANDLE h = CreateFileW(path, GENERIC_READ,
                           FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
                           nullptr, OPEN_EXISTING,
                           FILE_ATTRIBUTE_NORMAL | FILE_FLAG_SEQUENTIAL_SCAN, nullptr);
    if (h == INVALID_HANDLE_VALUE) return false;

    LARGE_INTEGER size;
    size.QuadPart = 0;
    bool parsed = false;
    std::string coreXml, appXml;
    bool haveCore = false, haveApp = false;

    if (GetFileSizeEx(h, &size) && size.QuadPart > 0)
    {
        std::vector<BYTE> cd;
        ZipEntry core = { 0, 0, 0, false }, app = { 0, 0, 0, false };
        if (ReadCentralDirectory(h, size.QuadPart, &cd) && FindEntries(cd, &core, &app))
        {
            if (core.found) haveCore = ReadEntry(h, core, &coreXml);
            if (app.found)  haveApp  = ReadEntry(h, app, &appXml);
            parsed = haveCore || haveApp;
        }
    }
    CloseHandle(h);

    if (!parsed) return false;

    Meta m;
    std::wstring text;

    // core.xml -> the same properties Office's handler publishes.
    if (haveCore)
    {
        if (ReadText(coreXml, "title", &text))          m.AddString(PKEY_Title, text);
        if (ReadText(coreXml, "subject", &text))        m.AddString(PKEY_Subject, text);
        if (ReadText(coreXml, "creator", &text))        m.AddString(PKEY_Author, text);
        if (ReadText(coreXml, "keywords", &text))       m.AddString(PKEY_Keywords, text);
        if (ReadText(coreXml, "lastModifiedBy", &text)) m.AddString(PKEY_Document_LastAuthor, text);
        if (ReadText(coreXml, "category", &text))       m.AddString(PKEY_Category, text);
        if (ReadText(coreXml, "contentStatus", &text))  m.AddString(PKEY_ContentStatus, text);
        if (ReadText(coreXml, "language", &text))       m.AddString(PKEY_Language, text);
        if (ReadText(coreXml, "revision", &text))       m.AddString(PKEY_Document_RevisionNumber, text);
        if (ReadText(coreXml, "description", &text))    m.description = text;

        FILETIME ft;
        if (ReadW3CDate(coreXml, "created", &ft))  m.AddFileTime(PKEY_Document_DateCreated, ft);
        if (ReadW3CDate(coreXml, "modified", &ft)) m.AddFileTime(PKEY_Document_DateSaved, ft);
    }

    // app.xml -> counts and the strings Office shows in the Details tab.
    if (haveApp)
    {
        unsigned long long num = 0;
        if (ReadUnsigned(appXml, "Pages", &num))         m.AddUInt32(PKEY_Document_PageCount, (unsigned)num);
        if (ReadUnsigned(appXml, "Words", &num))         m.AddUInt32(PKEY_Document_WordCount, (unsigned)num);
        if (ReadUnsigned(appXml, "Characters", &num))    m.AddUInt32(PKEY_Document_CharacterCount, (unsigned)num);
        if (ReadUnsigned(appXml, "Lines", &num))         m.AddUInt32(PKEY_Document_LineCount, (unsigned)num);
        if (ReadUnsigned(appXml, "Paragraphs", &num))    m.AddUInt32(PKEY_Document_ParagraphCount, (unsigned)num);
        if (ReadUnsigned(appXml, "Slides", &num))        m.AddUInt32(PKEY_Document_SlideCount, (unsigned)num);
        if (ReadUnsigned(appXml, "Notes", &num))         m.AddUInt32(PKEY_Document_NoteCount, (unsigned)num);
        if (ReadUnsigned(appXml, "HiddenSlides", &num))  m.AddUInt32(PKEY_Document_HiddenSlideCount, (unsigned)num);
        if (ReadUnsigned(appXml, "DocSecurity", &num))   m.AddUInt32(PKEY_Document_Security, (unsigned)num);
        // TotalTime is minutes; the property is 100 ns units (4 min = 2.4e9).
        if (ReadUnsigned(appXml, "TotalTime", &num))
            m.AddUInt64(PKEY_Document_TotalEditingTime, num * 600000000ULL);

        if (ReadText(appXml, "Template", &text))            m.AddString(PKEY_Document_Template, text);
        if (ReadText(appXml, "Company", &text))             m.AddString(PKEY_Company, text);
        if (ReadText(appXml, "Manager", &text))             m.AddString(PKEY_Document_Manager, text);
        if (ReadText(appXml, "Application", &text))         m.AddString(PKEY_ApplicationName, text);
        if (ReadText(appXml, "PresentationFormat", &text))  m.AddString(PKEY_Document_PresentationFormat, text);
    }

    // The content type is a constant of the file type, not of the contents.
    const WCHAR* dot = wcsrchr(path, L'.');
    if (dot)
    {
        const WCHAR* type = ContentTypeFor(dot);
        if (type) m.AddString(PKEY_ContentType, type);
    }

    out->values.swap(m.values);
    out->description.swap(m.description);
    out->ok = true;
    return true;
}

} // namespace ooxml
} // namespace fr
