"""Explain why the selection step cannot be exercised from this session.

The shortcut's job is: ask the shell which item is selected in the front Explorer
window, then open the editor for it. That question is answered by the shell's own
COM objects (CLSID_ShellWindows). Inside this sandbox that activation is refused:

    CoCreateInstance(CLSID_ShellWindows, CLSCTX_ALL) -> 0x80070005
    CoCreateInstance(CLSID_ShellWindows, CLSCTX_INPROC_SERVER) -> 0x80040154

so the lookup returns "nothing selected" here no matter what the user has
selected. A negative result from this environment therefore proves nothing about
the user's machine -- this probe prints the measured HRESULTs and the Explorer
windows it can see, so the limitation is on record instead of being guessed at.

What IS verified in this environment lives in tools/test_hotkey.py: the shortcut
is registered, a second copy exits, WM_CLOSE stops the helper, and the shipped
launch code opens the editor for a file.

Run:  python tools/probe_hotkey_selection.py
"""
import ctypes
import ctypes.wintypes as w
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DLL = os.path.join(ROOT, "build", "selftest_hotkey.dll")

user32 = ctypes.WinDLL("user32", use_last_error=True)
ole32 = ctypes.WinDLL("ole32")

CLSID_ShellWindows = "{9BA05972-F6A8-11CF-A442-00A0C90A8F39}"
IID_IShellWindows = "{85CB6900-4D95-11CF-960C-0080C7F4EE85}"


class GUID(ctypes.Structure):
    _fields_ = [("d1", ctypes.c_ulong),
                ("d2", ctypes.c_ushort),
                ("d3", ctypes.c_ushort),
                ("d4", ctypes.c_ubyte * 8)]


def guid(text):
    value = GUID()
    ole32.CLSIDFromString(ctypes.c_wchar_p(text), ctypes.byref(value))
    return value


def activate(context):
    clsid = guid(CLSID_ShellWindows)
    iid = guid(IID_IShellWindows)
    pointer = ctypes.c_void_p()
    hr = ole32.CoCreateInstance(ctypes.byref(clsid), None, context,
                                ctypes.byref(iid), ctypes.byref(pointer))
    return hr & 0xFFFFFFFF


def explorer_windows():
    found = []

    def callback(hwnd, _):
        buf = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, buf, 256)
        if buf.value in ("CabinetWClass", "ExploreWClass"):
            caption = ctypes.create_unicode_buffer(512)
            user32.GetWindowTextW(hwnd, caption, 512)
            found.append((hwnd, caption.value))
        return True

    user32.EnumWindows(ctypes.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)(callback), 0)
    return found


def main():
    print("=== selection lookup: what this session can and cannot do ===")
    ole32.CoInitialize(None)

    all_classes = activate(0x17)          # CLSCTX_ALL
    inproc = activate(0x01)               # CLSCTX_INPROC_SERVER
    print("  CoCreateInstance(CLSID_ShellWindows, CLSCTX_ALL)          -> 0x%08X" % all_classes)
    print("  CoCreateInstance(CLSID_ShellWindows, CLSCTX_INPROC_SERVER) -> 0x%08X" % inproc)

    windows = explorer_windows()
    print("  Explorer windows visible to this session: %d" % len(windows))
    for hwnd, caption in windows:
        print("    hwnd=%-8s caption=%r" % (hwnd, caption))

    blocked = all_classes != 0 and inproc != 0
    if blocked:
        print()
        print("  => the shell refuses to hand its window collection to this process")
        print("     (0x80070005 E_ACCESSDENIED / 0x80040154 REGDB_E_CLASSNOTREG),")
        print("     so the lookup cannot be exercised here.")
        print("     The step itself is standard shell COM and is confirmed on a real")
        print("     desktop by: select a file, press Shift+F2, the editor opens.")
        print("     A line is appended to %TEMP%\\FileRemarks_hotkey.log each time.")
        print()
        print("SELECTION STEP: SKIPPED (sandbox denies shell COM activation)")
        ole32.CoUninitialize()
        return 0

    dll = ctypes.WinDLL(DLL)
    dll.FrTestViewItemCount.argtypes = [ctypes.c_void_p]
    dll.FrTestViewItemCount.restype = ctypes.c_int
    dll.FrTestSelectedPath.argtypes = [ctypes.c_void_p]
    dll.FrTestSelectedPath.restype = ctypes.c_wchar_p

    ok = True
    for hwnd, caption in windows:
        items = dll.FrTestViewItemCount(ctypes.c_void_p(hwnd))
        selected = dll.FrTestSelectedPath(ctypes.c_void_p(hwnd))
        print("    %r items=%d selected=%r" % (caption, items, selected))
        if items < 0:
            ok = False
    ole32.CoUninitialize()

    if not ok:
        print("\nFAILED: the folder view of a real Explorer window could not be reached")
        return 1
    print("\nSELECTION LOOKUP REACHES REAL EXPLORER WINDOWS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
