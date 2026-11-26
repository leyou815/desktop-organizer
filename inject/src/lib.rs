//! 桌面整理 · 任务栏背景透明（explorer 内进程组件）
//!
//! 为什么必须是「注入」：
//!   Win11 任务栏的背景是一块 XAML `Shape`（元素名 `BackgroundFill`），和图标一起画在
//!   explorer 的同一个视觉树里。进程外没有任何 API 能只改背景——实测
//!   SetWindowCompositionAttribute 只拉动 4 级灰度、隐藏背景子窗口连图标一起消失、
//!   色键把整条任务栏变成一块 #202020 死色块。TranslucentTB 的做法也是注入，
//!   本文件按它的公开实现重写了一遍（不复制代码）：走 XAML Diagnostics。
//!
//! 链路（对着 xamlom.h 和 TTB 的 ExplorerTAP 逐个接口核过）：
//!   1. 宿主用 SetWindowsHookEx(WH_CALLWNDPROC) 把本 DLL 送进 explorer
//!   2. DllMain 认出自己在 explorer 里 → 起线程调 Windows.UI.Xaml.dll 的
//!      InitializeXamlDiagnosticsEx(conn, pid, null, 本DLL路径, CLSID_SITE, null)
//!   3. XAML 按 CLSID 调本 DLL 的 DllGetClassObject → 我们的 TapSite
//!   4. XAML 把 IXamlDiagnostics 塞进 TapSite::SetSite → 我们 QI 出 IVisualTreeService
//!      并在**另一个线程**里 AdviseVisualTreeChange（TTB 注释：同线程会卡住）
//!   5. 逐条收到视觉树通知，挑出 `...Shapes.Shape` 且名字是 BackgroundFill /
//!      BackgroundStroke 的元素，GetIInspectableFromHandle → QI IShape → put_Fill(null)
//!   6. 原画刷 AddRef 存下来，收到 restore 命令时原样放回去
//!
//! 目录：%APPDATA%\DesktopOrganizer\inject.log（日志，一行一件事）
//!       %APPDATA%\DesktopOrganizer\inject.cmd（命令：probe / clear / restore，1 秒轮询）
//!
//! 注意：InitializeXamlDiagnosticsEx 会把本 DLL 永久钉在 explorer 里，
//! 还原后也不要指望它被卸载——只需要它不再动任何东西。

#![allow(non_snake_case, non_upper_case_globals, dead_code)]

use std::ffi::c_void;
use std::io::Write;
use std::sync::atomic::{AtomicPtr, AtomicU32, AtomicUsize, Ordering};
use std::sync::Mutex;

// --------------------------------------------------------------------------- //
// 基础类型
// --------------------------------------------------------------------------- //
type HRESULT = i32;
type ULONG = u32;
type DWORD = u32;
type BOOL = i32;
type HINSTANCE = *mut c_void;
type HANDLE = *mut c_void;
type LPCWSTR = *const u16;
type BSTR = *mut u16;
type InstanceHandle = u64;

const S_OK: HRESULT = 0;
const E_NOINTERFACE: HRESULT = 0x8000_4002u32 as HRESULT;
const E_FAIL: HRESULT = 0x8000_4005u32 as HRESULT;
const CLASS_E_CLASSNOTAVAILABLE: HRESULT = 0x8004_0111u32 as HRESULT;
const E_NOTIMPL: HRESULT = 0x8000_4001u32 as HRESULT;

#[repr(C)]
#[derive(Clone, Copy)]
struct GUID {
    d1: u32,
    d2: u16,
    d3: u16,
    d4: [u8; 8],
}

const IID_IUNKNOWN: GUID = GUID { d1: 0x0000_0000, d2: 0x0000, d3: 0x0000,
                                  d4: [0xC0, 0, 0, 0, 0, 0, 0, 0x46] };
const IID_ICLASSFACTORY: GUID = GUID { d1: 0x0000_0001, d2: 0x0000, d3: 0x0000,
                                       d4: [0xC0, 0, 0, 0, 0, 0, 0, 0x46] };
// 注意末两字节：是 ...3D7352，不是 ...3D732D（我一开始记错了，XAML 在 QI 时把真值报了出来）
const IID_IOBJECTWITHSITE: GUID = GUID { d1: 0xFC48_01A3, d2: 0x2BA9, d3: 0x11CF,
                                         d4: [0xA2, 0x29, 0x00, 0xAA, 0x00, 0x3D, 0x73, 0x52] };
// xamlom.h: MIDL_INTERFACE("18C9E2B6-3F43-4116-9F2B-FF935D7770D2") IXamlDiagnostics
const IID_IXAMLDIAGNOSTICS: GUID = GUID { d1: 0x18C9_E2B6, d2: 0x3F43, d3: 0x4116,
                                          d4: [0x9F, 0x2B, 0xFF, 0x93, 0x5D, 0x77, 0x70, 0xD2] };
// xamlom.h: MIDL_INTERFACE("A593B11A-D17F-48BB-8F66-83910731C8A5") IVisualTreeService
const IID_IVISUALTREESERVICE: GUID = GUID { d1: 0xA593_B11A, d2: 0xD17F, d3: 0x48BB,
                                            d4: [0x8F, 0x66, 0x83, 0x91, 0x07, 0x31, 0xC8, 0xA5] };
// Windows.UI.Xaml.winmd 里 IShape 的 GuidAttribute 是二进制存的，这里是解出来的值
// （Windows.UI.Xaml.Shapes.IShape = 786F2B75-9AA0-454D-AE06-A2466E37C832，
//   方法顺序：slot3 get_Fill / slot4 put_Fill / slot5 get_Stroke / slot6 put_Stroke）
const IID_ISHAPE: GUID = GUID { d1: 0x786F_2B75, d2: 0x9AA0, d3: 0x454D,
                                d4: [0xAE, 0x06, 0xA2, 0x46, 0x6E, 0x37, 0xC8, 0x32] };

