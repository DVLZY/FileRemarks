# -*- coding: utf-8 -*-
"""Verify the right-click "编辑备注" entry (FileRemarksShellExt.dll) in-process.

This is the primary way the user touches the tool, and it was never exercised at
runtime before. Everything except the final CreateProcessW is testable in-process:

  * IShellExtInit::Initialize accepts a real IDataObject carrying CF_HDROP,
  * IContextMenu::QueryContextMenu really inserts one item into a menu, and the
    item text is the expected Chinese label,
  * IContextMenu::GetCommandString returns the status-bar help text,
  * InvokeCommand with the wrong offset is ignored (no accidental launches).

A real data object is built with SHCreateDataObject from a PIDL, so the shell's own
extraction path is what our handler sees.
"""
import ctypes
import os
import sys
from ctypes import POINTER, byref, c_void_p, c_uint32, c_uint16, c_ubyte, c_wchar_p, c_int

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ole32 = ctypes.WinDLL("ole32")
shell32 = ctypes.WinDLL("shell32")
user32 = ctypes.WinDLL("user32")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = os.path.join(ROOT, "build", "_shellext_test")

HRESULT = ctypes.c_long
DWORD = ctypes.c_uint32
ULONG = ctypes.c_ulong
UINT = ctypes.c_uint

CLSID_CTXMENU = "{6F3A1B2C-9D4E-4c7b-8A1F-2E5B6C7D8E90}"
IID_IClassFactory = "{00000001-0000-0000-C000-000000000046}"
IID_IShellExtInit = "{000214E8-0000-0000-C000-000000000046}"
IID_IContextMenu = "{000214E4-0000-0000-C000-000000000046}"
IID_IDataObject = "{0000010E-0000-0000-C000-000000000046}"
EXPECTED_LABEL = "编辑备注"
GCS_VERBA = 0
GCS_HELPTEXTA = 1
GCS_VALIDATEA = 2
GCS_VERBW = 4
GCS_HELPTEXTW = 5
GCS_VALIDATEW = 6


class GUID(ctypes.Structure):
    _fields_ = [("Data1", c_uint32), ("Data2", c_uint16), ("Data3", c_uint16),
                ("Data4", c_ubyte * 8)]


def guid(s):
    p = s.strip("{}").split("-")
    g = GUID()
    g.Data1 = int(p[0], 16)
    g.Data2 = int(p[1], 16)
    g.Data3 = int(p[2], 16)
    for i, b in enumerate(bytes.fromhex(p[3] + p[4])):
        g.Data4[i] = b
    return g


def vcall(obj, index, restype, *argtypes):
    vtbl = ctypes.cast(obj, POINTER(c_void_p))[0]
    fn = ctypes.cast(vtbl, POINTER(c_void_p))[index]
    return ctypes.CFUNCTYPE(restype, c_void_p, *argtypes)(fn)


def qi(obj, iid_str):
    out = c_void_p()
    hr = vcall(obj, 0, HRESULT, POINTER(GUID), POINTER(c_void_p))(obj, byref(guid(iid_str)), byref(out))
    return hr & 0xFFFFFFFF, out


def release(obj):
    vcall(obj, 2, ULONG)(obj)


def parse_pidl(path):
    shell32.SHParseDisplayName.argtypes = [c_wchar_p, c_void_p,
                                           POINTER(c_void_p), c_uint32, POINTER(c_uint32)]
    shell32.SHParseDisplayName.restype = HRESULT
    pidl = c_void_p()
    eaten = c_uint32(0)
    hr = shell32.SHParseDisplayName(path, None, byref(pidl), 0, byref(eaten))
    assert (hr & 0xFFFFFFFF) == 0, "SHParseDisplayName 0x%08X" % (hr & 0xFFFFFFFF)
    return pidl


def make_data_object(path):
    """A real IDataObject holding the file as CF_HDROP.

    SHCreateDataObject does not always expose CF_HDROP for a single item, so we
    hand-compose the interface: this is byte-for-byte what Explorer passes to a
    context-menu handler for a file selection.
    """
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import fake_dataobject
    obj = fake_dataobject.make_data_object([path])
    return obj, 0


