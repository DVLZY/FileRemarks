// FileRemarks Editor
// ---------------------------------------------------------------------------
// A tiny standalone Win32 window that shows the "备注" (remark) for ONE file and
// lets you add / edit / clear it. The remark is stored in the file's NTFS
// Alternate Data Stream ":remark" (UTF-8), exactly like the Property Handler,
// so it works for ANY file type (exe, png, jpg, doc, py, md, ...) launched from
// the Explorer right-click menu ("编辑备注").
//
// Where the file type allows it, the value is ALSO written to the built-in
// System.Comment property -- the one Explorer's 备注 column already displays --
// so the column works for Office documents too, whose own metadata handler we
// must not replace (see src/native_comment.h).
//
// There are deliberately NO buttons: losing the foreground saves and closes the
// window ("type, then click away"), and so do the X button and Ctrl+Enter.
// A save that fails keeps the window open with the reason in the status line,
// so nothing is lost silently. An untouched window closes without writing
// anything. Esc is 取消: it closes without saving even if text was typed.
// Clearing a remark is simply deleting its text; plain Enter inserts a newline.
//
// The look follows Windows 11 -- flat page, one rounded input surface, Segoe UI,
// rounded window corners, and both the light and the dark palette -- and is
// painted by hand with plain GDI (see src/theme.h), so there is no .rc file and
// no resource compiler in the build. There is deliberately no focus ring: the
// caret is the focus, and the window holds exactly one editable surface.
//
// The window is deliberately reduced to two things: a title bar carrying the
// file NAME (a native caption, so it is left-aligned and elided by Windows
// itself), and one remark box. No path row, no labels, no buttons, and no
// scrollbar. An empty remark box shows the cue text "在这输入备注..." which
// disappears the moment anything is typed.
//
// Usage: FileRemarksEditor.exe "<file path>"
// ---------------------------------------------------------------------------

#include <windows.h>
#include <commctrl.h>
#include <shellapi.h>
#include <shlobj.h>
#include <objbase.h>
#include <string>
#include <cwctype>      // iswspace, for Ctrl+Backspace

#include "remark_io.h"
#include "native_comment.h"
#include "logo.h"
#include "theme.h"
#include "version.h"

#pragma comment(linker, "\"/MANIFESTDEPENDENCY:type='win32' \
name='Microsoft.Windows.Common-Controls' version='6.0.0.0' \
processorArchitecture='*' publicKeyToken='6595b64144ccf1df' language='*'\"")

// Control IDs.
enum {
    IDC_REMARK = 102,
    IDC_STATUS = 103,
};

// The status line clears itself after this long, so the window never keeps a
// line of text sitting under the input area.
static const UINT_PTR kStatusTimer = 1;

// Client width in 96-DPI units. The height follows from the layout, which is
// fixed now: one card plus a one-line status strip.
static const int CLIENT_W = 464;

// Fixed-size, non-resizable frame: the window is sized to its content, so a
// drag handle would only be a way to make it look wrong.
static const DWORD kWindowStyle =
    (WS_OVERLAPPEDWINDOW & ~WS_THICKFRAME & ~WS_MAXIMIZEBOX);

static std::wstring g_filePath;
// Base name only -- it is the entire title bar, so no row of the window is
// spent repeating what the title already says.
static std::wstring g_fileName;
static HWND    g_hRemark = nullptr;
static HWND    g_hStatus = nullptr;
static HWND    g_hMain   = nullptr;
static HFONT   g_fBody   = nullptr;
static HFONT   g_fSmall  = nullptr;
static HFONT   g_fTiny   = nullptr;
static HICON   g_hIconBig = nullptr;
static HICON   g_hIconSmall = nullptr;
static HICON   g_hIconPaint = nullptr;
static HBRUSH  g_brPage  = nullptr;
static HBRUSH  g_brCard  = nullptr;
static WNDPROC g_oldEditProc = nullptr;
static int     g_dpi = 96;

static int S(int v) { return MulDiv(v, g_dpi, 96); }

// The text currently stored for this file. Used to tell "the user actually
// edited something" from "the window just lost focus", so an idle window that
// merely gets deactivated does not rewrite the file (and does not flash a
// misleading "saved" message).
static std::wstring g_savedText;

// Set while Esc is closing the window: WM_CLOSE then closes without writing
// anything, so "Esc 取消" really means discard rather than "cancel, but save".
static bool g_fDiscard = false;

// True while a focus loss is already being handled. Destroying the window, or
// the status update that the save itself triggers, can produce another
// WM_ACTIVATE(WA_INACTIVE); it must not start a second save in that case.
static bool g_fBlurClosing = false;

