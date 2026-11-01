# -*- coding: utf-8 -*-
"""A minimal, real IDataObject carrying CF_HDROP, built in Python.

SHCreateDataObject does not reliably expose CF_HDROP for a single item, so this
implements the interface directly: exactly what Explorer hands to a context-menu
handler for a file selection.
"""
import ctypes
from ctypes import (POINTER, byref, c_void_p, c_uint32, c_uint16, c_ubyte,
                    c_int, Structure, WINFUNCTYPE)

kernel32 = ctypes.WinDLL("kernel32")

HRESULT = ctypes.c_long
ULONG = ctypes.c_ulong
DWORD = ctypes.c_uint32
LPUNKNOWN = c_void_p
BOOL = c_int

CF_HDROP = 15
TYMED_HGLOBAL = 1
GMEM_MOVEABLE = 0x0002
GMEM_ZEROINIT = 0x0040

DV_E_FORMATETC = 0x80040064
E_NOINTERFACE = 0x80004002
E_NOTIMPL = 0x80004001
E_FAIL = 0x80004005


class GUID(Structure):
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


IID_IDataObject = "{0000010E-0000-0000-C000-000000000046}"


class FORMATETC(Structure):
    _fields_ = [("cfFormat", c_uint16), ("ptd", c_void_p), ("dwAspect", DWORD),
                ("lindex", ctypes.c_long), ("tymed", DWORD)]


class STGMEDIUM(Structure):
    _fields_ = [("tymed", DWORD), ("hGlobal", c_void_p), ("pUnkForRelease", c_void_p)]


class DROPFILES(Structure):
    _fields_ = [("pFiles", DWORD), ("x", ctypes.c_long), ("y", ctypes.c_long),
                ("fNC", c_int), ("fWide", c_int)]


# Prototypes for the vtable slots we actually implement.
P_QI = WINFUNCTYPE(HRESULT, c_void_p, POINTER(GUID), POINTER(c_void_p))
P_ADDREF = WINFUNCTYPE(ULONG, c_void_p)
P_RELEASE = WINFUNCTYPE(ULONG, c_void_p)
P_GETDATA = WINFUNCTYPE(HRESULT, c_void_p, POINTER(FORMATETC), POINTER(STGMEDIUM))
P_GETDATAHERE = WINFUNCTYPE(HRESULT, c_void_p, POINTER(FORMATETC), POINTER(STGMEDIUM))
P_QUERYGETDATA = WINFUNCTYPE(HRESULT, c_void_p, POINTER(FORMATETC))
P_CANON = WINFUNCTYPE(HRESULT, c_void_p, POINTER(FORMATETC), POINTER(FORMATETC))
P_SETDATA = WINFUNCTYPE(HRESULT, c_void_p, POINTER(FORMATETC), POINTER(STGMEDIUM), BOOL)
P_ENUMFMT = WINFUNCTYPE(HRESULT, c_void_p, DWORD, POINTER(c_void_p))
P_ADVISE = WINFUNCTYPE(HRESULT, c_void_p, POINTER(FORMATETC), DWORD, c_void_p, POINTER(DWORD))
P_UNADVISE = WINFUNCTYPE(HRESULT, c_void_p, DWORD)
P_ENUMADVISE = WINFUNCTYPE(HRESULT, c_void_p, POINTER(c_void_p))


def _hglobal_drop(paths):
    text = "".join(p + "\0" for p in paths) + "\0"
    data = text.encode("utf-16-le")
    header_size = ctypes.sizeof(DROPFILES)
    kernel32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = c_void_p
    kernel32.GlobalLock.argtypes = [c_void_p]
    kernel32.GlobalLock.restype = c_void_p
    kernel32.GlobalUnlock.argtypes = [c_void_p]
    kernel32.GlobalUnlock.restype = BOOL
    h = kernel32.GlobalAlloc(GMEM_MOVEABLE | GMEM_ZEROINIT, header_size + len(data))
    assert h, "GlobalAlloc failed"
    p = kernel32.GlobalLock(h)
    hdr = DROPFILES()
    hdr.pFiles = header_size
    hdr.fWide = 1
    ctypes.memmove(p, byref(hdr), header_size)
    ctypes.memmove(p + header_size, data, len(data))
    kernel32.GlobalUnlock(h)
    return h


