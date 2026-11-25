# 桌面整理 · Desktop Organizer

一个托盘小工具，干三件事：**把任务栏调成毛玻璃**、**一键把桌面文件收进抽屉**、**截屏加标注并贴到屏幕上**。
外带一个从屏幕右边缘滑出的抽屉，带模糊搜索（支持拼音首字母）和批量处理。

一套代码，两个平台：**银河麒麟 V10（UKUI）** 与 **Windows 10/11**。

![主界面](assets/main-files.png)

---

## 功能

### 1. 任务栏毛玻璃

不是简单调个透明度——**不管拉到多少，都保留玻璃质感**：

- 玻璃质感开关（默认开）：强制系统磨砂常驻，并把透明度上限压到 **92%**
  （100% 会变成一块实心色，磨砂就没东西可"磨"了）
- 四档材质预设：浓雾 / 磨砂 / 玻璃 / 通透
- 实时预览卡：把"任务栏叠在壁纸上"的样子画出来，拖滑块即时可见

![任务栏](assets/main-panel.png)

### 2. 桌面文件一键整理

文件照常存桌面，想收拾的时候点一下：

```
桌面 → 点「一键整理」 → 按类型归到 桌面/.桌面抽屉/ → 结果条 + 撤销
```

- 四个入口：主窗口大按钮 / 托盘右键 / 抽屉顶部 / 命令行 `tidy`
- **不弹确认框**，安全靠"可撤销"：整理后 6 秒内点「撤销」全部回滚
- 「自动整理新文件」默认**关闭**，你想收拾了才点

### 3. 右侧滑出抽屉 + 搜索

屏幕右边缘一条 11px 的小竖条，点一下往左滑出抽屉。分类行可展开，**应用类直接显示成可点的图标**，点一下就启动。

![抽屉](assets/drawer-apps.png)

标题栏下有搜索框，支持中文、拼音首字母、文件名、扩展名：

| 输入 | 命中 |
|---|---|
| `报告` | 文件名含「报告」的 |
| `wx` | 微信（拼音首字母） |
| `sls` | 商洛市… |
| `wechat` | 按文件名也能搜 |
| `doc` | 扩展名也算文件名的一部分 |

![搜索](assets/search.png)

### 4. 搜到了就顺手处理掉

搜索不只是"看见"，勾上就能动：**移动到别的文件夹 / 统一重命名 / 删除进回收站**。

![勾选](assets/bulk-select.png)

点搜索结果左边的勾选框选中（点名字仍然是打开文件），选中 1 项以上时浮出操作栏：

| 动作 | 做什么 |
|---|---|
| **移动到…** | 搬进抽屉里任意分类或子目录、当场新建一个文件夹、或另选别的位置 |
| **重命名** | 把文件名里的某个词统一换掉，带实时预览 |
| **删除** | 放进系统回收站（不是 `rm`），先弹确认框 |

三个动作**都能撤销**：点抽屉底部「撤销上次」，或终端 `zhengli undo`。

### 5. 截图与贴图

快捷键照 Snipaste 那套：

| 键 | 干什么 |
|---|---|
| `F1` | 截屏（进标注界面） |
| `F2` | 截屏并自动复制（框完直接进剪贴板，不进标注） |
| `Shift+F1` | 自定义截屏（先定尺寸，再拖着框定位） |
| `F3` | 把剪贴板里的图贴到屏幕上 |
| `Shift+F3` | 隐藏 / 显示所有贴图 |

![截图](assets/snip-overlay.png)

- **八种标注**：方框、圆形（`Shift` 出正方 / 正圆）、箭头、折线、画笔、记号笔（荧光笔）、马赛克、文字；`Ctrl+Z` 撤销、`Ctrl+Y` 重做
- **像素级对齐**：拖选时鼠标旁边有 4 倍放大镜 + 坐标，框定后用方向键微调 1px（`Shift` 10px）
- **贴图**：钉在屏幕上当参考图，**落在原截图的位置**，鼠标拖边角缩放（拖角锁比例）、滚轮缩放、`Ctrl+滚轮`调透明度
- **一键让路**：设置里可以整体关掉这组快捷键，把 F1/F2/F3 还给别的程序

