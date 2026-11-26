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
# 代码里用了 f-string / 海象等 3.6+ 语法，但 PyQt5>=5.12 的轮子要求 3.8+
"$PY" -c "import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)" \
    || die "Python 版本过低：$("$PY" -c 'import sys;print("%d.%d"%sys.version_info[:2])')（需要 3.8+）"
"$PY" -c "import PyQt5.QtWidgets" 2>/dev/null || die "缺少 python3-pyqt5（sudo apt install python3-pyqt5）"
[ -d "$SRC/app" ] || die "源码目录里找不到 app/，请在项目根目录下运行本脚本"
green "    Python：$PY"
green "    系统：$(grep PRETTY_NAME /etc/os-release 2>/dev/null | cut -d'"' -f2 || echo 未知)"

if [ -f /usr/lib/x86_64-linux-gnu/qt5/qml/org/ukui/panel/items/libukui-panel-items.so ] \
   || [ -f /usr/lib/aarch64-linux-gnu/qt5/qml/org/ukui/panel/items/libukui-panel-items.so ]; then
    green "    任务栏：Qt 版 ukui-panel（支持实时透明）"
else
    warn "    未检测到 Qt 版任务栏，透明度模块可能不可用（文件整理不受影响）"
fi

echo "==> 安装到 $DEST"
mkdir -p "$BIN" "$APPS"
# 先拷到 .new 再整体替换：中途失败（磁盘满 / 权限）不会把旧的可运行版本删掉
STAGE="$DEST.new"
rm -rf "$STAGE"
mkdir -p "$STAGE"
trap 'rm -rf "$STAGE"' EXIT
for part in app bin assets; do
    [ -e "$SRC/$part" ] || continue
    cp -r "$SRC/$part" "$STAGE"/
done
[ -f "$STAGE/app/cli.py" ] || die "拷贝不完整：缺少 app/cli.py，已中止（原安装未改动）"
chmod +x "$STAGE/bin/zhengli"
find "$STAGE/app" -name "*.py" -exec chmod 644 {} \;
rm -rf "$DEST.old"
if [ -d "$DEST" ]; then mv "$DEST" "$DEST.old"; fi
mv "$STAGE" "$DEST"
rm -rf "$DEST.old"
trap - EXIT
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
