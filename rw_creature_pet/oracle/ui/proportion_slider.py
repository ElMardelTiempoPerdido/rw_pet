"""总计 100% 的分段比例编辑器，显示精度为 0.1%"""
from math import floor

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from .inputs import WheelSafeDoubleSpinBox, _WheelScrollsPage
from .settings_style import INK, MUTED, PAPER, pixel_box

TOTAL = 1000


def shares(values, total=TOTAL):
    """按原比例分配整数单位，并补齐舍入余数；全零时等分"""
    weights = [max(0., float(value)) for value in values]
    if not any(weights):
        weights = [1.] * len(weights)
    exact = [value / sum(weights) * total for value in weights]
    result = [floor(value) for value in exact]
    order = sorted(range(len(result)), key=lambda i: (exact[i]-result[i], -i), reverse=True)
    for i in order[:total-sum(result)]:
        result[i] += 1
    return result


def redistribute(values, index, value):
    value = max(0, min(TOTAL, round(value)))
    others = shares([v for i, v in enumerate(values) if i != index], TOTAL-value)
    others.insert(index, value)
    return others


class ProportionSlider(_WheelScrollsPage, QWidget):
    edited = Signal(object)

    def __init__(self, count, parent=None):
        super().__init__(parent)
        if count < 2:
            raise ValueError('A proportion slider needs at least two choices')
        self.values = shares([1] * count)
        self.handle = 0
        self.dragging = False
        self.drag_offset = 0.
        self.setFixedHeight(48)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)

    def set_values(self, values):
        self.values = list(values)
        self.update()

    def track(self):
        return QRectF(6, 8, max(1, self.width()-12), 32)

    def boundaries(self):
        return [sum(self.values[:i+1]) for i in range(len(self.values)-1)]

    def move_boundary(self, index, value):
        before = sum(self.values[:index])
        after = before + self.values[index] + self.values[index+1]
        boundary = max(before, min(after, round(value)))
        values = self.values.copy()
        values[index:index+2] = (boundary-before, after-boundary)
        if values != self.values:
            self.set_values(values)
            self.edited.emit(values)

    def drag_to(self, x):
        rect = self.track()
        self.move_boundary(self.handle, (x-self.drag_offset-rect.left())/rect.width()*TOTAL)

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton or not self.isEnabled():
            return super().mousePressEvent(event)
        rect = self.track()
        positions = [rect.left()+v/TOTAL*rect.width() for v in self.boundaries()]
        x = event.position().x()
        self.handle = min(range(len(positions)), key=lambda i: (abs(positions[i]-x), -i if x >= positions[i] else i))
        self.drag_offset = x-positions[self.handle] if abs(x-positions[self.handle]) <= 8 else 0.
        self.dragging = True
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        self.drag_to(x)
        event.accept()

    def mouseMoveEvent(self, event):
        if self.dragging and self.isEnabled():
            self.drag_to(event.position().x())
        else:
            rect = self.track()
            near = any(abs(event.position().x()-(rect.left()+v/TOTAL*rect.width())) <= 8 for v in self.boundaries())
            self.setCursor(Qt.CursorShape.SplitHCursor if near else Qt.CursorShape.ArrowCursor)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if self.dragging and self.isEnabled():
                self.drag_to(event.position().x())
            self.dragging = False
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        key = event.key()
        if key in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            self.handle = (self.handle + (1 if key == Qt.Key.Key_Down else -1)) % (len(self.values)-1)
            self.update()
        elif key in (Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Home, Qt.Key.Key_End):
            value = self.boundaries()[self.handle]
            if key == Qt.Key.Key_Home:
                value = 0
            elif key == Qt.Key.Key_End:
                value = TOTAL
            else:
                step = 1 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 10
                value += step if key == Qt.Key.Key_Right else -step
            self.move_boundary(self.handle, value)
        else:
            return super().keyPressEvent(event)
        event.accept()

    def paintEvent(self, event):
        painter = QPainter(self)
        rect = self.track()
        path = QPainterPath()
        path.addRoundedRect(rect, 4, 4)
        painter.save()
        painter.setClipPath(path)
        left = rect.left()
        for i, value in enumerate(self.values):
            shade = round(191 + (PAPER.red()-191) * i / (len(self.values)-1))
            color = QColor(shade, shade, shade)
            right = left + value/TOTAL*rect.width()
            painter.fillRect(QRectF(left, rect.top(), right-left, rect.height()), color)
            left = right
        painter.restore()
        border = INK if self.isEnabled() else MUTED
        pixel_box(painter, rect, fill=QColor(0, 0, 0, 0), border=border)
        for i, value in enumerate(self.boundaries()):
            x = rect.left()+value/TOTAL*rect.width()
            pen = QPen(border, 3 if self.hasFocus() and i == self.handle else 2)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.drawLine(QPointF(x, 3), QPointF(x, self.height()-3))
            painter.drawLine(QPointF(x-3, 3), QPointF(x+3, 3))
            painter.drawLine(QPointF(x-3, self.height()-3), QPointF(x+3, self.height()-3))


class ProportionEditor(QWidget):
    edited = Signal(object)

    def __init__(self, labels):
        super().__init__()
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.slider = ProportionSlider(len(labels), self)
        layout.addWidget(self.slider)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)
        self.inputs, self.labels = [], []
        self.updating = False
        for i, text in enumerate(labels):
            if i:
                row.addWidget(QLabel('/'))
            cell = QWidget(self)
            line = QHBoxLayout(cell)
            line.setContentsMargins(0, 0, 0, 0)
            line.setSpacing(8)
            label = QLabel(text)
            label.setWordWrap(True)
            label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
            label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            control = WheelSafeDoubleSpinBox()
            control.setDecimals(1)
            control.setRange(0, 100)
            control.setSingleStep(1)
            control.setSuffix(' %')
            control.setKeyboardTracking(False)
            control.setFixedWidth(100)
            label.setBuddy(control)
            line.addStretch(1)
            line.addWidget(label)
            line.addWidget(control)
            line.addStretch(1)
            row.addWidget(cell, 1)
            self.labels.append(label)
            self.inputs.append(control)
            control.valueChanged.connect(lambda value, index=i: self.edit_number(index, value))
        layout.addLayout(row)
        self.slider.edited.connect(self.edit_values)

    def set_values(self, values):
        self.updating = True
        try:
            self.slider.set_values(values)
            for control, value in zip(self.inputs, values):
                control.setValue(value/10)
        finally:
            self.updating = False

    def edit_number(self, index, value):
        if not self.updating:
            self.edit_values(redistribute(self.slider.values, index, round(value*10)))

    def edit_values(self, values):
        self.set_values(values)
        self.edited.emit(values)

    def set_editable(self, enabled):
        self.slider.setEnabled(enabled)
        if not enabled:
            self.slider.dragging = False
        for control in self.inputs:
            control.setEnabled(enabled)