// 我们自己这个「任务栏外观提供者」的类 ID，随便挑一个不会撞车的
const CLSID_SITE: GUID = GUID { d1: 0x8D3A_1C7E, d2: 0x4B2F, d3: 0x4E6A,
                                d4: [0x9C, 0x15, 0x7D, 0x2B, 0x44, 0xE1, 0x6A, 0x90] };

#[repr(C)]
struct SourceInfo {
    FileName: BSTR,
    LineNumber: u32,
    ColumnNumber: u32,
    CharPosition: u32,
    Hash: BSTR,
}

#[repr(C)]
struct VisualElement {
    Handle: InstanceHandle,
    SrcInfo: SourceInfo,
    Type: BSTR,
    Name: BSTR,
    NumChildren: u32,
}

#[repr(C)]
struct ParentChildRelation {
    Parent: InstanceHandle,
    Child: InstanceHandle,
    ChildIndex: u32,
}

// --------------------------------------------------------------------------- //
// Win32
// --------------------------------------------------------------------------- //
#[link(name = "kernel32")]
extern "system" {
    fn GetModuleFileNameW(h: HINSTANCE, buf: *mut u16, n: u32) -> u32;
    fn LoadLibraryExW(name: LPCWSTR, file: HANDLE, flags: u32) -> HINSTANCE;
    fn GetProcAddress(h: HINSTANCE, name: *const u8) -> *const c_void;
    fn CreateEventW(attr: *mut c_void, manual: BOOL, initial: BOOL, name: LPCWSTR) -> HANDLE;
    fn SetEvent(h: HANDLE) -> BOOL;
    fn GetCurrentProcessId() -> u32;
    fn GetEnvironmentVariableW(name: LPCWSTR, buf: *mut u16, n: u32) -> u32;
    fn CreateThread(attr: *mut c_void, stack: usize, start: usize, param: *mut c_void,
                    flags: DWORD, tid: *mut DWORD) -> HANDLE;
    fn Sleep(ms: DWORD);
    fn GetTickCount64() -> u64;
    fn GetCurrentThreadId() -> DWORD;
}

#[link(name = "oleaut32")]
extern "system" {
    fn SysFreeString(s: BSTR);
}

const LOAD_LIBRARY_SEARCH_SYSTEM32: u32 = 0x0000_0800;
const READY_EVENT: &str = "Local\\DesktopOrganizerTapReady";
const WM_DO_WORK: u32 = 0x8001; // WM_APP + 1

#[repr(C)]
struct WNDCLASSEXW {
    cbSize: u32,
    style: u32,
    lpfnWndProc: usize,
    cbClsExtra: i32,
    cbWndExtra: i32,
    hInstance: HINSTANCE,
    hIcon: *mut c_void,
    hCursor: *mut c_void,
    hbrBackground: *mut c_void,
    lpszMenuName: LPCWSTR,
    lpszClassName: LPCWSTR,
    hIconSm: *mut c_void,
}

#[link(name = "user32")]
extern "system" {
    fn CallNextHookEx(h: HANDLE, code: i32, w: usize, l: isize) -> isize;
    fn RegisterClassExW(wc: *const WNDCLASSEXW) -> u16;
    fn CreateWindowExW(style: DWORD, class: LPCWSTR, name: LPCWSTR, wstyle: DWORD,
                       x: i32, y: i32, w: i32, h: i32, parent: *mut c_void,
                       menu: *mut c_void, inst: HINSTANCE, param: *mut c_void) -> *mut c_void;
    fn DefWindowProcW(hwnd: *mut c_void, msg: u32, w: usize, l: isize) -> isize;
    fn PostMessageW(hwnd: *mut c_void, msg: u32, w: usize, l: isize) -> BOOL;
}

// --------------------------------------------------------------------------- //
// 字符串 / 日志
// --------------------------------------------------------------------------- //
fn wide(s: &str) -> Vec<u16> {
    let mut v: Vec<u16> = s.encode_utf16().collect();
    v.push(0);
    v
}

fn appdata() -> String {
    let name = wide("APPDATA");
    let mut buf = [0u16; 512];
    unsafe {
        let n = GetEnvironmentVariableW(name.as_ptr(), buf.as_mut_ptr(), buf.len() as u32);
        if n > 0 && (n as usize) < buf.len() {
            return String::from_utf16_lossy(&buf[..n as usize]);
        }
    }
    String::from("C:\\ProgramData")
}

fn state_dir() -> String {
    let d = format!("{}\\DesktopOrganizer", appdata());
    let _ = std::fs::create_dir_all(&d);
    d
}

static LOG_LOCK: Mutex<()> = Mutex::new(());
static START: AtomicUsize = AtomicUsize::new(0);

fn log(msg: &str) {
    let _g = LOG_LOCK.lock();
    let t0 = START.load(Ordering::Relaxed);
    let ms = unsafe { GetTickCount64() } as usize;
    let base = if t0 == 0 {
        START.store(ms, Ordering::Relaxed);
        ms
    } else {
        t0
    };
    let line = format!("[+{:>6}ms] {}\n", ms.saturating_sub(base), msg);
    let path = format!("{}\\inject.log", state_dir());
    if let Ok(mut f) = std::fs::OpenOptions::new().create(true).append(true).open(&path) {
        let _ = f.write_all(line.as_bytes());
    }
}

unsafe fn bstr_to_string(b: BSTR) -> String {
    if b.is_null() {
        return String::new();
    }
    // BSTR 前面 4 字节是字节长度（不含结尾 0）
    let bytes = *((b as *const u32).sub(1)) as usize;
    let len = bytes / 2;
    let slice = std::slice::from_raw_parts(b as *const u16, len);
    String::from_utf16_lossy(slice)
}

// --------------------------------------------------------------------------- //
// COM 调用助手：拿外部对象的 vtable 槽位
// --------------------------------------------------------------------------- //
unsafe fn slot(obj: *mut c_void, idx: usize) -> *const c_void {
    if obj.is_null() {
        return std::ptr::null();
    }
    let vt = *(obj as *const *const *const c_void);
    *vt.add(idx)
}

