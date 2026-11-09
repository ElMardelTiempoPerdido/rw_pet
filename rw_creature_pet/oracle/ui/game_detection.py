"""首次设置的后台目录检测、整体输入锁定和超时回退"""
import logging
from threading import Thread

from PySide6.QtCore import QObject, QEvent, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QWidget

from ...i18n import tr
from ...shared.game_installation import find_game_directory
from .settings_style import INK, pixel_box


class InitializationOverlay(QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName(tr('初始化中'))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(233, 233, 233, 225))
        width = min(400, self.width()-40)
        panel = QRect((self.width()-width)//2, (self.height()-126)//2, width, 126)
        pixel_box(painter, panel, radius=8)
        painter.setPen(INK)
        painter.drawText(panel.adjusted(16, 20, -16, -64), Qt.AlignmentFlag.AlignCenter, tr('初始化中'))
        painter.drawText(panel.adjusted(20, 57, -20, -18),
                         Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                         tr('正在查找本机的雨世界安装目录'))

    def keyPressEvent(self, event):
        event.accept()

    def wheelEvent(self, event):
        event.accept()


def _discover(preferred, deliver):
    try:
        result = find_game_directory(preferred)
    except Exception:
        logging.getLogger(__name__).exception('Rain World directory detection failed')
        result = None
    try:
        deliver(result)
    except RuntimeError:
        # 窗口已销毁时丢弃迟到结果，后台任务不拥有 Qt 窗口的生命周期
        pass


class GameDirectoryDetection(QObject):
    completed = Signal(object)
    TIMEOUT_MS = 8000

    def __init__(self, dialog):
        super().__init__(dialog)
        self.dialog = dialog
        self.active = True
        self.started = False
        self.overlay = InitializationOverlay(dialog)
        self.overlay.setGeometry(dialog.rect())
        self.overlay.show()
        self.overlay.raise_()
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(lambda: self.finish(None, timed_out=True))
        self.completed.connect(self.finish, Qt.ConnectionType.QueuedConnection)
        dialog.installEventFilter(self)
        dialog.finished.connect(self.shutdown)
        dialog.busy(True)

    def start(self):
        if self.started or not self.active:
            return
        self.started = True
        self.overlay.raise_()
        self.overlay.setFocus()
        self.timer.start(self.TIMEOUT_MS)
        # 只读文件访问可能被离线磁盘阻塞；守护线程允许超时后手动选择和正常退出
        Thread(target=_discover, args=(self.dialog.original.game_dir, self.completed.emit),
               name='rain-world-detection', daemon=True).start()

    def finish(self, directory, *, timed_out=False):
        if not self.active or self.dialog._shutdown:
            return
        self.active = False
        self.timer.stop()
        d = self.dialog
        if directory is not None:
            d.game_dir.setText(str(directory))
            message = '已找到雨世界安装目录，确认后点击“保存并启动”'
        elif timed_out:
            message = '自动检测超时，请点击“浏览...”手动选择雨世界安装目录'
        else:
            message = '未能自动找到雨世界安装目录，请点击“浏览...”手动选择'
        self.overlay.hide()
        d.busy(False)
        d.sync_dependencies()
        d.set_status(message)
        d.game_dir.setFocus()
        d.resource_settings.schedule()
        if d._migration_notice:
            d._migration_notice = False
            QTimer.singleShot(0, d, d.confirm_legacy_parameters)

    def shutdown(self, *args):
        self.active = False
        self.timer.stop()
        self.overlay.hide()

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Resize:
            self.overlay.setGeometry(self.dialog.rect())
        return super().eventFilter(watched, event)
