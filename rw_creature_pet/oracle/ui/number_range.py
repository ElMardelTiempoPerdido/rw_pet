"""同框编辑数值范围，两端仍由原字段负责保存、校验和默认值恢复"""
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QWidget

from .settings_style import INK, MUTED, pixel_box


class NumberRange(QWidget):
    def __init__(self, minimum, maximum):
        super().__init__()
        self.minimum_input, self.maximum_input = minimum, maximum
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        row = QHBoxLayout(self)
        row.setContentsMargins(2, 2, 2, 2)
        row.setSpacing(2)
        self.separator = QLabel('至')
        self.separator.setAlignment(Qt.AlignmentFlag.AlignCenter)
        for control in (minimum, maximum):
            control.setFrame(False)
            control.installEventFilter(self)
        row.addWidget(minimum)
        row.addWidget(self.separator)
        row.addWidget(maximum)
        self.setFocusProxy(minimum)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.EnabledChange:
            self.separator.setEnabled(self.minimum_input.isEnabled() or self.maximum_input.isEnabled())
            self.update()
        return super().eventFilter(watched, event)

    def paintEvent(self, event):
        painter = QPainter(self)
        enabled = self.minimum_input.isEnabled() or self.maximum_input.isEnabled()
        pixel_box(painter, self.rect(), border=INK if enabled else MUTED)