![贴图](assets/snip-pin.png)

## 平台支持

| 能力 | 麒麟 V10 SP1（UKUI） | Windows 11（10.0.26200） |
|---|---|---|
| 任务栏毛玻璃 | `gsettings` 三键 + 92% 封顶 | `SetWindowCompositionAttribute` 亚克力 ✅ 已实测（60% / 88% 均生效） |
| 桌面文件整理 | ✅ 已实测 | 逻辑平台无关，自检通过（未做真实整理） |
| 抽屉 / 搜索 / 托盘 | ✅ 已实测 | 托盘可用性自检通过 |
| 桌面图标（应用） | `.desktop` | `.lnk` / `.url`（图标读取已实测） |
| 系统图标（此电脑/回收站） | peony 三个 gsettings 键 | `HideDesktopIcons` 注册表（读取已实测） |
| 开机自启 | `~/.config/autostart/*.desktop` | `HKCU\...\Run` 读写已实测 |
| 截图与贴图 | ✅ 已实测（Qt 抓屏 + X11 热键） | 全局热键注册已实测（Ctrl+Alt+G） |

> **关于 Windows 版**：已在 Windows 11（内部版本 26200）+ Python 3.13 + PyQt 5.15.11
> 上跑过 [`tools/selftest_win.py`](tools/selftest_win.py)，**12/12 项全部通过**：
> 任务栏窗口、亚克力 API 与贴附、注册表读写、托盘、`.lnk` 图标、热键注册都正常。
> 换其它 Windows 版本后仍建议跑一次自检，把生成的 `selftest.txt` 贴到 issue 里。

## 快速开始

### Windows

需要 Python 3.8+ 和 PyQt5：

```bat
pip install -r requirements.txt
```

- **直接跑**：双击 `run_windows.bat`
- **装到系统**（开始菜单快捷方式 + 可选开机自启）：

```bat
python install_windows.py
```

- **打包成 exe**（给没装 Python 的机器，需要 PyInstaller）：

```bat
build_windows.bat
```

卸载：`python uninstall_windows.py`（只删程序，已归档的文件不动）

### 麒麟 V10 / Linux

```bash
bash install.sh              # 装到 ~/.local/share/desktop-organizer
bash install.sh --autostart  # 顺带开机自启
zhengli                      # 启动，直接进托盘
```

依赖：系统自带的 `python3` + `python3-pyqt5`，无第三方包。

## 归类规则

归到桌面下的隐藏文件夹 `桌面/.桌面抽屉/`（Windows 是 `%USERPROFILE%\Desktop\.桌面抽屉`）：

```
├── 文档/    Word/ Excel/ PPT/ PDF/ 文本/
├── 文件夹/  桌面上的文件夹整包搬进来
├── 应用/    桌面图标背后的启动器（.desktop / .lnk / .url）
├── 快捷方式/ 指向绝对路径的符号链接
├── 图片/  图标/  视频/  音频/
├── 压缩包/  安装包/  代码/  其他/
```

| 分类 | 认这些 |
|---|---|
| 文档/Word | doc docx wps rtf odt dot docm |
| 文档/Excel | xls xlsx xlsm et csv ods |
| 文档/PPT | ppt pptx pps dps odp |
| 文档/PDF | pdf ofd xps |
| 文档/文本 | txt md log tex epub mobi |
| 图片 | jpg png bmp gif webp tif heic psd xcf raw… |
| 图标 | svg svgz ico icns cur；**外加**正方形、边长≤256、带 alpha 的 png |
| 应用 | `.desktop`（麒麟）/ `.lnk` `.url`（Windows） |
| 快捷方式 | 目标为绝对路径的符号链接 |

