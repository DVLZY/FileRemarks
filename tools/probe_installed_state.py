# -*- coding: utf-8 -*-
"""Read-only snapshot: is FileRemarks registered on this machine right now?"""
import winreg

OURS = "{B4C8E6D1-7A2F-4c3b-9D5E-1F6C2A8B3D41}"
PS = r"SOFTWARE\Microsoft\Windows\CurrentVersion\PropertySystem\PropertyHandlers"


def rd(root, path, val=None):
    try:
        with winreg.OpenKey(root, path, 0, winreg.KEY_READ) as k:
            return winreg.QueryValueEx(k, val)[0]
    except OSError:
        return None


print("=== our CLSID ===")
key = r"SOFTWARE\Classes\CLSID\\" + OURS
print("default        :", rd(winreg.HKEY_LOCAL_MACHINE, key))
inproc = key + r"\InprocServer32"
print("InprocServer32 :", rd(winreg.HKEY_LOCAL_MACHINE, inproc))
print("ThreadingModel :", rd(winreg.HKEY_LOCAL_MACHINE, inproc, "ThreadingModel"))
print("DisableProcIso :", rd(winreg.HKEY_LOCAL_MACHINE, key, "DisableProcessIsolation"))
print("ManualSafeSave :", rd(winreg.HKEY_LOCAL_MACHINE, key, "ManualSafeSave"))

print("\n=== associations ===")
print("wildcard *     :", rd(winreg.HKEY_LOCAL_MACHINE,
                             r"SOFTWARE\Classes\*\shellex\PropertyHandler"))
ctx = rd(winreg.HKEY_LOCAL_MACHINE,
         r"SOFTWARE\Classes\*\shellex\ContextMenuHandlers\FileRemarks")
print("* context menu :", ctx)

print("\n=== per-extension ===")
for ext in (".jpg", ".png", ".exe", ".dll", ".py", ".md", ".txt", ".docx",
            ".doc", ".xlsx", ".mp3", ".zip", ".pdf", ".rtf", ".7z"):
    a = rd(winreg.HKEY_LOCAL_MACHINE, PS + "\\" + ext)
    b = rd(winreg.HKEY_LOCAL_MACHINE,
           r"SOFTWARE\Classes\\" + ext + r"\ShellEx\PropertyHandler")
    tag_a = "OURS" if (a or "").upper() == OURS.upper() else (a or "-")
    tag_b = "OURS" if (b or "").upper() == OURS.upper() else (b or "-")
    print("  %-6s PropertyHandlers=%-40s ShellEx=%s" % (ext, tag_a, tag_b))

print("\n=== our bookkeeping ===")
for name in ("Original", "Pinned", "ColumnList"):
    path = r"SOFTWARE\FileRemarks\\" + name
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path, 0, winreg.KEY_READ) as k:
            n = winreg.QueryInfoKey(k)[0]
            print("  %-10s exists, %d subkeys" % (name, n))
    except OSError:
        print("  %-10s absent" % name)

print("\n=== ARP (uninstall entry) ===")
arp = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\FileRemarks"
print("  DisplayName     :", rd(winreg.HKEY_LOCAL_MACHINE, arp, "DisplayName"))
print("  UninstallString :", rd(winreg.HKEY_LOCAL_MACHINE, arp, "UninstallString"))

print("\n=== column defaults (FolderTypes Generic) ===")
for ft in ("{5c4f28b5-f869-4e84-8e60-f11db97c5cc7}",
           "{7d49d726-3c21-4f05-99aa-fdc2c9474656}"):
    vk = (r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\FolderTypes\\" + ft +
          r"\TopViews\{00000000-0000-0000-0000-000000000000}")
    cl = rd(winreg.HKEY_LOCAL_MACHINE, vk, "ColumnList")
    print("  %s" % ft)
    print("    %s" % cl)
    print("    has System.Comment: %s" % ("System.Comment" in (cl or "")))
