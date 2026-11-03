// FileRemarks installer UI — a small Windows 11 styled choice window.
// ---------------------------------------------------------------------------
// The installer used to ask with plain MessageBoxes ("是 = 重新安装 / 否 = 卸载"),
// which is both dated and unable to show which version is installed versus
// which one is about to be installed. This window replaces them:
//
//   * header with the product logo and name,
//   * one card with two stacked rows (当前版本 / 目标版本), label left, value
//     right-aligned on the same baseline, a hairline between them,
//   * one card explaining what the buttons do,
//   * owner-drawn rounded buttons (primary / secondary) that still behave like
//     real buttons for the keyboard, focus and accessibility layers.
//
// There is no progress page and there never was one: the installer either shows
// this window or a result message box.
//
// Header-only and painted with plain GDI, so it needs no resource compiler.
// ---------------------------------------------------------------------------
#pragma once

#include <windows.h>
#include <string>

#include "theme.h"
#include "logo.h"

namespace fr {
namespace ui {

// What the user picked.
enum Choice {
    kChoiceCancel = 0,
    kChoiceInstall = 1,
    kChoiceUninstall = 2,
};

namespace detail {

struct ButtonSpec {
    int id;
    const WCHAR* text;
    RECT rc;        // in pixels, filled in during layout
    bool primary;
};

struct ChoiceState {
    HFONT fTitle = nullptr;
    HFONT fSub = nullptr;
    HFONT fLabel = nullptr;
    HFONT fValue = nullptr;
    HFONT fBody = nullptr;
    HFONT fBtn = nullptr;
    HBRUSH brPage = nullptr;
    HBRUSH brCard = nullptr;
    HICON icon = nullptr;
    HICON iconSmall = nullptr;
    int dpi = 96;
    bool dark = false;
    bool installed = false;
    std::wstring curVersion;
    std::wstring newVersion;
    int result = kChoiceCancel;
    // Two actions only: the primary (install / reinstall) and uninstall.
    // Backing out is the window's own close affordance (X, Alt+F4) or Esc.
    ButtonSpec buttons[2];
    int buttonCount = 2;
    // Measured layout, in scaled pixels, filled by CreateFonts()+Layout()
    // BEFORE the window exists so the window can be sized to fit its content.
    RECT noteCard = { 0, 0, 0, 0 };
    RECT noteBody = { 0, 0, 0, 0 };
    int contentBottom = 0;
};

inline int Sc(const ChoiceState* st, int v) { return MulDiv(v, st->dpi, 96); }

inline RECT CardRect(const ChoiceState* st, int top, int bottom)
{
    RECT r = { Sc(st, 16), Sc(st, top), Sc(st, 504), Sc(st, bottom) };
    return r;
}

// The explanation shown in the lower card. Kept in one place so the painter and
// the measurer can never disagree about what has to fit.
inline const WCHAR* NoteText(const ChoiceState* st)
{
    return st->installed
        ? L"“重新安装”会用上面的新版覆盖已安装的文件，并重新登记右键菜单和“备注”列。\r\n"
          L"“卸载”会移除本软件及其所有登记项。\r\n"
          L"安装在 C:\\Program Files\\FileRemarks，需要管理员权限（下一步会提示 UAC）。\r\n"
          L"关掉这个窗口即取消，不会做任何更改。"
        : L"安装后，在任意文件上点右键即可“编辑备注”，资源管理器里的“备注”列也会默认打开。\r\n"
          L"安装在 C:\\Program Files\\FileRemarks，需要管理员权限（下一步会提示 UAC）。\r\n"
          L"关掉这个窗口即取消，不会做任何更改。";
}

// Creates the type ramp. Called before the window exists so the note text can
// be measured and the window sized to fit it.
inline void CreateFonts(ChoiceState* st)
{
    if (st->fTitle) return;
    st->fTitle = theme::Font(Sc(st, 15), FW_SEMIBOLD);
    st->fSub = theme::Font(Sc(st, 11), FW_NORMAL);
    st->fLabel = theme::Font(Sc(st, 11), FW_NORMAL);
    st->fValue = theme::Font(Sc(st, 15), FW_SEMIBOLD);
    st->fBody = theme::Font(Sc(st, 12), FW_NORMAL);
    st->fBtn = theme::Font(Sc(st, 12), FW_NORMAL);
}

// Drops and rebuilds the type ramp at the state's current dpi.
inline void RecreateFonts(ChoiceState* st)
{
    if (st->fTitle) DeleteObject(st->fTitle);
    if (st->fSub) DeleteObject(st->fSub);
    if (st->fLabel) DeleteObject(st->fLabel);
    if (st->fValue) DeleteObject(st->fValue);
    if (st->fBody) DeleteObject(st->fBody);
    if (st->fBtn) DeleteObject(st->fBtn);
    st->fTitle = st->fSub = st->fLabel = st->fValue = st->fBody = st->fBtn = nullptr;
    CreateFonts(st);
}

// Measures the note text and lays out every element, including the buttons.
// Everything is stored in scaled pixels in st, so Paint() and the window
// creation code agree by construction.
inline void Layout(ChoiceState* st)
{
    // Measure the wrapped note text against the card's inner width (16..504
    // card, 32 padding each side).
    RECT body = { 0, 0, Sc(st, 456), 0 };
    HDC hdc = GetDC(nullptr);
    if (hdc)
    {
        HGDIOBJ oldFont = SelectObject(hdc, st->fBody);
        SetBkMode(hdc, TRANSPARENT);
        DrawTextW(hdc, NoteText(st), -1, &body,
                  DT_CALCRECT | DT_WORDBREAK | DT_NOPREFIX);
        SelectObject(hdc, oldFont);
        ReleaseDC(nullptr, hdc);
    }
    const int textH = body.bottom - body.top;
    const int padY = Sc(st, 12);
    const int noteTop = Sc(st, 160);
    st->noteCard = { Sc(st, 16), noteTop, Sc(st, 504), noteTop + padY * 2 + textH };
    st->noteBody = { Sc(st, 32), noteTop + padY, Sc(st, 488), noteTop + padY + textH };

    // Button row sits below the note card. The affirmative action is the one on
    // the right, which is where a Windows installer puts it.
    const int gap = Sc(st, 8);
    const int btnH = Sc(st, 30);
    const int btnY = st->noteCard.bottom + Sc(st, 24);

    st->buttons[0] = { kChoiceInstall, st->installed ? L"重新安装" : L"安装", {}, true };
    st->buttons[1] = { kChoiceUninstall, L"卸载", {}, false };

    const int wPrimary = Sc(st, 96);
    const int wSecondary = Sc(st, 88);
    int x = Sc(st, 504) - (wPrimary + wSecondary + gap);
    st->buttons[1].rc = { x, btnY, x + wSecondary, btnY + btnH };
    x += wSecondary + gap;
    st->buttons[0].rc = { x, btnY, x + wPrimary, btnY + btnH };

    st->contentBottom = btnY + btnH + Sc(st, 30);
}

// Point-in-rect helper used for the owner-drawn button hit test.
inline bool Inside(const RECT& r, POINT p)
{
    return p.x >= r.left && p.x < r.right && p.y >= r.top && p.y < r.bottom;
}

// The buttons are real BUTTON controls (so Tab, Space, focus rings and the
// accessibility tree all work), which means the keyboard goes to the button,
// not to the parent. This forwards Esc / Enter to the parent so the shortcuts
// work no matter which control has focus, and re-paints on hover.
//
// All three buttons share one subclass procedure, so the original BUTTON
// window procedure is stored once here.
inline WNDPROC& ButtonOldProc()
{
    static WNDPROC p = nullptr;
    return p;
}

// Hover state of one button, stored as a window property so it can never clash
// with whatever a BUTTON control keeps in GWLP_USERDATA itself.
inline const WCHAR* HotPropName() { return L"FileRemarksButtonHot"; }

// How many times this button has asked to be repainted. Kept as a window
// property purely so a test can prove that redundant requests are suppressed:
// the count may never grow faster than the hover state actually flips.
inline const WCHAR* RepaintCountName() { return L"FileRemarksButtonRepaints"; }

inline int RepaintCount(HWND hWnd)
{
    return (int)(INT_PTR)GetPropW(hWnd, RepaintCountName());
}

inline void SetButtonHot(HWND hWnd, bool hot)
{
    const bool was = GetPropW(hWnd, HotPropName()) != nullptr;
    if (was == hot) return;          // nothing to repaint
    if (hot) SetPropW(hWnd, HotPropName(), (HANDLE)1);
    else     RemovePropW(hWnd, HotPropName());
    SetPropW(hWnd, RepaintCountName(), (HANDLE)(INT_PTR)(RepaintCount(hWnd) + 1));
    InvalidateRect(hWnd, nullptr, FALSE);
}

inline bool ButtonHot(HWND hWnd)
{
    return GetPropW(hWnd, HotPropName()) != nullptr;
}

inline LRESULT CALLBACK ButtonProc(HWND hWnd, UINT msg, WPARAM wParam, LPARAM lParam)
{
    switch (msg)
    {
    case WM_KEYDOWN:
        if (wParam == VK_ESCAPE || wParam == VK_RETURN)
        {
            PostMessageW(GetParent(hWnd), WM_KEYDOWN, wParam, lParam);
            return 0;
        }
        break;

    case WM_MOUSEMOVE:
    {
        // Hover is not a button state the control tracks itself, so it is
        // tracked here -- but a repaint is only requested when the state really
        // flips. Invalidating on every WM_MOUSEMOVE repainted the whole button
        // dozens of times per second, which is what made the buttons strobe
        // while the cursor crossed the window.
        TRACKMOUSEEVENT tme = { sizeof(tme), TME_LEAVE, hWnd, 0 };
        TrackMouseEvent(&tme);
        RECT rc;
        GetClientRect(hWnd, &rc);
        const POINT p = { (short)LOWORD(lParam), (short)HIWORD(lParam) };
        SetButtonHot(hWnd, Inside(rc, p));
        break;
    }

    case WM_MOUSELEAVE:
        SetButtonHot(hWnd, false);
        break;
    }
    return CallWindowProcW(ButtonOldProc(), hWnd, msg, wParam, lParam);
}

// Draws one button into its OWN device context, which starts at the button's
// top-left corner -- so the painting rect must be client-local, not the
// parent-space rect stored in ButtonSpec::rc.
//
// States, in the order they matter: disabled (flat, tertiary label), idle,
// hover (+surface step), pressed (one more step). The primary keeps the accent
// fill in every enabled state and only darkens it, so it never loses its
// "this is the action" reading.
inline void PaintButton(HDC hdc, const ChoiceState* st, const ButtonSpec& b,
                        const RECT& rc, bool pressed, bool hot, bool disabled)
{
    const theme::Palette& c = theme::Colors();
    COLORREF fill, text, border;

    if (disabled)
    {
        fill = c.page;
        text = c.tertiary;
        border = c.border;
    }
    else if (b.primary)
    {
        fill = pressed ? c.accentPress : (hot ? c.accentHover : c.accent);
        text = c.onAccent;
        border = fill;
    }
    else
    {
        fill = pressed ? c.pressSurface : (hot ? c.hoverSurface : c.card);
        text = c.text;
        border = c.border;
    }

    theme::RoundedRect(hdc, rc, Sc(st, 4), fill, border, 1);

    RECT r = rc;
    theme::Text(hdc, st->fBtn, text, r, b.text,
                DT_CENTER | DT_VCENTER | DT_SINGLELINE);
}

inline void Paint(ChoiceState* st, HWND hWnd, HDC hdc)
{
    RECT client;
    GetClientRect(hWnd, &client);
    FillRect(hdc, &client, st->brPage);
    SetBkMode(hdc, TRANSPARENT);

    const theme::Palette& c = theme::Colors();

    // Header: 20px logo, product name, one line of context.
    if (st->icon)
        DrawIconEx(hdc, Sc(st, 16), Sc(st, 18), st->icon, Sc(st, 20), Sc(st, 20),
                   0, nullptr, DI_NORMAL);
    theme::TextBaseline(hdc, st->fTitle, c.text, Sc(st, 44), Sc(st, 504),
                        Sc(st, 30), L"FileRemarks");
    theme::TextBaseline(hdc, st->fSub, c.muted, Sc(st, 44), Sc(st, 504),
                        Sc(st, 48), L"安装程序");

    // Version card: two rows, label left, value right, one hairline between.
    // Labels and values share a baseline, which is what makes the two rows read
    // as a table instead of four drifting boxes.
    RECT card = CardRect(st, 68, 148);
    theme::RoundedRect(hdc, card, Sc(st, 8), c.card, c.border, 1);

    theme::TextBaseline(hdc, st->fLabel, c.muted, Sc(st, 32), Sc(st, 300),
                        Sc(st, 96), L"当前版本");
    theme::TextBaseline(hdc, st->fValue,
            st->installed ? c.text : c.muted,
            Sc(st, 300), Sc(st, 488), Sc(st, 96),
            st->installed ? st->curVersion.c_str() : L"未安装", DT_RIGHT);

    theme::Hairline(hdc, Sc(st, 32), Sc(st, 488), Sc(st, 116), c.divider);

    theme::TextBaseline(hdc, st->fLabel, c.muted, Sc(st, 32), Sc(st, 300),
                        Sc(st, 136), L"目标版本");
    theme::TextBaseline(hdc, st->fValue, c.accent, Sc(st, 300), Sc(st, 488),
                        Sc(st, 136), st->newVersion.c_str(), DT_RIGHT);

    // Explanation card. Its height was measured from the wrapped text, so the
    // hint is always shown in full -- a fixed height used to clip the last line.
    theme::RoundedRect(hdc, st->noteCard, Sc(st, 8), c.card, c.border, 1);
    theme::Text(hdc, st->fBody, c.muted, st->noteBody, NoteText(st),
                DT_LEFT | DT_TOP | DT_WORDBREAK);

    // The buttons paint themselves through WM_DRAWITEM (they are child
    // windows), so nothing to do for them here.
}

inline LRESULT CALLBACK Proc(HWND hWnd, UINT msg, WPARAM wParam, LPARAM lParam)
{
    ChoiceState* st = (ChoiceState*)GetWindowLongPtrW(hWnd, GWLP_USERDATA);

    switch (msg)
    {
    case WM_CREATE:
    {
        CREATESTRUCTW* cs = (CREATESTRUCTW*)lParam;
        st = (ChoiceState*)cs->lpCreateParams;
        SetWindowLongPtrW(hWnd, GWLP_USERDATA, (LONG_PTR)st);
        st->dpi = theme::DpiOf(hWnd);
        st->dark = theme::DetectSystemDark();
        theme::SetDark(st->dark);
        st->brPage = CreateSolidBrush(theme::Colors().page);
        st->brCard = CreateSolidBrush(theme::Colors().card);
        // The fonts were created for the screen dpi before the window existed;
        // rebuild them at this window's dpi so the measured layout stays exact.
        RecreateFonts(st);
        st->icon = logo::CreateLogoIcon(Sc(st, 20));
        st->iconSmall = logo::CreateLogoIcon(Sc(st, 16));
        theme::RoundWindow(hWnd);
        theme::ApplyTitleBarTheme(hWnd);
        if (st->iconSmall)
            SendMessageW(hWnd, WM_SETICON, ICON_SMALL, (LPARAM)st->iconSmall);

        Layout(st);
        for (int i = 0; i < st->buttonCount; ++i)
        {
            HWND btn = CreateWindowExW(0, L"BUTTON", st->buttons[i].text,
                WS_CHILD | WS_VISIBLE | WS_TABSTOP | BS_OWNERDRAW,
                st->buttons[i].rc.left, st->buttons[i].rc.top,
                st->buttons[i].rc.right - st->buttons[i].rc.left,
                st->buttons[i].rc.bottom - st->buttons[i].rc.top,
                hWnd, (HMENU)(INT_PTR)st->buttons[i].id, cs->hInstance, nullptr);
            // The original BUTTON procedure is stored once (first button) and
            // shared, because every button uses the same subclass.
            WNDPROC prev = (WNDPROC)SetWindowLongPtrW(btn, GWLP_WNDPROC, (LONG_PTR)ButtonProc);
            if (prev && !ButtonOldProc()) ButtonOldProc() = prev;

            // Nothing to uninstall when the product is not installed: disabling
            // the control is louder than the beep the click handler used to
            // produce, and the keyboard no longer stops on it while tabbing.
            if (st->buttons[i].id == kChoiceUninstall && !st->installed)
                EnableWindow(btn, FALSE);
        }
        SetFocus(GetDlgItem(hWnd, st->buttons[0].id));
        return 0;
    }

    case WM_ERASEBKGND:
        return 1;

    case WM_PAINT:
    {
        PAINTSTRUCT ps;
        HDC hdc = BeginPaint(hWnd, &ps);
        RECT client;
        GetClientRect(hWnd, &client);
        HDC mem = CreateCompatibleDC(hdc);
        HBITMAP bmp = CreateCompatibleBitmap(hdc, client.right, client.bottom);
        HGDIOBJ oldBmp = SelectObject(mem, bmp);
        if (st) Paint(st, hWnd, mem);
        // Copy back only the region the system asked for. Together with
        // WS_CLIPCHILDREN this keeps the buttons' pixels intact: blitting the
        // whole client would paint page background over them and make them
        // flicker on every parent repaint.
        BitBlt(hdc, ps.rcPaint.left, ps.rcPaint.top,
               ps.rcPaint.right - ps.rcPaint.left,
               ps.rcPaint.bottom - ps.rcPaint.top,
               mem, ps.rcPaint.left, ps.rcPaint.top, SRCCOPY);
        SelectObject(mem, oldBmp);
        DeleteObject(bmp);
        DeleteDC(mem);
        EndPaint(hWnd, &ps);
        return 0;
    }

    case WM_DRAWITEM:
    {
        DRAWITEMSTRUCT* dis = (DRAWITEMSTRUCT*)lParam;
        if (st && dis->CtlType == ODT_BUTTON && dis->hwndItem)
        {
            for (int i = 0; i < st->buttonCount; ++i)
            {
                if (st->buttons[i].id != (int)dis->CtlID) continue;

                // dis->hDC is the button's own device context, so draw in
                // button-local coordinates (0,0 .. w,h).
                RECT rc;
                GetClientRect(dis->hwndItem, &rc);

                PaintButton(dis->hDC, st, st->buttons[i], rc,
                            (dis->itemState & ODS_SELECTED) != 0,
                            ButtonHot(dis->hwndItem),
                            (dis->itemState & ODS_DISABLED) != 0);
                return TRUE;
            }
        }
        break;
    }

    case WM_COMMAND:
    {
        const int id = LOWORD(wParam);
        if (HIWORD(wParam) == BN_CLICKED && st)
        {
            if (id == kChoiceInstall)   { st->result = kChoiceInstall;   DestroyWindow(hWnd); return 0; }
            if (id == kChoiceUninstall)
            {
                if (!st->installed) { Beep(1200, 60); return 0; }  // nothing to remove
                st->result = kChoiceUninstall;
                DestroyWindow(hWnd);
                return 0;
            }
        }
        break;
    }

    case WM_KEYDOWN:
        if (wParam == VK_ESCAPE && st) { st->result = kChoiceCancel; DestroyWindow(hWnd); return 0; }
        if (wParam == VK_RETURN && st) { st->result = kChoiceInstall; DestroyWindow(hWnd); return 0; }
        break;

    case WM_CLOSE:
        if (st) st->result = kChoiceCancel;
        DestroyWindow(hWnd);
        return 0;

    case WM_DESTROY:
        // The window is gone, so end the message loop in ShowChoice().
        // Without this, GetMessageW() would block forever waiting for a message
        // that never comes, and the installer would hang after the dialog.
        PostQuitMessage(0);
        return 0;

    case WM_MOUSEMOVE:
    case WM_LBUTTONUP:
        // Nothing to do here. The buttons track their own hover state and
        // repaint themselves through WM_DRAWITEM, so the parent must NOT
        // repaint: it used to call InvalidateRect on every mouse move, and
        // because the window did not clip out its children each of those
        // repaints bitblitted the page background over the buttons and let them
        // draw themselves again -- visible as a steady flicker.
        break;
    }
    return DefWindowProcW(hWnd, msg, wParam, lParam);
}

} // namespace detail

// Modal choice window. Returns one of the Choice values.
inline int ShowChoice(bool installed, const std::wstring& curVersion,
                      const std::wstring& newVersion, HINSTANCE hInst)
{
    detail::ChoiceState st;
    st.installed = installed;
    st.curVersion = curVersion;
    st.newVersion = newVersion;

    WNDCLASSEXW wc = { sizeof(wc) };
    wc.lpfnWndProc = detail::Proc;
    wc.hInstance = hInst;
    wc.hCursor = LoadCursorW(nullptr, IDC_ARROW);
    wc.lpszClassName = L"FileRemarksInstallChoice";
    wc.style = CS_HREDRAW | CS_VREDRAW;
    RegisterClassExW(&wc);  // benign when already registered

    // Measure first, then create the window at exactly the height the content
    // needs. A fixed height used to clip the explanation card.
    st.dpi = theme::DpiOfScreen();
    detail::CreateFonts(&st);
    detail::Layout(&st);

    const int clientW = detail::Sc(&st, 520);
    const int clientH = st.contentBottom;
    RECT want = { 0, 0, clientW, clientH };
    AdjustWindowRectEx(&want, WS_OVERLAPPED | WS_CAPTION | WS_SYSMENU, FALSE,
                       WS_EX_DLGMODALFRAME);

    // WS_CLIPCHILDREN is what stops the parent's background from being painted
    // over the buttons; without it every parent repaint wiped them and the
    // buttons visibly flickered.
    const DWORD style = WS_OVERLAPPED | WS_CAPTION | WS_SYSMENU | WS_CLIPCHILDREN;
    HWND hWnd = CreateWindowExW(WS_EX_DLGMODALFRAME, wc.lpszClassName,
        L"FileRemarks 安装程序", style,
        CW_USEDEFAULT, CW_USEDEFAULT, want.right - want.left, want.bottom - want.top,
        nullptr, nullptr, hInst, &st);
    if (!hWnd) return kChoiceCancel;

    ShowWindow(hWnd, SW_SHOW);
    UpdateWindow(hWnd);

    MSG msg;
    while (IsWindow(hWnd) && GetMessageW(&msg, nullptr, 0, 0))
    {
        TranslateMessage(&msg);
        DispatchMessageW(&msg);
    }

    if (st.fTitle) DeleteObject(st.fTitle);
    if (st.fSub) DeleteObject(st.fSub);
    if (st.fLabel) DeleteObject(st.fLabel);
    if (st.fValue) DeleteObject(st.fValue);
    if (st.fBody) DeleteObject(st.fBody);
    if (st.fBtn) DeleteObject(st.fBtn);
    if (st.brPage) DeleteObject(st.brPage);
    if (st.brCard) DeleteObject(st.brCard);
    if (st.icon) DestroyIcon(st.icon);
    if (st.iconSmall) DestroyIcon(st.iconSmall);
    return st.result;
}

} // namespace ui
} // namespace fr
