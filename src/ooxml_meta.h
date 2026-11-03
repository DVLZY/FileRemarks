// OOXML document metadata reader.
// ---------------------------------------------------------------------------
// Words/PowerPoint/Excel packages (.docx/.pptx/.xlsx and their macro/模板
// siblings) are ZIP containers, and the only durable metadata they carry lives
// in two tiny XML parts: docProps/core.xml (title, subject, creator, keywords,
// description, lastModifiedBy, created, modified, category, ...) and
// docProps/app.xml (pages, words, characters, lines, paragraphs, slides, notes,
// template, company, manager, application, total editing time, ...).
//
// Windows reads those through Office's own property handler (msoshext.dll). That
// handler can only open a real package, so a 0-byte "新建 Word 文档" placeholder
// -- or a damaged one -- makes Explorer fail with 0x80030050 and the 备注 column
// stays empty no matter what was written to the file's ADS. Serving the OOXML
// types ourselves lets us return the ADS remark for those files too, while
// reproducing the same document properties from the two XML parts above.
//
// Everything here is defensive on purpose: invalid ZIP, encrypted (CFB) packages,
// missing docProps, oversized entries, unsupported compression and unreadable
// files all return false and leave `Meta::ok` false. The caller then serves only
// the ADS remark, exactly as if no metadata existed.
// ---------------------------------------------------------------------------

#pragma once

#include <windows.h>
#include <propkey.h>
#include <propsys.h>

#include <string>
#include <vector>

namespace fr {
namespace ooxml {

struct Value
{
    PROPERTYKEY key;
    PROPVARIANT var;
};

struct Meta
{
    // Document properties other than System.Comment. System.Comment is handled
    // separately because the ADS remark takes precedence over dc:description.
    std::vector<Value> values;

    // dc:description of core.xml, in UTF-16. Shown as 备注 only when the file
    // has no ADS remark of its own.
    std::wstring description;

    // True only when the file was a readable OOXML package. When false the
    // caller must not claim any document property at all.
    bool ok;

    Meta() : ok(false) {}
    ~Meta() { Clear(); }
    Meta(const Meta&) = delete;
    Meta& operator=(const Meta&) = delete;

    void Clear();
    void AddString(REFPROPERTYKEY key, const std::wstring& text);
    void AddUInt32(REFPROPERTYKEY key, unsigned value);
    void AddUInt64(REFPROPERTYKEY key, unsigned long long value);
    void AddFileTime(REFPROPERTYKEY key, const FILETIME& ft);
};

// True for every extension a ZIP-based Office document can use. `ext` must
// include the leading dot; case-insensitive.
bool IsOoxmlExtension(const WCHAR* ext);

// Reads docProps/core.xml and docProps/app.xml out of `path`. Never throws,
// never blocks on a share violation, and bails out on anything it cannot parse.
bool Read(const WCHAR* path, Meta* out);

} // namespace ooxml
} // namespace fr
