"""设置与外观编辑器共用的控件，滚轮仅滚动页面"""
from PySide6.QtCore import QCoreApplication, QPointF, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap, QWheelEvent
from PySide6.QtWidgets import QColorDialog, QComboBox, QDoubleSpinBox, QPushButton, QScrollArea, QSpinBox

from ...i18n import tr


class _WheelScrollsPage:
    def wheelEvent(self, event):
        parent = self.parentWidget()
        while parent is not None and not isinstance(parent, QScrollArea):
            parent = parent.parentWidget()
        if parent is not None:
            viewport = parent.viewport()
            forwarded = QWheelEvent(QPointF(viewport.mapFromGlobal(event.globalPosition().toPoint())),
                                    event.globalPosition(), event.pixelDelta(), event.angleDelta(), event.buttons(),
                                    event.modifiers(), event.phase(), event.inverted(), event.source(),
                                    event.pointingDevice())
            QCoreApplication.sendEvent(viewport, forwarded)
            event.setAccepted(forwarded.isAccepted())
        else:
            event.ignore()


class WheelSafeSpinBox(_WheelScrollsPage, QSpinBox):
    pass


class WheelSafeDoubleSpinBox(_WheelScrollsPage, QDoubleSpinBox):
    pass


class WheelSafeComboBox(_WheelScrollsPage, QComboBox):
    pass


class ColorButton(QPushButton):
    valueChanged = Signal(str)

    def __init__(self, value, title):
        super().__init__()
        self.title = title
        self.setAutoDefault(False)
        self.setValue(value)
        self.clicked.connect(self.choose_color)

    def value(self):
        return self._color

    def setValue(self, value):
        color = QColor(value)
        if getattr(self, '_color', None) == color.name():
            return
        self._color = color.name()
        self.setText(self._color.upper())
        swatch = QPixmap(16, 16)
        swatch.fill(color)
        painter = QPainter(swatch)
        painter.setPen(QColor('#707070'))
        painter.drawRect(0, 0, 15, 15)
        painter.end()
        self.setIcon(QIcon(swatch))
        self.valueChanged.emit(self._color)

    def choose_color(self):
        color = QColorDialog.getColor(QColor(self._color), self, tr(self.title),
                                      QColorDialog.ColorDialogOption.DontUseNativeDialog)
        if color.isValid():
            self.setValue(color.name())