// Placeholder shown inside an empty remark box. It is painted, never stored, so
// it can never be mistaken for content or saved by accident.
static const WCHAR SZ_PLACEHOLDER[] = L"在这输入备注...";

// Layout in scaled pixels, filled by ComputeLayout() before the window exists
// so the window can be created at its final size in one go.
static RECT g_rcRemarkCard;
static RECT g_rcRemarkEdit;
static RECT g_rcStatus;
static int  g_clientH = 0;

static void CreateFonts()
{
    if (g_fBody) return;
    g_fBody  = fr::theme::Font(S(14), FW_NORMAL);
    g_fSmall = fr::theme::Font(S(11), FW_NORMAL);
    g_fTiny  = fr::theme::Font(S(10), FW_NORMAL);
}

// The remark surface fills most of the window: a 464x238 client cannot offer a
// second row of chrome without taking space away from the text. Below it sits a
// single footer line that carries the version number on the right and a save
// failure on the left -- nothing else. The box is inset 16 from the card on all
// four sides, so the text never touches the 1px outline.
static void ComputeLayout()
{
    const int left    = S(12);
    const int right   = S(CLIENT_W - 12);
    const int cardTop = S(12);
    const int cardH   = S(188);

    g_rcRemarkCard = { left, cardTop, right, cardTop + cardH };
    g_rcRemarkEdit = { left + S(16), cardTop + S(16),
                       right - S(16), cardTop + cardH - S(16) };

    // Footer band: 4px under the card, 4px above the bottom edge. Version 1.22
    // and a failure message share one baseline so neither moves when the other
    // appears.
    g_rcStatus = { left + S(4), g_rcRemarkCard.bottom + S(4),
                   right - S(4), g_rcRemarkCard.bottom + S(34) };
    g_clientH = S(238);
}

// Two independent things decide how a message looks:
//   * `sticky` -- it stays until replaced (anything the user must be able to
//     re-read), instead of fading out after a couple of seconds;
//   * `error`  -- it is painted in the error colour. Only a failed WRITE is an
//     error; the informational warnings loaded with the file ("the column will
//     not show this remark") stay neutral so red keeps meaning "something
//     failed right now".
static bool g_statusError = false;

static void SetStatus(const std::wstring& msg, bool sticky = false,
                      bool error = false)
{
    if (!g_hStatus) return;
    g_statusError = error;
    SetWindowTextW(g_hStatus, msg.c_str());
    // The text is painted by the parent, so repaint that strip.
    RECT r = g_rcStatus;
    InvalidateRect(GetParent(g_hStatus), &r, FALSE);
    if (!g_hMain) return;
    KillTimer(g_hMain, kStatusTimer);
    if (!msg.empty() && !sticky) SetTimer(g_hMain, kStatusTimer, 2500, nullptr);
}

static void ClearStatus()
{
    if (!g_hStatus) return;
    g_statusError = false;
    if (g_hMain) KillTimer(g_hMain, kStatusTimer);
    SetWindowTextW(g_hStatus, L"");
    RECT r = g_rcStatus;
    InvalidateRect(GetParent(g_hStatus), &r, FALSE);
}

static std::wstring GetRemarkText()
{
    if (!g_hRemark) return std::wstring();
    int len = GetWindowTextLengthW(g_hRemark);
    if (len <= 0) return std::wstring();
    std::wstring text(len + 1, 0);
    GetWindowTextW(g_hRemark, &text[0], len + 1);
    text.resize(len);
    return text;
}

// OOXML documents (.docx/.pptx/.xlsx). Their own property handlers are the only
// thing Explorer can read a remark from, and a handler can only open a real
// package: a 0-byte "新建 ..." placeholder cannot carry metadata at all.
static bool IsOoxmlDocument(const std::wstring& path)
{
    const WCHAR* exts[] = {
        L".docx", L".docm", L".dotx", L".dotm",
        L".pptx", L".pptm", L".potx", L".potm",
        L".xlsx", L".xlsm", L".xlsb", L".xltx", L".xltm"
    };
    const WCHAR* dot = wcsrchr(path.c_str(), L'.');
    if (!dot) return false;
    for (size_t i = 0; i < ARRAYSIZE(exts); ++i)
        if (_wcsicmp(dot, exts[i]) == 0) return true;
    return false;
}

