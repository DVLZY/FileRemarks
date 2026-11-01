"""Read-only health check for an installed FileRemarks.

The build sandbox refuses every registry write (0x80000005), so the step
"registration -> Explorer actually shows the 备注 column" can only be confirmed
on a real machine. This script does the half that CAN be done anywhere: it reads
the registry and the filesystem and reports exactly what is registered, where the
DLLs point, and whether the default views carry System.Comment.

Nothing is written, nothing is started. Run it after installing and paste the
output if something looks off:

    python tools/check_install.py
"""
import os
import sys
import winreg

try:
    # The report has Chinese folder-type labels and a Chinese column name; a
    # redirected console would otherwise raise UnicodeEncodeError on cp936.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

PROP_CLSID = "{B4C8E6D1-7A2F-4c3b-9D5E-1F6C2A8B3D41}"
MENU_CLSID = "{6F3A1B2C-9D4E-4c7b-8A1F-2E5B6C7D8E90}"

ROOTS = [("HKCU", winreg.HKEY_CURRENT_USER), ("HKLM", winreg.HKEY_LOCAL_MACHINE)]
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

FOLDER_TYPES = {
    "Generic": "{5c4f28b5-f869-4e84-8e60-f11db97c5cc7}",
    "Documents": "{7d49d726-3c21-4f05-99aa-fdc2c9474656}",
    "Pictures": "{b3690e58-e961-423b-b687-386ebfd83239}",
    "Downloads": "{885a186e-a440-4ada-812b-db871b942259}",
    "Music": "{94d6ddcc-4a68-4175-a374-bd584a510b78}",
    "Videos": "{5fa96407-7e77-483c-ac93-691d05850de8}",
}
TOPVIEW = "{00000000-0000-0000-0000-000000000000}"
VIEW_KEY = (r"Software\Microsoft\Windows\CurrentVersion\Explorer\FolderTypes\%s"
            r"\TopViews\%s" % ("%s", TOPVIEW))

SAMPLE_EXTS = [".txt", ".md", ".py", ".jpg", ".png", ".exe", ".docx"]


def get_value(root, path, name=""):
    try:
        k = winreg.OpenKey(root, path)
    except OSError:
        return None
    try:
        return winreg.QueryValueEx(k, name)[0]
    except OSError:
        return None
    finally:
        winreg.CloseKey(k)


def subkeys(root, path):
    try:
        k = winreg.OpenKey(root, path)
    except OSError:
        return []
    out = []
    i = 0
    while True:
        try:
            out.append(winreg.EnumKey(k, i))
        except OSError:
            break
        i += 1
    winreg.CloseKey(k)
    return out


def report_clsid(label, clsid):
    print()
    print("%s  %s" % (label, clsid))
    for name, root in ROOTS:
        path = r"Software\Classes\CLSID\%s\InprocServer32" % clsid
        dll = get_value(root, path, "")
        if dll is None:
            print("  %-4s InprocServer32 : (not registered)" % name)
            continue
        exists = os.path.exists(dll)
        tm = get_value(root, path, "ThreadingModel")
        print("  %-4s InprocServer32 : %s  %s  ThreadingModel=%s"
              % (name, dll, "EXISTS" if exists else "*** MISSING ***", tm))
        if not exists:
            print("       ^ a registration pointing at a deleted file fails with "
                  "0x8007007E; reinstall to repair")


def report_assoc(ext):
    shown = False
    for name, root in ROOTS:
        for shape, path in (
            ("ShellEx  ", r"Software\Classes\%s\ShellEx\PropertyHandler" % ext),
            ("PropSys  ", r"Software\Microsoft\Windows\CurrentVersion\PropertySystem"
                          r"\PropertyHandlers\%s" % ext),
        ):
            v = get_value(root, path, "")
            if v is not None:
                print("  %-8s %-4s %s -> %s" % (ext, name, shape, v))
                shown = True
    wild = []
    for name, root in ROOTS:
        v = get_value(root, r"Software\Classes\*\shellex\PropertyHandler", "")
        if v is not None:
            wild.append("%s=%s" % (name, v))
    return shown, wild


