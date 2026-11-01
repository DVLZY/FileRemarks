"""Capture the real editor window to a PNG, so the layout can be looked at.

Not an automated assertion suite (see test_editor_*.py for those): this exists
to turn "the name is clipped" / "the UI is too busy" into something visible.
"""
import ctypes
import ctypes.wintypes as w
import os
import struct
import subprocess
import sys
import time
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
EDITOR = os.path.join(ROOT, "dist", "FileRemarksEditor.exe")
WORK = os.path.join(ROOT, "build", "_shot")

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)


class RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", w.DWORD), ("biWidth", ctypes.c_long),
                ("biHeight", ctypes.c_long), ("biPlanes", w.WORD),
                ("biBitCount", w.WORD), ("biCompression", w.DWORD),
                ("biSizeImage", w.DWORD), ("biXPelsPerMeter", ctypes.c_long),
                ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", w.DWORD),
                ("biClrImportant", w.DWORD)]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", w.DWORD * 3)]


def find_window(pid):
    found = []

    @ctypes.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
    def cb(hwnd, _lp):
        p = w.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
        if p.value == pid and user32.IsWindowVisible(hwnd):
            n = user32.GetWindowTextLengthW(hwnd)
            if n:
                found.append(hwnd)
        return True

    user32.EnumWindows(cb, 0)
    return found[0] if found else None


def grab(hwnd, path):
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.35)
    rc = RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rc))
    width, height = rc.right - rc.left, rc.bottom - rc.top

    hdc_screen = user32.GetDC(0)
    hdc = gdi32.CreateCompatibleDC(hdc_screen)
    bmp = gdi32.CreateCompatibleBitmap(hdc_screen, width, height)
    gdi32.SelectObject(hdc, bmp)
    # PW_RENDERFULLCONTENT = 2 (needed for layered/DWM-composited windows).
    user32.PrintWindow(hwnd, hdc, 2)

    bi = BITMAPINFO()
    bi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bi.bmiHeader.biWidth = width
    bi.bmiHeader.biHeight = -height          # top-down
    bi.bmiHeader.biPlanes = 1
    bi.bmiHeader.biBitCount = 32
    bi.bmiHeader.biCompression = 0           # BI_RGB
    buf = ctypes.create_string_buffer(width * height * 4)
    gdi32.GetDIBits(hdc, bmp, 0, height, buf, ctypes.byref(bi), 0)

    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(hdc)
    user32.ReleaseDC(0, hdc_screen)

    # BGRA -> RGB rows for the PNG encoder.
    raw = bytearray()
    data = buf.raw
    for y in range(height):
        raw.append(0)                        # filter type 0
        row = data[y * width * 4:(y + 1) * width * 4]
        for x in range(width):
            b, g, r = row[x * 4], row[x * 4 + 1], row[x * 4 + 2]
            raw += bytes((r, g, b))

    def chunk(tag, payload):
        return (struct.pack(">I", len(payload)) + tag + payload
                + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF))

    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(bytes(raw), 6))
           + chunk(b"IEND", b""))
    with open(path, "wb") as f:
        f.write(png)
    return width, height


def shoot(name, target):
    os.makedirs(WORK, exist_ok=True)
    proc = subprocess.Popen([EDITOR, target])
    hwnd = None
    for _ in range(60):
        time.sleep(0.1)
        hwnd = find_window(proc.pid)
        if hwnd:
            break
    if not hwnd:
        print("  %-8s window never appeared" % name)
        proc.kill()
        return

    rc = RECT()
    user32.GetClientRect(hwnd, ctypes.byref(rc))
    print("  %-8s client=%dx%d title=%r"
          % (name, rc.right, rc.bottom, ctypes.create_unicode_buffer(128).value))

    win_rc = RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(win_rc))
    print("  %-8s window rect=(%d,%d,%d,%d)" % (name, win_rc.left, win_rc.top,
                                                win_rc.right, win_rc.bottom))
    out = os.path.join(WORK, "%s.png" % name)
    print("  %-8s wrote %s (%dx%d)" % ((name, out) + grab(hwnd, out)))
    proc.kill()
    proc.wait()


def main():
    short = os.path.join(WORK, "短名字.txt")
    os.makedirs(WORK, exist_ok=True)
    with open(short, "wb") as f:
        f.write(b"x\n")
    deep = WORK
    for i in range(6):
        deep = os.path.join(deep, "目录%02d_abcdefghijklmnop" % i)
    os.makedirs(deep, exist_ok=True)
    long_path = os.path.join(deep, "很长很长的一个文件名用来测试换行显示效果.txt")
    with open(long_path, "wb") as f:
        f.write(b"x\n")

    print("=== capturing ===")
    shoot("short", short)
    shoot("long", long_path)
    print("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
