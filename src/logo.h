// FileRemarks logo
// ---------------------------------------------------------------------------
// The logo is drawn at run time, pixel by pixel, instead of being loaded from a
// .ico resource: GNU windres cannot be run while building this project (it
// shells out to the compiler's preprocessor, and spawning that is blocked), so
// there is no resource compiler available. Drawing it here also keeps it sharp
// at any DPI -- the right-click menu asks for a small icon and gets exactly that
// many pixels.
//
// Shape: a rounded blue tile carrying a white speech bubble with text lines --
// a "note", which is what the software is about.
//
// Two consumers:
//   CreateLogoBitmap(px) -> HBITMAP for MENUITEMINFOW.hbmpItem (right-click menu)
//   CreateLogoIcon(px)   -> HICON for WM_SETICON on the editor window
// ---------------------------------------------------------------------------
#pragma once

#include <windows.h>
#include <cmath>

namespace fr
{
namespace logo
{

struct Rgba { double r, g, b, a; };

static inline double Clamp01(double v) { return v < 0 ? 0 : (v > 1 ? 1 : v); }

// Signed distance to a rounded rectangle: negative inside.
static inline double RoundRectSdf(double x, double y, double x0, double y0,
                                  double x1, double y1, double r)
{
    const double cx = (x0 + x1) * 0.5, cy = (y0 + y1) * 0.5;
    double hx = (x1 - x0) * 0.5 - r, hy = (y1 - y0) * 0.5 - r;
    if (hx < 0) hx = 0;
    if (hy < 0) hy = 0;
    const double dx = std::fabs(x - cx) - hx;
    const double dy = std::fabs(y - cy) - hy;
    const double ax = dx > 0 ? dx : 0;
    const double ay = dy > 0 ? dy : 0;
    if (dx > 0 || dy > 0) return std::sqrt(ax * ax + ay * ay) - r;
    return (dx > dy ? dx : dy) - r;
}

// Point in triangle (barycentric sign test); works for either winding.
static inline bool InTriangle(double u, double v, double ax, double ay,
                              double bx, double by, double cx, double cy)
{
    const double s1 = (bx - ax) * (v - ay) - (by - ay) * (u - ax);
    const double s2 = (cx - bx) * (v - by) - (cy - by) * (u - bx);
    const double s3 = (ax - cx) * (v - cy) - (ay - cy) * (u - cx);
    return (s1 >= 0 && s2 >= 0 && s3 >= 0) || (s1 <= 0 && s2 <= 0 && s3 <= 0);
}

// Antialiased coverage: fraction of a 3x3 sub-pixel sample grid inside the shape.
template <class F>
static inline double Coverage(double x, double y, F inside)
{
    static const double k[3] = { 1.0 / 6.0, 0.5, 5.0 / 6.0 };
    int hits = 0;
    for (int i = 0; i < 3; ++i)
        for (int j = 0; j < 3; ++j)
            if (inside(x + k[i], y + k[j])) ++hits;
    return hits / 9.0;
}

static inline void Blend(Rgba& dst, const Rgba& src, double cov)
{
    const double sa = src.a * cov;
    if (sa <= 0) return;
    const double da = dst.a * (1.0 - sa);
    const double outA = sa + da;
    if (outA <= 0) { dst = Rgba{ 0, 0, 0, 0 }; return; }
    dst.r = (src.r * sa + dst.r * da) / outA;
    dst.g = (src.g * sa + dst.g * da) / outA;
    dst.b = (src.b * sa + dst.b * da) / outA;
    dst.a = outA;
}

// Renders the logo into a size*size RGBA buffer (straight alpha).
static inline void Render(Rgba* px, int size)
{
    const double S = (double)size;

    // Rounded tile, a hair inset so antialiasing has room.
    const double inset = S * 0.055;
    const double tileR = S * 0.235;

    // Speech bubble.
    const double bx0 = S * 0.185, bx1 = S * 0.815;
    const double by0 = S * 0.190, by1 = S * 0.645;
    const double bR  = S * 0.115;

    // Tail: down-left pointing triangle under the bubble.
    const double t1x = S * 0.285, t1y = by1 - 0.5;
    const double t2x = S * 0.475, t2y = by1 - 0.5;
    const double t3x = S * 0.335, t3y = S * 0.800;

    // Text bars inside the bubble. The layout is computed rather than tabulated
    // so small sizes get fewer, fatter bars instead of an unreadable stripe.
    // At icon sizes the bars must leave a clear white margin all round, or the
    // bubble reads as a flat blue blob instead of a note with text lines.
    const bool   roomy    = S >= 40.0;
    const int    bars     = roomy ? 3 : 2;
    const double areaTop  = roomy ? S * 0.250 : S * 0.300;
    const double areaBot  = roomy ? S * 0.590 : S * 0.560;
    const double gap      = roomy ? S * 0.052 : S * 0.075;
    const double barH     = ((areaBot - areaTop) - gap * (bars - 1)) / bars;
    const double barR     = barH * 0.5;
    const double barLen[3] = { 1.00, 0.82, 0.62 };   // fraction of the area width
    const double barAreaW = roomy ? S * 0.450 : S * 0.340;
    const double barX0    = roomy ? S * 0.275 : S * 0.330;

    const Rgba cTop    = { 0.250, 0.545, 0.980, 1.0 };  // #408BF9
    const Rgba cBot    = { 0.105, 0.290, 0.845, 1.0 };  // #1B4AD8
    const Rgba cBubble = { 1.000, 1.000, 1.000, 1.0 };
    const Rgba cBar    = { 0.145, 0.388, 0.922, 1.0 };  // #2563EB

    for (int y = 0; y < size; ++y)
    {
        for (int x = 0; x < size; ++x)
        {
            Rgba out = { 0, 0, 0, 0 };
            const double fx = (double)x, fy = (double)y;

            // Tile, with a vertical gradient.
            const double tileCov = Coverage(fx, fy, [&](double u, double v) {
                return RoundRectSdf(u, v, inset, inset, S - inset, S - inset, tileR) <= 0.0;
            });
            if (tileCov > 0)
            {
                const double t = Clamp01((fy + 0.5) / S);
                const Rgba bg = { cTop.r + (cBot.r - cTop.r) * t,
                                  cTop.g + (cBot.g - cTop.g) * t,
                                  cTop.b + (cBot.b - cTop.b) * t,
                                  1.0 };
                Blend(out, bg, tileCov);
            }

            // Bubble body and tail.
            const double bubbleCov = Coverage(fx, fy, [&](double u, double v) {
                if (RoundRectSdf(u, v, bx0, by0, bx1, by1, bR) <= 0.0) return true;
                return InTriangle(u, v, t1x, t1y, t2x, t2y, t3x, t3y);
            });
            Blend(out, cBubble, bubbleCov);

            // Text bars.
            for (int i = 0; i < bars; ++i)
            {
                const double y0 = areaTop + i * (barH + gap);
                const double y1 = y0 + barH;
                const double x1 = barX0 + barAreaW * barLen[i];
                const double cov = Coverage(fx, fy, [&](double u, double v) {
                    return RoundRectSdf(u, v, barX0, y0, x1, y1, barR) <= 0.0;
                });
                Blend(out, cBar, cov);
            }

            px[y * size + x] = out;
        }
    }
}

// Allocates a 32bpp top-down DIB of the logo. premultiply=true gives the
// premultiplied BGRA that AlphaBlend/MENUITEMINFO expect; false gives straight
// BGRA, which is what CreateIconIndirect expects.
static inline HBITMAP RenderToDib(int px, bool premultiply)
{
    if (px < 8) px = 8;
    if (px > 256) px = 256;

    BITMAPINFO bi = { 0 };
    bi.bmiHeader.biSize = sizeof(BITMAPINFOHEADER);
    bi.bmiHeader.biWidth = px;
    bi.bmiHeader.biHeight = -px;   // top-down
    bi.bmiHeader.biPlanes = 1;
    bi.bmiHeader.biBitCount = 32;
    bi.bmiHeader.biCompression = BI_RGB;

    void* bits = nullptr;
    HBITMAP hbm = CreateDIBSection(nullptr, &bi, DIB_RGB_COLORS, &bits, nullptr, 0);
    if (!hbm || !bits) return nullptr;

    Rgba* src = (Rgba*)HeapAlloc(GetProcessHeap(), 0, sizeof(Rgba) * (size_t)px * (size_t)px);
    if (!src) { DeleteObject(hbm); return nullptr; }
    Render(src, px);

    unsigned char* dst = (unsigned char*)bits;
    for (int i = 0; i < px * px; ++i)
    {
        const Rgba& c = src[i];
        const double a = premultiply ? c.a : 1.0;
        dst[i * 4 + 0] = (unsigned char)(c.b * a * 255.0 + 0.5);
        dst[i * 4 + 1] = (unsigned char)(c.g * a * 255.0 + 0.5);
        dst[i * 4 + 2] = (unsigned char)(c.r * a * 255.0 + 0.5);
        dst[i * 4 + 3] = (unsigned char)(c.a * 255.0 + 0.5);
    }
    HeapFree(GetProcessHeap(), 0, src);
    return hbm;
}

// Icon for the right-click menu (MENUITEMINFOW.hbmpItem). Caller: DeleteObject.
static inline HBITMAP CreateLogoBitmap(int px) { return RenderToDib(px, true); }

// Icon for the editor window (WM_SETICON). Caller: DestroyIcon.
static inline HICON CreateLogoIcon(int px)
{
    if (px < 8) px = 8;
    if (px > 256) px = 256;

    HBITMAP hColor = RenderToDib(px, false);
    if (!hColor) return nullptr;

    // AND mask: all ones (transparent) -- only consulted by callers that ignore
    // the alpha channel.
    HBITMAP hMask = CreateBitmap(px, px, 1, 1, nullptr);
    if (hMask)
    {
        HDC dc = CreateCompatibleDC(nullptr);
        if (dc)
        {
            HGDIOBJ old = SelectObject(dc, hMask);
            RECT rc = { 0, 0, px, px };
            FillRect(dc, &rc, (HBRUSH)GetStockObject(WHITE_BRUSH));
            SelectObject(dc, old);
            DeleteDC(dc);
        }
    }

    ICONINFO ii = { 0 };
    ii.fIcon = TRUE;
    ii.hbmColor = hColor;
    ii.hbmMask = hMask;
    HICON hIcon = CreateIconIndirect(&ii);

    DeleteObject(hColor);
    if (hMask) DeleteObject(hMask);
    return hIcon;
}

} // namespace logo
} // namespace fr
