#!/usr/bin/env bash
# 桌面整理 安装脚本（用户级，不需要 root）
set -euo pipefail

SRC="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
DEST="$HOME/.local/share/desktop-organizer"
BIN="$HOME/.local/bin"
APPS="$HOME/.local/share/applications"
AUTOSTART="$HOME/.config/autostart"

green() { printf "\033[32m%s\033[0m\n" "$*"; }
dim()   { printf "\033[2m%s\033[0m\n" "$*"; }
warn()  { printf "\033[33m%s\033[0m\n" "$*"; }
die()   { printf "\033[31m%s\033[0m\n" "$*"; exit 1; }

echo "==> 检查环境"
PY=/usr/bin/python3
[ -x "$PY" ] || PY=$(command -v python3 || true)
[ -n "$PY" ] || die "缺少 python3"
"$PY" -c "import PyQt5.QtWidgets" 2>/dev/null || die "缺少 python3-pyqt5（sudo apt install python3-pyqt5）"
green "    Python：$PY"
green "    系统：$(grep PRETTY_NAME /etc/os-release 2>/dev/null | cut -d'"' -f2 || echo 未知)"

if [ -f /usr/lib/x86_64-linux-gnu/qt5/qml/org/ukui/panel/items/libukui-panel-items.so ] \
   || [ -f /usr/lib/aarch64-linux-gnu/qt5/qml/org/ukui/panel/items/libukui-panel-items.so ]; then
    green "    任务栏：Qt 版 ukui-panel（支持实时透明）"
else
    warn "    未检测到 Qt 版任务栏，透明度模块可能不可用（文件整理不受影响）"
fi

echo "==> 安装到 $DEST"
rm -rf "$DEST"
mkdir -p "$DEST" "$BIN" "$APPS"
cp -r "$SRC/app" "$SRC/bin" "$SRC/assets" "$DEST"/
chmod +x "$DEST/bin/zhengli"
find "$DEST/app" -name "*.py" -exec chmod 644 {} \;
ln -sf "$DEST/bin/zhengli" "$BIN/zhengli"

cat > "$APPS/desktop-organizer.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=桌面整理
Name[en_US]=Desktop Organizer
Comment=任务栏透明度 + 桌面文件一键整理
Exec=$DEST/bin/zhengli run
Icon=$DEST/assets/icon.svg
Terminal=false
Categories=Utility;FileTools;Settings;
Keywords=panel;transparency;desktop;tidy;整理;透明度;抽屉;
StartupNotify=false
EOF
chmod 644 "$APPS/desktop-organizer.desktop"

if [ "${1:-}" = "--autostart" ]; then
    mkdir -p "$AUTOSTART"
    cat > "$AUTOSTART/desktop-organizer.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=桌面整理
Comment=启动后驻留托盘：任务栏透明度 + 桌面一键整理
Exec=$DEST/bin/zhengli run
X-UKUI-Autostart-enabled=true
X-GNOME-Autostart-enabled=true
Hidden=false
NoDisplay=true
StartupNotify=false
EOF
    chmod 644 "$AUTOSTART/desktop-organizer.desktop"
    green "==> 已加入开机自启"
fi

green "==> 安装完成"
echo
echo "  启动（进托盘）：  zhengli"
echo "  打开主窗口：      zhengli show"
echo "  一键整理：        zhengli tidy"
echo "  先看预览：        zhengli scan"
echo
dim "  归档位置：$HOME/桌面/.桌面抽屉"
dim "  自启开关：设置页里勾选，或 zhengli autostart on"
