# -*- coding: utf-8 -*-
"""Probe: can the Office metadata handler (docx/xls) be wrapped after all?

tools/test_chain_matrix.py initialised the Office handler from a READ stream and
QueryInterface(IPropertyStore) failed with E_NOINTERFACE. If the handler only
exposes IPropertyStore for a read/write stream, we can wrap Office types too and
keep their native Details columns while adding the 备注 column.
"""
import ctypes
import os
import sys
from ctypes import POINTER, byref, c_void_p, c_uint32, c_uint16, c_wchar_p

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ole32 = ctypes.WinDLL("ole32")
shlwapi = ctypes.WinDLL("shlwapi")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLES = os.path.join(ROOT, "build", "_chain_matrix")

IID_IUnknown = "{00000000-0000-0000-C000-000000000046}"
IID_IPropertyStore = "{886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99}"
IID_IInitializeWithStream = "{B824B49D-22AC-4161-AC8A-9916E8FA3F7F}"
IID_IInitializeWithFile = "{B7D14566-0509-4CCE-A71F-0A554233BD9B}"
IID_IInitializeWithItem = "{7F73BE3F-FB79-493C-A6C7-7EE14E245841}"

STGM_READ = 0x00000000
STGM_WRITE = 0x00000001
STGM_READWRITE = 0x00000002
STGM_SHARE_DENY_NONE = 0x00000040
FILE_ATTRIBUTE_NORMAL = 0x80


class GUID(ctypes.Structure):
    _fields_ = [("Data1", c_uint32), ("Data2", c_uint16), ("Data3", c_uint16),
                ("Data4", ctypes.c_ubyte * 8)]


def guid(s):
    p = s.strip("{}").split("-")
    g = GUID()
    g.Data1 = int(p[0], 16)
    g.Data2 = int(p[1], 16)
    g.Data3 = int(p[2], 16)
    for i, b in enumerate(bytes.fromhex(p[3] + p[4])):
        g.Data4[i] = b
    return g


def hx(v):
    return f"{(v & 0xFFFFFFFF):#010x}"


def vcall(obj, index, restype, *argtypes):
    vtbl = ctypes.cast(obj, POINTER(POINTER(c_void_p)))[0]
    fn = ctypes.WINFUNCTYPE(restype, c_void_p, *argtypes)(vtbl[index])
    return lambda *a: fn(obj, *a)


def open_stream(path, mode):
    shlwapi.SHCreateStreamOnFileEx.argtypes = [
        c_wchar_p, c_uint32, c_uint32, ctypes.c_int, c_void_p, POINTER(c_void_p)]
    shlwapi.SHCreateStreamOnFileEx.restype = ctypes.c_long
    st = c_void_p()
    hr = shlwapi.SHCreateStreamOnFileEx(path, mode, FILE_ATTRIBUTE_NORMAL, 0, None, byref(st))
    return (hr & 0xFFFFFFFF), st


def try_wrap(clsid_str, path):
    clsid = guid(clsid_str)
    ole32.CoCreateInstance.argtypes = [
        POINTER(GUID), c_void_p, c_uint32, POINTER(GUID), POINTER(c_void_p)]
    ole32.CoCreateInstance.restype = ctypes.c_long
    punk = c_void_p()
    hr = ole32.CoCreateInstance(byref(clsid), None, 1, byref(guid(IID_IUnknown)), byref(punk))
    if (hr & 0xFFFFFFFF) != 0 or not punk:
        print(f"    CoCreateInstance hr={hx(hr)}")
        return

    QI = vcall(punk, 0, ctypes.c_long, POINTER(GUID), POINTER(c_void_p))
    for name in ("IInitializeWithItem", "IInitializeWithFile", "IInitializeWithStream"):
        p = c_void_p()
        print(f"    QI({name}) hr={hx(QI(byref(guid({'IInitializeWithItem': IID_IInitializeWithItem, 'IInitializeWithFile': IID_IInitializeWithFile, 'IInitializeWithStream': IID_IInitializeWithStream}[name])), byref(p)))}")

    # Try every init path with every stream mode.
    attempts = []
    for mode_name, mode in (("READ", STGM_READ | STGM_SHARE_DENY_NONE),
                            ("READWRITE", STGM_READWRITE | STGM_SHARE_DENY_NONE)):
        hr, st = open_stream(path, mode)
        if (hr & 0xFFFFFFFF) != 0:
            print(f"    open_stream({mode_name}) hr={hx(hr)}")
            continue
        pStream = c_void_p()
        if (QI(byref(guid(IID_IInitializeWithStream)), byref(pStream)) & 0xFFFFFFFF) == 0 and pStream:
            Init = vcall(pStream, 3, ctypes.c_long, c_void_p, c_uint32)
            ihr = Init(st, 0)
            ps = c_void_p()
            qhr = QI(byref(guid(IID_IPropertyStore)), byref(ps))
            print(f"    stream-init[{mode_name}] hr={hx(ihr)} QI(IPropertyStore)={hx(qhr)}")
            if (qhr & 0xFFFFFFFF) == 0 and ps:
                GetCount = vcall(ps, 3, ctypes.c_long, POINTER(c_uint32))
                cnt = c_uint32()
                print(f"      GetCount hr={hx(GetCount(byref(cnt)))} count={cnt.value}")
                attempts.append(mode_name)
                break
    if not attempts:
        print("    -> no working wrap path")


def main():
    hr = ole32.CoInitializeEx(None, 0x2)
    print(f"CoInitializeEx hr={hx(hr)}")
    try:
        import winreg
        targets = [".docx", ".xls", ".xlsx", ".doc", ".pptx", ".mp3", ".mp4", ".rtf", ".odt"]
        for ext in targets:
            sample = os.path.join(SAMPLES, "sample" + ext)
            if not os.path.exists(sample):
                print(f"{ext:6s} (no sample)")
                continue
            clsid = None
            for root, path in ((winreg.HKEY_LOCAL_MACHINE,
                                r"SOFTWARE\Microsoft\Windows\CurrentVersion\PropertySystem\PropertyHandlers" + "\\" + ext),
                               (winreg.HKEY_LOCAL_MACHINE,
                                r"SOFTWARE\Classes" + "\\" + ext + r"\ShellEx\PropertyHandler")):
                try:
                    with winreg.OpenKey(root, path) as k:
                        clsid = winreg.QueryValueEx(k, "")[0]
                        break
                except OSError:
                    continue
            print(f"{ext:6s} clsid={clsid}")
            if clsid:
                try_wrap(clsid, sample)
    finally:
        ole32.CoUninitialize()
    return 0


if __name__ == "__main__":
    sys.exit(main())