**永不移动**：`.` 开头的锁文件（Office 的 `.~xxx.docx`）、相对路径的符号链接、
挂载点、`desktop.ini` / `Thumbs.db` 这类系统占位文件、未下完的 `.part`。

补充：重名自动改名 `名字 (2).ext` 不覆盖；3 秒内刚写过的文件跳过；每次移动都记账，可按批撤销。

### 桌面图标怎么"进抽屉还能用"

桌面上的图标其实分三种，处理方式完全不同：

| 图标 | 本质 | 怎么处理 |
|---|---|---|
| 微信、WPS、Chrome… | 快捷方式文件（`.desktop` / `.lnk`） | 搬进「应用」，抽屉里变成可点磁贴 |
| 快捷方式 - xxx | 指向绝对路径的符号链接 | 搬进「快捷方式」，点一下跳到目标 |
| 此电脑、回收站、主目录 | **不是文件**，系统画的虚拟图标 | 搬不走；用开关把桌面图标藏掉，抽屉里补等价磁贴 |

搬走仍然能启动，是因为**快捷方式能不能用跟它在哪个目录无关**——`.lnk` 记的是目标的绝对路径，
`.desktop` 靠 Exec 字段，两者都不依赖自身位置。

## 抽屉与搜索

- **入口**：屏幕右边缘 11px 竖条（可关，只留托盘）
- **展开**：230ms 从右往左滑出；分类行点一下就地展开
- **应用类**：4 列图标网格，图标从系统实时取，点一下启动
- **收起**：点抽屉左边缘的把手（把手跟着抽屉走）、`ESC`、`✕`、点别处
- **搜索**：`↑↓` 选择、`回车` 打开、`ESC` 清空

搜索排序是调出来的：开头命中 > 中间命中 > 子序列 > 首字母；长文件名里的"巧合"
（比如 `_cgi-bin_mmwebwx-bin_...` 里的 `wx`）会被降权，深层文件排在顶层之后。

## 搜索之后的批量操作

搜索结果每行左边有一个勾选框。点勾选框是选中，点名字是打开文件——不会为了勾一下反而把文件打开了。
选中 1 项以上，搜索框下面浮出操作栏：`已选 N 项` + `全选 / 反选 / 清空` + 三个动作。

### 移动到

![移动到](assets/bulk-move.png)

列出抽屉里全部 12 个分类及其子目录，**默认选中文件当前所在的目录**；底部三个出口：

- **新建文件夹**：在当前选中的目录下建，建完自动选中
- **其他位置…**：跳到系统文件夹选择器，可以搬到抽屉外面的任意路径
- **移动**：双击列表项也是直接移动

### 重命名

![重命名](assets/bulk-rename.png)

填「查找」和「替换为」，下面实时预览每一个文件会变成什么：旧名带删除线，新名用主题色标出。
**扩展名默认不动**（免得把 `.docx` 改名成 `.txt` 打不开），需要连扩展名一起改再勾那个复选框。
不含查找词的文件会标出来并跳过，不会算作失败。

### 删除

![删除](assets/bulk-confirm.png)

**进回收站，不是 `rm`。** 麒麟上按 freedesktop 规范写 `~/.local/share/Trash`（文件进 `files/`，
同时在 `info/` 写 `.trashinfo` 记录原位置），所以文件管理器的回收站里能正常看到，也能从那里还原。
勾选里含文件夹时会额外提示"会连同里面的内容一起进去"。

### 几个刻意的设计

| 设计 | 为什么 |
|---|---|
| **勾选跨搜索保留** | 搜「报告」勾几项，再搜「总结」勾几项，能一起删。操作栏会注明"其中 N 项不在此结果里"，不会误删看不见的东西 |
| **Shift 连选一段** | 一次勾一片，不用一个个点 |
| **归档骨架受保护** | 12 个分类目录、桌面目录本身不能删也不能移，否则抽屉结构就散了 |
| **不原地打转** | 目标就是文件当前所在目录时直接拦下，不会生成一个 `xxx (2).docx` |
| **重名不覆盖** | 移动/重命名遇到同名一律改名成 `名字 (2)` |
| **两套日志分开记** | 整理用 `moves.jsonl`（桌面→抽屉的单向搬运），批量操作用 `ops.jsonl`（任意方向的用户意图）。撤销时比较两个文件的修改时间，谁更新撤谁，所以界面上只有一个「撤销上次」 |

