# -*- coding: utf-8 -*-
"""Ask Explorer what the 备注 column shows for one file, and why it is empty.

Explorer and PowerShell ask the property system for ``System.Comment``; the
editor asks the ADS (``<file>:remark``) directly. When those disagree the
column is broken even though the remark is on disk, so this probe prints the
two side by side, per file type:

    python tools/probe_column_type.py build\\_exetest\\a.exe

It reports

  * the ADS value  (what the editor reads and writes),
  * the 备注 column value as Explorer sees it, via Shell.Application,
  * the property-handler CLSID registered for the extension, in HKCU and HKLM.

Exit code 0 when the column matches the ADS for every file given, 1 otherwise.
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = os.path.join(ROOT, "build", "_column_type")
REMARK = "列里应该显示的备注"


def ads_value(path):
    try:
        with open(path + ":remark", "r", encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return None


def column_value(path):
    """Read the 備注 column the way Explorer does: Shell.Application.GetDetailsOf."""
    os.makedirs(WORK, exist_ok=True)
    out = os.path.join(WORK, "out.txt")
    if os.path.exists(out):
        os.remove(out)
    script = os.path.join(WORK, "read.ps1")
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
""" % (path, out, out)
    with open(script, "w", encoding="utf-8-sig") as fh:
        fh.write(ps)
    subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                    "-File", script], shell=True, stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL)
    if not os.path.exists(out):
        return "<no answer>"
    with open(out, encoding="utf-8") as fh:
        raw = fh.read()
    return raw.split("|", 1)[1] if "|" in raw else raw


def handler_for(ext):
    import winreg
    got = {}
    for label, root in (("HKCU", winreg.HKEY_CURRENT_USER),
                        ("HKLM", winreg.HKEY_LOCAL_MACHINE)):
        for shape in ("Software\\Classes\\%s\\ShellEx\\PropertyHandler" % ext,
                      "Software\\Microsoft\\Windows\\CurrentVersion\\PropertySystem"
                      "\\PropertyHandlers\\%s" % ext):
            try:
                with winreg.OpenKey(root, shape) as key:
                    got[label] = winreg.QueryValueEx(key, "")[0]
            except OSError:
                pass
    return got


def main():
    files = sys.argv[1:]
    if not files:
        print("usage: python tools/probe_column_type.py <file> [file ...]")
        return 2
    bad = 0
    for path in files:
        path = os.path.abspath(path)
        if not os.path.exists(path):
            print("%s  MISSING" % path)
            bad += 1
            continue
        ext = os.path.splitext(path)[1].lower()
        want = ads_value(path)
        got = column_value(path)
        handlers = handler_for(ext)
        same = (want or "") == (got or "")
        print("%s" % path)
        print("   ads      : %r" % want)
        print("   column   : %r" % got)
        print("   handlers : %s" % (handlers or "(none)"))
        print("   %s" % ("OK  column matches the remark" if same
                         else "BAD column does not show the remark"))
        if not same:
            bad += 1
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