static void LoadRemark()
{
    std::wstring shown;
    std::wstring remark;
    std::wstring note;
    bool sticky = false;

    if (fr::ReadRemark(g_filePath, remark) && !remark.empty())
    {
        shown = remark;
        // For documents whose column Windows serves from the file's own metadata
        // (Office types above all) an ADS-only remark is invisible in Explorer.
        // Mirror it once so an existing remark starts showing up in the column,
        // but never overwrite a comment the document already carries.
        if (!fr::HandlerIsOurs(g_filePath))
        {
            std::wstring native;
            bool exists = false;
            // Only when a native store actually opened: types with no handler at
            // all must not produce a warning they cannot act on.
            const bool opened = fr::ReadNativeComment(g_filePath, native, exists);
            if (!opened && IsOoxmlDocument(g_filePath))
            {
                note = L"这个 Office 文件读不出文档属性（多半是 0 字节的空文档或已损坏），"
                       L"资源管理器“备注”列需要文件里存得下备注才会显示；"
                       L"用 Office 打开并保存一次后就会恢复。";
                sticky = true;
            }
            else if (opened && !exists)
            {
                if (fr::WriteNativeCommentIfNeeded(g_filePath, remark))
                    note = L"已把备注同步到文档属性，资源管理器列可以显示。";
                else
                {
                    note = L"备注已存在，但没能写入文档属性（文件可能正被 Office 占用或只读），"
                           L"资源管理器“备注”列暂时不显示。";
                    sticky = true;
                }
            }
        }
    }
    else
    {
        // Nothing in the ADS yet: show a value the file already carries natively
        // (a Word document's or photo's own comment), so it is not silently
        // hidden.
        std::wstring native;
        bool exists = false;
        const bool opened = fr::ReadNativeComment(g_filePath, native, exists);
        if (opened && exists)
            shown = native;
        else if (!opened && !fr::HandlerIsOurs(g_filePath) && IsOoxmlDocument(g_filePath))
        {
            // A 0-byte Explorer placeholder is not a package yet, so no handler
            // can store System.Comment in it -- this is the one case where the
            // column stays empty no matter what we write. Say so instead of
            // letting the user believe the remark was saved and lost.
            note = L"这个 Office 文件读不出文档属性（多半是 0 字节的空文档或已损坏），"
                   L"资源管理器“备注”列需要文件里存得下备注才会显示；"
                   L"用 Office 打开并保存一次后就会恢复。";
            sticky = true;
        }
    }
    SetWindowTextW(g_hRemark, shown.c_str());
    g_savedText = shown;
    ClearStatus();
    if (!note.empty()) SetStatus(note, sticky);
}

// Ask Explorer to re-read this one item so the 备注 column shows the new value
// immediately instead of waiting for its own cache to expire. SHCNE_UPDATEITEM
// targets exactly this file; the directory notification is the belt-and-braces
// fallback for views that only listen for folder-level changes. Failures are
// cosmetic, so nothing is reported to the user.
static void NotifyShell()
{
    if (g_filePath.empty()) return;
    // SHCNF_FLUSH matters: without it the shell only queues the notification and
    // delivers it on its own schedule, which is exactly the "the change shows up
    // a moment later" symptom. Flushing makes Explorer re-read the item before
    // this call returns.
    const UINT flags = SHCNF_PATHW | SHCNF_FLUSH;
    SHChangeNotify(SHCNE_UPDATEITEM, flags, g_filePath.c_str(), nullptr);

    std::wstring dir = g_filePath;
    const size_t slash = dir.find_last_of(L"/");
    if (slash != std::wstring::npos && slash > 0)
    {
        dir.resize(slash);
        SHChangeNotify(SHCNE_UPDATEDIR, flags, dir.c_str(), nullptr);
    }
}

// Whether a window belongs to this process. A message box, a common dialog or
// any other window of ours deactivates the main window exactly like clicking
// another application does, and that must never be read as "the user left".
static bool IsOwnWindow(HWND hWnd)
{
    if (!hWnd) return false;
    DWORD pid = 0;
    GetWindowThreadProcessId(hWnd, &pid);
    return pid == GetCurrentProcessId();
}