unsafe fn com_addref(o: *mut c_void) {
    let p = slot(o, 1);
    if !p.is_null() {
        let f: unsafe extern "system" fn(*mut c_void) -> ULONG = std::mem::transmute(p);
        f(o);
    }
}

unsafe fn com_release(o: *mut c_void) {
    let p = slot(o, 2);
    if !p.is_null() {
        let f: unsafe extern "system" fn(*mut c_void) -> ULONG = std::mem::transmute(p);
        f(o);
    }
}

unsafe fn com_qi(o: *mut c_void, iid: *const GUID, out: *mut *mut c_void) -> HRESULT {
    let p = slot(o, 0);
    if p.is_null() {
        return E_FAIL;
    }
    let f: unsafe extern "system" fn(*mut c_void, *const GUID, *mut *mut c_void) -> HRESULT =
        std::mem::transmute(p);
    f(o, iid, out)
}

// IXamlDiagnostics: slot3 GetDispatcher … slot6 GetIInspectableFromHandle
unsafe fn diag_get_instance(diag: *mut c_void, h: InstanceHandle, out: *mut *mut c_void) -> HRESULT {
    let p = slot(diag, 6);
    let f: unsafe extern "system" fn(*mut c_void, InstanceHandle, *mut *mut c_void) -> HRESULT =
        std::mem::transmute(p);
    f(diag, h, out)
}

// IVisualTreeService: slot3 AdviseVisualTreeChange
unsafe fn vts_advise(vts: *mut c_void, cb: *mut c_void) -> HRESULT {
    let p = slot(vts, 3);
    let f: unsafe extern "system" fn(*mut c_void, *mut c_void) -> HRESULT = std::mem::transmute(p);
    f(vts, cb)
}

// IShape
//
// vtable 布局（这次是踩出来的）：IShape 是正常 WinRT 接口，ABI 上继承 IInspectable，
//   0..2 = IUnknown(QI/AddRef/Release)
//   3..5 = IInspectable(GetIids/GetRuntimeClassName/GetTrustLevel)
//   6..  = IShape 自己的方法(get_Fill/put_Fill/get_Stroke/put_Stroke/...)
// 我一开始按「继承 IUnknown、方法从 3 开始」算，把 GetIids 当 get_Fill 调了，
// 它往野指针写 IID 数组 → explorer 当场崩（日志停在 [3.5]，后面一行都留不下来）。
// 注意 IXamlDiagnostics 不是这样：它是 xamlom.h 里显式 `: public IUnknown` 声明的，
// 方法从 3 开始，所以它的 GetIInspectableFromHandle 在 6 槽——两套规矩别混用。
unsafe fn shape_get_fill(s: *mut c_void, out: *mut *mut c_void) -> HRESULT {
    let p = slot(s, 6);
    let f: unsafe extern "system" fn(*mut c_void, *mut *mut c_void) -> HRESULT =
        std::mem::transmute(p);
    f(s, out)
}
unsafe fn shape_put_fill(s: *mut c_void, brush: *mut c_void) -> HRESULT {
    let p = slot(s, 7);
    let f: unsafe extern "system" fn(*mut c_void, *mut c_void) -> HRESULT =
        std::mem::transmute(p);
    f(s, brush)
}
unsafe fn shape_get_stroke(s: *mut c_void, out: *mut *mut c_void) -> HRESULT {
    let p = slot(s, 8);
    let f: unsafe extern "system" fn(*mut c_void, *mut *mut c_void) -> HRESULT =
        std::mem::transmute(p);
    f(s, out)
}
unsafe fn shape_put_stroke(s: *mut c_void, brush: *mut c_void) -> HRESULT {
    let p = slot(s, 9);
    let f: unsafe extern "system" fn(*mut c_void, *mut c_void) -> HRESULT =
        std::mem::transmute(p);
    f(s, brush)
}

// --------------------------------------------------------------------------- //
// 状态：被我们改过的画刷，以及当前命令
// --------------------------------------------------------------------------- //
const KIND_FILL: u8 = 0;
const KIND_STROKE: u8 = 1;

struct Item {
    handle: InstanceHandle,
    shape: usize,      // IShape*
    kind: u8,
    original: usize,   // 原画刷（带一个引用）
    applied: bool,
    label: String,
}

static ITEMS: Mutex<Vec<Item>> = Mutex::new(Vec::new());
static MODE: Mutex<String> = Mutex::new(String::new());
static DIAG: AtomicPtr<c_void> = AtomicPtr::new(std::ptr::null_mut());
static CALLBACK: AtomicPtr<c_void> = AtomicPtr::new(std::ptr::null_mut());
static LOGGED_TYPES: Mutex<Vec<String>> = Mutex::new(Vec::new());
// 待处理的目标：(handle, kind, 名字, 类型名)。回调里只往这里塞，绝不碰 XAML 对象。
static PENDING: Mutex<Vec<(InstanceHandle, u8, String, String)>> = Mutex::new(Vec::new());
static HIDDEN_HWND: AtomicPtr<c_void> = AtomicPtr::new(std::ptr::null_mut());
// 创建隐藏窗口的那个线程 = XAML 的 UI 线程。只有它才允许碰视觉树对象。
static UI_TID: AtomicU32 = AtomicU32::new(0);
// 视觉树通知落在哪个线程 = UI 线程。第一次回调时记下来，用来判断"我是不是 UI 线程"。
static CALLBACK_TID: AtomicU32 = AtomicU32::new(0);
static CLASS_REGISTERED: AtomicUsize = AtomicUsize::new(0);
// 跨线程请求的动作（轮询线程读到 inject.cmd 后放这里，由 UI 线程执行）
static ACTION: Mutex<String> = Mutex::new(String::new());

fn current_mode() -> String {
    MODE.lock().map(|m| m.clone()).unwrap_or_default()
}

fn read_cmd_file() -> String {
    let p = format!("{}\\inject.cmd", state_dir());
    std::fs::read_to_string(p).map(|s| s.trim().to_lowercase()).unwrap_or_default()
}

