// Shared Windows 11 visual language for FileRemarks windows.
// ---------------------------------------------------------------------------
// Both the editor and the installer use the same palette, type ramp and
// rounded-card drawing so the product looks like one app instead of two
// unrelated Win32 dialogs. Header-only: no resource compiler, no extra libs.
//
// The palette is chosen at runtime from the Windows "app mode" setting
// (Settings > Personalization > Colors). The dark palette is its own grey ramp,
// not an inversion of the light one: surfaces step 32 -> 43 -> 56, text sits at
// 240 and the accent is lightened so it still reads on a dark surface.
// ---------------------------------------------------------------------------
#pragma once

#include <windows.h>

namespace fr {
namespace theme {

// One full set of colours. Every window asks for the current one through
// Colors() at paint time, so a theme switch needs nothing more than a repaint.
struct Palette {
    COLORREF page;          // window background
    COLORREF card;         // input / content surface
    COLORREF border;       // 1px hairline around a card
    COLORREF text;         // primary text
    COLORREF muted;        // secondary text
    COLORREF tertiary;     // version numbers, disabled labels
    COLORREF accent;       // the single emphasis colour
    COLORREF accentHover;
    COLORREF accentPress;
    COLORREF onAccent;     // text on an accent-filled button
    COLORREF error;        // save failures only
    COLORREF hoverSurface; // secondary button, hovered
    COLORREF pressSurface; // secondary button, pressed
    COLORREF divider;      // hairline inside a card
};

inline const Palette& LightPalette()
{
    static const Palette p = {
        RGB(243, 243, 243),  // #F3F3F3
        RGB(255, 255, 255),  // #FFFFFF
        RGB(224, 224, 224),  // #E0E0E0
        RGB(27, 27, 27),     // #1B1B1B
        RGB(96, 96, 96),     // #606060
        RGB(145, 145, 145),  // #919191
        RGB(0, 103, 192),    // #0067C0
        RGB(0, 90, 158),     // #005A9E
        RGB(0, 78, 140),     // #004E8C
        RGB(255, 255, 255),
        RGB(196, 43, 28),    // #C42B1C
        RGB(246, 246, 246),
        RGB(238, 238, 238),
        RGB(224, 224, 224)
    };
    return p;
}

inline const Palette& DarkPalette()
{
    static const Palette p = {
        RGB(32, 32, 32),     // #202020
        RGB(43, 43, 43),     // #2B2B2B
        RGB(56, 56, 56),     // #383838
        RGB(240, 240, 240),  // #F0F0F0
        RGB(173, 173, 173),  // #ADADAD
        RGB(118, 118, 118),  // #767676
        RGB(76, 194, 255),   // #4CC2FF
        RGB(105, 197, 255),
        RGB(58, 165, 222),
        RGB(20, 20, 20),
        RGB(255, 153, 164),  // #FF99A4
        RGB(51, 51, 51),     // #333333
        RGB(61, 61, 61),     // #3D3D3D
        RGB(56, 56, 56)
    };
    return p;
}

inline bool& DarkFlag()
{
    static bool dark = false;
    return dark;
}

inline bool IsDark() { return DarkFlag(); }
inline void SetDark(bool dark) { DarkFlag() = dark; }

inline const Palette& Colors()
{
    return IsDark() ? DarkPalette() : LightPalette();
}

// Reads the Windows "app mode" preference. Missing value means light, which is
// also what a fresh Windows 10 install reports.
inline bool DetectSystemDark()
{
    HKEY key = nullptr;
    DWORD useLight = 1, size = sizeof(useLight), type = 0;
    if (RegOpenKeyExW(HKEY_CURRENT_USER,
            L"Software\\Microsoft\\Windows\\CurrentVersion\\Themes\\Personalize",
            0, KEY_READ, &key) == ERROR_SUCCESS)
    {
        RegQueryValueExW(key, L"AppsUseLightTheme", nullptr, &type,
                         (LPBYTE)&useLight, &size);
        RegCloseKey(key);
    }
    return useLight == 0;
}

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
#ifndef DWMWA_USE_IMMERSIVE_DARK_MODE
#define DWMWA_USE_IMMERSIVE_DARK_MODE 20
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

// Dark title bar. Attribute 20 is the documented value; very old Windows 10
// builds used 19, so both are set and the unsupported one fails harmlessly.
inline void ApplyTitleBarTheme(HWND hWnd)
{
    typedef HRESULT (WINAPI *PFN_SetAttr)(HWND, DWORD, LPCVOID, DWORD);
    HMODULE dwm = LoadLibraryW(L"dwmapi.dll");
    if (!dwm) return;
    PFN_SetAttr fn = (PFN_SetAttr)GetProcAddress(dwm, "DwmSetWindowAttribute");
    if (fn)
    {
        const BOOL dark = IsDark() ? TRUE : FALSE;
        fn(hWnd, (DWORD)DWMWA_USE_IMMERSIVE_DARK_MODE, &dark, sizeof(dark));
        fn(hWnd, (DWORD)19, &dark, sizeof(dark));
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

// Draws one line so its BASELINE lands exactly on `baseline`. Two runs set in
// different sizes that share a baseline (a label and its value, a status line
// and a version number) line up without hand-tuned offsets, which is what
// keeps the rows from drifting apart by a pixel.
inline void TextBaseline(HDC hdc, HFONT font, COLORREF color,
                         int left, int right, int baseline,
                         const WCHAR* text, UINT flags = DT_LEFT)
{
    HGDIOBJ oldFont = SelectObject(hdc, font);
    TEXTMETRICW tm = {};
    GetTextMetricsW(hdc, &tm);
    RECT r = { left, baseline - tm.tmAscent, right,
               baseline + tm.tmDescent + tm.tmExternalLeading + 2 };
    const int oldBk = SetBkMode(hdc, TRANSPARENT);
    SetTextColor(hdc, color);
    DrawTextW(hdc, text, -1, &r,
              flags | DT_SINGLELINE | DT_TOP | DT_NOPREFIX);
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
