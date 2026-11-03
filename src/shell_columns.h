// Shell column defaults
// ---------------------------------------------------------------------------
// Makes the "备注" column appear in Explorer without the user having to add it
// by hand, and puts everything back exactly as it was on uninstall.
//
// Where Explorer keeps this: each folder type ("Generic", "Documents",
// "Pictures", ...) has a default view under
//
//   HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\FolderTypes
//        \<folder-type-guid>\TopViews\{00000000-0000-0000-0000-000000000000}
//
// whose (Default) value is a ColumnList such as
//
//   prop:0(34)System.ItemNameDisplay;0System.DateModified;...
// i.e. one semicolon-separated ColumnList whose entries are "prop:" + width
// flags + the property's canonical name. Appending ";0System.Comment" adds the
// column Windows already calls 备注 (verified: its display name is exactly
// 备注 and its edit invitation is 添加备注 -- see README).
//
// Notes:
//  * Everything is written under HKCU, because the product installs per-user
//    and therefore runs without administrator rights. Explorer resolves
//    FolderTypes per-user first, so an HKCU override is honoured exactly like
//    an HKLM one -- it just applies to this user instead of the whole machine.
//  * HKLM is not merely inconvenient, it is impossible: those view keys are
//    owned by TrustedInstaller/SYSTEM and grant BUILTIN\Administrators only
//    ReadKey for Generic, Documents, Pictures and Downloads (measured; only
//    Music and Videos grant FullControl). That ACL is exactly why the old
//    machine-wide, elevated installer added the column to two types out of six
//    and reported success anyway.
//  * The per-user view is a full COPY of the machine view, then our column is
//    appended to its ColumnList. A per-user FolderTypes key is not merged value
//    by value, so copying only ColumnList would drop LogicalViewMode,
//    SortByList, IconSize and anything else the view defines.
//  * The CURRENT default is read from HKLM, never from our own override: the
//    machine value is the pristine base, so running the installer twice cannot
//    stack the column twice or freeze an old override as the new baseline.
//  * The original string is saved first under
//    HKCU\SOFTWARE\FileRemarks\ColumnList\<guid>, and its presence is the
//    marker that says "we created this override", which is what uninstall and
//    the change counter both key off.
//  * Nothing is reported as enabled without reading the value back: see
//    IsCommentColumnEnabled()/CountEnabledFolderTypes().
//  * A per-folder saved view the user made themselves (a "Bag") wins over this
//    default and is deliberately left alone -- we change defaults, not the
//    user's own column layout.
// ---------------------------------------------------------------------------
#pragma once

#include <windows.h>
#include <shlobj.h>
#include <strsafe.h>
#include <new>

