# -*- coding: utf-8 -*-
"""win32_frame — 无边框窗口的原生窗口行为 (Win32 细节封装).

Chrome/VS Code 方案: 恢复 WS_CAPTION|WS_THICKFRAME 系统样式,
再用 WM_NCCALCSIZE 吃掉原生边框 → 自绘标题栏 + 系统级
最大化/还原/最小化动画、Aero Snap、DWM 阴影。

从 AppController 抽出的纯 Win32 模块 — 控制器只调
enable_native_frame(win) / native_max_toggle(win)。
"""
import ctypes
import ctypes.wintypes

from PySide6.QtCore import QAbstractNativeEventFilter

_user32 = ctypes.windll.user32

# ---- 常量 ----
WM_NCCALCSIZE = 0x0083
WM_SYSCOMMAND = 0x0112
SC_MAXIMIZE = 0xF030
SC_RESTORE = 0xF120
GWL_STYLE = -16
WS_SYSMENU = 0x00080000
WS_THICKFRAME = 0x00040000
WS_MINIMIZEBOX = 0x00020000
WS_MAXIMIZEBOX = 0x00010000
WS_CAPTION = 0x00C00000
SM_CXSIZEFRAME, SM_CYSIZEFRAME, SM_CXPADDEDBORDER = 32, 33, 92
SWP_FLAGS = 0x0001 | 0x0002 | 0x0004 | 0x0010 | 0x0020  # NOSIZE..FRAMECHANGED
DWMWA_TRANSITIONS_FORCED_DISABLED = 3


class _RECT(ctypes.Structure):
    _fields_ = [('left', ctypes.c_long), ('top', ctypes.c_long),
                ('right', ctypes.c_long), ('bottom', ctypes.c_long)]


class _NCCALCSIZE_PARAMS(ctypes.Structure):
    _fields_ = [('rgrc', _RECT * 3), ('lppos', ctypes.c_void_p)]


# 进程级状态 (一个过滤器服务所有已注册窗口)
_filter = None
_hwnds = set()


class _NcCalcFilter(QAbstractNativeEventFilter):
    def nativeEventFilter(self, eventType, message):
        if eventType != b'windows_generic_MSG' or not _hwnds:
            return False, 0
        try:
            msg = ctypes.wintypes.MSG.from_address(int(message))
        except Exception:
            return False, 0
        if msg.hWnd is None:
            return False, 0            # 线程消息 (无窗口) 直接放行
        if msg.message == WM_NCCALCSIZE and msg.wParam and \
                int(msg.hWnd) in _hwnds:
            p = _NCCALCSIZE_PARAMS.from_address(msg.lParam)
            r = p.rgrc[0]
            if _user32.IsZoomed(ctypes.wintypes.HWND(msg.hWnd)):
                # 最大化时窗口向屏幕外扩了边框宽 → 客户区缩回,
                # 否则内容顶到屏幕边缘 (Chrome/VS Code 同款修法)
                bx = (_user32.GetSystemMetrics(SM_CXSIZEFRAME) +
                      _user32.GetSystemMetrics(SM_CXPADDEDBORDER))
                by = (_user32.GetSystemMetrics(SM_CYSIZEFRAME) +
                      _user32.GetSystemMetrics(SM_CXPADDEDBORDER))
                r.left += bx
                r.right -= bx
                r.top += by
                r.bottom -= by
            return True, 0              # WM_NCCALCSIZE: 客户区=整窗
        return False, 0


def enable_native_frame(win):
    """给 QQuickWindow 装原生边框行为 (幂等, 多窗口安全)."""
    if win is None:
        return
    global _filter
    _user32.GetWindowLongW.argtypes = [ctypes.wintypes.HWND, ctypes.c_int]
    _user32.GetWindowLongW.restype = ctypes.c_long
    _user32.SetWindowLongW.argtypes = [ctypes.wintypes.HWND,
                                       ctypes.c_int, ctypes.c_long]
    hwnd = int(win.winId())
    # 1) 先装 NCCALCSIZE 过滤器并注册 hwnd (必须在改样式前!)
    if _filter is None:
        from PySide6.QtCore import QCoreApplication
        _filter = _NcCalcFilter()
        QCoreApplication.instance().installNativeEventFilter(_filter)
    _hwnds.add(hwnd)
    # 2) 加回系统窗口样式
    style = _user32.GetWindowLongW(hwnd, GWL_STYLE)
    _user32.SetWindowLongW(hwnd, GWL_STYLE, style | WS_SYSMENU |
                           WS_THICKFRAME | WS_MINIMIZEBOX |
                           WS_MAXIMIZEBOX | WS_CAPTION)
    # 3) 触发样式重算
    _user32.SetWindowPos(ctypes.wintypes.HWND(hwnd), 0, 0, 0, 0, 0, SWP_FLAGS)
    # 4) Qt 建无边框窗口时禁用了 DWM 过渡动画 → 重新启用 (原生最大化/
    #    还原/最小化动画的关键)
    dwm = ctypes.windll.dwmapi
    val = ctypes.c_int(0)              # FALSE = 强制启用过渡
    dwm.DwmSetWindowAttribute(ctypes.wintypes.HWND(hwnd),
                              DWMWA_TRANSITIONS_FORCED_DISABLED,
                              ctypes.byref(val), 4)


def round_corners(win):
    """让窗口四角变圆 (Windows 11 的系统圆角, 由 DWM 裁剪和描边; 最大化时系统自动变回直角)。
    Windows 10 没有这个属性, 调用会失败但没有副作用 — 那里窗口保持直角。"""
    if win is None:
        return
    DWMWA_WINDOW_CORNER_PREFERENCE, DWMWCP_ROUND = 33, 2
    value = ctypes.c_int(DWMWCP_ROUND)
    ctypes.windll.dwmapi.DwmSetWindowAttribute(ctypes.wintypes.HWND(int(win.winId())),
                                               DWMWA_WINDOW_CORNER_PREFERENCE, ctypes.byref(value), 4)


def native_max_toggle(win):
    """用系统命令最大化/还原 (WM_SYSCOMMAND), 走 DefWindowProc →
    原生 DWM 缩放动画; Qt 躲不开的 SetWindowPos 路径不播动画。

    是否已最大化以原生 IsZoomed 为准: 工作区等于整屏 (任务栏自动隐藏或
    在别的屏) 时, Qt 把最大化的无边框窗口报告成 FullScreen 而不是
    Maximized, 按 Qt 状态判断会永远发 SC_MAXIMIZE, 窗口再也还原不了。"""
    if win is None:
        return
    hwnd = ctypes.wintypes.HWND(int(win.winId()))
    command = SC_RESTORE if _user32.IsZoomed(hwnd) else SC_MAXIMIZE
    _user32.PostMessageW(hwnd, WM_SYSCOMMAND, command, 0)
