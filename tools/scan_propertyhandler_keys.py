# -*- coding: utf-8 -*-
"""Read-only scan: find every 'PropertyHandler' shell-extension key registered
anywhere under HKCR / HKCU\\Software\\Classes, and show its parent + value.

This tells us empirically WHICH registration shapes real software uses, and
whether the wildcard '*' form is ever used.
"""
import winreg
import sys

MAX_KEYS = 400000


def scan(root, root_name, report):
    stack = [("", root)]
    n = 0
    while stack:
        path, h = stack.pop()
        try:
            i = 0
            while True:
                try:
                    name = winreg.EnumKey(h, i)
                except OSError:
                    break
                i += 1
                n += 1
                if n > MAX_KEYS:
                    return
                full = path + "\\" + name if path else name
                try:
                    sub = winreg.OpenKey(h, name, 0, winreg.KEY_READ)
                except OSError:
                    continue
                if name.lower() == "propertyhandler":
                    try:
                        val, typ = winreg.QueryValueEx(sub, "")
                    except OSError:
                        val, typ = None, None
                    report.append((root_name + "\\" + full, val, typ))
                # limit depth to keep it sane (CLSID\{..}\shellex\PropertyHandler is depth 4)
                if full.count("\\") < 6:
                    stack.append((full, sub))
                else:
                    winreg.CloseKey(sub)
        finally:
            pass


def main():
    report = []
    for hive, name in ((winreg.HKEY_CLASSES_ROOT, "HKCR"),
                       (winreg.HKEY_CURRENT_USER, "HKCU\\Software\\Classes")):
        try:
            if hive == winreg.HKEY_CURRENT_USER:
                root = winreg.OpenKey(hive, r"Software\Classes", 0, winreg.KEY_READ)
                scan(root, name, report)
            else:
                scan(hive, name, report)
        except OSError as e:
            print("open failed", name, e)

    print("found %d PropertyHandler keys" % len(report))
    for path, val, typ in report:
        print("  %-90s = %s  (type %s)" % (path, val, typ))


if __name__ == "__main__":
    sys.exit(main())
