#!/usr/bin/env bash
# 桌面整理 —— 麒麟/Linux 卸载
# 用法： bash uninstall.sh            # 删程序，保留配置
#        bash uninstall.sh --purge    # 连配置一起删
set -uo pipefail

DEST="$HOME/.local/share/desktop-organizer"
BIN="$HOME/.local/bin/zhengli"
DESKTOP="$HOME/.local/share/applications/desktop-organizer.desktop"
AUTO="$HOME/.config/autostart/desktop-organizer.desktop"
CFG="$HOME/.config/desktop-organizer"
SHELF="$HOME/桌面/.桌面抽屉"

PURGE=0
[ "${1:-}" = "--purge" ] && PURGE=1

PY=/usr/bin/python3
[ -x "$PY" ] || PY=$(command -v python3 || echo python3)

# 真实命令行是 "$PY $DEST/app/cli.py run"。
# 以前这里写的是 pkill -f "desktop-organizer/app/app.py" —— 文件名都不对，永远匹配不到，
# 于是程序还在跑、文件却已经被删，托盘里留着一个半死的进程。
PAT="$DEST/app/cli.py"

echo "==> 停止正在运行的实例"
if ! pgrep -f "$PAT" >/dev/null 2>&1; then
    echo "    没在运行"
else
    # 1) 先让它自己退：会停热键、关贴图、把任务栏透明度还原
    "$PY" - <<'PYEOF' >/dev/null 2>&1
import sys, time
try:
    from PyQt5.QtCore import QCoreApplication
    from PyQt5.QtNetwork import QLocalSocket
except Exception:
    sys.exit(1)
app = QCoreApplication([])
s = QLocalSocket()
s.connectToServer("desktop-organizer")
if not s.waitForConnected(400):
    sys.exit(1)
s.write(b"quit")
s.flush()
s.waitForBytesWritten(400)
s.disconnectFromServer()
end = time.time() + 3
while time.time() < end:
    app.processEvents()
    time.sleep(0.05)
PYEOF

    # 2) 还没退（老版本没有 quit 命令、或进程卡死）才强杀，且只杀本项目的进程
    if pgrep -f "$PAT" >/dev/null 2>&1; then
        pkill -f "$PAT" 2>/dev/null
        sleep 1
        if pgrep -f "$PAT" >/dev/null 2>&1; then
            pkill -9 -f "$PAT" 2>/dev/null
            sleep 1
        fi
        if pgrep -f "$PAT" >/dev/null 2>&1; then
            echo "    停不掉，请手动结束： pgrep -af \"$PAT\""
        else
            echo "    已停止"
        fi
    else
        echo "    已停止"
    fi
fi

echo "==> 删除程序文件"
rm -f "$BIN" "$DESKTOP" "$AUTO"
if [ -d "$DEST" ]; then
    rm -rf "$DEST" && echo "    $DEST" || echo "    $DEST 删除失败（可手动删）"
fi
command -v update-desktop-database >/dev/null 2>&1 && \
    update-desktop-database "$HOME/.local/share/applications" >/dev/null 2>&1

if [ -d "$CFG" ]; then
    if [ "$PURGE" -eq 1 ]; then
        rm -rf "$CFG" && echo "==> 已删除配置 $CFG" || echo "==> 配置删除失败：$CFG"
    else
        echo "==> 保留配置（含整理记录，撤销要用它）：$CFG"
        echo "    想一起删干净： bash uninstall.sh --purge"
    fi
fi

echo
echo "==> 卸载完成。"
echo "    任务栏透明度已由系统控制中心接管，若想彻底恢复默认："
echo "      gsettings reset org.ukui.control-center.personalise transparency"
if [ -d "$SHELF" ]; then
    echo
    echo "    已归档的文件没有动，还在："
    echo "      $SHELF"
fi
