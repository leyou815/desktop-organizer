#!/usr/bin/env bash
# 桌面整理 卸载脚本：只删程序，不动已归档的文件
set -uo pipefail

DEST="$HOME/.local/share/desktop-organizer"
BIN="$HOME/.local/bin/zhengli"
DESKTOP="$HOME/.local/share/applications/desktop-organizer.desktop"
AUTO="$HOME/.config/autostart/desktop-organizer.desktop"
SHELF="$(xdg-user-dir DESKTOP 2>/dev/null || echo "$HOME/桌面")/.桌面抽屉"

echo "==> 停止正在运行的实例"
pkill -f "desktop-organizer/app/app.py" 2>/dev/null && echo "    已停止" || echo "    没在运行"

echo "==> 删除程序文件"
rm -f "$BIN" "$DESKTOP" "$AUTO"
rm -rf "$DEST"

echo
echo "==> 卸载完成。"
echo "    任务栏透明度已由系统控制中心接管，若想彻底恢复默认："
echo "      gsettings reset org.ukui.control-center.personalise transparency"
if [ -d "$SHELF" ]; then
    echo
    echo "    已归档的文件没有动，还在："
    echo "      $SHELF"
fi