// Writes the current text if it differs from what is already stored, and
// reports the outcome in the status line. Called on close and on deactivation.
//
// Returns true when the window may be closed afterwards: either nothing had to
// be written (the text is unchanged -- an untouched window closes silently and
// leaves the file alone) or the write fully succeeded. False means the window
// has to stay open, with the reason already shown in the status line, so the
// user can retry or keep editing instead of losing the text.
static bool SaveIfChanged()
{
    const std::wstring text = GetRemarkText();
    if (text == g_savedText)
    {
        ClearStatus();
        return true;
    }

    // Show that the work has started and force it onto the screen before the
    // write: for Office files the metadata write can take a moment, and without
    // this the window would look frozen for that whole time (and, if the user
    // just closed it, the save would appear to have happened "late").
    SetStatus(L"正在保存…");
    UpdateWindow(GetParent(g_hStatus));

    bool ok = fr::WriteRemark(g_filePath, text);
    // For types we do not own a handler for (Office documents above all) the
    // column can only come from the file's own metadata. That write can fail --
    // the file may be open in Word, or read-only -- and reporting "已自动保存"
    // then would be exactly the "看不出到底成没成功" problem this release is
    // about, because the 备注 column stays empty.
    const bool owned = fr::HandlerIsOurs(g_filePath);
    const bool nativeOk = fr::WriteNativeCommentIfNeeded(g_filePath, text);

    if (ok)
    {
        // Push the change to Explorer right away; without this the column can
        // keep showing the old text until the view is refreshed by hand.
        NotifyShell();
        if (!owned && !nativeOk)
        {
            // The remark is stored in the ADS but the file itself still does not
            // carry it, so the column cannot show it yet: that counts as a failed
            // save and the window stays open, exactly like a hard failure. The
            // saved text is not updated either, so retrying really retries.
            SetStatus(L"已保存到文件；但文档属性写入失败（文件可能正被 Office 占用或只读），"
                      L"资源管理器“备注”列暂时不会显示。", true, true);
            return false;
        }
        g_savedText = text;
        // Success is deliberately silent: the window closes on the same action,
        // so a "已自动保存" line would flash for one frame and never be read.
        ClearStatus();
        return true;
    }

    SetStatus(L"保存失败（文件可能只读或不可写）。", true, true);
    return false;
}

// The remark box draws the cue text itself when it is empty: the control paints
// its own white background first, so the cue is covered by the very first
// character the user types, and it is never part of the saved value.
static void PaintPlaceholder(HWND hWnd)
{
    if (GetWindowTextLengthW(hWnd) != 0) return;

    HDC hdc = GetDC(hWnd);
    if (!hdc) return;

    RECT fr;
    SendMessageW(hWnd, EM_GETRECT, 0, (LPARAM)&fr);

    HGDIOBJ oldFont = SelectObject(hdc, g_fBody);
    const int oldBk = SetBkMode(hdc, TRANSPARENT);
    const COLORREF oldColor = SetTextColor(hdc, fr::theme::Colors().muted);
    DrawTextW(hdc, SZ_PLACEHOLDER, -1, &fr, DT_LEFT | DT_TOP | DT_NOPREFIX);
    SetTextColor(hdc, oldColor);
    SetBkMode(hdc, oldBk);
    SelectObject(hdc, oldFont);
    ReleaseDC(hWnd, hdc);
}

// Whether the cue is currently on screen. The cue spans the whole first line,
// but an EDIT control only invalidates the small rectangle around the character
// it just inserted -- so after the first keystroke the rest of the cue would
// stay on screen and the hint would appear to sit *on top of* the typed text.
// Whenever the box crosses the empty/non-empty boundary the whole control has to
// be repainted, which is what this does.
static bool g_cueShown = true;

static void SyncPlaceholder(HWND hWnd)
{
    const bool empty = GetWindowTextLengthW(hWnd) == 0;
    if (empty == g_cueShown) return;
    g_cueShown = empty;
    InvalidateRect(hWnd, nullptr, TRUE);
}

// Ctrl+A / Ctrl+Backspace are handled from two places: the WM_KEYDOWN branch
// (a real keyboard delivers the modifier through GetAsyncKeyState) and the
// WM_CHAR branch (TranslateMessage turns Ctrl+A into character 1 and
// Ctrl+Backspace into 127, which is what a control actually receives). Doing
// both means the shortcut works no matter which of the two messages a given
// input path produces, and it makes the behaviour verifiable by sending the
// character message directly.
static void SelectAllText(HWND hWnd)
{
    // -1 as the end offset means "the end of the text", so a multi-line remark
    // is selected as a whole too.
    SendMessageW(hWnd, EM_SETSEL, 0, (LPARAM)-1);
}

static void DeleteWordBeforeCaret(HWND hWnd)
{
    DWORD selStart = 0, selEnd = 0;
    SendMessageW(hWnd, EM_GETSEL, (WPARAM)&selStart, (LPARAM)&selEnd);
    if (selStart != selEnd)
    {
        // There is a selection: Ctrl+Backspace removes exactly that, like the
        // plain Backspace key would.
        SendMessageW(hWnd, WM_CLEAR, 0, 0);
        SyncPlaceholder(hWnd);
        return;
    }
    const int len = GetWindowTextLengthW(hWnd);
    if (len == 0) return;
    std::wstring all;
    all.resize(len + 1);
    GetWindowTextW(hWnd, &all[0], len + 1);
    all.resize(len);
    size_t cut = selStart;
    while (cut > 0 && iswspace(all[cut - 1])) --cut;
    while (cut > 0 && !iswspace(all[cut - 1])) --cut;
    SendMessageW(hWnd, EM_SETSEL, cut, selStart);
    SendMessageW(hWnd, WM_CLEAR, 0, 0);
    SendMessageW(hWnd, EM_SETSEL, cut, cut);
    SyncPlaceholder(hWnd);
}

