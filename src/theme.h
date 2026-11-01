// Shared Windows 11 visual language for FileRemarks windows.
// ---------------------------------------------------------------------------
// Both the editor and the installer use the same palette, type ramp and
// rounded-card drawing so the product looks like one app instead of two
// unrelated Win32 dialogs. Header-only: no resource compiler, no extra libs.
// ---------------------------------------------------------------------------
#pragma once

#include <windows.h>

namespace fr {
namespace theme {

// Windows 11 "light" surface colours.
const COLORREF kPage        = RGB(243, 243, 243);  // #F3F3F3
const COLORREF kCard        = RGB(255, 255, 255);  // #FFFFFF
const COLORREF kBorder      = RGB(229, 229, 229);  // #E5E5E5
const COLORREF kText        = RGB(32, 32, 32);     // #202020
const COLORREF kMuted       = RGB(96, 96, 96);     // #606060
const COLORREF kAccent      = RGB(0, 95, 184);     // #005FB8
const COLORREF kAccentHover = RGB(0, 80, 158);
const COLORREF kAccentPress = RGB(0, 66, 130);
const COLORREF kAccentText  = RGB(255, 255, 255);

// DPI helpers --------------------------------------------------------------
inline int DpiOf(HWND hWnd)
{
    HDC hdc = GetDC(hWnd);
    if (!hdc) return 96;
    int dpi = GetDeviceCaps(hdc, LOGPIXELSX);
    ReleaseDC(hWnd, hdc);
    return dpi > 0 ? dpi : 96;
}

inline int DpiOfScreen()
{
    HDC hdc = GetDC(nullptr);
    if (!hdc) return 96;
    int dpi = GetDeviceCaps(hdc, LOGPIXELSX);
    ReleaseDC(nullptr, hdc);
    return dpi > 0 ? dpi : 96;
}

// Segoe UI type ramp (ClearType), the Windows 11 default face.
inline HFONT Font(int px, int weight)
{
    return CreateFontW(-px, 0, 0, 0, weight, FALSE, FALSE, FALSE,
        DEFAULT_CHARSET, OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS,
        CLEARTYPE_QUALITY, DEFAULT_PITCH | FF_DONTCARE, L"Segoe UI");
}

// Rounded window corners (Windows 11). Looked up at runtime so the program
// still runs on Windows 10, where the attribute simply does not exist.
#ifndef DWMWA_WINDOW_CORNER_PREFERENCE
#define DWMWA_WINDOW_CORNER_PREFERENCE 33
#endif
#ifndef DWMWCP_ROUND
#define DWMWCP_ROUND 2
#endif

inline void RoundWindow(HWND hWnd)
{
    typedef HRESULT (WINAPI *PFN_SetAttr)(HWND, DWORD, LPCVOID, DWORD);
    HMODULE dwm = LoadLibraryW(L"dwmapi.dll");
    if (!dwm) return;
    PFN_SetAttr fn = (PFN_SetAttr)GetProcAddress(dwm, "DwmSetWindowAttribute");
    if (fn)
    {
        const int pref = DWMWCP_ROUND;
        fn(hWnd, (DWORD)DWMWA_WINDOW_CORNER_PREFERENCE, &pref, sizeof(pref));
    }
    FreeLibrary(dwm);
}

// Filled + outlined rounded rectangle, the one shape the design uses.
inline void RoundedRect(HDC hdc, const RECT& r, int radius,
                        COLORREF fill, COLORREF border, int penWidth)
{
    HBRUSH br = CreateSolidBrush(fill);
    HPEN pen = CreatePen(PS_SOLID, penWidth, border);
    HGDIOBJ oldBr = SelectObject(hdc, br);
    HGDIOBJ oldPen = SelectObject(hdc, pen);
    RoundRect(hdc, r.left, r.top, r.right, r.bottom, radius, radius);
    SelectObject(hdc, oldPen);
    SelectObject(hdc, oldBr);
    DeleteObject(pen);
    DeleteObject(br);
}

// Single-line text helper that restores the DC state it changed.
inline void Text(HDC hdc, HFONT font, COLORREF color, const RECT& r,
                 const WCHAR* text,
                 UINT flags = DT_LEFT | DT_VCENTER | DT_SINGLELINE)
{
    HGDIOBJ oldFont = SelectObject(hdc, font);
    // A fresh device context (WM_DRAWITEM hands one over per control) starts in
    // OPAQUE background mode with a white background colour, which paints a
    // white block behind every glyph. Always draw transparently.
    const int oldBk = SetBkMode(hdc, TRANSPARENT);
    SetTextColor(hdc, color);
    RECT rr = r;
    DrawTextW(hdc, text, -1, &rr, flags | DT_NOPREFIX);
    SetBkMode(hdc, oldBk);
    SelectObject(hdc, oldFont);
}

// Horizontal hairline, used to separate card rows.
inline void Hairline(HDC hdc, int x0, int x1, int y, COLORREF color)
{
    HPEN pen = CreatePen(PS_SOLID, 1, color);
    HGDIOBJ oldPen = SelectObject(hdc, pen);
    MoveToEx(hdc, x0, y, nullptr);
    LineTo(hdc, x1 + 1, y);
    SelectObject(hdc, oldPen);
    DeleteObject(pen);
}

} // namespace theme
} // namespace fr
