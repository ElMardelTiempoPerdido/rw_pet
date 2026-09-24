"""桌宠共用的透明置顶与鼠标穿透窗口设置。"""
from PySide6.QtCore import Qt


def configure_desktop_overlay(window):
    """两种桌宠共用的顶层窗口契约；透明像素与可见像素都不接收输入。"""
    window.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
                          | Qt.WindowType.WindowStaysOnTopHint
                          | Qt.WindowType.WindowTransparentForInput
                          | Qt.WindowType.WindowDoesNotAcceptFocus)
    window.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    window.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    window.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