// The remark box swallows keys, so the shortcuts it needs are handled here:
// Esc / Ctrl+Enter close the window, and Ctrl+A / Ctrl+Backspace edit the text.
//
// Ctrl+A is not free: a plain EDIT control has never implemented it (Notepad's
// "全选" comes from its own accelerator table, not from the control), so
// without this branch the key does nothing at all and there is no way to select
// the whole remark in order to replace or delete it.
//
// Ctrl is read with GetAsyncKeyState, not GetKeyState: the asynchronous state is
// global, so the modifier is still seen when the key messages were not delivered
// to a focused window (and it keeps the shortcut testable when the window cannot
// take the foreground, e.g. under automation).
//
// Focus changes only repaint the accent ring around the card; the closing
// decision is made by the main window (WM_ACTIVATE for a real focus loss,
// WM_CLOSE for Esc / Ctrl+Enter / the X button).
static LRESULT CALLBACK RemarkEditProc(HWND hWnd, UINT msg, WPARAM wParam, LPARAM lParam)
{
    switch (msg)
    {
    case WM_KEYDOWN:
        if (wParam == VK_ESCAPE)
        {
            // Esc is 取消: close without saving anything, even if the text was
            // edited. WM_CLOSE honours the flag instead of saving.
            g_fDiscard = true;
            PostMessageW(GetParent(hWnd), WM_CLOSE, 0, 0);
            return 0;
        }
        if (wParam == VK_RETURN && (GetAsyncKeyState(VK_CONTROL) & 0x8000))
        {
            // Ctrl+Enter is 保存: same path as blurring out of the window, so a
            // failed save keeps the window open here too.
            PostMessageW(GetParent(hWnd), WM_CLOSE, 0, 0);
            return 0;
        }
        // Ctrl+A: select the whole remark.
        if (wParam == 'A' && (GetAsyncKeyState(VK_CONTROL) & 0x8000))
        {
            SelectAllText(hWnd);
            return 0;
        }
        // Ctrl+Backspace: delete the word before the caret, which is the other
        // shortcut people reach for when clearing a remark.
        if (wParam == VK_BACK && (GetAsyncKeyState(VK_CONTROL) & 0x8000))
        {
            DeleteWordBeforeCaret(hWnd);
            return 0;
        }
        // Any other key can still change the text (Delete, Backspace, arrows
        // over a selection), so run the same cue refresh as below.
        {
            const LRESULT r = CallWindowProcW(g_oldEditProc, hWnd, msg, wParam, lParam);
            SyncPlaceholder(hWnd);
            return r;
        }

    case WM_PAINT:
    {
        // Let the control paint normally, then lay the cue text on top of the
        // freshly painted background.
        const LRESULT r = CallWindowProcW(g_oldEditProc, hWnd, msg, wParam, lParam);
        PaintPlaceholder(hWnd);
        return r;
    }

    // Every way the text can change, so the cue is dropped the moment the box
    // stops being empty (and comes back when it is emptied again).
    case WM_CHAR:
        // TranslateMessage delivers Ctrl+A as character 1 and Ctrl+Backspace as
        // character 127. Handle them here as well as in WM_KEYDOWN, so the
        // shortcut does not depend on which message an input path produces.
        if (wParam == 1)
        {
            SelectAllText(hWnd);
            return 0;
        }
        if (wParam == 127)
        {
            DeleteWordBeforeCaret(hWnd);
            return 0;
        }
        [[fallthrough]];
    case WM_PASTE:
    case WM_CUT:
    case WM_CLEAR:
    case WM_UNDO:
    case WM_SETTEXT:
    {
        const LRESULT r = CallWindowProcW(g_oldEditProc, hWnd, msg, wParam, lParam);
        SyncPlaceholder(hWnd);
        return r;
    }

    case WM_SETFOCUS:
    case WM_KILLFOCUS:
        // Nothing on the page reacts to focus any more: the caret is the only
        // focus signal, and the control paints its own.
        break;
    }
    return CallWindowProcW(g_oldEditProc, hWnd, msg, wParam, lParam);
}