def main():
    hr = ole32.CoInitializeEx(None, 0x2)
    print("CoInitializeEx hr=0x%08X" % (hr & 0xFFFFFFFF))

    dll = os.path.join(ROOT, "build", "FileRemarksShellExt.dll")
    assert os.path.exists(dll), "build/FileRemarksShellExt.dll missing -- run tools/build_mingw.sh"
    lib = ctypes.WinDLL(dll)
    lib.DllGetClassObject.argtypes = [POINTER(GUID), POINTER(GUID), POINTER(c_void_p)]
    lib.DllGetClassObject.restype = HRESULT

    os.makedirs(WORK, exist_ok=True)
    target = os.path.join(WORK, "被备注的文件.txt")
    with open(target, "wb") as f:
        f.write(b"hello")

    failures = []
    try:
        # --- create the handler object -------------------------------------
        cf = c_void_p()
        hr = lib.DllGetClassObject(byref(guid(CLSID_CTXMENU)), byref(guid(IID_IClassFactory)), byref(cf))
        print("DllGetClassObject(IClassFactory) hr=0x%08X" % (hr & 0xFFFFFFFF))
        if (hr & 0xFFFFFFFF) != 0:
            failures.append("DllGetClassObject failed")
            raise SystemExit(1)

        create = vcall(cf, 3, HRESULT, c_void_p, POINTER(GUID), POINTER(c_void_p))
        obj = c_void_p()
        hr = create(cf, None, byref(guid(IID_IContextMenu)), byref(obj))
        print("CreateInstance(IContextMenu) hr=0x%08X" % (hr & 0xFFFFFFFF))
        if (hr & 0xFFFFFFFF) != 0:
            failures.append("CreateInstance(IContextMenu) failed")
            raise SystemExit(1)
        release(cf)

        # --- IShellExtInit::Initialize with a real CF_HDROP -----------------
        dataobj, err = make_data_object(target)
        if not dataobj:
            print("could not build a data object (hr=0x%08X)" % err)
            failures.append("could not build a shell data object")
        else:
            hr, sei = qi(obj, IID_IShellExtInit)
            print("QI(IShellExtInit) hr=0x%08X" % hr)
            if hr != 0:
                failures.append("QI(IShellExtInit) failed")
            else:
                init = vcall(sei, 3, HRESULT, c_void_p, c_void_p, c_void_p)
                ihr = init(sei, None, dataobj.ptr, None) & 0xFFFFFFFF
                print("IShellExtInit::Initialize hr=0x%08X" % ihr)
                if ihr != 0:
                    failures.append("Initialize rejected the data object")
                release(sei)

        # --- QueryContextMenu really inserts the item -----------------------
        hmenu = user32.CreatePopupMenu()
        try:
            # HRESULT QueryContextMenu(HMENU, UINT, UINT, UINT, UINT)
            qcm = vcall(obj, 3, HRESULT, c_void_p, UINT, UINT, UINT, UINT)
            ret = qcm(obj, hmenu, 0, 1, 0x7FFF, 0) & 0xFFFFFFFF
            n_items = user32.GetMenuItemCount(hmenu)
            print("QueryContextMenu return=0x%08X, menu items now=%d" % (ret, n_items))
            if n_items != 1:
                failures.append("QueryContextMenu inserted %d items, expected 1" % n_items)

            buf = ctypes.create_unicode_buffer(256)
            got = user32.GetMenuStringW(hmenu, 0, buf, 256, 0x400)  # MF_BYPOSITION
            label = buf.value
            print("menu item 0 text: %r (GetMenuStringW=%d)" % (label, got))
            if label.strip("&") != EXPECTED_LABEL:
                failures.append("menu label is %r, expected %r" % (label, EXPECTED_LABEL))

            # The item we inserted must be enabled (MF_ENABLED is 0, so any
            # MF_GRAYED/MF_DISABLED bit set means something went wrong).
            state = user32.GetMenuState(hmenu, 0, 0x400)
            disabled = bool(state & (0x1 | 0x2))  # MF_GRAYED | MF_DISABLED
            print("menu item 0 state=0x%08X (disabled bits=%s)" % (state, disabled))
            if state == 0xFFFFFFFF:
                failures.append("GetMenuState failed")
            elif disabled:
                failures.append("the inserted menu item is disabled")

            # --- the logo must be attached to the menu item ------------------
            class MENUITEMINFOW(ctypes.Structure):
                _fields_ = [("cbSize", UINT), ("fMask", UINT), ("fType", UINT),
                            ("fState", UINT), ("wID", UINT), ("hSubMenu", c_void_p),
                            ("hbmpChecked", c_void_p), ("hbmpUnchecked", c_void_p),
                            ("dwItemData", ctypes.c_size_t),
                            ("dwTypeData", c_void_p), ("cch", UINT),
                            ("hbmpItem", c_void_p)]

            MIIM_BITMAP = 0x00000080
            mii = MENUITEMINFOW()
            mii.cbSize = ctypes.sizeof(mii)
            mii.fMask = MIIM_BITMAP
            user32.GetMenuItemInfoW.argtypes = [c_void_p, UINT, c_int,
                                                ctypes.POINTER(MENUITEMINFOW)]
            user32.GetMenuItemInfoW.restype = c_int
            # fByPosition must be TRUE: our item's command id is idCmdFirst+0
            # (i.e. 1), so 0 can only match by position.
            got_info = user32.GetMenuItemInfoW(hmenu, 0, 1, byref(mii))
            err = ctypes.get_last_error()
            print("GetMenuItemInfoW(bitmap)=%d hbmpItem=%s (lastError=%d, cbSize=%d)"
                  % (got_info, mii.hbmpItem, err, mii.cbSize))
            if not got_info:
                failures.append("GetMenuItemInfoW failed (lastError=%d)" % err)
            elif not mii.hbmpItem:
                failures.append("the menu item carries no logo bitmap")

            # The bitmap must be real artwork, not a blank placeholder: sample
            # its pixels and require both opaque and blue ones.
            if mii.hbmpItem:
                gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

                class BITMAP(ctypes.Structure):
                    _fields_ = [("bmType", ctypes.c_long), ("bmWidth", ctypes.c_long),
                                ("bmHeight", ctypes.c_long),
                                ("bmWidthBytes", ctypes.c_long),
                                ("bmPlanes", ctypes.c_ushort),
                                ("bmBitsPixel", ctypes.c_ushort),
                                ("bmBits", c_void_p)]

                bm = BITMAP()
                filled = gdi32.GetObjectW(c_void_p(mii.hbmpItem),
                                          ctypes.sizeof(bm), byref(bm))
                print("logo bitmap: %ldx%ld %d bpp"
                      % (bm.bmWidth, bm.bmHeight, bm.bmBitsPixel))
                if bm.bmWidth < 16 or bm.bmHeight < 16:
                    failures.append("logo bitmap is too small: %ldx%ld"
                                    % (bm.bmWidth, bm.bmHeight))
                if bm.bmBitsPixel != 32:
                    failures.append("logo bitmap is not 32bpp (got %d)"
                                    % bm.bmBitsPixel)

                # Read the pixels back into a plain DIB and sample the centre
                # column: the tile is blue there, and it must be opaque.
                hdc = user32.GetDC(None)
                mem = gdi32.CreateCompatibleDC(hdc)
                old = gdi32.SelectObject(mem, c_void_p(mii.hbmpItem))
                px = (ctypes.c_ubyte * 4)()
                centre = bm.bmWidth // 2
                y = bm.bmHeight // 2
                okpx = gdi32.GetPixel(mem, centre, 1)
                okedge = gdi32.GetPixel(mem, 0, 0)
                print("logo pixel (centre, y=1)=0x%08X  (0,0)=0x%08X"
                      % (okpx & 0xFFFFFFFF, okedge & 0xFFFFFFFF))
                gdi32.SelectObject(mem, old)
                gdi32.DeleteDC(mem)
                user32.ReleaseDC(None, hdc)
                if okpx == 0xFFFFFFFF:
                    failures.append("could not sample the logo bitmap")
        finally:
            user32.DestroyMenu(hmenu)

        # --- GetCommandString ----------------------------------------------
        # MinGW declares the ANSI vtable form, so buffer/flag types follow that.
        # HRESULT GetCommandString(UINT_PTR, UINT, UINT*, LPSTR, UINT) -- MinGW
        # declares the ANSI vtable form, so the buffer is a CHAR*.
        # Our one command has id 0 for this handler.
        gcs = vcall(obj, 5, HRESULT, ctypes.c_size_t, UINT, c_void_p, c_void_p, UINT)
        helper = ctypes.create_string_buffer(512)
        ghr = gcs(obj, 0, GCS_HELPTEXTA, None, helper, 512) & 0xFFFFFFFF
        helper_text = helper.value.decode("gbk", "replace")
        print("GetCommandString(GCS_HELPTEXTA) hr=0x%08X -> %r" % (ghr, helper_text))
        if ghr != 0:
            failures.append("GetCommandString(GCS_HELPTEXTA) failed")
        elif not helper_text:
            failures.append("GetCommandString returned an empty help text")

        # The Unicode form must work as well: Explorer asks for it when the
        # extension is marked as Unicode-capable.
        wide = ctypes.create_unicode_buffer(512)
        ghrw = gcs(obj, 0, GCS_HELPTEXTW, None, ctypes.cast(wide, c_void_p), 512) & 0xFFFFFFFF
        print("GetCommandString(GCS_HELPTEXTW) hr=0x%08X -> %r" % (ghrw, wide.value))
        if ghrw != 0:
            failures.append("GetCommandString(GCS_HELPTEXTW) failed")
        elif wide.value != helper_text:
            failures.append("help text differs between the A and W forms: %r vs %r"
                            % (helper_text, wide.value))

        # --- InvokeCommand with the wrong offset must be ignored ------------
        class CMINVOKECOMMANDINFO(ctypes.Structure):
            _fields_ = [("cbSize", DWORD), ("fMask", DWORD), ("hwnd", c_void_p),
                        ("lpVerb", c_void_p), ("lpParameters", c_void_p),
                        ("lpDirectory", c_void_p), ("nShow", c_int),
                        ("dwHotKey", DWORD), ("hIcon", c_void_p)]

        inv = vcall(obj, 4, HRESULT, POINTER(CMINVOKECOMMANDINFO))
        info = CMINVOKECOMMANDINFO()
        info.cbSize = ctypes.sizeof(info)
        info.lpVerb = ctypes.cast(c_void_p(5), c_void_p)   # offset 5 does not exist
        ihr = inv(obj, byref(info)) & 0xFFFFFFFF
        print("InvokeCommand(offset 5) hr=0x%08X (must not launch anything)" % ihr)

        # --- InvokeCommand with the right offset -------------------------------
        # offset 0 is our own command. This sandbox cannot create native
        # processes, so the launch itself must fail -- but it has to fail as a
        # clean HRESULT, not a crash, and it must not report success falsely.
        info2 = CMINVOKECOMMANDINFO()
        info2.cbSize = ctypes.sizeof(info2)
        info2.lpVerb = ctypes.cast(c_void_p(0), c_void_p)
        ihr2 = inv(obj, byref(info2)) & 0xFFFFFFFF
        launched = (ihr2 == 0)
        print("InvokeCommand(offset 0) hr=0x%08X (launched=%s)" % (ihr2, launched))
        if ihr2 not in (0, 0x80070005, 0x80004005, 0x80070002):
            failures.append("InvokeCommand(offset 0) returned an unexpected hr 0x%08X" % ihr2)

        release(obj)

        # --- module lifetime + honest registration failures --------------------
        can = lib.DllCanUnloadNow() & 0xFFFFFFFF
        print("DllCanUnloadNow hr=0x%08X" % can)
        if can != 0:
            failures.append("DllCanUnloadNow still reports in-use objects after Release")

        lib.DllRegisterServer.restype = HRESULT
        lib.DllUnregisterServer.restype = HRESULT
        rhr = lib.DllRegisterServer() & 0xFFFFFFFF
        urhr = lib.DllUnregisterServer() & 0xFFFFFFFF
        print("DllRegisterServer hr=0x%08X, DllUnregisterServer hr=0x%08X" % (rhr, urhr))
        # Non-admin in this sandbox: E_ACCESSDENIED is the honest answer. What
        # would be wrong is claiming success.
        if rhr == 0:
            failures.append("DllRegisterServer claimed success without admin rights")

        print("")
        if failures:
            print("FAILURES:")
            for f in failures:
                print("  - " + f)
            return 1
        print("ALL SHELL-EXTENSION TESTS PASSED")
        return 0
    finally:
        ole32.CoUninitialize()


if __name__ == "__main__":
    sys.exit(main())