unsafe fn put_raw(shape: usize, kind: u8, brush: *mut c_void) -> HRESULT {
    let s = shape as *mut c_void;
    if kind == KIND_FILL {
        shape_put_fill(s, brush)
    } else {
        shape_put_stroke(s, brush)
    }
}

fn mark_applied(shape: usize, kind: u8, applied: bool) {
    if let Ok(mut items) = ITEMS.lock() {
        for it in items.iter_mut() {
            if it.shape == shape && it.kind == kind {
                it.applied = applied;
            }
        }
    }
}

// 关键约束：调 put_* 的时候**绝不能**持有 ITEMS 锁。
// 换画刷会让 XAML 同步派发视觉树通知回来，那条路径（元素被移除时）也要锁 ITEMS，
// 而 std 的 Mutex 不可重入 → 当场死锁把任务栏冻住。所以先拍快照、放锁、再动 COM。
fn apply_all(why: &str) {
    let targets: Vec<(usize, u8)> = match ITEMS.lock() {
        Ok(items) => items
            .iter()
            .filter(|it| !it.applied)
            .map(|it| (it.shape, it.kind))
            .collect(),
        Err(_) => return,
    };
    if targets.is_empty() {
        return;
    }
    let mut n = 0;
    for (shape, kind) in targets {
        let hr = unsafe { put_raw(shape, kind, std::ptr::null_mut()) };
        if hr >= 0 {
            mark_applied(shape, kind, true);
            n += 1;
        } else {
            log(&format!("{why}: 清空画刷失败 0x{:08X}", hr as u32));
        }
    }
    if n > 0 {
        log(&format!("{why}: 已清空 {n} 个画刷（背景应当消失）"));
    }
}

fn restore_all(why: &str) {
    let targets: Vec<(usize, u8, usize)> = match ITEMS.lock() {
        Ok(items) => items
            .iter()
            .filter(|it| it.applied)
            .map(|it| (it.shape, it.kind, it.original))
            .collect(),
        Err(_) => return,
    };
    if targets.is_empty() {
        return;
    }
    let mut n = 0;
    for (shape, kind, original) in targets {
        let hr = unsafe { put_raw(shape, kind, original as *mut c_void) };
        if hr >= 0 {
            mark_applied(shape, kind, false);
            n += 1;
        } else {
            log(&format!("{why}: 还原画刷失败 0x{:08X}", hr as u32));
        }
    }
    if n > 0 {
        log(&format!("{why}: 已还原 {n} 个画刷"));
    }
}

// --------------------------------------------------------------------------- //
// 视觉树回调
// --------------------------------------------------------------------------- //
unsafe extern "system" fn cb_on_visual_tree_change(
    this: *mut c_void,
    relation: *const ParentChildRelation,
    element: *const VisualElement,
    mutation: i32,
) -> HRESULT {
    if element.is_null() {
        return S_OK;
    }
    if CALLBACK_TID.load(Ordering::Relaxed) == 0 {
        CALLBACK_TID.store(GetCurrentThreadId(), Ordering::SeqCst);
    }
    let e = &*element;
    let ty = bstr_to_string(e.Type);
    let name = bstr_to_string(e.Name);
    let _ = relation;

    if mutation == 1 {
        // Remove：元素没了，相关记录必须丢掉，否则还原时会对野指针写画刷。
        // 这里用 try_lock：万一通知是在我们自己 put_* 的过程中同步派发回来的，
        // 阻塞等锁会把自己锁死（同线程、不可重入）。抢不到就下一轮再说。
        if let Ok(mut items) = ITEMS.try_lock() {
            items.retain(|it| it.handle != e.Handle);
        }
    } else {
        // 实测（Win11 26200）：任务栏背景是
        //   Windows.UI.Xaml.Shapes.Rectangle # BackgroundFill
        //   Windows.UI.Xaml.Shapes.Rectangle # BackgroundStroke
        // 父级是 Taskbar.TaskbarFrame / Taskbar.TaskbarBackground # BackgroundControl。
        // 注意不是 Shape 而是 Rectangle（Shape 是它的基类），所以按名字认、按命名空间校验。
        let interesting = (name == "BackgroundFill" || name == "BackgroundStroke")
            && ty.starts_with("Windows.UI.Xaml.Shapes.");
        if interesting {
            log(&format!("命中 {ty} name={name} handle=0x{:X}", e.Handle));
            let kind = if name == "BackgroundStroke" { KIND_STROKE } else { KIND_FILL };
            if let Ok(mut q) = PENDING.lock() {
                q.push((e.Handle, kind, name.to_string(), ty.to_string()));
            }
            // 不在回调里直接动画刷：不是因为"回调里碰 XAML 必崩"（那是误判，真凶是
            // IShape 的 vtable 槽位算错，改到回调外照样崩），而是因为这里正处在 XAML
            // 修改视觉树的中途，同步调 COM 容易撞上重入/半成品状态。
            // 记下 handle，用消息甩到 UI 线程的消息循环里，等这轮改完再干。
            post_work();
        } else if !name.is_empty() {
            record_type(&format!("{ty} # {name}"));
        } else {
            record_type(&ty);
        }
    }

    SysFreeString(e.Type);
    SysFreeString(e.Name);
    SysFreeString(e.SrcInfo.FileName);
    SysFreeString(e.SrcInfo.Hash);
    let _ = this;
    S_OK
}

unsafe extern "system" fn cb_on_element_state_changed(
    _this: *mut c_void,
    _h: InstanceHandle,
    _state: i32,
    _ctx: LPCWSTR,
) -> HRESULT {
    S_OK
}

fn record_type(s: &str) {
    // 只记前 400 种不重复的，够我们看清任务栏那一层的类型名，又不至于把日志写爆
    if let Ok(mut v) = LOGGED_TYPES.lock() {
        if v.len() >= 400 || v.iter().any(|x| x == s) {
            return;
        }
        v.push(s.to_string());
        log(&format!("类型样本: {s}"));
    }
}