## 截图

### 四个入口

| 入口 | 怎么用 |
|---|---|
| **快捷键** | `F1` 截图 / `F2` 截图并复制 / `Shift+F1` 固定尺寸 |
| **托盘右键** | 前四项：截图 / 截图并复制 / 自定义截屏 / 贴图 |
| **主窗口** | 导航「截图」页 → 「开始截图」 |
| **命令行** | `zhengli snip`（主程序没在跑也能用）/ `zhengli snipcopy` |

截图开始时会**自动收起主窗口**，免得把自己截进去；按 `ESC` 取消会把窗口还回来。

### 框选

拖动鼠标框出一块区域，屏幕其余部分压暗、选区保持原亮度。选区四周有 8 个把手，
拖着可以调整；也可以在选区里按住拖动整体挪位置。

拖的时候鼠标旁边有一块 **4 倍放大镜 + 实时坐标**，用来对齐像素边界；
框定之后放大镜自动消失（不然挡视线）。

按钮栏浮在选区下方（下方空间不够就翻到上方），跟着选区走。

### 标注

| 工具 | 怎么用 |
|---|---|
| **箭头** | 从起点拖到终点，箭头跟着方向转 |
| **方框** | 拖出矩形，框住一块重点；按住 `Shift` 拖就是正方形 |
| **圆形** | 拖出椭圆（圈重点）；按住 `Shift` 拖就是正圆 |
| **折线** | 逐点点击定折点，双击 / 回车 / 右键收尾；ESC 丢掉这条 |
| **画笔** | 按住自由画，适合圈圈点点 |
| **记号笔** | 半透明粗线（荧光笔），压在文字上还能看清底下 |
| **马赛克** | 拖一片区域，从原图取样做方块化，用来遮敏感信息 |
| **文字** | 点一下出输入框，回车落字（带半透明黑底，深浅背景都看得清） |

八种工具、六种颜色（红橙绿蓝白黑）、三档线宽（工具条上用逐渐变粗的圆点表示），`Ctrl+Z` 撤销、`Ctrl+Y` 重做。

方框和圆形都是**空心描边**（不填色，压不住底下的内容）：拖的时候就能看到实时预览，松手落图；描边内缩半个线宽，整条线都落在你拖出来的框里，不会糊出去半根。
`Shift` 是**拖动过程中按下就生效**，松手前松开 `Shift` 会回到自由矩形——想画正方/正圆就在拖的时候一直按住。

![工具条](assets/snip-toolbar.png)

工具条的图标是自己用 QPainter 画的，不依赖图标主题——换个精简的主题也不会变成一堆空方块。

### 输出

| 动作 | 快捷键 |
|---|---|
| 复制到剪贴板 | `Enter`（或双击选区 / 点「复制」） |
| 存盘 | `Ctrl+S`（或点「保存」，存到设置里的目录） |
| 贴到屏幕上 | `F3`（或点「贴图」，同时也会复制） |
| 整屏 | `Ctrl+A` |
| 撤销 / 重做标注 | `Ctrl+Z` / `Ctrl+Y` |
| 取消 | `ESC` |

设置页可以打开「截完自动复制」和「截完自动存盘」，那样框完松手就已经在剪贴板和文件夹里了。

文件名是 `截图_20261125_160503.png`，重名自动加序号，不会覆盖。

### 贴图

贴图是一个无边框、置顶的小窗口，**默认贴在刚截的那块位置**（不是屏幕中央），看起来就是那一片画面留在原地：

