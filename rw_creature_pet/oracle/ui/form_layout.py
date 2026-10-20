"""设置表单按内容排列，并合并动态显隐、换行和字体变化引起的重新布局"""
from PySide6.QtCore import QRect, Qt, QTimer
from PySide6.QtWidgets import QFormLayout, QLayout, QWidget


class ContentForm(QFormLayout):
    """只让内容决定行高，剩余空间留在表单下方"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._refreshing = False
        self._content_key = None
        self._reflow_timer = QTimer(self)
        self._reflow_timer.setSingleShot(True)
        self._reflow_timer.timeout.connect(self._reflow)
        self.setFormAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)

    def _root_form(self):
        root = self
        widget = self.parentWidget()
        while widget is not None:
            if isinstance(widget.layout(), ContentForm):
                root = widget.layout()
            widget = widget.parentWidget()
        return root

    def invalidate(self):
        super().invalidate()
        if not hasattr(self, '_reflow_timer'):
            return
        root = self._root_form()
        if not root._refreshing and not root._reflow_timer.isActive():
            root._reflow_timer.start(0)

    def _reflow(self):
        root = self._root_form()
        if root is not self:
            root.invalidate()
            return
        host = self.parentWidget()
        if host is None:
            return
        # Qt 自身的 activate 也会调用 invalidate，不能把它当成新内容变化
        # 同时等待子控件几何分配收敛，避免沿用显隐过程中暂时压缩的行高
        layouts = host.findChildren(QLayout)
        widgets = host.findChildren(QWidget)
        key = (host.width(), self.heightForWidth(host.width()), tuple(
            (widget, widget.size(), widget.isHidden(), widget.minimumSize(), widget.maximumSize(),
             widget.sizePolicy(), widget.heightForWidth(widget.width()),
             widget.sizeHint() if widget.layout() is None else None)
            for widget in widgets), tuple(
            (layout, layout.count(), layout.spacing(), layout.contentsMargins()) for layout in layouts))
        if key == self._content_key:
            return
        self._content_key = key
        self._refreshing = True
        try:
            # Qt 的按宽度计算高度缓存跨多层布局传播，须先清内部再清外层
            for layout in reversed(layouts):
                if isinstance(layout, ContentForm):
                    layout._reflow_timer.stop()
                layout.invalidate()
            # 父布局还会缓存 QWidgetItem 的尺寸，仅清布局缓存会留下旧行高
            for widget in reversed(widgets):
                widget.updateGeometry()
            self.activate()
            host.updateGeometry()
        finally:
            self._refreshing = False

    def setGeometry(self, rect):
        height = self.heightForWidth(rect.width())
        if height < 0:
            height = self.sizeHint().height()
        compact = QRect(rect)
        compact.setHeight(min(rect.height(), height))
        # 等宽参数列仍可在同一行内居中，页面和分组默认从顶部排列
        spare = rect.height() - compact.height()
        if self.formAlignment() & Qt.AlignmentFlag.AlignVCenter:
            compact.translate(0, spare // 2)
        elif self.formAlignment() & Qt.AlignmentFlag.AlignBottom:
            compact.translate(0, spare)
        super().setGeometry(compact)
