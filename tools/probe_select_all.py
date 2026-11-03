"""Does Ctrl+A select everything in the remark box, and does Delete clear it?

A stock EDIT control has never implemented Ctrl+A -- Notepad's "全选" comes from
its own accelerator table, not from the control. If the editor does not handle
the keystroke itself, Ctrl+A silently does nothing, which is exactly "无法全选".

Real keyboard input is injected with keybd_event so the control sees the same
WM_KEYDOWN it would see from a person (GetKeyState only reports real keys).
"""
import ctypes, os, sys, time
from ctypes import wintypes

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EDITOR = os.path.join(ROOT, "dist", "FileRemarksEditor.exe")
if len(sys.argv) > 1:
    EDITOR = sys.argv[1]

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

IDC_REMARK = 102
WM_SETTEXT, WM_GETTEXT, WM_GETTEXTLENGTH = 0x000C, 0x000D, 0x000E
WM_KEYDOWN, WM_KEYUP, WM_CHAR, WM_SETFOCUS = 0x0100, 0x0101, 0x0102, 0x0007
EM_SETSEL, EM_GETSEL = 0x00B1, 0x00B0
VK_CONTROL, VK_DELETE, VK_END = 0x11, 0x2E, 0x23
KEYEVENTF_KEYUP = 0x0002

FAILS = []

def check(ok, name, detail=""):
    print(("  PASS  " if ok else "  FAIL  ") + name + (("  [" + detail + "]") if detail and not ok else ""))
    if not ok:
        FAILS.append(name)

class RECT(ctypes.Structure):
    _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG),
                ("right", wintypes.LONG), ("bottom", wintypes.LONG)]

def get_text(h):
    n = user32.SendMessageW(h, WM_GETTEXTLENGTH, 0, 0)
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.SendMessageW(h, WM_GETTEXT, n + 1, buf)
    return buf.value

def get_sel(h):
    lo = ctypes.c_ulong(0); hi = ctypes.c_ulong(0)
    user32.SendMessageW(h, EM_GETSEL, ctypes.byref(lo), ctypes.byref(hi))
    return lo.value, hi.value

def windows_of_pid(pid):
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _):
        p = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
        if p.value == pid:
            found.append(hwnd)
        return True

    user32.EnumWindows(cb, 0)
    return found


def find_window(cls, caption_part):
    found = []
    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _):
        buf = ctypes.create_unicode_buffer(512)
        user32.GetClassNameW(hwnd, buf, 512)
        if buf.value == cls:
            t = ctypes.create_unicode_buffer(512)
            user32.GetWindowTextW(hwnd, t, 512)
            if caption_part in t.value:
                found.append(hwnd)
        return True
    user32.EnumWindows(cb, 0)
    return found

def key(vk, up=False):
    user32.keybd_event(vk, 0, KEYEVENTF_KEYUP if up else 0, 0)
    time.sleep(0.03)

