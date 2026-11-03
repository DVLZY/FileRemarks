"""In-process test of the installer's final result box (src/result_msg.h).

The box itself cannot be driven from a sandbox (UAC + MessageBox), so the REAL
text builders are compiled into build/selftest_result.dll and asserted here.
What is checked is exactly what the user reads after 安装 / 重新安装 / 卸载 /
取消 / 失败, plus the marker handshake between the elevated child and the outer
instance (that handshake is why the outer one no longer exits silently).

    python tools/test_installer_result.py
"""
import ctypes
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD = os.path.join(ROOT, "build")

OK, PARTIAL, FAILED = 0, 1, 2
ACTION_INSTALL, ACTION_REINSTALL, ACTION_UNINSTALL = 0, 1, 2

fails = []


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + (("  -> " + detail) if detail else ""))
    if not cond:
        fails.append(name)


try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

dll = ctypes.WinDLL(os.path.join(BUILD, "selftest_result.dll"))
dll.FrTestLogPath.argtypes = [ctypes.c_wchar_p, ctypes.c_int]
dll.FrTestLogPath.restype = ctypes.c_int
dll.FrTestInstallResult.argtypes = [ctypes.c_int, ctypes.c_wchar_p, ctypes.c_wchar_p,
                                    ctypes.c_int, ctypes.c_int,
                                    ctypes.POINTER(ctypes.c_wchar_p), ctypes.c_int,
                                    ctypes.c_wchar_p, ctypes.c_int]
dll.FrTestInstallResult.restype = ctypes.c_int
dll.FrTestUninstallResult.argtypes = [ctypes.c_wchar_p,
                                      ctypes.POINTER(ctypes.c_wchar_p), ctypes.c_int,
                                      ctypes.c_wchar_p, ctypes.c_int]
dll.FrTestUninstallResult.restype = ctypes.c_int
dll.FrTestCancelResult.argtypes = [ctypes.c_wchar_p, ctypes.c_int]
dll.FrTestCancelResult.restype = ctypes.c_int
dll.FrTestFailureResult.argtypes = [ctypes.c_int, ctypes.c_wchar_p, ctypes.c_uint,
                                    ctypes.c_wchar_p, ctypes.c_int]
dll.FrTestFailureResult.restype = ctypes.c_int
dll.FrTestNoResultResult.argtypes = [ctypes.c_wchar_p, ctypes.c_int, ctypes.c_uint,
                                     ctypes.c_wchar_p, ctypes.c_int]
dll.FrTestNoResultResult.restype = ctypes.c_int
dll.FrTestMarkerPath.argtypes = [ctypes.c_wchar_p, ctypes.c_int]
dll.FrTestMarkerPath.restype = ctypes.c_int
dll.FrTestWriteMarker.argtypes = [ctypes.c_wchar_p, ctypes.c_int]
dll.FrTestWriteMarker.restype = ctypes.c_int
dll.FrTestMarkerExists.argtypes = [ctypes.c_wchar_p]
dll.FrTestMarkerExists.restype = ctypes.c_int
dll.FrTestDeleteMarker.argtypes = [ctypes.c_wchar_p]
dll.FrTestDeleteMarker.restype = None

BUF = 2048
DIR = r"C:\Program Files\FileRemarks\app-1.18"
VER = "1.18.0.0"


def warn_array(items):
    arr = (ctypes.c_wchar_p * len(items))(*items) if items else None
    return arr, len(items)


def call(fn, *args):
    buf = ctypes.create_unicode_buffer(BUF)
    return fn(*args, buf, BUF), buf.value


print("[1] the log path the box tells the user to open")
kind, log_path = call(dll.FrTestLogPath)
check("log path names the diagnostic file",
      log_path.endswith("FileRemarks_log.txt"), log_path)
check("log path is absolute", os.path.isabs(log_path), log_path)

print("[2] clean install (6 column types)")
kind, text = call(dll.FrTestInstallResult, 0, DIR, VER, 6, 0, None, 0)
check("clean install reports ok", kind == OK, str(kind))
check("says 已安装到", "已安装到" in text)
check("names the install directory", DIR in text, text)
check("names the version", VER in text)
check("claims the 备注 column is a default column", "“备注”列已经设为默认列" in text, text)
check("warns that already-opened folders keep their saved layout",
      "已经打开过的文件夹会保留原来的列设置" in text, text)
check("tells the user to restart Explorer", "重启“资源管理器”" in text, text)
check("points at the log", log_path in text)