static void CreateChildren(HWND hWnd)
{
    // The remark box is the only control. No WS_VSCROLL on purpose: the box is
    // tall enough for a normal remark, and a scrollbar would eat width for the
    // rare long one. ES_AUTOVSCROLL is what lets the control scroll its own
    // contents so the caret stays visible while typing past the bottom edge;
    // without it a long remark cannot be reached at all.
    g_hRemark = CreateWindowExW(0, L"EDIT", L"",
        WS_CHILD | WS_VISIBLE | WS_TABSTOP | ES_MULTILINE |
        ES_AUTOVSCROLL | ES_WANTRETURN | ES_NOHIDESEL,
        g_rcRemarkEdit.left, g_rcRemarkEdit.top,
        g_rcRemarkEdit.right - g_rcRemarkEdit.left,
        g_rcRemarkEdit.bottom - g_rcRemarkEdit.top,
        hWnd, (HMENU)IDC_REMARK, nullptr, nullptr);

    // Status: the control holds the string, the parent paints it. It is not
    // WS_VISIBLE on purpose (see PaintAll), but GetWindowTextW still works, so
    // SetStatus stays the single source of truth.
    g_hStatus = CreateWindowExW(0, L"STATIC", L"",
        WS_CHILD, g_rcStatus.left, g_rcStatus.top,
        g_rcStatus.right - g_rcStatus.left, g_rcStatus.bottom - g_rcStatus.top,
        hWnd, (HMENU)IDC_STATUS, nullptr, nullptr);

    if (g_hRemark) SendMessageW(g_hRemark, WM_SETFONT, (WPARAM)g_fBody, TRUE);
    if (g_hStatus) SendMessageW(g_hStatus, WM_SETFONT, (WPARAM)g_fSmall, TRUE);

    if (g_hRemark)
    {
        g_oldEditProc = (WNDPROC)SetWindowLongPtrW(g_hRemark, GWLP_WNDPROC,
            (LONG_PTR)RemarkEditProc);
        SetFocus(g_hRemark);
    }
}

static void ApplyIcon(HWND hWnd)
{
    // Only the two title-bar sizes: the window no longer paints a logo itself.
    g_hIconBig = fr::logo::CreateLogoIcon(S(32));
    g_hIconSmall = fr::logo::CreateLogoIcon(S(16));
    if (g_hIconBig)   SendMessageW(hWnd, WM_SETICON, ICON_BIG, (LPARAM)g_hIconBig);
    if (g_hIconSmall) SendMessageW(hWnd, WM_SETICON, ICON_SMALL, (LPARAM)g_hIconSmall);
}

// --- painting --------------------------------------------------------------
// One surface, one hairline, no focus ring. The outline is 1px at every state:
// the design keeps a single emphasis (the caret) instead of stacking a border
// colour change on top of it.
static void DrawCard(HDC hdc, const RECT& r)
{
    fr::theme::RoundedRect(hdc, r, S(8), fr::theme::Colors().card,
        fr::theme::Colors().border, 1);
}

static void PaintAll(HWND hWnd, HDC hdc)
{
    RECT client;
    GetClientRect(hWnd, &client);

    FillRect(hdc, &client, g_brPage);
    SetBkMode(hdc, TRANSPARENT);

    DrawCard(hdc, g_rcRemarkCard);

    // Footer: a failure on the left, the version on the right, both on the same
    // baseline. Success is silent, so this row is normally just the version --
    // and a failure never moves it.
    const int baseline = g_rcStatus.top + S(18);

    WCHAR status[512] = { 0 };
    if (g_hStatus) GetWindowTextW(g_hStatus, status, 511);
    if (status[0])
        fr::theme::TextBaseline(hdc, g_fSmall,
            g_statusError ? fr::theme::Colors().error : fr::theme::Colors().muted,
            g_rcStatus.left, g_rcStatus.right - S(56), baseline, status,
            DT_LEFT | DT_END_ELLIPSIS);

    fr::theme::TextBaseline(hdc, g_fTiny, fr::theme::Colors().tertiary,
        g_rcStatus.left, g_rcStatus.right, baseline,
        L"v" FR_VERSION_TEXT, DT_RIGHT);
}