| 操作 | 效果 |
|---|---|
| 拖动 | 移到任意位置 |
| 拖四角 / 四边 | 缩放；**拖角默认锁比例**（图不变形），按住 `Shift` 拖角可自由拉伸 |
| 滚轮 | 缩放（24px ~ 4000px），以中心为锚点 |
| `Ctrl+滚轮` | 调透明度（15% ~ 100%） |
| 双击 | 在「100% 原图尺寸」和「铺到屏幕 80%」之间切换 |
| 悬停 | 四边四角出白色小方块（拖它缩放），右上角出关闭点，左下角显示尺寸 / 缩放比例 / 不透明度 |
| 右键 | 复制 / 另存为 / 还原为 100% / 三档不透明度 / 关闭 |
| `ESC` | 关闭 |

右上角那个 `×` 就是关闭按钮，所以**右上角不做缩放热区**；要放大往右下角或其它三条边拖。
贴图太小（任一边 < 56px）时不出缩放热区，免得太小点不准。

可以同时贴很多张。托盘菜单的「贴图剪贴板」（`Ctrl+Alt+V`）能把剪贴板里的图直接钉上来——
比如从网页复制的图、别处截的图。

### 快捷键总开关

F1 / F2 / F3 是全局抓的，会盖住别的程序：**浏览器的 F1 是帮助、F3 是查找下一个**。
所以给了个开关，位置有三处：

- 主窗口「截图」页 →「启用截图快捷键」
- 托盘右键 →「启用截图快捷键」
- 命令行 `zhengli snipkeys off` / `on`

关掉之后：

- 这四个键**完全不再抓取**（应用根本收不到它们，等于还给了系统）
- 热键注册会重建一次，`Ctrl+Alt+G`（任务栏材质）不受影响
- 截图功能本身还在——托盘菜单和主窗口按钮照样能用
- 设置页那行提示会变成「截图快捷键已关闭，F1 / F2 / F3 归还给其它程序」

> 为什么不做成"只放掉冲突的那一个"：X 的 key grab 是整键粒度，没法只让某个应用例外。
> 要么全抓、要么全放，开关做在这个粒度上才对得上实际行为。

### 关于抓屏

用的是 Qt 的 `QScreen.grabWindow(0)`，多屏时把每块屏拼成一张虚拟桌面画布，
坐标按设备像素统一处理（高分屏不会出现半像素错位）。

一个已知坑：**如果桌面特效关了，抓到的可能是一片黑**（没有合成器时只能拿到窗口内容，
拿不到桌面背景）。所以加了检测——整张图采样后是同一个颜色时会提示你去控制中心开启特效。

## 命令

麒麟 / Linux：

```bash
zhengli                 # 启动（默认进托盘）
zhengli show            # 唤出主窗口
zhengli tidy            # 一键整理
zhengli scan            # 预览会怎么归，不移动
zhengli undo            # 撤销上一次操作（整理或批量改动）
zhengli snip            # 截图（主程序没在跑也能用）
zhengli snipcopy        # 截图并直接复制
zhengli pin             # 把剪贴板里的图钉到屏幕上
zhengli snipkeys off    # 关掉截图快捷键，把 F1/F2/F3 还给别的程序
zhengli stat            # 两个模块的状态一起看
zhengli panel 55        # 任务栏透明度 55%
zhengli glass on|off    # 玻璃质感开关
zhengli autostart on|off
zhengli diagnose        # 环境诊断
```

Windows 把 `zhengli` 换成 `python app\cli.py`，例如 `python app\cli.py tidy`。

## 实现说明：两个平台差在哪

差异全部收在 `app/sysenv.py`、`app/panel_core.py`、`app/panel_win.py`、`app/launchers.py` 四个文件里，
UI（`ui_main.py` / `ui_drawer.py`）完全平台无关。