// --------------------------------------------------------------------------- //
// UI 线程执行通道
// --------------------------------------------------------------------------- //
// 为什么需要这层：视觉树通知回调里碰 XAML 对象会让 explorer 崩（重入断言）。
// 而 COM 接口又只能在创建它的线程（= XAML 的 UI 线程）上直接调，跨线程裸指针调用同样危险。
// 解法：在 UI 线程上建一个「只有消息、不显示」的窗口，回调里 PostMessage 自己，
// 等这一轮视觉树操作彻底结束、消息循环转回来时再干活。
unsafe extern "system" fn wnd_proc(hwnd: *mut c_void, msg: u32, w: usize, l: isize) -> isize {
    if msg == WM_DO_WORK {
        drain_pending();
        return 0;
    }
    DefWindowProcW(hwnd, msg, w, l)
}

unsafe fn ensure_work_window() -> *mut c_void {
    let hwnd = HIDDEN_HWND.load(Ordering::SeqCst);
    if !hwnd.is_null() {
        return hwnd;
    }
    let inst = INSTANCE.load(Ordering::SeqCst) as HINSTANCE;
    let cls = wide("DesktopOrganizerTapWnd");
    if CLASS_REGISTERED.swap(1, Ordering::SeqCst) == 0 {
        let wc = WNDCLASSEXW {
            cbSize: std::mem::size_of::<WNDCLASSEXW>() as u32,
            style: 0,
            lpfnWndProc: wnd_proc as usize,
            cbClsExtra: 0,
            cbWndExtra: 0,
            hInstance: inst,
            hIcon: std::ptr::null_mut(),
            hCursor: std::ptr::null_mut(),
            hbrBackground: std::ptr::null_mut(),
            lpszMenuName: std::ptr::null(),
            lpszClassName: cls.as_ptr(),
            hIconSm: std::ptr::null_mut(),
        };
        let atom = RegisterClassExW(&wc);
        log(&format!("RegisterClassExW(\"DesktopOrganizerTapWnd\") atom={atom}"));
    }
    // HWND_MESSAGE = -3：消息专用窗口，不参与绘制、不进 Alt-Tab，但能收 PostMessage
    let msg_parent = (-3isize) as *mut c_void;
    let title = wide("DesktopOrganizerTap");
    let h = CreateWindowExW(
        0, cls.as_ptr(), title.as_ptr(), 0, 0, 0, 0, 0,
        msg_parent, std::ptr::null_mut(), inst, std::ptr::null_mut(),
    );
    if h.is_null() {
        log("创建消息窗口失败，本轮无法改动任务栏");
        return std::ptr::null_mut();
    }
    UI_TID.store(GetCurrentThreadId(), Ordering::SeqCst);
    HIDDEN_HWND.store(h, Ordering::SeqCst);
    log(&format!("UI 线程消息窗口就绪 hwnd={:p} tid={}", h, GetCurrentThreadId()));
    h
}

fn post_work() {
    let hwnd = HIDDEN_HWND.load(Ordering::SeqCst);
    if hwnd.is_null() {
        // 只允许 UI 线程建这个窗口。判定依据是「视觉树通知跑在哪个线程」，
        // 不能用 UI_TID——它此时还是 0，会把第一次调用误判成"非 UI 线程"，窗口永远建不出来。
        let tid = unsafe { GetCurrentThreadId() };
        if tid != CALLBACK_TID.load(Ordering::SeqCst) {
            log(&format!("post_work: 当前不是 UI 线程（tid={tid}），跳过"));
            return;
        }
        let h = unsafe { ensure_work_window() };
        if h.is_null() {
            return;
        }
    }
    unsafe {
        PostMessageW(HIDDEN_HWND.load(Ordering::SeqCst), WM_DO_WORK, 0, 0);
    }
}

/// 只有 UI 线程会进这里（由 WM_DO_WORK 驱动）
unsafe fn drain_pending() {
    // ① 先执行轮询线程塞过来的动作命令
    let act = ACTION
        .lock()
        .map(|mut a| if a.is_empty() { String::new() } else { std::mem::take(&mut *a) })
        .unwrap_or_default();
    match act.as_str() {
        "clear" => apply_all("命令 clear"),
        "restore" => restore_all("命令 restore"),
        _ => {}
    }

    // ② 再处理回调期间记下的目标元素
    let batch: Vec<(InstanceHandle, u8, String, String)> = PENDING
        .lock()
        .map(|mut q| q.drain(..).collect())
        .unwrap_or_default();
    if batch.is_empty() {
        return;
    }
    log(&format!("UI 线程处理 {} 个目标", batch.len()));
    for (handle, _kind, name, ty) in batch {
        register_shape(handle, &ty, &name);
    }
}


unsafe fn register_shape(handle: InstanceHandle, ty: &str, name: &str) {
    let diag = DIAG.load(Ordering::SeqCst);
    log(&format!("  [1] register_shape 开始 diag={:p}", diag));
    if diag.is_null() {
        log("还没拿到 IXamlDiagnostics，先记下");
        return;
    }
    let mut insp: *mut c_void = std::ptr::null_mut();
    let hr = diag_get_instance(diag, handle, &mut insp);
    log(&format!("  [2] GetIInspectableFromHandle hr=0x{:08X} insp={:p}", hr as u32, insp));
    if hr < 0 || insp.is_null() {
        log(&format!("GetIInspectableFromHandle 失败 0x{:08X}", hr as u32));
        return;
    }
    let mut shape: *mut c_void = std::ptr::null_mut();
    let hr = com_qi(insp, &IID_ISHAPE as *const GUID, &mut shape);
    log(&format!("  [3] QI IShape hr=0x{:08X} shape={:p}", hr as u32, shape));
    if hr < 0 || shape.is_null() {
        log(&format!("QI IShape 失败 0x{:08X}（{ty}）", hr as u32));
        return;
    }

    let kind = if name == "BackgroundStroke" { KIND_STROKE } else { KIND_FILL };
    let mut original: *mut c_void = std::ptr::null_mut();
    log("  [3.5] 准备 get 画刷");
    let hr = if kind == KIND_FILL {
        shape_get_fill(shape, &mut original)
    } else {
        shape_get_stroke(shape, &mut original)
    };
    log(&format!(
        "  [4] {name}: get 画刷 hr=0x{:08X} brush={:p}",
        hr as u32, original
    ));
    log("  [4.5] 准备 release insp");
    com_release(insp);
    log("  [4.6] insp 已释放");

    if let Ok(mut items) = ITEMS.lock() {
        if items.iter().any(|it| it.shape == shape as usize && it.kind == kind) {
            com_release(shape);
            return;
        }
        items.push(Item {
            handle,
            shape: shape as usize,
            kind,
            original: original as usize,
            applied: false,
            label: name.to_string(),
        });
    }

    match current_mode().as_str() {
        "clear" => apply_all("收到 clear"),
        _ => {
            let _ = shape_get_fill; // 静默：probe 模式只看不动
        }
    }
}

