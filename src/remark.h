// Shared declarations for the FileRemarks remark data stream and the public
// CLSID, so the property handler, the context menu and the in-process tests
// can agree on them.
#ifndef FILEREMARKS_REMARK_H
#define FILEREMARKS_REMARK_H

#include <windows.h>
#include <propkey.h>

// {B4C8E6D1-7A2F-4c3b-9D5E-1F6C2A8B3D41}
extern "C" const CLSID CLSID_FileRemarksPropHandler;

// The remark is published as the property Windows itself calls "备注"
// (System.Comment, {F29F85E0-4FF9-1068-AB91-08002B27B3D9} pid 6). Windows
// already ships a property description for it -- display name "备注", edit
// invitation "添加备注" -- so Explorer's own 备注 column shows our value and no
// custom .propdesc has to be registered. PKEY_Comment comes from propkey.h.

// Name of the NTFS Alternate Data Stream that stores the remark (UTF-8 text).
#define FILEREMARKS_ADS_NAME L":remark"

#endif // FILEREMARKS_REMARK_H
