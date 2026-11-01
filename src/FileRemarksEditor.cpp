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
// There are deliberately NO buttons: the remark is saved automatically when the
// window is closed or when it loses the foreground, so editing is just "type,
// then click away". Losing focus NEVER closes the window -- it only saves, and
// the window stays open exactly where it is. Clearing a remark is simply
// deleting its text. Esc closes the window, Ctrl+Enter does the same (both save
// first); plain Enter inserts a newline.
//
// The look follows Windows 11 -- light page, one rounded white box, Segoe UI,
// accent-coloured focus ring and rounded window corners -- and is painted by
// hand with plain GDI (see src/theme.h), so there is no .rc file and no resource
// compiler in the build.
//
// The window is deliberately reduced to three things: the logo, the file's path
// (directly beside the logo, with no "文件" label), and the remark box. An empty
// remark box shows the cue text "在这输入备注..." which disappears the moment
// anything is typed.
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

#pragma comment(linker, "\"/MANIFESTDEPENDENCY:type='win32' \
name='Microsoft.Windows.Common-Controls' version='6.0.0.0' \
processorArchitecture='*' publicKeyToken='6595b64144ccf1df' language='*'\"")

// Control IDs.
enum {
    IDC_FILENAME = 101,
    IDC_REMARK   = 102,
    IDC_STATUS   = 103,
};

// Client width in 96-DPI units; the height is measured from the wrapped file
// path so a long path is always shown in full instead of being clipped.
static const int CLIENT_W = 464;

// Fixed-size, non-resizable frame: the window is sized to its content, so a
// drag handle would only be a way to make it look wrong.
static const DWORD kWindowStyle =
    (WS_OVERLAPPEDWINDOW & ~WS_THICKFRAME & ~WS_MAXIMIZEBOX);

static std::wstring g_filePath;
static HWND    g_hRemark = nullptr;
static HWND    g_hStatus = nullptr;
static HWND    g_hFile   = nullptr;
static HFONT   g_fBody   = nullptr;
static HFONT   g_fSmall  = nullptr;
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

static const WCHAR SZ_HINT[] =
    L"直接输入备注，关闭窗口或切到别的窗口时会自动保存。";

// Placeholder shown inside an empty remark box. It is painted, never stored, so
// it can never be mistaken for content or saved by accident.
static const WCHAR SZ_PLACEHOLDER[] = L"在这输入备注...";

// Measured layout, in scaled pixels, filled by ComputeLayout() before the
// window exists so the window can be sized to fit the whole file path.
static RECT g_rcIcon;
static RECT g_rcPath;
static RECT g_rcHeaderCard;
static RECT g_rcRemarkCard;
static RECT g_rcRemarkEdit;
static RECT g_rcStatus;
static int  g_clientH = 0;

// Slack added to the path box after the real EDIT control reported that it still
// could not show every wrapped line. The pre-window estimate below is only an
// estimate: an edit control keeps a small internal margin, so the box that
// "should" fit exactly one line more can come up a few pixels short. Once the
// control exists we ask IT how many lines it has and how much room it has, and
// grow the box by exactly the shortfall (see FitPathControl) -- that is what
// guarantees the file name is never clipped.
static int  g_pathPad = 0;

static void CreateFonts()
{
    if (g_fBody) return;
    g_fBody  = fr::theme::Font(S(15), FW_NORMAL);
    g_fSmall = fr::theme::Font(S(12), FW_NORMAL);
}

// Line height of a font, exactly as the control will lay the text out.
static int LineHeightPx(HDC hdc, HFONT font)
{
    HGDIOBJ oldFont = SelectObject(hdc, font);
    TEXTMETRICW tm = { 0 };
    GetTextMetricsW(hdc, &tm);
    SelectObject(hdc, oldFont);
    return tm.tmHeight > 0 ? tm.tmHeight : S(16);
}

