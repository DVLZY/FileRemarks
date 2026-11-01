// FileRemarks installer UI — a small Windows 11 styled choice window.
// ---------------------------------------------------------------------------
// The installer used to ask with plain MessageBoxes ("是 = 重新安装 / 否 = 卸载"),
// which is both dated and unable to show which version is installed versus
// which one is about to be installed. This window replaces them:
//
//   * header with the product logo and name,
//   * one card stating 当前已安装版本 and 要安装的版本 side by side,
//   * one card explaining what the buttons do,
//   * owner-drawn rounded buttons (primary / secondary) that still behave like
//     real buttons for the keyboard, focus and accessibility layers.
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
    HBRUSH brPage = nullptr;
    HBRUSH brCard = nullptr;
    HICON icon = nullptr;
    int dpi = 96;
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
    RECT r = { Sc(st, 24), Sc(st, top), Sc(st, 496), Sc(st, bottom) };
    return r;
}

// The explanation shown in the lower card. Kept in one place so the painter and
// the measurer can never disagree about what has to fit.
inline const WCHAR* NoteText(const ChoiceState* st)
{
    return st->installed
        ? L"“重新安装”会用上面的新版覆盖已安装的文件，并重新登记右键菜单和“备注”列。\r\n"
          L"“卸载”会移除本软件及其所有登记项。\r\n"
          L"安装在当前用户目录下，不需要管理员权限。关掉这个窗口即可退出。"
        : L"安装后，在任意文件上点右键即可“编辑备注”，资源管理器里的“备注”列也会默认打开。\r\n"
          L"安装在当前用户目录下，不需要管理员权限。关掉这个窗口即可退出。";
}

// Creates the type ramp. Called before the window exists so the note text can
// be measured and the window sized to fit it.
inline void CreateFonts(ChoiceState* st)
{
    if (st->fTitle) return;
    st->fTitle = theme::Font(Sc(st, 19), FW_SEMIBOLD);
    st->fSub = theme::Font(Sc(st, 12), FW_NORMAL);
    st->fLabel = theme::Font(Sc(st, 12), FW_NORMAL);
    st->fValue = theme::Font(Sc(st, 16), FW_SEMIBOLD);
    st->fBody = theme::Font(Sc(st, 14), FW_NORMAL);
}

// Drops and rebuilds the type ramp at the state's current dpi.
inline void RecreateFonts(ChoiceState* st)
{
    if (st->fTitle) DeleteObject(st->fTitle);
    if (st->fSub) DeleteObject(st->fSub);
    if (st->fLabel) DeleteObject(st->fLabel);
    if (st->fValue) DeleteObject(st->fValue);
    if (st->fBody) DeleteObject(st->fBody);
    st->fTitle = st->fSub = st->fLabel = st->fValue = st->fBody = nullptr;
    CreateFonts(st);
}