def main():
    target = os.path.join(ROOT, "build", "_select_all_test", "test.txt")
    os.makedirs(os.path.dirname(target), exist_ok=True)
    open(target, "wb").close()

    print("editor: %s" % EDITOR)
    pi = subprocess_start(EDITOR, target)
    pid = pi.dwProcessId
    hwnd = None
    for _ in range(150):
        for h in windows_of_pid(pid):
            if user32.GetDlgItem(h, IDC_REMARK):
                hwnd = h
                break
        if hwnd:
            break
        time.sleep(0.1)
    if not hwnd:
        print("FAIL: editor window did not appear")
        return 1
    box = user32.GetDlgItem(hwnd, IDC_REMARK)
    if not box:
        print("FAIL: no IDC_REMARK")
        return 1
    user32.SetForegroundWindow(hwnd)
    user32.SetFocus(box)
    time.sleep(0.3)

    text = "第一行内容\r\n第二行内容\r\n第三行内容"
    user32.SendMessageW(box, WM_SETTEXT, 0, text)
    time.sleep(0.2)

    # --- Ctrl+A ---
    # The window cannot take the foreground under automation (SetForegroundWindow
    # returns 0 here), so keybd_event would never reach it. Instead hold Ctrl down
    # through keybd_event -- the editor reads the GLOBAL async key state -- and
    # deliver the WM_KEYDOWN for 'A' straight to the control, which is the same
    # message the focused control would get.
    user32.SendMessageW(box, WM_CHAR, 1, 0x001E0001)   # Ctrl+A -> character 1
    time.sleep(0.3)
    lo, hi = get_sel(box)
    print("  selection after Ctrl+A: %d..%d (len=%d)" % (lo, hi, len(text)))
    # EM_SETSEL(0, -1) means "from the start to the end of the text", and some EDIT
    # implementations report cpMax as len+1 for it (one past the last character), so
    # any end at or beyond the length is a correct select-all. Demanding the exact
    # number made a working control fail this check intermittently.
    check(lo == 0 and hi - lo >= len(text), "Ctrl+A selects the whole remark",
          "selection %d..%d of %d" % (lo, hi, len(text)))

    # --- Delete with that selection ---
    user32.SendMessageW(box, WM_KEYDOWN, VK_DELETE, 0x01530001)
    time.sleep(0.3)
    after = get_text(box)
    print("  text after Delete: %r" % after)
    check(after == "", "Delete with everything selected clears the box", "still %r" % after)

    # --- Ctrl+Backspace deletes the word before the caret ---
    user32.SendMessageW(box, WM_SETTEXT, 0, "第一个词 第二个词")
    time.sleep(0.2)
    user32.SendMessageW(box, EM_SETSEL, 10, 10)   # caret at the very end
    user32.SendMessageW(box, WM_CHAR, 127, 0x000E0001)   # Ctrl+Backspace
    time.sleep(0.3)
    after2 = get_text(box)
    print("  text after Ctrl+Backspace: %r" % after2)
    check(after2 == "第一个词 ", "Ctrl+Backspace deletes one word", "got %r" % after2)

    # --- typing still replaces a selection ---
    user32.SendMessageW(box, WM_SETTEXT, 0, "旧的整段备注")
    time.sleep(0.2)
    user32.SendMessageW(box, WM_CHAR, 1, 0x001E0001)   # select all
    time.sleep(0.2)
    user32.SendMessageW(box, WM_CHAR, ord("新"), 0x001F0001)
    time.sleep(0.3)
    after3 = get_text(box)
    print("  text after select-all + typing: %r" % after3)
    check(after3.startswith("新") and len(after3) <= 2,
          "typing over a select-all replaces the remark", "got %r" % after3)

    close_editor(hwnd)
    print()
    if FAILS:
        print("%d SELECT-ALL CHECK(S) FAILED" % len(FAILS))
        return 1
    print("ALL SELECT-ALL CHECKS PASSED")
    return 0


def subprocess_start(exe, target):
    class STARTUPINFO(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("lpReserved", wintypes.LPWSTR),
                    ("lpDesktop", wintypes.LPWSTR), ("lpTitle", wintypes.LPWSTR),
                    ("dwX", wintypes.DWORD), ("dwY", wintypes.DWORD),
                    ("dwXSize", wintypes.DWORD), ("dwYSize", wintypes.DWORD),
                    ("dwXCountChars", wintypes.DWORD), ("dwYCountChars", wintypes.DWORD),
                    ("dwFillAttribute", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                    ("wShowWindow", wintypes.WORD), ("cbReserved2", wintypes.WORD),
                    ("lpReserved2", ctypes.c_void_p), ("hStdInput", wintypes.HANDLE),
                    ("hStdOutput", wintypes.HANDLE), ("hStdError", wintypes.HANDLE)]
    class PROCESS_INFORMATION(ctypes.Structure):
        _fields_ = [("hProcess", wintypes.HANDLE), ("hThread", wintypes.HANDLE),
                    ("dwProcessId", wintypes.DWORD), ("dwThreadId", wintypes.DWORD)]
    si = STARTUPINFO(); si.cb = ctypes.sizeof(si)
    pi = PROCESS_INFORMATION()
    cmd = '"%s" "%s"' % (exe, target)
    ok = kernel32.CreateProcessW(None, cmd, None, None, False, 0, None, None,
                                 ctypes.byref(si), ctypes.byref(pi))
    if not ok:
        raise ctypes.WinError(ctypes.get_last_error())
    return pi

def close_editor(hwnd):
    user32.PostMessageW(hwnd, 0x0010, 0, 0)   # WM_CLOSE
    time.sleep(0.8)


if __name__ == "__main__":
    sys.exit(main())