| 关注点 | 麒麟 | Windows |
|---|---|---|
| 任务栏透明度 | `org.ukui.control-center.personalise:transparency`（0~1），写入实时生效 | 未公开 API `user32!SetWindowCompositionAttribute` + `ACCENT_ENABLE_ACRYLICBLURBEHIND` |
| 磨砂强度 | `personalise:blurry` 有低/中/高三档 | 无对应概念，该行控件在 Windows 上自动隐藏 |
| 玻璃前提 | `effect=true`、`enabled-global-blur=true`、`blurry` 三项每次重写 | 系统「透明效果」必须开（`EnableTransparency=1`） |
| 任务栏窗口 | QML 面板，改键即刷新 | `Shell_TrayWnd` + `Shell_SecondaryTrayWnd`；资源管理器重启后句柄失效，需每 4 秒复查重贴 |
| 启动应用 | `Gio.DesktopAppInfo`（处理 `%U`、`Terminal=true`） | `os.startfile` |
| 取图标 | `.desktop` 的 `Icon` 字段（主题名或绝对路径） | `QFileIconProvider`（读 shell 图标） |
| 隐藏判定 | 点开头 | 点开头 + `FILE_ATTRIBUTE_HIDDEN/SYSTEM` |
| 全局快捷键 | X11 `XGrabKey` + `QSocketNotifier` | `RegisterHotKey` + `QAbstractNativeEventFilter` |

**为什么 Windows 不改注册表**：网上流传的 `TaskbarAcrylicOpacity` 之类键在不同版本上行为不一致，
甚至根本不存在。真正能让任务栏变亚克力的是那个未公开 API（TranslucentTB 走的也是这条路），
所以这里直接用它，并且**先确保系统"透明效果"是开的**——那是前提，不开的话任务栏是纯色，
贴什么模糊都看不出来。

## 验证情况

**麒麟 V10 SP1 上实测过的**：

| 项目 | 结果 |
|---|---|
| 透明度写入 | 68% → 系统值 0.68，实时生效不用重启任务栏 |
| 玻璃质感封顶 | 拉 100% 被压到 **92%**，且 `blurry/effect/enabled-global-blur` 每次重写 |
| 一键整理 | 20 项归类（18 应用 + 2 快捷方式），统计/结果条/托盘提示同步 |
| 撤销 | 20 项全部还原 |
| 搬走仍可启动 | 移入隐藏目录后 `launch()` 返回 True |
| 搜索 | `wx`→微信、`sls`→商洛市、`报告`→7 条；↑↓/回车/ESC 正常 |
| 批量移动 | 勾 2 项 → 选目录 → 到位 → 撤销复原 |
| 批量重命名 | 5 个文件里 4 个含「报告」全部替换，1 个自动跳过；撤销复原 |
| 批量删除 | 2 项进回收站（`files/` + `.trashinfo` 齐全），撤销精确移回原位 |
| 边界拦截 | 删分类根目录、移动到当前目录，都被明确拦下并给出原因 |
| 跨搜索勾选 | 两个搜索词各勾 1 项，操作栏提示"其中 1 项不在此结果里" |
| 跳过规则 | 锁文件、相对链接、挂载点均未动 |
| 框选截图 | 拖选 641×441，选区外压暗、8 个把手、尺寸提示正确 |
| 标注 | 方框/圆形/箭头/画笔/文字/马赛克都落到导出图里，`Ctrl+Z` 逐个撤销 |
| 方框·圆形 | 空心描边、不填色；`Shift` 拖出正方形/正圆（四象限方向都对），描边内缩半个线宽不出框 |
| 键盘 | 方向键 1px、`Shift`+方向键 10px，选区与内部坐标同步 |
| 输出 | `Enter` 复制（尺寸与选区一致）、`Ctrl+S` 存盘、`F3` 贴图、`ESC` 取消 |
| 贴图 | 拖动/缩放（420×260 → 630×390）/透明度 0.6，关闭后从列表移除 |
| 六热键 | `F1` / `F2` / `Shift+F1` / `F3` / `Shift+F3` / `Ctrl+Alt+G` 六个键各自独立触发，互不串 |
| 快捷键开关 | 关掉后只剩 `Ctrl+Alt+G` 被占用，按 F1 不再弹截图；再打开立刻恢复 |
| 截屏并复制 | `F2` 框完直接进剪贴板（561×441），不进标注界面 |
| 固定尺寸 | `Shift+F1` 定 400×300，选区恒为 400×300，跟着鼠标定位 |
| 折线 / 记号笔 | 折线 3 个折点正确落图；记号笔存成 `marker` 类型、半透明粗线 |
| 撤销重做 | 画 2 笔 → undo 剩 1 → redo 回到 2，重做链在画新笔时清空 |