static LRESULT CALLBACK WndProc(HWND hWnd, UINT msg, WPARAM wParam, LPARAM lParam)
{
    switch (msg)
    {
    case WM_CREATE:
        g_dpi = fr::theme::DpiOf(hWnd);
        // Re-measure for this window's real DPI: the layout was computed before
        // the window existed, using the screen DPI, which can differ per monitor.
        CreateFonts();
        ComputeLayout();
        fr::theme::SetDark(fr::theme::DetectSystemDark());
        g_brPage = CreateSolidBrush(fr::theme::Colors().page);
        g_brCard = CreateSolidBrush(fr::theme::Colors().card);
        g_hMain = hWnd;
        ApplyIcon(hWnd);
        fr::theme::RoundWindow(hWnd);
        fr::theme::ApplyTitleBarTheme(hWnd);
        CreateChildren(hWnd);
        // The title bar carries the file name and nothing else. A native caption
        // left-aligns whatever it is given, which is exactly the layout asked
        // for, and it truncates an over-long name with an ellipsis by itself.
        SetWindowTextW(hWnd, g_fileName.c_str());
        LoadRemark();
        return 0;

    case WM_TIMER:
        if (wParam == kStatusTimer)
        {
            KillTimer(hWnd, kStatusTimer);
            ClearStatus();
        }
        return 0;

    case WM_SETTINGCHANGE:
        // Windows broadcasts this when Settings > Personalization > Colors
        // changes. Re-read the app mode and repaint only when it really flipped.
        if (wParam == 0 && lParam &&
            wcscmp((LPCWSTR)lParam, L"ImmersiveColorSet") == 0)
        {
            const bool wasDark = fr::theme::IsDark();
            fr::theme::SetDark(fr::theme::DetectSystemDark());
            if (fr::theme::IsDark() != wasDark)
            {
                fr::theme::ApplyTitleBarTheme(hWnd);
                if (g_brPage) DeleteObject(g_brPage);
                if (g_brCard) DeleteObject(g_brCard);
                g_brPage = CreateSolidBrush(fr::theme::Colors().page);
                g_brCard = CreateSolidBrush(fr::theme::Colors().card);
                InvalidateRect(hWnd, nullptr, FALSE);
                if (g_hRemark) InvalidateRect(g_hRemark, nullptr, TRUE);
            }
        }
        return 0;

    case WM_PAINT:
    {
        PAINTSTRUCT ps;
        HDC hdc = BeginPaint(hWnd, &ps);
        RECT client;
        GetClientRect(hWnd, &client);
        HDC mem = CreateCompatibleDC(hdc);
        HBITMAP bmp = CreateCompatibleBitmap(hdc, client.right, client.bottom);
        HGDIOBJ oldBmp = SelectObject(mem, bmp);
        PaintAll(hWnd, mem);
        BitBlt(hdc, 0, 0, client.right, client.bottom, mem, 0, 0, SRCCOPY);
        SelectObject(mem, oldBmp);
        DeleteObject(bmp);
        DeleteDC(mem);
        EndPaint(hWnd, &ps);
        return 0;
    }

    case WM_ERASEBKGND:
        // Fully painted in WM_PAINT; erasing here would only flicker.
        return 1;

    case WM_ACTIVATE:
        // Focus left this window (another app was clicked, Alt+Tab, ...).
        // Save and, if the save went through, close: leaving the window is the
        // user's way of saying "I'm done". A failed save keeps the window open
        // with the reason in the status line, so nothing is silently lost.
        if (LOWORD(wParam) == WA_INACTIVE)
        {
            if (g_fBlurClosing) return 0;
            // Our own windows (a message box, a file dialog, a child window) also
            // deactivate us, and that is not the user leaving.
            if (IsOwnWindow(GetForegroundWindow())) return 0;
            g_fBlurClosing = true;
            if (SaveIfChanged())
                DestroyWindow(hWnd);
            else
                g_fBlurClosing = false;   // still here: let a later blur retry
            return 0;
        }
        // Back in the foreground (the save failed, or the user returned): the
        // next focus loss is a fresh decision and must be handled again.
        if (LOWORD(wParam) == WA_ACTIVE) g_fBlurClosing = false;
        return 0;

    case WM_CLOSE:
    {
        // Esc = 取消: discard whatever was typed and close without touching the
        // file. Everything else (the X button, Ctrl+Enter) saves first, and a
        // failed save keeps the window open so its message can be read.
        if (g_fDiscard)
        {
            DestroyWindow(hWnd);
            return 0;
        }
        if (!SaveIfChanged()) return 0;
        DestroyWindow(hWnd);
        return 0;
    }

    case WM_CTLCOLOREDIT:
    case WM_CTLCOLORSTATIC:
    {
        HDC hdc = (HDC)wParam;
        HWND child = (HWND)lParam;
        if (child == g_hStatus)
        {
            SetBkMode(hdc, TRANSPARENT);
            SetTextColor(hdc, g_statusError ? fr::theme::Colors().error
                                            : fr::theme::Colors().muted);
            return (LRESULT)g_brPage;
        }
        //
        // The background mode MUST stay OPAQUE here. A multiline EDIT erases the
        // area it repaints by drawing text with this DC, so with TRANSPARENT the
        // background is never filled: delete part of the text and the removed
        // characters keep their pixels on screen while being gone from the value
        // -- they can no longer be selected, but they are still visible.
        SetBkMode(hdc, OPAQUE);
        SetBkColor(hdc, fr::theme::Colors().card);
        SetTextColor(hdc, fr::theme::Colors().text);
        return (LRESULT)g_brCard;
    }

    case WM_DESTROY:
        if (g_fBody)  DeleteObject(g_fBody);
        if (g_fSmall) DeleteObject(g_fSmall);
        if (g_fTiny)  DeleteObject(g_fTiny);
        g_fBody = g_fSmall = g_fTiny = nullptr;
        if (g_brPage) DeleteObject(g_brPage);
        if (g_brCard) DeleteObject(g_brCard);
        g_brPage = g_brCard = nullptr;
        if (g_hIconBig)   DestroyIcon(g_hIconBig);
        if (g_hIconSmall) DestroyIcon(g_hIconSmall);
        if (g_hIconPaint) DestroyIcon(g_hIconPaint);
        g_hIconBig = g_hIconSmall = g_hIconPaint = nullptr;
        g_hMain = nullptr;
        PostQuitMessage(0);
        return 0;
    }
    return DefWindowProcW(hWnd, msg, wParam, lParam);
}