// --------------------------------------------------------------------------- //
// 我们的 COM 对象
// --------------------------------------------------------------------------- //
type FnQI = unsafe extern "system" fn(*mut c_void, *const GUID, *mut *mut c_void) -> HRESULT;
type FnRef = unsafe extern "system" fn(*mut c_void) -> ULONG;

#[repr(C)]
struct Site {
    vtbl: *const SiteVtbl,
    refs: AtomicU32,
    site: AtomicPtr<c_void>,
    diag: AtomicPtr<c_void>,
}

#[repr(C)]
struct SiteVtbl {
    qi: FnQI,
    addref: FnRef,
    release: FnRef,
    setsite: unsafe extern "system" fn(*mut c_void, *mut c_void) -> HRESULT,
    getsite: unsafe extern "system" fn(*mut c_void, *const GUID, *mut *mut c_void) -> HRESULT,
}

fn guid_str(g: &GUID) -> String {
    format!(
        "{{{:08X}-{:04X}-{:04X}-{:02X}{:02X}-{:02X}{:02X}{:02X}{:02X}{:02X}{:02X}}}",
        g.d1, g.d2, g.d3, g.d4[0], g.d4[1], g.d4[2], g.d4[3], g.d4[4], g.d4[5], g.d4[6], g.d4[7]
    )
}

unsafe extern "system" fn site_qi(this: *mut c_void, iid: *const GUID, out: *mut *mut c_void) -> HRESULT {
    if iid.is_null() || out.is_null() {
        return E_FAIL;
    }
    let g = &*iid;
    let same = |a: &GUID| a.d1 == g.d1 && a.d2 == g.d2 && a.d3 == g.d3 && a.d4 == g.d4;
    let known = same(&IID_IUNKNOWN) || same(&IID_IOBJECTWITHSITE);
    log(&format!("TapSite::QI {} {}", guid_str(g), if known { "（已知）" } else { "（未知）" }));
    if known {
        *out = this;
        com_addref(this);
        S_OK
    } else {
        *out = std::ptr::null_mut();
        E_NOINTERFACE
    }
}

unsafe extern "system" fn site_addref(this: *mut c_void) -> ULONG {
    let s = &*(this as *const Site);
    s.refs.fetch_add(1, Ordering::SeqCst) + 1
}

unsafe extern "system" fn site_release(this: *mut c_void) -> ULONG {
    let s = &*(this as *const Site);
    let n = s.refs.fetch_sub(1, Ordering::SeqCst) - 1;
    if n == 0 {
        drop(Box::from_raw(this as *mut Site));
    }
    n
}

unsafe extern "system" fn site_setsite(this: *mut c_void, punk: *mut c_void) -> HRESULT {
    let s = &*(this as *const Site);
    if punk.is_null() {
        return S_OK;
    }
    log("SetSite 被调用，正在取 IXamlDiagnostics");
    let mut diag: *mut c_void = std::ptr::null_mut();
    let hr = com_qi(punk, &IID_IXAMLDIAGNOSTICS as *const GUID, &mut diag);
    if hr < 0 || diag.is_null() {
        log(&format!("SetSite: QI IXamlDiagnostics 失败 0x{:08X}", hr as u32));
        return E_NOINTERFACE;
    }
    s.diag.store(diag, Ordering::SeqCst);
    DIAG.store(diag, Ordering::SeqCst);
    s.site.store(punk, Ordering::SeqCst);
    log("SetSite: 拿到 IXamlDiagnostics");

    // TTB 的注释：在主线程里 Advise 会卡住，必须另起线程（回调本身会被 marshal 回 UI 线程）
    let raw = this as usize;
    let cb = CALLBACK.load(Ordering::SeqCst);
    if cb.is_null() {
        log("SetSite: 回调对象不存在");
        return S_OK;
    }
    com_addref(cb);
    let cb_raw = cb as usize;
    let _ = CreateThread(
        std::ptr::null_mut(),
        0,
        advise_thread as usize,
        Box::into_raw(Box::new((diag as usize, cb_raw, raw))) as *mut c_void,
        0,
        std::ptr::null_mut(),
    );
    S_OK
}

unsafe extern "system" fn advise_thread(param: *mut c_void) -> DWORD {
    let (diag, cb, _site) = *Box::from_raw(param as *mut (usize, usize, usize));
    let diag = diag as *mut c_void;
    let cb = cb as *mut c_void;
    log("advise 线程启动");
    let mut vts: *mut c_void = std::ptr::null_mut();
    let hr = com_qi(diag, &IID_IVISUALTREESERVICE as *const GUID, &mut vts);
    if hr < 0 || vts.is_null() {
        log(&format!("QI IVisualTreeService 失败 0x{:08X}", hr as u32));
        com_release(cb);
        return 0;
    }
    let hr = vts_advise(vts, cb);
    log(&format!("AdviseVisualTreeChange hr=0x{:08X}", hr as u32));
    com_release(vts);
    com_release(cb);
    0
}