// How many lines a multiline EDIT will use for `text` at `width` pixels.
//
// Counted by CHARACTER, because that is exactly what an edit control does.
// DrawTextW with DT_WORDBREAK only breaks at spaces, and a file path contains
// none -- it would report far fewer lines than the control really needs, and the
// last lines got clipped (the bug this measurement replaces).
static int CountLines(HDC hdc, HFONT font, const std::wstring& text, int width)
{
    if (width <= S(8) || text.empty()) return 1;

    HGDIOBJ oldFont = SelectObject(hdc, font);
    int lines = 1;
    size_t pos = 0;
    while (pos < text.size() && lines < 64)
    {
        int fit = 0;
        SIZE extent = { 0, 0 };
        if (!GetTextExtentExPointW(hdc, text.c_str() + pos,
                                   (int)(text.size() - pos), width,
                                   &fit, nullptr, &extent))
            break;
        if (fit <= 0) break;
        pos += (size_t)fit;
        if (pos < text.size()) ++lines;
    }
    SelectObject(hdc, oldFont);
    return lines;
}

// Two things only, top to bottom: a card holding the logo with the file path
// immediately to its right (no "文件" label), and the remark box (no "备注"
// label). The path is measured line by line so it is never clipped, and the
// window is sized to whatever that works out to.
static void ComputeLayout()
{
    const int left  = S(16);
    const int right = S(CLIENT_W - 16);
    const int padIn = S(14);

    HDC hdc = GetDC(nullptr);
    const int lineH = hdc ? LineHeightPx(hdc, g_fSmall) : S(16);

    // Header card: logo, then the path right beside it.
    const int cardTop  = S(12);
    const int iconSize = S(24);
    const int iconTop  = cardTop + S(12);
    g_rcIcon = { left + padIn, iconTop, left + padIn + iconSize, iconTop + iconSize };

    const int pathLeft  = g_rcIcon.right + S(10);
    const int pathRight = right - padIn;
    // The edit insets its own text by a couple of pixels, so measure against a
    // slightly narrower box: over-counting one line is harmless, under-counting
    // clips the text.
    const int lines = hdc ? CountLines(hdc, g_fSmall, g_filePath,
                                       (pathRight - pathLeft) - S(6)) : 1;
    const int pathH = lines * lineH + S(4) + g_pathPad;

    // One line of text sits centred against the logo; a long path starts level
    // with it and simply makes the card taller.
    int pathTop = iconTop + (iconSize - pathH) / 2;
    if (pathTop < iconTop) pathTop = iconTop;

    g_rcPath = { pathLeft, pathTop, pathRight, pathTop + pathH };

    const int contentBottom = pathTop + pathH > iconTop + iconSize
                            ? pathTop + pathH : iconTop + iconSize;
    g_rcHeaderCard = { left, cardTop, right, contentBottom + S(12) };

    if (hdc) ReleaseDC(nullptr, hdc);

    // Remark card: one box, no label on top of it -- the placeholder inside says
    // what it is, so a whole row of text is saved.
    const int remarkTop = g_rcHeaderCard.bottom + S(10);
    const int remarkH   = S(168);
    g_rcRemarkCard = { left, remarkTop, right, remarkTop + remarkH };
    g_rcRemarkEdit = { left + S(12), remarkTop + S(10),
                       right - S(12), remarkTop + remarkH - S(10) };

    g_rcStatus = { left, g_rcRemarkCard.bottom + S(8), right,
                   g_rcRemarkCard.bottom + S(8) + S(18) };
    g_clientH = g_rcStatus.bottom + S(10);
}