int WINAPI WinMain(HINSTANCE hInst, HINSTANCE, LPSTR, int)
{
    // Parse the first argument from the Unicode command line (works under
    // both MinGW and MSVC without relying on __wargv).
    LPWSTR cmdLine = GetCommandLineW();
    int argc = 0;
    LPWSTR* argv = CommandLineToArgvW(cmdLine, &argc);
    if (!argv || argc < 2)
    {
        if (argv) LocalFree(argv);
        MessageBoxW(nullptr, L"用法：FileRemarksEditor.exe \"文件完整路径\"",
            L"备注", MB_OK | MB_ICONINFORMATION);
        return 1;
    }
    g_filePath = std::wstring(argv[1]);
    LocalFree(argv);

    // The title bar shows the file name only. Everything up to the last
    // separator is dropped: the full path is still what the remark is stored
    // against, it just is not worth a line of screen space.
    g_fileName = g_filePath;
    const size_t sep = g_fileName.find_last_of(L"\\/");
    if (sep != std::wstring::npos && sep + 1 < g_fileName.size())
        g_fileName = g_fileName.substr(sep + 1);

    // Needed by the property-system calls in native_comment.h.
    CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED);

    INITCOMMONCONTROLSEX icc = { sizeof(icc), ICC_STANDARD_CLASSES };
    InitCommonControlsEx(&icc);

    WNDCLASSEXW wc = { sizeof(wc) };
    wc.lpfnWndProc = WndProc;
    wc.hInstance = hInst;
    wc.hCursor = LoadCursorW(nullptr, IDC_ARROW);
    wc.lpszClassName = L"FileRemarksEditorWnd";
    wc.hbrBackground = nullptr;  // painted in WM_PAINT
    wc.style = CS_HREDRAW | CS_VREDRAW;
    RegisterClassExW(&wc);

    // Measure the layout BEFORE the window exists, so the window can be created
    // at the exact size the wrapped file path needs -- no clipped path, and no
    // leftover band of empty page at the bottom.
    g_dpi = fr::theme::DpiOfScreen();
    CreateFonts();
    ComputeLayout();

    RECT want = { 0, 0, S(CLIENT_W), g_clientH };
    AdjustWindowRectEx(&want, kWindowStyle, FALSE, WS_EX_DLGMODALFRAME);

    HWND hWnd = CreateWindowExW(WS_EX_DLGMODALFRAME, wc.lpszClassName,
        g_fileName.c_str(),
        kWindowStyle | WS_CLIPCHILDREN,
        CW_USEDEFAULT, CW_USEDEFAULT, want.right - want.left, want.bottom - want.top,
        nullptr, nullptr, hInst, nullptr);
    if (!hWnd) return 1;
    ShowWindow(hWnd, SW_SHOW);
    UpdateWindow(hWnd);

    MSG msg;
    while (GetMessageW(&msg, nullptr, 0, 0))
    {
        TranslateMessage(&msg);
        DispatchMessageW(&msg);
    }
    CoUninitialize();
    return 0;
}
