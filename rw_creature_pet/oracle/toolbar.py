"""桌面人偶的六项即时操作；独立小窗口，不改变透明桌面层的鼠标穿透。"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QGridLayout, QLabel, QLayout, QPushButton, QSizePolicy, QWidget


class OracleActionToolbar(QWidget):
    requested = Signal(str)
    closed = Signal()
    ACTIONS = (('drift', '反重力漫游'), ('matrix', '抽取矩阵珍珠'), ('pulse', '光环扩张'),
               ('flash', '外圈闪烁'), ('fill', '实心化'), ('arcs', '触发电弧'))

    def __init__(self):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.WindowTitleHint | Qt.WindowType.WindowCloseButtonHint)
        self.setWindowTitle('Bell · 行动工具栏')
        layout = QGridLayout(self)
        layout.setSizeConstraint(QLayout.SizeConstraint.SetFixedSize)
        self.buttons = {}
        for i, (name, label) in enumerate(self.ACTIONS):
            button = QPushButton(label)
            button.clicked.connect(lambda checked=False, action=name: self.requested.emit(action))
            layout.addWidget(button, i//3, i % 3)
            self.buttons[name] = button
        self.status = QLabel()
        self.status.setMinimumHeight(self.fontMetrics().height()+2)
        self.status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        layout.addWidget(self.status, 2, 0, 1, 3)
        self._state = None
        self._feedback = ''

    def sync(self, scene, blocked=''):
        drag = bool(scene and scene.drag.controlling)
        matrix = bool(scene and scene.pearl_matrix is not None)
        halo = bool(scene and scene.halo_visible)
        arcs = bool(halo and scene.config.halo_arcs_enabled)
        active_arcs = bool(scene and scene.halo_arcs.arcs)
        state = (blocked, drag, matrix, halo, arcs, active_arcs)
        if state == self._state:
            return
        self._state = state
        for name, button in self.buttons.items():
            reason = blocked
            if not reason and name in ('drift', 'matrix') and drag:
                reason = '拖动结束后可用'
            if not reason and name == 'matrix' and not matrix:
                reason = '请先在托盘菜单开启矩阵珍珠（数量需大于 0）'
            if not reason and name in ('pulse', 'flash', 'fill', 'arcs') and not halo:
                reason = '光环关闭或投影透明度为 0'
            if not reason and name == 'arcs':
                reason = ('配置中已关闭电弧' if not arcs else '电弧显示中' if active_arcs else '')
            button.setEnabled(not reason)
            button.setToolTip(reason or ('跳过等待，仍遵守距离及活动带限制' if name == 'arcs' else ''))
            button.setCursor(Qt.CursorShape.ForbiddenCursor if reason else Qt.CursorShape.PointingHandCursor)
        self.status.setText(blocked or self._feedback)

    def feedback(self, text):
        self._feedback = text
        self.status.setText(text)

    def fit_workarea(self, rect, *, initial=False):
        self.adjustSize()
        frame = self.frameGeometry()
        x, y = (rect.right()-frame.width()-16, rect.bottom()-frame.height()-16) if initial else (frame.x(), frame.y())
        # 给平台窗口边框最终定位留少量余量，尤其是负坐标副屏切到主屏时。
        x = max(rect.left()+8, min(x, rect.right()-frame.width()-7))
        y = max(rect.top()+8, min(y, rect.bottom()-frame.height()-7))
        self.move(x, y)

    def closeEvent(self, event):
        self.closed.emit()
        super().closeEvent(event)