static void SetStatus(const std::wstring& msg)
{
    if (!g_hStatus) return;
    SetWindowTextW(g_hStatus, msg.c_str());
    // The text is painted by the parent, so repaint that strip.
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

static void LoadRemark()
{
    std::wstring shown;
    std::wstring remark;
    if (fr::ReadRemark(g_filePath, remark) && !remark.empty())
    {
        shown = remark;
    }
    else
    {
        // Nothing in the ADS yet: show a value the file already carries natively
        // (a Word document's or photo's own comment), so it is not silently
        // hidden.
        std::wstring native;
        bool exists = false;
        if (fr::ReadNativeComment(g_filePath, native, exists) && exists)
            shown = native;
    }
    SetWindowTextW(g_hRemark, shown.c_str());
    g_savedText = shown;
    SetStatus(SZ_HINT);
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

// Writes the current text if it differs from what is already stored, and
// reports the outcome in the status line. Called on close and on deactivation.
static void SaveIfChanged()
{
    const std::wstring text = GetRemarkText();
    if (text == g_savedText)
    {
        SetStatus(SZ_HINT);
        return;
    }

    // Show that the work has started and force it onto the screen before the
    // write: for Office files the metadata write can take a moment, and without
    // this the window would look frozen for that whole time (and, if the user
    // just closed it, the save would appear to have happened "late").
    SetStatus(L"正在保存…");
    UpdateWindow(GetParent(g_hStatus));

    bool ok = fr::WriteRemark(g_filePath, text);
    // For types we do not own a handler for (Office documents above all) the
    // column can only come from the file's own metadata. Best effort: a refusal
    // here is normal and must not look like an error.
    fr::WriteNativeCommentIfNeeded(g_filePath, text);

    if (ok)
    {
        g_savedText = text;
        // Push the change to Explorer right away; without this the column can
        // keep showing the old text until the view is refreshed by hand.
        NotifyShell();
        SetStatus(text.empty() ? L"备注已清空（自动保存）。" : L"已自动保存。");
    }
    else
    {
        SetStatus(L"保存失败（文件可能只读或不可写）。");
    }
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
    const COLORREF oldColor = SetTextColor(hdc, fr::theme::kMuted);
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
// Focus changes only repaint the accent ring around the card -- they never
// close anything (the save itself happens in WM_ACTIVATE below).
static LRESULT CALLBACK RemarkEditProc(HWND hWnd, UINT msg, WPARAM wParam, LPARAM lParam)
{
    switch (msg)
    {
    case WM_KEYDOWN:
        if (wParam == VK_ESCAPE)
        {
            PostMessageW(GetParent(hWnd), WM_CLOSE, 0, 0);
            return 0;
        }
        if (wParam == VK_RETURN && (GetAsyncKeyState(VK_CONTROL) & 0x8000))
        {
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
        InvalidateRect(GetParent(hWnd), nullptr, FALSE);
        break;
    }
    return CallWindowProcW(g_oldEditProc, hWnd, msg, wParam, lParam);
}

static void CreateChildren(HWND hWnd)
{
    // File path: a borderless read-only multiline edit right beside the logo.
    // Multiline + read-only makes the control wrap the text itself, character by
    // character, so even a very long path is shown in full instead of clipped.
    g_hFile = CreateWindowExW(0, L"EDIT", g_filePath.c_str(),
        WS_CHILD | WS_VISIBLE | ES_READONLY | ES_MULTILINE | ES_NOHIDESEL,
        g_rcPath.left, g_rcPath.top,
        g_rcPath.right - g_rcPath.left, g_rcPath.bottom - g_rcPath.top,
        hWnd, (HMENU)IDC_FILENAME, nullptr, nullptr);

    // Remark: borderless multiline box filling the card. When it is empty the
    // control paints the cue text itself (see PaintPlaceholder).
    g_hRemark = CreateWindowExW(0, L"EDIT", L"",
        WS_CHILD | WS_VISIBLE | WS_VSCROLL | WS_TABSTOP | ES_MULTILINE |
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

    if (g_hFile)   SendMessageW(g_hFile, WM_SETFONT, (WPARAM)g_fSmall, TRUE);
    if (g_hRemark) SendMessageW(g_hRemark, WM_SETFONT, (WPARAM)g_fBody, TRUE);
    if (g_hStatus) SendMessageW(g_hStatus, WM_SETFONT, (WPARAM)g_fSmall, TRUE);

    if (g_hRemark)
    {
        g_oldEditProc = (WNDPROC)SetWindowLongPtrW(g_hRemark, GWLP_WNDPROC,
            (LONG_PTR)RemarkEditProc);
        SetFocus(g_hRemark);
    }
}

// Ask the real path control how many lines it actually has vs how many it can
// display, and grow it by the shortfall.
//
// ComputeLayout() has to measure BEFORE the window exists (the frame is sized to
// the content), so it can only estimate: it counts characters per line with the
// same font, but an EDIT control adds its own internal margin and rounds the
// line count differently. Measuring the estimate against the real control and
// correcting it is the only way to promise that the file name is never clipped,
// for any path length and any DPI.
static bool FitPathControl(HWND hWnd)
{
    if (!g_hFile) return false;

    HDC hdc = GetDC(g_hFile);
    const int lineH = hdc ? LineHeightPx(hdc, g_fSmall) : S(16);
    if (hdc) ReleaseDC(g_hFile, hdc);

    const int needed = (int)SendMessageW(g_hFile, EM_GETLINECOUNT, 0, 0);

    RECT fr;
    SendMessageW(g_hFile, EM_GETRECT, 0, (LPARAM)&fr);
    const int have = fr.bottom - fr.top;

    const int want = needed * lineH + S(4);
    if (want <= have) return false;

    g_pathPad += want - have;
    ComputeLayout();

    // Move the controls to the corrected geometry.
    SetWindowPos(g_hFile, nullptr, g_rcPath.left, g_rcPath.top,
                 g_rcPath.right - g_rcPath.left, g_rcPath.bottom - g_rcPath.top,
                 SWP_NOZORDER | SWP_NOACTIVATE);
    SetWindowPos(g_hRemark, nullptr, g_rcRemarkEdit.left, g_rcRemarkEdit.top,
                 g_rcRemarkEdit.right - g_rcRemarkEdit.left,
                 g_rcRemarkEdit.bottom - g_rcRemarkEdit.top,
                 SWP_NOZORDER | SWP_NOACTIVATE);
    SetWindowPos(g_hStatus, nullptr, g_rcStatus.left, g_rcStatus.top,
                 g_rcStatus.right - g_rcStatus.left,
                 g_rcStatus.bottom - g_rcStatus.top,
                 SWP_NOZORDER | SWP_NOACTIVATE);

    // Grow the window by the same amount so nothing gets cut off at the bottom.
    RECT cr;
    GetClientRect(hWnd, &cr);
    if (g_clientH > cr.bottom)
    {
        RECT want2 = { 0, 0, cr.right, g_clientH };
        AdjustWindowRectEx(&want2, kWindowStyle | WS_CLIPCHILDREN, FALSE,
                           WS_EX_DLGMODALFRAME);
        SetWindowPos(hWnd, nullptr, 0, 0, want2.right - want2.left,
                     want2.bottom - want2.top,
                     SWP_NOMOVE | SWP_NOZORDER | SWP_NOACTIVATE);
    }
    InvalidateRect(hWnd, nullptr, FALSE);
    return true;
}

static void ApplyIcon(HWND hWnd)
{
    g_hIconBig = fr::logo::CreateLogoIcon(S(32));
    g_hIconSmall = fr::logo::CreateLogoIcon(S(16));
    g_hIconPaint = fr::logo::CreateLogoIcon(S(22));
    if (g_hIconBig)   SendMessageW(hWnd, WM_SETICON, ICON_BIG, (LPARAM)g_hIconBig);
    if (g_hIconSmall) SendMessageW(hWnd, WM_SETICON, ICON_SMALL, (LPARAM)g_hIconSmall);
}

// --- painting --------------------------------------------------------------
static void DrawCard(HDC hdc, const RECT& r, bool focused)
{
    fr::theme::RoundedRect(hdc, r, S(10), fr::theme::kCard,
        focused ? fr::theme::kAccent : fr::theme::kBorder, focused ? 2 : 1);
}

static void PaintAll(HWND hWnd, HDC hdc)
{
    RECT client;
    GetClientRect(hWnd, &client);

    FillRect(hdc, &client, g_brPage);
    SetBkMode(hdc, TRANSPARENT);

    const bool remarkFocused = (GetFocus() == g_hRemark);
    // Header card holds the logo and the file path; the remark card is the box
    // the user types in. Neither carries a caption: the placeholder inside the
    // remark box says what it is, and a path beside the logo needs no label.
    DrawCard(hdc, g_rcHeaderCard, false);
    DrawCard(hdc, g_rcRemarkCard, remarkFocused);

    if (g_hIconPaint)
        DrawIconEx(hdc, g_rcIcon.left, g_rcIcon.top, g_hIconPaint,
                   g_rcIcon.right - g_rcIcon.left,
                   g_rcIcon.bottom - g_rcIcon.top, 0, nullptr, DI_NORMAL);

    // Status text comes from the control so SetStatus() remains authoritative.
    WCHAR status[512] = { 0 };
    if (g_hStatus) GetWindowTextW(g_hStatus, status, 511);
    fr::theme::Text(hdc, g_fSmall, fr::theme::kMuted, g_rcStatus, status,
                    DT_LEFT | DT_VCENTER | DT_SINGLELINE | DT_END_ELLIPSIS);
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
        g_brPage = CreateSolidBrush(fr::theme::kPage);
        g_brCard = CreateSolidBrush(fr::theme::kCard);
        ApplyIcon(hWnd);
        fr::theme::RoundWindow(hWnd);
        CreateChildren(hWnd);
        // Correct the pre-window estimate against the real control, so the path
        // is guaranteed to be shown in full (possibly several passes, because
        // growing the box can change the wrap).
        for (int i = 0; i < 6 && FitPathControl(hWnd); ++i) {}
        LoadRemark();
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
        // Save only -- never close. The window stays exactly where it is.
        if (LOWORD(wParam) == WA_INACTIVE)
            SaveIfChanged();
        return 0;

    case WM_CLOSE:
        // Closing always saves -- this is the only "button" the user needs.
        SaveIfChanged();
        DestroyWindow(hWnd);
        return 0;

    case WM_CTLCOLOREDIT:
    case WM_CTLCOLORSTATIC:
    {
        HDC hdc = (HDC)wParam;
        HWND child = (HWND)lParam;
        if (child == g_hStatus)
        {
            SetBkMode(hdc, TRANSPARENT);
            SetTextColor(hdc, fr::theme::kMuted);
            return (LRESULT)g_brPage;
        }
        // Both edits sit on a white card; the read-only path is greyed out.
        //
        // The background mode MUST stay OPAQUE here. A multiline EDIT erases the
        // area it repaints by drawing text with this DC, so with TRANSPARENT the
        // background is never filled: delete part of the text and the removed
        // characters keep their pixels on screen while being gone from the value
        // -- they can no longer be selected, but they are still visible.
        SetBkMode(hdc, OPAQUE);
        SetBkColor(hdc, fr::theme::kCard);
        SetTextColor(hdc, child == g_hFile ? fr::theme::kMuted : fr::theme::kText);
        return (LRESULT)g_brCard;
    }

    case WM_DESTROY:
        if (g_fBody)  DeleteObject(g_fBody);
        if (g_fSmall) DeleteObject(g_fSmall);
        g_fBody = g_fSmall = nullptr;
        if (g_brPage) DeleteObject(g_brPage);
        if (g_brCard) DeleteObject(g_brCard);
        g_brPage = g_brCard = nullptr;
        if (g_hIconBig)   DestroyIcon(g_hIconBig);
        if (g_hIconSmall) DestroyIcon(g_hIconSmall);
        if (g_hIconPaint) DestroyIcon(g_hIconPaint);
        g_hIconBig = g_hIconSmall = g_hIconPaint = nullptr;
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
        L"备注",
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
