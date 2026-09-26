"""局部输入窗口。显示窗口仍完全穿透，只有目标 alpha 轮廓拦截输入。"""
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QWidget

from ..shared.geometry import Vec2


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
        if self.adapter is not None:
            self.adapter.release(cancel=True)
        if self._captured:
            self._captured = False
            self.releaseMouse()
        self.setCursor(Qt.CursorShape.OpenHandCursor)

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
            event.accept()
        else:
            event.ignore()

    def mouseMoveEvent(self, event):
        if self._captured and self.adapter is not None:
            self.adapter.move(self.world_point(event))
            event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._captured:
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