unsafe extern "system" fn site_getsite(
    this: *mut c_void,
    iid: *const GUID,
    out: *mut *mut c_void,
) -> HRESULT {
    let s = &*(this as *const Site);
    let p = s.site.load(Ordering::SeqCst);
    if p.is_null() {
        return E_FAIL;
    }
    com_qi(p, iid, out)
}

static SITE_VTBL: SiteVtbl = SiteVtbl {
    qi: site_qi,
    addref: site_addref,
    release: site_release,
    setsite: site_setsite,
    getsite: site_getsite,
};

#[repr(C)]
struct Factory {
    vtbl: *const FactoryVtbl,
    refs: AtomicU32,
}

#[repr(C)]
struct FactoryVtbl {
    qi: FnQI,
    addref: FnRef,
    release: FnRef,
    create: unsafe extern "system" fn(*mut c_void, *mut c_void, *const GUID, *mut *mut c_void) -> HRESULT,
    lock: unsafe extern "system" fn(*mut c_void, BOOL) -> HRESULT,
}

unsafe extern "system" fn fac_qi(this: *mut c_void, iid: *const GUID, out: *mut *mut c_void) -> HRESULT {
    if iid.is_null() || out.is_null() {
        return E_FAIL;
    }
    let g = &*iid;
    let same = |a: &GUID| a.d1 == g.d1 && a.d2 == g.d2 && a.d3 == g.d3 && a.d4 == g.d4;
    if same(&IID_IUNKNOWN) || same(&IID_ICLASSFACTORY) {
        *out = this;
        com_addref(this);
        S_OK
    } else {
        *out = std::ptr::null_mut();
        E_NOINTERFACE
    }
}

unsafe extern "system" fn fac_addref(this: *mut c_void) -> ULONG {
    let f = &*(this as *const Factory);
    f.refs.fetch_add(1, Ordering::SeqCst) + 1
}

unsafe extern "system" fn fac_release(this: *mut c_void) -> ULONG {
    let f = &*(this as *const Factory);
    let n = f.refs.fetch_sub(1, Ordering::SeqCst) - 1;
    if n == 0 {
        drop(Box::from_raw(this as *mut Factory));
    }
    n
}

unsafe extern "system" fn fac_create(
    this: *mut c_void,
    outer: *mut c_void,
    iid: *const GUID,
    out: *mut *mut c_void,
) -> HRESULT {
    let _ = this;
    if !outer.is_null() {
        return 0x8004_0155u32 as HRESULT; // CLASS_E_NOAGGREGATION
    }
    let site = Box::new(Site {
        vtbl: &SITE_VTBL,
        refs: AtomicU32::new(1),
        site: AtomicPtr::new(std::ptr::null_mut()),
        diag: AtomicPtr::new(std::ptr::null_mut()),
    });
    let raw = Box::into_raw(site) as *mut c_void;
    let hr = site_qi(raw, iid, out);
    if hr < 0 {
        site_release(raw);
    }
    log(&format!("TapSite 已创建（QI hr=0x{:08X}）", hr as u32));
    hr
}

unsafe extern "system" fn fac_lock(_this: *mut c_void, _lock: BOOL) -> HRESULT {
    S_OK
}

static FACTORY_VTBL: FactoryVtbl = FactoryVtbl {
    qi: fac_qi,
    addref: fac_addref,
    release: fac_release,
    create: fac_create,
    lock: fac_lock,
};

#[repr(C)]
struct Cb {
    vtbl: *const CbVtbl,
    refs: AtomicU32,
}

#[repr(C)]
struct CbVtbl {
    qi: FnQI,
    addref: FnRef,
    release: FnRef,
    change: unsafe extern "system" fn(*mut c_void, *const ParentChildRelation, *const VisualElement, i32) -> HRESULT,
    state: unsafe extern "system" fn(*mut c_void, InstanceHandle, i32, LPCWSTR) -> HRESULT,
}

unsafe extern "system" fn cb_qi(this: *mut c_void, iid: *const GUID, out: *mut *mut c_void) -> HRESULT {
    if iid.is_null() || out.is_null() {
        return E_FAIL;
    }
    let g = &*iid;
    let same = |a: &GUID| a.d1 == g.d1 && a.d2 == g.d2 && a.d3 == g.d3 && a.d4 == g.d4;
    // IVisualTreeServiceCallback 与 ...Callback2 的 IID 我们不去查表：XAML 只会用
    // 「它给的那个接口指针」来调，不会反过来 QI 我们的其它接口，所以对任何 IID 都返回自己
    // 反而最稳（QueryInterface 返回自己 + AddRef，语义上是合法的）。
    let _ = same;
    *out = this;
    com_addref(this);
    S_OK
}

unsafe extern "system" fn cb_addref(this: *mut c_void) -> ULONG {
    let c = &*(this as *const Cb);
    c.refs.fetch_add(1, Ordering::SeqCst) + 1
}

unsafe extern "system" fn cb_release(this: *mut c_void) -> ULONG {
    let c = &*(this as *const Cb);
    c.refs.fetch_sub(1, Ordering::SeqCst) - 1
}

static CB_VTBL: CbVtbl = CbVtbl {
    qi: cb_qi,
    addref: cb_addref,
    release: cb_release,
    change: cb_on_visual_tree_change,
    state: cb_on_element_state_changed,
};

// --------------------------------------------------------------------------- //
// 导出：DllGetClassObject / DllMain / HookProc
// --------------------------------------------------------------------------- //
#[no_mangle]
pub unsafe extern "system" fn DllGetClassObject(
    rclsid: *const GUID,
    riid: *const GUID,
    ppv: *mut *mut c_void,
) -> HRESULT {
    log("DllGetClassObject 被调用");
    if rclsid.is_null() || ppv.is_null() {
        return E_FAIL;
    }
    let g = &*rclsid;
    if g.d1 != CLSID_SITE.d1 || g.d2 != CLSID_SITE.d2 || g.d3 != CLSID_SITE.d3
        || g.d4 != CLSID_SITE.d4
    {
        return CLASS_E_CLASSNOTAVAILABLE;
    }
    let fac = Box::new(Factory { vtbl: &FACTORY_VTBL, refs: AtomicU32::new(1) });
    let raw = Box::into_raw(fac) as *mut c_void;
    let hr = fac_qi(raw, riid, ppv);
    if hr < 0 {
        fac_release(raw);
    }
    hr
}