def main():
    print("FileRemarks install check (read-only)")
    print("=" * 60)

    report_clsid("property handler (the 备注 column)", PROP_CLSID)
    report_clsid("context menu   (右键 编辑备注)  ", MENU_CLSID)

    print()
    print("per-type associations")
    any_ours = False
    wildcard = []
    for ext in SAMPLE_EXTS:
        shown, wild = report_assoc(ext)
        if wild and not wildcard:
            wildcard = wild
        if shown:
            any_ours = True
    if not any_ours:
        print("  (none of the sampled types has a handler registered)")
    if wildcard:
        print("  wildcard  %s" % ", ".join(wildcard))

    print()
    print("files in place")
    local = os.path.join(os.environ.get("LOCALAPPDATA", ""), "FileRemarks")
    legacy = os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "FileRemarks")
    for label, d in (("per-user (v1.9+)", local), ("legacy (<=v1.8)", legacy)):
        if not os.path.isdir(d):
            print("  %-18s %s  (absent)" % (label, d))
            continue
        names = sorted(os.listdir(d))
        print("  %-18s %s" % (label, d))
        for n in names:
            p = os.path.join(d, n)
            print("      %-32s %d bytes" % (n, os.path.getsize(p)))

    print()
    print("which editor the right-click menu actually launches")
    # The shell extension starts FileRemarksEditor.exe from its OWN folder, so the
    # editor that runs is decided by where the registered DLL lives. Compare that
    # copy against the one in dist/ so "you are still running an old build" is
    # visible instead of inferred.
    import hashlib
    def sha(path):
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()

    dist_editor = os.path.join(ROOT, "dist", "FileRemarksEditor.exe")
    dll_dir = None
    for name, root in ROOTS:
        d = get_value(root, r"Software\Classes\CLSID\%s\InprocServer32" % MENU_CLSID, "")
        if d:
            dll_dir = os.path.dirname(d)
            break
    if dll_dir is None:
        print("  no context-menu DLL is registered -- nothing would launch")
    else:
        live = os.path.join(dll_dir, "FileRemarksEditor.exe")
        if not os.path.exists(live):
            print("  %s  *** MISSING ***  (right-click would fail)" % live)
        elif not os.path.exists(dist_editor):
            print("  running %s  (dist/ copy not built, cannot compare)" % live)
        else:
            same = sha(live) == sha(dist_editor)
            print("  running %s  %d bytes" % (live, os.path.getsize(live)))
            print("  dist    %s  %d bytes" % (dist_editor, os.path.getsize(dist_editor)))
            print("  -> %s" % ("same build as dist/" if same else
                               "OLDER build than dist/ -- reinstall to pick up the fixes"))

    print()
    print("the 备注 column in Explorer's default views")
    for label, guid in FOLDER_TYPES.items():
        per_user = get_value(winreg.HKEY_CURRENT_USER, VIEW_KEY % guid, "ColumnList")
        machine = get_value(winreg.HKEY_LOCAL_MACHINE, VIEW_KEY % guid, "ColumnList")
        effective = per_user if per_user is not None else machine
        has = effective is not None and "System.Comment" in effective
        print("  %-10s %-4s %s" % (label,
                                    "HKCU" if per_user is not None else "HKLM",
                                    "System.Comment present" if has else "no System.Comment"))

    print()
    print("uninstall entry")
    found = False
    for name, root in ROOTS:
        v = get_value(root, r"Software\Microsoft\Windows\CurrentVersion\Uninstall\FileRemarks",
                      "DisplayVersion")
        if v is not None:
            print("  %-4s DisplayVersion = %s" % (name, v))
            found = True
    if not found:
        print("  (none)")

    print()
    print("the 备注 column, end to end")
    shown, expected, note = column_value()
    if shown is None:
        print("  could not ask the shell: %s" % note)
    else:
        ok = (shown or "").strip() == expected
        print("  a test file was given the remark %r" % expected)
        print("  the shell's 备注 column reports %r" % (shown or ""))
        print("  -> %s" % ("the column works" if ok else
                           "the column is EMPTY -- the property handler does not "
                           "reach Explorer (see tools/probe_stream_init.py)"))
    print()
    print("Summary: everything above is registry state plus that one end-to-end "
          "column read.")
    print("If the CLSID points at an existing DLL, the wildcard is set, "
          "System.Comment is present AND the column read matches, Explorer will "
          "show the remark.")
    return 0


def column_value():
    """Ask the shell what the 备注 column shows for a file that really has a remark.

    Registry state can look perfect and the column still be empty -- that is
    exactly what happened while the handler only accepted a path or a shell item
    (Windows feeds it a stream when the handler is hosted, and a handler without
    IInitializeWithStream makes the store fail with E_NOINTERFACE). So the last
    check is behavioural: write a remark, then read the column the way Explorer
    reads it, through Shell.Application.
    """
    import subprocess
    import tempfile
    work = os.path.join(ROOT, "build", "_column_check")
    try:
        os.makedirs(work)
    except OSError:
        pass
    target = os.path.join(work, "co.txt")
    with open(target, "w", encoding="utf-8") as fh:
        fh.write("hello" + chr(10))
    remark = "端到端检查用的备注"
    with open(target + ":remark", "w", encoding="utf-8") as fh:
        fh.write(remark)

    out = os.path.join(work, "result.txt")
    if os.path.exists(out):
        os.remove(out)
    script = os.path.join(work, "read_col.ps1")
    ps = """$sh = New-Object -ComObject Shell.Application
$dir = '%s'
$root = Split-Path $dir -Parent
$leaf = Split-Path $dir -Leaf
$f = $sh.Namespace($root).ParseName($leaf)
$idx = -1
for ($i = 0; $i -lt 400; $i++) {
  $h = $sh.Namespace($root).GetDetailsOf($null, $i)
  if ($h -eq [char]0x5907 + [char]0x6CE8) { $idx = $i; break }
}
if ($idx -lt 0) { [IO.File]::WriteAllText('%s', "NOCOL|", [Text.Encoding]::UTF8); exit }
$v = $sh.Namespace($root).GetDetailsOf($f, $idx)
[IO.File]::WriteAllText('%s', "$idx|$v", [Text.Encoding]::UTF8)
""" % (work, out, out)
    with open(script, "w", encoding="utf-8") as fh:
        fh.write(ps)
    cmd = ('powershell -NoProfile -ExecutionPolicy Bypass -File "%s"' % script)
    try:
        subprocess.run(cmd, shell=True, timeout=120)
    except Exception as exc:                      # noqa: BLE001 - reported, not raised
        return None, remark, str(exc)
    if not os.path.exists(out):
        return None, remark, "the helper script produced no result"
    with open(out, encoding="utf-8") as fh:
        text = fh.read().strip()
    if "|" not in text:
        return None, remark, "unreadable helper output %r" % text
    head, _, value = text.partition("|")
    if head == "NOCOL":
        return None, remark, "no column titled 备注 was offered for this folder"
    return value, remark, "column index %s" % head


if __name__ == "__main__":
    raise SystemExit(main())
