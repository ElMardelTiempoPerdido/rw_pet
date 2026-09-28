"""局部输入窗口。显示窗口仍完全穿透，只有目标 alpha 轮廓拦截输入。"""
import sys

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtGui import QColor, QGuiApplication, QPainter
from PySide6.QtWidgets import QWidget

from ..shared.geometry import Vec2


def left_button_down():
    """查询当前逻辑左键；Windows 不依赖可能遗漏松键事件的 Qt 缓存。"""
    if sys.platform == 'win32' and QGuiApplication.platformName() == 'windows':
        import ctypes
        user32 = ctypes.windll.user32
        # GetAsyncKeyState 返回物理按键，尊重系统交换左右键的设置。
        button = 0x02 if user32.GetSystemMetrics(23) else 0x01  # SM_SWAPBUTTON
        return bool(user32.GetAsyncKeyState(button) & 0x8000)
    return bool(QGuiApplication.mouseButtons() & Qt.MouseButton.LeftButton)


class DragInputWindow(QWidget):
    def __init__(self, owner):
        super().__init__(owner, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setWindowTitle('桌宠 · 人偶拖拽输入')
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.adapter = self.hit = self.viewport = None
        self._captured = False
        self._shape_key = None
        self._release_watch = QTimer(self)
        self._release_watch.setInterval(150)
        self._release_watch.timeout.connect(self.check_buttons)

    def sync(self, adapter, hit, viewport):
        if self.adapter is not adapter:
            self.cancel()
        self.adapter, self.hit, self.viewport = adapter, hit, viewport
        key = (hit, viewport)
        if key == self._shape_key:
            if not self.isVisible():
                self.show()
            return
        region = hit.region(viewport.scale, Vec2(viewport.x, viewport.y))
        bounds = region.boundingRect()
        if bounds.isEmpty():
            self.suspend()
            return
        self.setGeometry(bounds)
        self.setMask(region.translated(-bounds.x(), -bounds.y()))
        self._shape_key = key
        if not self.isVisible():
            self.show()

    def cancel(self):
        self._release_watch.stop()
        if self.adapter is not None:
            self.adapter.release(cancel=True)
        if self._captured:
            self._captured = False
            self.releaseMouse()
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    def check_buttons(self):
        # 只恢复已有抓取；绝不因轮询到按键按下而开始抓取。
        if self._captured and not left_button_down():
            self.cancel()

    def suspend(self):
        self.cancel()
        self.hide()

    def world_point(self, event):
        p = event.globalPosition()
        return self.viewport.to_world(Vec2(p.x(), p.y()))

    def mousePressEvent(self, event):
        if (event.button() == Qt.MouseButton.LeftButton and self.adapter is not None
                and self.adapter.press(self.world_point(event), self.hit.contains)):
            self._captured = True
            self.grabMouse()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            if self._captured:
                self._release_watch.start()
            event.accept()
        else:
            event.ignore()

    def mouseMoveEvent(self, event):
        if self._captured and self.adapter is not None:
            if event.buttons() & Qt.MouseButton.LeftButton:
                self.adapter.move(self.world_point(event))
            else:
                self.cancel()
            event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._captured:
            self._release_watch.stop()
            self.adapter.move(self.world_point(event))
            self.adapter.release()
            self._captured = False
            self.releaseMouse()
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            event.accept()

    def event(self, event):
        if (event.type() == QEvent.Type.UngrabMouse and getattr(self, '_captured', False)):
            self.cancel()
        return super().event(event)

    def paintEvent(self, event):
        # Windows 的逐像素透明窗口只将非零 alpha 像素算作输入表面。
        # 窗口 mask 限定到人偶；1/255 alpha 无可感知的额外轮廓。
        painter = QPainter(self)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 1))
        painter.end()

    def closeEvent(self, event):
        self.cancel()
        super().closeEvent(event)