// Measures the note text and lays out every element, including the buttons.
// Everything is stored in scaled pixels in st, so Paint() and the window
// creation code agree by construction.
inline void Layout(ChoiceState* st)
{
    // Measure the wrapped note text against the card's inner width.
    RECT body = { 0, 0, Sc(st, 440), 0 };
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
    const int noteTop = Sc(st, 184);
    st->noteCard = { Sc(st, 24), noteTop, Sc(st, 496), noteTop + padY * 2 + textH };
    st->noteBody = { Sc(st, 40), noteTop + padY, Sc(st, 480), noteTop + padY + textH };

    // Button row sits below the note card with a comfortable gap.
    const int gap = Sc(st, 8);
    const int btnH = Sc(st, 36);
    const int btnY = st->noteCard.bottom + Sc(st, 20);

    st->buttons[0] = { kChoiceInstall, st->installed ? L"重新安装" : L"安装", {}, true };
    st->buttons[1] = { kChoiceUninstall, L"卸载", {}, false };

    int widths[2] = { Sc(st, 108), Sc(st, 84) };
    int x = Sc(st, 496) - (widths[0] + widths[1] + gap);
    for (int i = 0; i < st->buttonCount; ++i)
    {
        RECT r = { x, btnY, x + widths[i], btnY + btnH };
        st->buttons[i].rc = r;
        x += widths[i] + gap;
    }

    st->contentBottom = btnY + btnH + Sc(st, 24);
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
inline void PaintButton(HDC hdc, const ChoiceState* st, const ButtonSpec& b,
                        const RECT& rc, bool pressed, bool hot)
{
    COLORREF fill, text, border;
    if (b.primary)
    {
        fill = pressed ? theme::kAccentPress : (hot ? theme::kAccentHover : theme::kAccent);
        text = theme::kAccentText;
        border = fill;
    }
    else
    {
        fill = pressed ? RGB(240, 240, 240) : (hot ? RGB(249, 249, 249) : theme::kCard);
        text = theme::kText;
        border = theme::kBorder;
    }
    theme::RoundedRect(hdc, rc, Sc(st, 6), fill, border, 1);

    RECT r = rc;
    theme::Text(hdc, st->fBody, text, r, b.text, DT_CENTER | DT_VCENTER | DT_SINGLELINE);
}

inline void Paint(ChoiceState* st, HWND hWnd, HDC hdc)
{
    RECT client;
    GetClientRect(hWnd, &client);
    FillRect(hdc, &client, st->brPage);
    SetBkMode(hdc, TRANSPARENT);

    // Header: logo + product name + subtitle.
    if (st->icon)
        DrawIconEx(hdc, Sc(st, 24), Sc(st, 18), st->icon, Sc(st, 28), Sc(st, 28),
                   0, nullptr, DI_NORMAL);
    RECT title = { Sc(st, 62), Sc(st, 14), Sc(st, 496), Sc(st, 40) };
    theme::Text(hdc, st->fTitle, theme::kText, title, L"FileRemarks");
    RECT sub = { Sc(st, 62), Sc(st, 40), Sc(st, 496), Sc(st, 60) };
    theme::Text(hdc, st->fSub, theme::kMuted, sub, L"安装程序");

    // Version card.
    RECT card = CardRect(st, 72, 172);
    theme::RoundedRect(hdc, card, Sc(st, 10), theme::kCard, theme::kBorder, 1);

    RECT l1 = { Sc(st, 40), Sc(st, 86), Sc(st, 260), Sc(st, 104) };
    theme::Text(hdc, st->fLabel, theme::kMuted, l1, L"当前已安装版本");
    RECT v1 = { Sc(st, 40), Sc(st, 106), Sc(st, 260), Sc(st, 134) };
    theme::Text(hdc, st->fValue, st->installed ? theme::kText : theme::kMuted, v1,
                st->installed ? st->curVersion.c_str() : L"未安装");

    RECT l2 = { Sc(st, 276), Sc(st, 86), Sc(st, 480), Sc(st, 104) };
    theme::Text(hdc, st->fLabel, theme::kMuted, l2, L"要安装的版本");
    RECT v2 = { Sc(st, 276), Sc(st, 106), Sc(st, 480), Sc(st, 134) };
    theme::Text(hdc, st->fValue, theme::kText, v2, st->newVersion.c_str());

    // Vertical divider between the two columns.
    HPEN pen = CreatePen(PS_SOLID, 1, theme::kBorder);
    HGDIOBJ oldPen = SelectObject(hdc, pen);
    MoveToEx(hdc, Sc(st, 260), Sc(st, 88), nullptr);
    LineTo(hdc, Sc(st, 260), Sc(st, 156));
    SelectObject(hdc, oldPen);
    DeleteObject(pen);

    // Explanation card. Its height was measured from the wrapped text, so the
    // hint is always shown in full -- a fixed height used to clip the last line.
    theme::RoundedRect(hdc, st->noteCard, Sc(st, 10), theme::kCard, theme::kBorder, 1);
    theme::Text(hdc, st->fBody, theme::kMuted, st->noteBody, NoteText(st),
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
        st->brPage = CreateSolidBrush(theme::kPage);
        st->brCard = CreateSolidBrush(theme::kCard);
        // The fonts were created for the screen dpi before the window existed;
        // rebuild them at this window's dpi so the measured layout stays exact.
        RecreateFonts(st);
        st->icon = logo::CreateLogoIcon(Sc(st, 28));
        theme::RoundWindow(hWnd);

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
                            ButtonHot(dis->hwndItem));
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
        L"FileRemarks", style,
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
    if (st.brPage) DeleteObject(st.brPage);
    if (st.brCard) DeleteObject(st.brCard);
    if (st.icon) DestroyIcon(st.icon);
    return st.result;
}

} // namespace ui
} // namespace fr