namespace fr
{
namespace columns
{

// Folder types whose default view is used by the folders people actually browse.
// Generic covers normal folders (including user files with no special type);
// the others are the shell's own Documents/Pictures/Music/Videos/Downloads views.
static const WCHAR* const kFolderTypes[] = {
    L"{5c4f28b5-f869-4e84-8e60-f11db97c5cc7}", // Generic
    L"{7d49d726-3c21-4f05-99aa-fdc2c9474656}", // Documents
    L"{b3690e58-e961-423b-b687-386ebfd83239}", // Pictures
    L"{885a186e-a440-4ada-812b-db871b942259}", // Downloads
    L"{94d6ddcc-4a68-4175-a374-bd584a510b78}", // Music
    L"{5fa96407-7e77-483c-ac93-691d05850de8}", // Videos
    nullptr
};

// The canonical name of the property the editor writes and Explorer labels 备注.
static const WCHAR SZ_COMMENT_PROP[] = L"System.Comment";

// Appended with the one-digit flag prefix every non-first entry carries. Adding
// it as "0" (unspecified width) lets Explorer size the column from its content.
static const WCHAR SZ_APPEND[] = L";0System.Comment";

// Builds the TopViews\<view-guid> path of a folder type.
static inline void ViewKey(const WCHAR* folderType, WCHAR* out, size_t cch)
{
    StringCchPrintfW(out, cch,
        L"Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\FolderTypes\\%s\\"
        L"TopViews\\{00000000-0000-0000-0000-000000000000}", folderType);
}

// Builds the path where the untouched original ColumnList is remembered.
static inline void BackupKey(const WCHAR* folderType, WCHAR* out, size_t cch)
{
    StringCchPrintfW(out, cch, L"Software\\FileRemarks\\ColumnList\\%s", folderType);
}

// Reads a REG_SZ/REG_EXPAND_SZ value of any length into a new[] buffer.
// Returns nullptr when the value is absent or not a string.
static inline WCHAR* ReadString(HKEY root, const WCHAR* subKey, const WCHAR* valueName)
{
    HKEY hk = nullptr;
    if (RegOpenKeyExW(root, subKey, 0, KEY_READ, &hk) != ERROR_SUCCESS)
        return nullptr;

    DWORD cb = 0, type = 0;
    LONG rc = RegQueryValueExW(hk, valueName, nullptr, &type, nullptr, &cb);
    if (rc != ERROR_SUCCESS || (type != REG_SZ && type != REG_EXPAND_SZ) || cb < sizeof(WCHAR))
    {
        RegCloseKey(hk);
        return nullptr;
    }

    const size_t chars = cb / sizeof(WCHAR);
    WCHAR* buf = new (std::nothrow) WCHAR[chars + 1];
    if (!buf) { RegCloseKey(hk); return nullptr; }

    rc = RegQueryValueExW(hk, valueName, nullptr, &type, (BYTE*)buf, &cb);
    RegCloseKey(hk);
    if (rc != ERROR_SUCCESS)
    {
        delete[] buf;
        return nullptr;
    }
    // Registry strings are normally terminated, but never trust that: the
    // buffer has one spare slot for exactly this.
    buf[chars] = 0;
    return buf;
}

// Writes a REG_SZ value, creating the key when needed.
//
// HKCU only. An earlier release also mirrored this into HKLM "best effort", and
// that was wrong on two counts: Music and Videos do grant Administrators
// FullControl, so the machine-wide default of *every* user on the machine was
// silently changed, and uninstall had no way back. The per-user override is
// honoured by Explorer exactly like an HKLM one, so HKLM is left untouched.
static inline bool WriteString(HKEY root, const WCHAR* subKey, const WCHAR* valueName, const WCHAR* data)
{
    HKEY hk = nullptr;
    DWORD disp = 0;
    bool ok = false;
    if (RegCreateKeyExW(root, subKey, 0, nullptr, REG_OPTION_NON_VOLATILE,
        KEY_WRITE, nullptr, &hk, &disp) == ERROR_SUCCESS)
    {
        LONG rc = RegSetValueExW(hk, valueName, 0, REG_SZ, (const BYTE*)data,
            (DWORD)((wcslen(data) + 1) * sizeof(WCHAR)));
        RegCloseKey(hk);
        ok = (rc == ERROR_SUCCESS);
    }
    return ok;
}

// Removes the exact token we append, so uninstall can repair a machine-wide
// value an older release wrote. Operates on a copy in `out`; returns true when
// the token was there and `out` holds the repaired list.
static inline bool StripAppendedComment(const WCHAR* list, WCHAR* out, size_t cch)
{
    if (!list || !out || cch == 0) return false;
    const WCHAR* hit = wcsstr(list, SZ_APPEND);
    if (!hit) return false;

    StringCchCopyW(out, cch, list);
    WCHAR* at = out + (hit - list);
    *at = 0;
    // Entries are ';'-separated and our token starts with ';', so dropping it is
    // safe even when it is not the last entry.
    StringCchCatW(out, cch, hit + (ARRAYSIZE(SZ_APPEND) - 1));
    return true;
}

// True when `list` already mentions System.Comment as a column.
static inline bool AlreadyHasComment(const WCHAR* list)
{
    return wcsstr(list, SZ_COMMENT_PROP) != nullptr;
}

// Returns a newly allocated ColumnList with the 备注 column appended, or
// nullptr when nothing needs to change (the column is already there) or the
// input is unusable. Kept separate from the registry code so it can be unit
// tested without touching HKLM -- see src/selftest_columns.cpp.
//
// The entry is appended rather than inserted so the user's existing column
// order is untouched. Trailing whitespace and semicolons are trimmed first:
// either one would leave an empty entry behind, and a single empty entry makes
// Explorer discard the whole column list.
static inline WCHAR* BuildColumnList(const WCHAR* list)
{
    if (!list || !list[0]) return nullptr;
    if (AlreadyHasComment(list)) return nullptr;

    const size_t n = wcslen(list) + (ARRAYSIZE(SZ_APPEND) - 1) + 1;
    WCHAR* merged = new (std::nothrow) WCHAR[n];
    if (!merged) return nullptr;

    StringCchCopyW(merged, n, list);
    size_t len = wcslen(merged);
    while (len && (merged[len - 1] == L';' || merged[len - 1] == L' ' ||
                   merged[len - 1] == L'\t'))
        merged[--len] = 0;
    if (!len)
    {
        // Nothing but separators: better to leave the value alone than to write
        // a list that starts with an empty entry.
        delete[] merged;
        return nullptr;
    }
    StringCchCatW(merged, n, SZ_APPEND);
    return merged;
}

// Reads the current default of a folder type: the per-user override we or the
// user already created, otherwise the machine-wide base value Windows ships.
// Read-only access to HKLM needs no administrator rights, so this stays valid
// for a per-user install.
static inline WCHAR* ReadCurrentList(const WCHAR* keyView)
{
    WCHAR* s = ReadString(HKEY_CURRENT_USER, keyView, L"ColumnList");
    if (s) return s;
    return ReadString(HKEY_LOCAL_MACHINE, keyView, L"ColumnList");
}

// The pristine machine-wide default of a folder type, ignoring any per-user
// override. This is what our appended list is built from: the user's own saved
// per-folder views live in Bags, not here, so the base never contains them.
static inline WCHAR* ReadMachineList(const WCHAR* keyView)
{
    return ReadString(HKEY_LOCAL_MACHINE, keyView, L"ColumnList");
}

// Copies every value of the machine-wide default view into the per-user key.
//
// A per-user FolderTypes override is not merged value by value: once the key
// exists, Explorer reads the view from it. So the whole view has to be there,
// not just ColumnList -- otherwise the user would silently lose the view's
// logical mode, sort list or icon size. Copying also keeps any future Windows
// change to the base view working, because the copy is refreshed on each run
// before our column is appended.
static inline bool CopyViewToUser(const WCHAR* keyView)
{
    HKEY src = nullptr;
    if (RegOpenKeyExW(HKEY_LOCAL_MACHINE, keyView, 0, KEY_READ, &src) != ERROR_SUCCESS)
        return false;

    HKEY dst = nullptr;
    DWORD disp = 0;
    if (RegCreateKeyExW(HKEY_CURRENT_USER, keyView, 0, nullptr, REG_OPTION_NON_VOLATILE,
        KEY_WRITE, nullptr, &dst, &disp) != ERROR_SUCCESS)
    {
        RegCloseKey(src);
        return false;
    }

    bool ok = true;
    for (DWORD i = 0;; ++i)
    {
        WCHAR name[256];
        DWORD cchName = ARRAYSIZE(name);
        DWORD type = 0;
        DWORD cb = 0;
        LONG rc = RegEnumValueW(src, i, name, &cchName, nullptr, &type, nullptr, &cb);
        if (rc == ERROR_NO_MORE_ITEMS) break;
        if (rc != ERROR_SUCCESS) { ok = false; break; }
        if (cb > 64 * 1024) continue; // not something a view value should be

        BYTE* data = cb ? new (std::nothrow) BYTE[cb] : nullptr;
        if (cb && !data) { ok = false; break; }
        rc = RegQueryValueExW(src, name, nullptr, &type, data, &cb);
        if (rc == ERROR_SUCCESS)
        {
            if (RegSetValueExW(dst, name, 0, type, data, cb) != ERROR_SUCCESS)
                ok = false;
        }
        delete[] data;
    }

    RegCloseKey(dst);
    RegCloseKey(src);
    return ok;
}

// Adds the 备注 column to one folder type's default view. Returns true when the
// value ends up containing the column (whether we just added it or it was there).
//
// Why this writes HKCU and not HKLM: the view keys under HKLM are owned by
// TrustedInstaller and grant BUILTIN\Administrators only ReadKey for every
// folder type except Music and Videos (which grant FullControl). That is not a
// theory -- it is why the old machine-wide installer managed to add the column
// to exactly those two types and silently failed on the other four, even while
// running elevated. A per-user override is owned by the user, is always
// writable, and applies to this user, which is all this product needs.
static inline bool AddToFolderType(const WCHAR* folderType, bool* changed)
{
    if (changed) *changed = false;

    WCHAR keyView[512];
    ViewKey(folderType, keyView, ARRAYSIZE(keyView));

    // Start from the untouched machine-wide default, not from our own earlier
    // override: otherwise a second run would treat an old override as the new
    // baseline forever and could never notice that Windows changed the base.
    WCHAR* list = ReadMachineList(keyView);
    if (!list) return false; // folder type absent on this machine; nothing to do

    // Copy the whole view first, then replace just the ColumnList. Without the
    // copy the per-user key would contain our column list and nothing else, and
    // the folder would lose its layout mode, sort order and icon size.
    const bool copied = CopyViewToUser(keyView);

    WCHAR* merged = BuildColumnList(list);
    if (!merged)
    {
        // Already has the column (e.g. a previous run), or the base is unusable.
        const bool already = AlreadyHasComment(list);
        delete[] list;
        return already || copied;
    }

    // Remember the untouched original under our own key, so uninstall can put
    // the machine default back without needing to subtract anything. Its
    // presence BEFORE this write is also our marker for "this type already
    // carries our override", which is what makes the change count below honest.
    WCHAR keyBackup[512];
    BackupKey(folderType, keyBackup, ARRAYSIZE(keyBackup));
    WCHAR* previous = ReadString(HKEY_CURRENT_USER, keyBackup, nullptr);
    const bool firstTime = (previous == nullptr);
    if (previous)
        delete[] previous;
    else
        WriteString(HKEY_CURRENT_USER, keyBackup, nullptr, list);
    delete[] list;

    const bool wrote = WriteString(HKEY_CURRENT_USER, keyView, L"ColumnList", merged);
    delete[] merged;
    if (!wrote) return false;

    // Never report success from the write call alone: read the value back and
    // require the column to be in it. Group policy can make these keys
    // read-only, and an installer that claims "column enabled" while Explorer
    // shows nothing is worse than one that says it could not.
    WCHAR* live = ReadString(HKEY_CURRENT_USER, keyView, L"ColumnList");
    const bool took = live && AlreadyHasComment(live);
    delete[] live;
    if (!took) return false;

    // Re-running the installer must not claim the user's column layout moved
    // again: only a first-time override counts as a change.
    if (changed) *changed = firstTime;
    return true;
}

// Undoes AddToFolderType(): removes the per-user view we created, so Explorer
// falls back to the machine-wide one again, and forgets the backup. The backup
// is the marker for "we created this override", so without it there is nothing
// of ours to remove and the key is left untouched.
static inline void RemoveFromFolderType(const WCHAR* folderType)
{
    WCHAR keyView[512];
    ViewKey(folderType, keyView, ARRAYSIZE(keyView));

    WCHAR keyBackup[512];
    BackupKey(folderType, keyBackup, ARRAYSIZE(keyBackup));

    WCHAR* original = ReadString(HKEY_CURRENT_USER, keyBackup, nullptr);
    const bool ours = (original != nullptr);
    if (original)
    {
        delete[] original;
        // Delete the whole per-user view, not just ColumnList: we copied every
        // value of the machine view when we created it, and leaving the rest
        // behind would pin those stale values forever.
        RegDeleteTreeW(HKEY_CURRENT_USER, keyView);
    }
    RegDeleteKeyW(HKEY_CURRENT_USER, keyBackup);

    // Repair the machine-wide default if a previous release wrote our token into
    // it. Only Music and Videos are writable there, so all other writes simply
    // fail and their value is left exactly as Windows shipped it. Gated on the
    // backup marker so a value somebody else put there by hand is never touched.
    if (ours)
    {
        WCHAR* machine = ReadString(HKEY_LOCAL_MACHINE, keyView, L"ColumnList");
        if (machine)
        {
            WCHAR fixed[1024];
            if (StripAppendedComment(machine, fixed, ARRAYSIZE(fixed)))
                WriteString(HKEY_LOCAL_MACHINE, keyView, L"ColumnList", fixed);
            delete[] machine;
        }
    }
}

// Applies the change to every folder type in the list. Returns the number of
// views that actually changed, so the installer can say whether a restart of
// Explorer is needed.
static inline int EnableCommentColumn()
{
    int changed = 0;
    for (int i = 0; kFolderTypes[i]; ++i)
    {
        bool c = false;
        if (AddToFolderType(kFolderTypes[i], &c) && c) ++changed;
    }
    // Explorer caches folder views, and SHCNE_ASSOCCHANGED is what makes it
    // re-read FolderTypes; without a notification an already-open window keeps
    // the old column set until the user navigates away and back.
    if (changed)
        SHChangeNotify(SHCNE_ASSOCCHANGED, SHCNF_IDLIST, nullptr, nullptr);
    return changed;
}

// True when the 备注 column is currently part of a folder type's effective
// default view (per-user override first, machine value second). Used by the
// post-install report and by the tests, so "enabled" always means "readable
// from the registry right now", never "we called a function".
static inline bool IsCommentColumnEnabled(const WCHAR* folderType)
{
    WCHAR keyView[512];
    ViewKey(folderType, keyView, ARRAYSIZE(keyView));
    WCHAR* s = ReadCurrentList(keyView);
    if (!s) return false;
    const bool has = AlreadyHasComment(s);
    delete[] s;
    return has;
}

// How many of the tracked folder types currently show the 备注 column.
static inline int CountEnabledFolderTypes()
{
    int n = 0;
    for (int i = 0; kFolderTypes[i]; ++i)
        if (IsCommentColumnEnabled(kFolderTypes[i])) ++n;
    return n;
}

// Undoes EnableCommentColumn().
static inline void DisableCommentColumn()
{
    for (int i = 0; kFolderTypes[i]; ++i)
        RemoveFromFolderType(kFolderTypes[i]);
    RegDeleteTreeW(HKEY_CURRENT_USER, L"Software\\FileRemarks\\ColumnList");
    SHChangeNotify(SHCNE_ASSOCCHANGED, SHCNF_IDLIST, nullptr, nullptr);
}

} // namespace columns
} // namespace fr