print("[3] re-install into a new app-<ver> folder")
kind, text = call(dll.FrTestInstallResult, 1, DIR, VER, 2, 0, None, 0)
check("re-install reports ok", kind == OK, str(kind))
check("says 已重新安装到", "已重新安装到" in text)
check("partial column coverage is stated, not hidden",
      "2 种文件夹类型" in text, text)

print("[4] install with warnings must NOT look like a clean success")
w = ["“应用和功能”里没有写入卸载条目，卸载时可能找不到本软件"]
arr, n = warn_array(w)
kind, text = call(dll.FrTestInstallResult, 1, DIR, VER, 0, 1, arr, n)
check("install with warnings is Partial", kind == PARTIAL, str(kind))
check("box says 部分项目未完成", "部分项目未完成" in text, text)
check("the warning itself is printed", w[0] in text, text)
check("legacy directory note is printed", "旧版本" in text)

print("[5] uninstall must never be silent")
kind, text = call(dll.FrTestUninstallResult, DIR, None, 0, )
check("clean uninstall reports ok", kind == OK, str(kind))
check("says 已卸载完成", "已卸载完成" in text, text)
check("names what was removed", "右键菜单" in text and "卸载条目" in text)
check("explains the reboot deletion", "重启" in text)
check("points at the log", log_path in text)

print("[6] partial uninstall")
w2 = ["有 2 个登记项没有卸载成功，重启后“备注”列可能仍然显示（详见日志）"]
arr, n = warn_array(w2)
kind, text = call(dll.FrTestUninstallResult, DIR, arr, n)
check("partial uninstall is Partial", kind == PARTIAL, str(kind))
check("says 部分项目没有完全移除", "部分项目没有完全移除" in text, text)
check("prints the failed registrations", w2[0] in text)

print("[7] closing the choice window")
kind, text = call(dll.FrTestCancelResult)
check("cancel reports ok", kind == OK, str(kind))
check("says 已取消", "已取消" in text, text)
check("promises no changes", "未做任何更改" in text)
check("points at the log", log_path in text)

print("[8] failures carry the reason and the error code")
kind, text = call(dll.FrTestFailureResult, ACTION_INSTALL, "复制文件失败：X", 32)
check("install failure is Failed", kind == FAILED, str(kind))
check("says 安装失败", "安装失败" in text)
check("keeps the reason text", "复制文件失败：X" in text, text)
check("formats the error code as hex", "0x00000020" in text, text)
check("points at the log", log_path in text)
kind, text = call(dll.FrTestFailureResult, ACTION_UNINSTALL, "注册项无法删除", 0)
check("uninstall failure says 卸载失败", "卸载失败" in text, text)
check("no bogus 0x00000000 code", "0x00000000" not in text, text)

print("[9] the outer instance's fallback when the child reports nothing")
kind, text = call(dll.FrTestNoResultResult, log_path, 1, 0)
check("still-running fallback is Failed", kind == FAILED, str(kind))
check("says the installer is still running", "仍在运行" in text, text)
kind, text = call(dll.FrTestNoResultResult, log_path, 0, 5)
check("exit fallback carries the exit code", "退出码 5" in text, text)
check("fallback points at the log", log_path in text)
kind, _ = call(dll.FrTestNoResultResult, log_path, 0, 0)
check("exit fallback stays Failed", kind == FAILED, str(kind))

print("[10] parent/child marker handshake")
buf = ctypes.create_unicode_buffer(BUF)
dll.FrTestMarkerPath(buf, BUF)
marker = buf.value
check("marker path is a file path", marker and os.path.isabs(marker), marker)
if os.path.exists(marker):
    os.remove(marker)
check("marker absent before the child speaks", dll.FrTestMarkerExists(marker) == 0)
check("child can write the marker", dll.FrTestWriteMarker(marker, PARTIAL) == 1)
check("outer instance sees it", dll.FrTestMarkerExists(marker) == 1)
with open(marker, encoding="utf-8") as f:
    body = f.read()
check("marker records the kind", "kind=partial" in body, body)
dll.FrTestDeleteMarker(marker)
check("marker is cleaned up afterwards", dll.FrTestMarkerExists(marker) == 0)

print()
if fails:
    print("FAILED %d check(s): %s" % (len(fails), ", ".join(fails)))
    sys.exit(1)
print("ALL INSTALLER RESULT TESTS PASSED")
