"""设置表单的小节折叠，只管理可见性，不参与角色或本机配置"""
from PySide6.QtCore import QPointF, QSize, Qt
from PySide6.QtGui import QPainter, QPalette, QPolygonF
from PySide6.QtWidgets import QAbstractButton, QFormLayout, QSizePolicy, QVBoxLayout, QWidget

from .settings_style import NOTE_STYLE, PixelRuleThin
from .form_layout import ContentForm


class SectionHeading(QAbstractButton):
    """NOTE 字体的一行标题，箭头独立绘制，翻译只处理标题文本"""
    def __init__(self, title, parent):
        super().__init__(parent)
        self.setText(title)
        self.setCheckable(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setStyleSheet(NOTE_STYLE)

    def sizeHint(self):
        return QSize(self.fontMetrics().horizontalAdvance(self.text())+24, self.fontMetrics().height()+6)

    def minimumSizeHint(self):
        return QSize(24, self.sizeHint().height())

    def paintEvent(self, event):
        painter = QPainter(self)
        role = (QPalette.ColorRole.Highlight if self.underMouse() or self.hasFocus()
                else QPalette.ColorRole.ButtonText)
        color = self.palette().color(role)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        y = self.height()/2
        points = ((1, y-3), (9, y-3), (5, y+3)) if self.isChecked() else (
            (2, y-4), (2, y+4), (8, y))
        painter.drawPolygon(QPolygonF([QPointF(x, y) for x, y in points]))
        painter.setPen(color)
        rect = self.rect().adjusted(20, 0, 0, 0)
        text = self.fontMetrics().elidedText(self.text(), Qt.TextElideMode.ElideRight, max(0, rect.width()))
        painter.drawText(rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)


class CollapsibleSection(QWidget):
    def __init__(self, title, form, *, default_collapsed=False):
        super().__init__(form.parentWidget())
        self.default_collapsed = default_collapsed
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(form.verticalSpacing())
        self.heading = SectionHeading(title, self)
        self.content = QWidget(self)
        self.body = ContentForm(self.content)
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setVerticalSpacing(form.verticalSpacing())
        self.body.setHorizontalSpacing(form.horizontalSpacing())
        self.body.setFieldGrowthPolicy(form.fieldGrowthPolicy())
        self.body.setRowWrapPolicy(form.rowWrapPolicy())
        self.body.setLabelAlignment(form.labelAlignment())
        self.body.setFormAlignment(Qt.AlignmentFlag.AlignTop)
        layout.addWidget(self.heading)
        layout.addWidget(self.content)
        self.heading.toggled.connect(self.set_expanded)
        self.restore_default()

    def set_expanded(self, expanded):
        if self.heading.isChecked() != expanded:
            self.heading.setChecked(expanded)
            return
        # 只隐藏容器，保留 PNG 类型、附加外观等子控件各自的显隐状态
        self.content.setVisible(expanded)
        self.updateGeometry()

    def restore_default(self):
        self.set_expanded(not self.default_collapsed)


class SectionForm(ContentForm):
    """从标题起收集后续行；下个标题或分割线结束当前小节，未分组行保持原位"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._section = None

    def add_section(self, title, *, default_collapsed=False):
        section = CollapsibleSection(title, self, default_collapsed=default_collapsed)
        QFormLayout.addRow(self, section)
        self._section = section
        return section

    def addRow(self, *args):
        if len(args) == 1 and isinstance(args[0], PixelRuleThin):
            self._section = None
        if self._section is None:
            super().addRow(*args)
        else:
            self._section.body.addRow(*args)
