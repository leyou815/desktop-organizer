#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""桌面整理 —— Windows 卸载脚本

只删程序、快捷方式、自启项和（可选的）配置，**已经归好类的文件一个都不动**。

停止实例的方式（这里以前是 `taskkill /IM pythonw.exe /F`，等于把所有用
pythonw 跑的程序一起杀了 —— 用户可能还开着别的 Python 脚本/工具，那是数据事故）：
  1. 先用 IPC 发 quit，让运行中的实例自己退（它会顺手停热键、关贴图、还原外观）
  2. 等不到退出，才按「命令行里含本程序安装路径」精确找 PID，只杀自己这几个

用法：
    python uninstall_windows.py             # 删程序，保留配置
    python uninstall_windows.py --purge     # 连配置一起删
"""

import os
import shutil
import subprocess
import sys
import time

APP_NAME = "桌面整理"
FOLDER = "DesktopOrganizer"
SERVER_KEY = "desktop-organizer"

IS_WINDOWS = sys.platform.startswith("win")


# --------------------------------------------------------------------------- #
# 路径
# --------------------------------------------------------------------------- #
def local_appdata():
    return os.environ.get("LOCALAPPDATA") or os.path.join(
        os.path.expanduser("~"), "AppData", "Local")


def roaming_appdata():
    return os.environ.get("APPDATA") or os.path.join(
        os.path.expanduser("~"), "AppData", "Roaming")


def install_dir():
    """安装目录：优先用 %LOCALAPPDATA%\\DesktopOrganizer，没有再退回脚本所在目录。"""
    cand = os.path.join(local_appdata(), FOLDER)
    if os.path.isdir(cand):
        return cand
    return os.path.dirname(os.path.abspath(__file__))


def config_dir():
    return os.path.join(roaming_appdata(), FOLDER)


def start_menu():
    return os.path.join(roaming_appdata(), "Microsoft", "Windows", "Start Menu", "Programs")


def targets():
    """要删的文件/目录（只列存在的）。桌面抽屉不在其中。"""
    out = []
    d = install_dir()
    if os.path.isdir(d):
        out.append(d)
    for p in (os.path.join(start_menu(), APP_NAME + ".lnk"),
              os.path.join(start_menu(), FOLDER + ".lnk"),
              os.path.join(start_menu(), FOLDER),
              os.path.join(os.path.expanduser("~"), "Desktop", APP_NAME + ".lnk")):
        if os.path.exists(p):
            out.append(p)
    return out


# --------------------------------------------------------------------------- #
# 停实例
# --------------------------------------------------------------------------- #
def _qt():
    """延迟导入 PyQt5：没装就当作"没有可停的实例"，卸载照样能跑完。"""
    try:
        from PyQt5.QtCore import QCoreApplication
        from PyQt5.QtNetwork import QLocalSocket
    except Exception:
        return None, None
    app = QCoreApplication.instance() or QCoreApplication([])
    return app, QLocalSocket


def _still_listening():
    app, QLocalSocket = _qt()
    if QLocalSocket is None:
        return False
    s = QLocalSocket()
    s.connectToServer(SERVER_KEY)
    ok = bool(s.waitForConnected(200))
    s.abort()
    s.deleteLater()
    app.processEvents()
    return ok


def quit_by_ipc(timeout=3.0):
    """发 IPC quit 让实例自己退；返回是否已确认退出。"""
    app, QLocalSocket = _qt()
    if QLocalSocket is None:
        return False
    s = QLocalSocket()
    s.connectToServer(SERVER_KEY)
    if not s.waitForConnected(400):
        s.abort()
        return False
    s.write(b"quit")
    s.flush()
    s.waitForBytesWritten(400)
    s.disconnectFromServer()
    s.deleteLater()
    end = time.time() + timeout
    while time.time() < end:          # 转事件循环，等服务端收包 + 自己收尾
        app.processEvents()
        time.sleep(0.05)
        if not _still_listening():
            return True
    return not _still_listening()


def pids_by_commandline(needle):
    """命令行里含 needle 的进程 PID；查不了返回空列表（绝不做模糊匹配）。"""
    if not needle:
        return []
    ps = ("Get-CimInstance Win32_Process | "
          "Where-Object { $_.CommandLine -and $_.CommandLine -like '*%s*' } | "
          "Select-Object -ExpandProperty ProcessId" % needle.replace("'", "''"))
    try:
        p = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                           universal_newlines=True, timeout=25)
    except (OSError, subprocess.SubprocessError):
        return []
    out = []
    for line in (p.stdout or "").splitlines():
        line = line.strip()
        if line.isdigit():
            out.append(int(line))
    return out


def stop_instance():
    print("==> 停止正在运行的实例")
    if not IS_WINDOWS:
        print("    跳过（非 Windows）")
        return True
    d = install_dir()
    listening = _still_listening()
    if not listening and not pids_by_commandline(d):
        print("    没在运行")
        return True

    if listening and quit_by_ipc():
        print("    已让实例自行退出")
        return True

    # IPC 没成功（老版本没有 quit 命令、或进程卡住）：只杀命令行里带本项目路径的进程
    pids = [p for p in pids_by_commandline(d) if p != os.getpid()]
    if not pids:
        print("    探到实例但定位不到对应进程，跳过强杀（请手动退出后重试）")
        return False
    for pid in pids:
        try:
            subprocess.run(["taskkill", "/PID", str(pid), "/F"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=15)
            print("    已结束进程 PID %s" % pid)
        except (OSError, subprocess.SubprocessError):
            print("    结束 PID %s 失败（可稍后手动关闭）" % pid)
    return True


# --------------------------------------------------------------------------- #
# 清理
# --------------------------------------------------------------------------- #
def remove_path(path):
    """删文件/目录。目录先改名再删，删到一半失败也不会留残骸占着原位置。"""
    try:
        if os.path.isdir(path) and not os.path.islink(path):
            victim = path
            trash = path + ".deleted"
            try:
                if os.path.exists(trash):
                    shutil.rmtree(trash, ignore_errors=True)
                os.rename(path, trash)      # 同盘改名，几乎不会失败
                victim = trash
            except OSError:
                pass                        # 改不了名就直接删原来的
            shutil.rmtree(victim)
        else:
            os.remove(path)
        return True, ""
    except FileNotFoundError:
        return True, ""
    except OSError as e:
        return False, "%s" % e


def remove_autostart():
    print("==> 移除自启")
    try:
        import winreg
    except Exception:
        print("    跳过（非 Windows）")
        return
    removed = []
    for name in (FOLDER, "DesktopOrganizer", APP_NAME):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\Microsoft\Windows\CurrentVersion\Run",
                                0, winreg.KEY_SET_VALUE) as k:
                winreg.DeleteValue(k, name)
            removed.append(name)
        except FileNotFoundError:
            continue
        except Exception as e:
            print("    %s 删除失败：%s" % (name, e))
    if removed:
        print("    已移除 %s" % "、".join(removed))
    else:
        print("    没有自启项")


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    purge = "--purge" in argv or "--purge-config" in argv

    if not IS_WINDOWS:
        print("这个脚本只用于 Windows。麒麟/Linux 请用： bash uninstall.sh")
        return 1

    stop_instance()

    print("==> 删除程序文件")
    gone = 0
    for p in targets():
        ok, why = remove_path(p)
        if ok:
            gone += 1
            print("    %s" % p)
        else:
            print("    %s 删除失败：%s（可手动删）" % (p, why))
    if not gone:
        print("    没找到已安装的程序文件")

    remove_autostart()

    cfg = config_dir()
    if os.path.isdir(cfg):
        if purge:
            ok, why = remove_path(cfg)
            print("==> 删除配置：%s" % ("完成" if ok else "失败：%s" % why))
        else:
            print("==> 保留配置（含整理记录，撤销要用它）")
            print("    %s" % cfg)
            print("    想一起删干净：python uninstall_windows.py --purge")

    shelf = os.path.join(os.path.expanduser("~"), "Desktop", ".桌面抽屉")
    print()
    print("卸载完成。")
    if os.path.isdir(shelf):
        print("已归档的文件没有动，还在：")
        print("  %s" % shelf)
    return 0


if __name__ == "__main__":
    sys.exit(main())