fn module_path(h: HINSTANCE) -> String {
    let mut buf = [0u16; 1024];
    let n = unsafe { GetModuleFileNameW(h, buf.as_mut_ptr(), buf.len() as u32) };
    String::from_utf16_lossy(&buf[..n as usize])
}

fn is_explorer() -> bool {
    let p = module_path(std::ptr::null_mut()).to_lowercase();
    p.ends_with("explorer.exe")
}

static INSTANCE: AtomicUsize = AtomicUsize::new(0);

unsafe fn install() {
    let inst = INSTANCE.load(Ordering::SeqCst) as HINSTANCE;
    let dll = module_path(inst);
    log(&format!("== 注入成功 pid={} dll={}", GetCurrentProcessId(), dll));

    // 回调对象只造一个，长期存活
    if CALLBACK.load(Ordering::SeqCst).is_null() {
        let cb = Box::new(Cb { vtbl: &CB_VTBL, refs: AtomicU32::new(1) });
        CALLBACK.store(Box::into_raw(cb) as *mut c_void, Ordering::SeqCst);
    }
    *MODE.lock().unwrap_or_else(|e| e.into_inner()) = read_cmd_file();

    let ev_name = wide(READY_EVENT);
    let ev = CreateEventW(std::ptr::null_mut(), 1, 0, ev_name.as_ptr());

    let mut done = false;
    let xaml = LoadLibraryExW(
        wide("Windows.UI.Xaml.dll").as_ptr(),
        std::ptr::null_mut(),
        LOAD_LIBRARY_SEARCH_SYSTEM32,
    );
    if xaml.is_null() {
        log("LoadLibrary Windows.UI.Xaml.dll 失败");
    } else {
        let p = GetProcAddress(xaml, b"InitializeXamlDiagnosticsEx\0".as_ptr());
        if p.is_null() {
            log("取不到 InitializeXamlDiagnosticsEx");
        } else {
            type PfnIxde = unsafe extern "system" fn(
                LPCWSTR, DWORD, LPCWSTR, LPCWSTR, *const GUID, LPCWSTR,
            ) -> HRESULT;
            let ixde: PfnIxde = std::mem::transmute(p);
            let dll_w = wide(&dll);
            for attempt in 1..=40u32 {
                let conn = wide(&format!("VisualDiagConnection{}", attempt));
                let hr = ixde(
                    conn.as_ptr(),
                    GetCurrentProcessId(),
                    std::ptr::null(),
                    dll_w.as_ptr(),
                    &CLSID_SITE as *const GUID,
                    std::ptr::null(),
                );
                log(&format!("InitializeXamlDiagnosticsEx #{attempt} hr=0x{:08X}", hr as u32));
                if hr == S_OK {
                    done = true;
                    break;
                }
                Sleep(500);
            }
        }
    }

    if !ev.is_null() {
        SetEvent(ev);
    }
    if !done {
        log("初始化失败，本轮放弃（不改任何画刷）");
        return;
    }

    // 命令轮询：宿主改 inject.cmd 就能让背景透明/还原
    std::thread::spawn(|| loop {
        Sleep(700);
        let want = read_cmd_file();
        if want.is_empty() {
            continue;
        }
        let cur = current_mode();
        if want == cur {
            continue;
        }
        *MODE.lock().unwrap_or_else(|e| e.into_inner()) = want.clone();
        match want.as_str() {
            // 不能在这个线程直接改画刷：COM 对象属于 UI 线程，跨线程裸调一样会让 explorer 崩。
            // 塞进 ACTION 再敲一下消息，让 UI 线程去执行。
            "clear" | "restore" => {
                if let Ok(mut a) = ACTION.lock() {
                    *a = want.clone();
                }
                log(&format!("命令 {want} 已排队，等 UI 线程执行"));
                post_work();
            }
            "probe" => log("命令 probe：只看不动"),
            other => log(&format!("未知命令 {other}")),
        }
    });
}

unsafe extern "system" fn install_thread(_p: *mut c_void) -> DWORD {
    install();
    0
}

static INSTALLED: AtomicUsize = AtomicUsize::new(0);

/// 触发安装。DllMain 和 HookProc 都会调它，用 INSTALLED 保证只干一次
/// （DLL 被 InitializeXamlDiagnosticsEx 钉在 explorer 里之后，再注入一次不会再走 DllMain，
///  只有钩子过程会被调用——所以触发点必须放在这里）。
unsafe fn trigger_install() {
    if INSTALLED.swap(1, Ordering::SeqCst) != 0 {
        return;
    }
    CreateThread(
        std::ptr::null_mut(),
        0,
        install_thread as usize,
        std::ptr::null_mut(),
        0,
        std::ptr::null_mut(),
    );
}

#[no_mangle]
pub unsafe extern "system" fn DllMain(hinst: HINSTANCE, reason: DWORD, _res: *mut c_void) -> BOOL {
    if reason == 1 {
        INSTANCE.store(hinst as usize, Ordering::SeqCst);
        if is_explorer() {
            trigger_install();
        }
    }
    1
}

/// 钩子过程：宿主用 SetWindowsHookEx(WH_CALLWNDPROC) 挂上它把本 DLL 带进 explorer。
/// 真正的活在 trigger_install 起的线程里。
#[no_mangle]
pub unsafe extern "system" fn HookProc(code: i32, w: usize, l: isize) -> isize {
    if code >= 0 && is_explorer() {
        trigger_install();
    }
    CallNextHookEx(std::ptr::null_mut(), code, w, l)
}
