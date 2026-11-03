# -*- coding: utf-8 -*-
"""Can a plain file carry its remark in the NTFS "Summary Information" stream?

Explorer's 备注 column for a file type that Window ships a handler for is served
by that native handler, and the one Windows uses for most types (for `.exe`:
{66742402-F9B9-11D1-A202-0000F81FEDEE}) reads the OLE property set that lives in
the file's ``SummaryInformation`` stream. On an .exe that stream does not exist,
so the handler fails with 0x80070715 (ERROR_RESOURCE_TYPE_NOT_FOUND) and the
column comes up empty.

This probe answers the question that decides the fix: if we write PIDSI_COMMENTS
into that stream ourselves, does the native handler then report it as
System.Comment?  Usage:

    python tools/probe_summary_stream.py <file> [text]
"""
import ctypes
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ole32 = ctypes.WinDLL("ole32", use_last_error=True)

STGM_READWRITE = 0x00000002
STGM_SHARE_EXCLUSIVE = 0x00000010
STGFMT_FILE = 3
PRSPEC_PROPID = 0
VT_LPWSTR = 31
PIDSI_COMMENTS = 6


class GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_ulong), ("Data2", ctypes.c_ushort),
                ("Data3", ctypes.c_ushort), ("Data4", ctypes.c_ubyte * 8)]


def guid(s):
    out = GUID()
    ole32.CLSIDFromString(s, ctypes.byref(out))
    return out


class PROPSPEC(ctypes.Structure):
    _fields_ = [("ulKind", ctypes.c_ulong), ("propid", ctypes.c_ulong)]


class PROPVARIANT(ctypes.Structure):
    _fields_ = [("vt", ctypes.c_ushort), ("r1", ctypes.c_ushort),
                ("r2", ctypes.c_ushort), ("r3", ctypes.c_ushort),
                ("data", ctypes.c_ulonglong)]


IID_IPropertySetStorage = guid("{0000013A-0000-0000-C000-000000000046}")
IID_IPropertyStorage = guid("{00000138-0000-0000-C000-000000000046}")
FMTID_SummaryInformation = guid("{F29F85E0-4FF9-1068-AB91-08002B27B3D9}")


def vtbl_of(obj):
    return ctypes.cast(ctypes.cast(obj, ctypes.POINTER(ctypes.c_void_p))[0],
                       ctypes.POINTER(ctypes.c_void_p))


def write_comment(path, text):
    pss = ctypes.c_void_p()
    ole32.StgCreateStorageEx.argtypes = [
        ctypes.c_wchar_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong,
        ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(GUID),
        ctypes.POINTER(ctypes.c_void_p)]
    ole32.StgCreateStorageEx.restype = ctypes.c_long
    hr = ole32.StgCreateStorageEx(
        path, STGM_READWRITE | STGM_SHARE_EXCLUSIVE, STGFMT_FILE, 0,
        None, None, ctypes.byref(IID_IPropertySetStorage), ctypes.byref(pss))
    print("  StgCreateStorageEx hr=0x%08X" % (hr & 0xFFFFFFFF))
    if hr < 0:
        return hr

    v = vtbl_of(pss)
    open_ps = ctypes.WINFUNCTYPE(
        ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(GUID),
        ctypes.c_ulong, ctypes.c_ulong, ctypes.POINTER(ctypes.c_void_p))(v[4])
    release_pss = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(v[2])

    ps = ctypes.c_void_p()
    hr = open_ps(pss, ctypes.byref(FMTID_SummaryInformation),
                 STGM_READWRITE | STGM_SHARE_EXCLUSIVE, 0, ctypes.byref(ps))
    print("  Open(SummaryInformation) hr=0x%08X" % (hr & 0xFFFFFFFF))
    if hr < 0:
        release_pss(pss)
        return hr

    pv = PROPVARIANT()
    pv.vt = VT_LPWSTR
    pv.data = ctypes.cast(ctypes.c_wchar_p(text), ctypes.c_void_p).value
    spec = PROPSPEC(PRSPEC_PROPID, PIDSI_COMMENTS)
    v2 = vtbl_of(ps)
    # IPropertyStorage: QI,AddRef,Release,WriteMultiple,ReadMultiple,...
    write_multi = ctypes.WINFUNCTYPE(
        ctypes.c_long, ctypes.c_void_p, ctypes.c_ulong,
        ctypes.POINTER(PROPSPEC), ctypes.POINTER(PROPVARIANT))(v2[3])
    commit = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p)(v2[11])
    release_ps = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(v2[2])

    hr = write_multi(ps, 1, ctypes.byref(spec), ctypes.byref(pv))
    print("  WriteMultiple(PIDSI_COMMENTS) hr=0x%08X" % (hr & 0xFFFFFFFF))
    hr2 = commit(ps)
    print("  Commit hr=0x%08X" % (hr2 & 0xFFFFFFFF))
    release_ps(ps)
    release_pss(pss)
    return hr


def main():
    if len(sys.argv) < 2:
        print("usage: python tools/probe_summary_stream.py <file> [text]")
        return 2
    path = os.path.abspath(sys.argv[1])
    text = sys.argv[2] if len(sys.argv) > 2 else "Summary Information 里的备注"
    ole32.CoInitializeEx(None, 2)
    print(path)
    write_comment(path, text)
    print("  now check with: python tools/probe_store_value.py \"%s\"" % path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
