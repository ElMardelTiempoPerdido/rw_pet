"""只读的前台窗口快照与切换检测；坐标统一为屏幕物理像素，不依赖 Qt。"""
from contextlib import contextmanager
import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import os
import sys

from ..shared.geometry import Bounds, Vec2


@dataclass(frozen=True, slots=True)
class DesktopWindow:
    handle: int
    process_id: int
    bounds: Bounds
    screen: Bounds

    @property
    def identity(self):
        return self.handle, self.process_id

    @property
    def fullscreen(self):
        a, b = self.bounds, self.screen
        return (a.left <= b.left+2 and a.top <= b.top+2
                and a.right >= b.right-2 and a.bottom >= b.bottom-2)

    @property
    def center(self):
        b = self.screen if self.fullscreen else self.bounds
        return Vec2((b.left+b.right)/2, (b.top+b.bottom)/2)


@dataclass(frozen=True, slots=True)
class WindowUpdate:
    window: DesktopWindow | None
    changed: bool


class ForegroundWindowTracker:
    def __init__(self, reader=None):
        self.reader = reader
        self.reset()

    def reset(self):
        self.initialized = False
        self.identity = None

    def poll(self):
        window = self.reader.read() if self.reader is not None else None
        identity = window.identity if window is not None else None
        changed = self.initialized and identity != self.identity
        self.initialized, self.identity = True, identity
        return WindowUpdate(window, changed)


class MonitorInfo(ctypes.Structure):
    _fields_ = [('size', wintypes.DWORD), ('screen', wintypes.RECT),
                ('work', wintypes.RECT), ('flags', wintypes.DWORD)]


def bounds(rect):
    return Bounds(rect.left, rect.top, rect.right, rect.bottom)


class WindowsWindowReader:
    """不读标题/内容、不获取焦点、不安装鼠标或键盘钩子。"""
    IGNORED_CLASSES = {'Progman', 'WorkerW', 'Shell_TrayWnd', 'Shell_SecondaryTrayWnd'}

    def __init__(self):
        if sys.platform != 'win32':
            raise OSError('Foreground window reading requires Windows')
        self.user = ctypes.WinDLL('user32', use_last_error=True)
        self.dwm = ctypes.WinDLL('dwmapi', use_last_error=True)
        signatures = {
            'GetForegroundWindow': ((), wintypes.HWND),
            'GetAncestor': ((wintypes.HWND, wintypes.UINT), wintypes.HWND),
            'IsWindowVisible': ((wintypes.HWND,), wintypes.BOOL),
            'IsIconic': ((wintypes.HWND,), wintypes.BOOL),
            'GetWindowThreadProcessId': ((wintypes.HWND, ctypes.POINTER(wintypes.DWORD)), wintypes.DWORD),
            'GetWindowRect': ((wintypes.HWND, ctypes.POINTER(wintypes.RECT)), wintypes.BOOL),
            'GetClassNameW': ((wintypes.HWND, wintypes.LPWSTR, ctypes.c_int), ctypes.c_int),
            'MonitorFromWindow': ((wintypes.HWND, wintypes.DWORD), wintypes.HANDLE),
            'GetMonitorInfoW': ((wintypes.HANDLE, ctypes.POINTER(MonitorInfo)), wintypes.BOOL),
            'SetThreadDpiAwarenessContext': ((ctypes.c_void_p,), ctypes.c_void_p),
        }
        for name, (args, result) in signatures.items():
            function = getattr(self.user, name)
            function.argtypes, function.restype = args, result
        self.dwm.DwmGetWindowAttribute.argtypes = (wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD)
        self.dwm.DwmGetWindowAttribute.restype = ctypes.c_long

    @contextmanager
    def physical_pixels(self):
        # GetWindowRect 会按调用线程 DPI 虚拟化；只在读取期间统一到 PMv2。
        # finally 恢复 Qt 原有线程上下文，绝不改变进程 DPI 模式。
        previous = self.user.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
        try:
            yield bool(previous)
        finally:
            if previous:
                self.user.SetThreadDpiAwarenessContext(previous)

    def monitor(self, handle):
        monitor = self.user.MonitorFromWindow(handle, 2)  # MONITOR_DEFAULTTONEAREST
        info = MonitorInfo()
        info.size = ctypes.sizeof(info)
        if not monitor or not self.user.GetMonitorInfoW(monitor, ctypes.byref(info)):
            return None
        return info

    def work_area(self, handle):
        with self.physical_pixels() as valid:
            info = self.monitor(handle) if valid else None
            return bounds(info.work) if info is not None else None

    def read(self):
        with self.physical_pixels() as valid:
            if not valid:
                return None
            foreground = self.user.GetForegroundWindow()
            handle = self.user.GetAncestor(foreground, 2) if foreground else None  # GA_ROOT
            if not handle or not self.user.IsWindowVisible(handle) or self.user.IsIconic(handle):
                return None
            pid = wintypes.DWORD()
            if not self.user.GetWindowThreadProcessId(handle, ctypes.byref(pid)) or pid.value == os.getpid():
                return None
            name = ctypes.create_unicode_buffer(256)
            self.user.GetClassNameW(handle, name, len(name))
            if name.value in self.IGNORED_CLASSES:
                return None
            cloaked = wintypes.DWORD()
            if (self.dwm.DwmGetWindowAttribute(handle, 14, ctypes.byref(cloaked), ctypes.sizeof(cloaked)) == 0
                    and cloaked.value):  # DWMWA_CLOAKED：其他虚拟桌面等不可见窗口。
                return None
            rect = wintypes.RECT()
            if self.dwm.DwmGetWindowAttribute(handle, 9, ctypes.byref(rect), ctypes.sizeof(rect)) != 0:
                if not self.user.GetWindowRect(handle, ctypes.byref(rect)):
                    return None
            info = self.monitor(handle)
            if (info is None or rect.right <= rect.left or rect.bottom <= rect.top
                    or self.user.GetForegroundWindow() != foreground):
                return None
            return DesktopWindow(int(handle), pid.value, bounds(rect), bounds(info.screen))


def desktop_window_tracker(platform_name):
    reader = None
    if sys.platform == 'win32' and platform_name == 'windows':
        try:
            reader = WindowsWindowReader()
        except (OSError, AttributeError):
            pass
    return ForegroundWindowTracker(reader)