**Windows 上已在 Windows 11（10.0.26200）实测**：自检 12/12 项通过，覆盖 Python/PyQt 版本、
桌面目录、配置目录可写、注册表读写、任务栏窗口、亚克力 API、实际贴亚克力（60% / 88% 均成功并自动恢复）、
桌面文件盘点、`.lnk` 图标、系统托盘、全局热键（Ctrl+Alt+G）、系统图标开关读取。
未覆盖的真实操作：一键整理的真实搬运、批量删除进回收站、截图框选的实际交互（这些逻辑平台无关）。

## 已知限制

1. **Windows 的任务栏控制依赖未公开 API**，系统更新后可能失效；失效时会明确报错，不会静默失败。
2. Windows 没有"磨砂强度"分级，那一行控件会自动隐藏。
3. 文件分类靠扩展名，改了后缀会归错（文件夹按目录判断，快捷方式按类型判断，不受影响）。
4. 「此电脑 / 回收站 / 主目录」不是文件，只能靠系统开关隐藏，无法真正归档。
5. 桌面上若有链接指向被搬走的文件夹，链接会失效（链接本身不移动）。
6. 相对路径的符号链接永远不移动。
7. **截图只覆盖鼠标所在的那块屏幕**。多屏时不能跨屏拖一个选区——真要做需要多窗口联动，复杂度不值得。
8. **桌面特效关闭时截出来可能是黑的**（拿不到桌面背景）。程序会提示，但不会替你打开特效。
9. 截图复制到剪贴板依赖系统的剪贴板管理器（麒麟自带）。如果主程序退出后剪贴板内容消失，说明系统没有常驻管理器。

## License

[MIT](LICENSE)

---

<details>
<summary><b>English summary</b></summary>

A small tray utility for **Kylin V10 (UKUI)** and **Windows 10/11** that does three things:

1. **Frosted-glass taskbar** — adjustable opacity with the glass effect always preserved
   (capped at 92% so it never turns into a solid color block).
   On Kylin it drives `org.ukui.control-center.personalise` gsettings; on Windows it uses
   the undocumented `SetWindowCompositionAttribute` acrylic API (same approach as TranslucentTB).
2. **One-click desktop cleanup** — files stay on the desktop until you press the button,
   then get sorted into a hidden `.桌面抽屉` folder by type. Every move is logged and reversible.

3. **Screenshot & pin** — `F1` to drag-select (F2 = copy directly), annotate with rectangle /
   circle / arrow / polyline / pen / marker / mosaic / text, then copy, save, or pin the shot on
   screen as a floating reference (scroll to scale, Ctrl+scroll for opacity).

Plus a slide-out drawer on the right screen edge with fuzzy search (supports Chinese pinyin
initials) and clickable app icons. Search results are selectable: move several files into any
drawer folder (or a new one), batch-rename by find/replace with live preview, or send them to
the system trash — all reversible with one Undo.

Windows support was **verified on Windows 11 (build 26200)**: the self-test
(`python tools/selftest_win.py`) passed 12/12 checks, including acrylic taskbar,
registry, tray, icons and hotkeys. Run it on other Windows builds too and share the
generated `selftest.txt`. The UI is Chinese only.

</details>