class DataObject:
    """IUnknown + IDataObject, exposing CF_HDROP only."""

    def __init__(self, paths):
        self.hglobal = _hglobal_drop(paths)
        self.refs = 1
        # Bound methods must be wrapped in the right prototype before their
        # addresses go into the vtable.
        self.qi = P_QI(self._qi)
        self.addref = P_ADDREF(self._addref)
        self.release = P_RELEASE(self._release)
        self.getdata = P_GETDATA(self._get_data)
        self.getdatahere = P_GETDATAHERE(self._get_data_here)
        self.querygetdata = P_QUERYGETDATA(self._query_get_data)
        self.canon = P_CANON(self._get_canonical)
        self.setdata = P_SETDATA(self._set_data)
        self.enumfmt = P_ENUMFMT(self._enum_format_etc)
        self.advise = P_ADVISE(self._dadvise)
        self.unadvise = P_UNADVISE(self._dunadvise)
        self.enumadvise = P_ENUMADVISE(self._enum_dadvise)

        entries = [self.qi, self.addref, self.release, self.getdata, self.getdatahere,
                   self.querygetdata, self.canon, self.setdata, self.enumfmt,
                   self.advise, self.unadvise, self.enumadvise]
        vtable = (c_void_p * len(entries))()
        for i, fn in enumerate(entries):
            vtable[i] = ctypes.cast(fn, c_void_p)
        self._vtable = vtable
        # COM identifies an interface by a pointer to its vtable pointer.
        self._vtable_ptr = ctypes.cast(vtable, c_void_p)
        self.ptr = ctypes.cast(byref(self._vtable_ptr), c_void_p)

    # IUnknown
    def _qi(self, this, riid, ppv):
        g = riid[0]
        want = guid(IID_IDataObject)
        same = (g.Data1 == want.Data1 and g.Data2 == want.Data2 and
                g.Data3 == want.Data3 and bytes(g.Data4) == bytes(want.Data4))
        if same:
            ppv[0] = self._vtable_ptr
            self.refs += 1
            return 0
        ppv[0] = None
        return E_NOINTERFACE

    def _addref(self, this):
        self.refs += 1
        return self.refs

    def _release(self, this):
        self.refs -= 1
        return self.refs

    # IDataObject
    def _get_data(self, this, pformatetc, pmedium):
        fe = pformatetc[0]
        if fe.cfFormat != CF_HDROP or not (fe.tymed & TYMED_HGLOBAL):
            return DV_E_FORMATETC
        pmedium[0].tymed = TYMED_HGLOBAL
        pmedium[0].hGlobal = self.hglobal
        pmedium[0].pUnkForRelease = None
        return 0

    def _get_data_here(self, this, pformatetc, pmedium):
        return E_NOTIMPL

    def _query_get_data(self, this, pformatetc):
        fe = pformatetc[0]
        return 0 if (fe.cfFormat == CF_HDROP and (fe.tymed & TYMED_HGLOBAL)) else DV_E_FORMATETC

    def _get_canonical(self, this, pin, pout):
        return E_NOTIMPL

    def _set_data(self, this, pformatetc, pmedium, fRelease):
        return E_NOTIMPL

    def _enum_format_etc(self, this, direction, ppenum):
        return E_NOTIMPL

    def _dadvise(self, this, pformatetc, advf, sink, pconn):
        return E_NOTIMPL

    def _dunadvise(self, this, conn):
        return E_NOTIMPL

    def _enum_dadvise(self, this, ppenum):
        return E_NOTIMPL


def make_data_object(paths):
    return DataObject(paths)
