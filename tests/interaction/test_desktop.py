"""丢失松键事件的局部恢复；空闲时不轮询、不从移动或按键状态开始抓取。"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication, QWidget

from rw_creature_pet.interaction.desktop import DragInputWindow, left_button_down


class DragInputRecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.owner = QWidget()
        self.window = DragInputWindow(self.owner)
        self.adapter = Mock()
        self.adapter.press.return_value = True
        self.window.adapter = self.adapter
        self.window.hit = SimpleNamespace(contains=lambda _: True)
        self.window.viewport = SimpleNamespace(to_world=lambda p: p)
        for name in ('grabMouse', 'releaseMouse'):
            patcher = patch.object(self.window, name)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(self.owner.close)
        self.addCleanup(self.window.close)

    def event(self, kind, button=Qt.MouseButton.NoButton, buttons=Qt.MouseButton.NoButton):
        return QMouseEvent(kind, QPointF(5, 5), QPointF(5, 5), button, buttons,
                           Qt.KeyboardModifier.NoModifier)

    def press(self):
        self.window.mousePressEvent(self.event(QEvent.Type.MouseButtonPress,
            Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton))

    def test_buttonless_move_cancels_without_moving_to_stale_pointer(self):
        self.press()
        self.assertTrue(self.window._release_watch.isActive())
        self.window.mouseMoveEvent(self.event(QEvent.Type.MouseMove))
        self.adapter.move.assert_not_called()
        self.adapter.release.assert_called_once_with(cancel=True)
        self.assertFalse(self.window._captured)
        self.assertFalse(self.window._release_watch.isActive())

    def test_watch_recovers_without_new_mouse_event_and_preserves_held_button(self):
        self.press()
        with patch('rw_creature_pet.interaction.desktop.left_button_down', return_value=True):
            self.window.check_buttons()
        self.adapter.release.assert_not_called()
        self.assertTrue(self.window._captured)
        with patch('rw_creature_pet.interaction.desktop.left_button_down', return_value=False):
            self.window.check_buttons()
        self.adapter.release.assert_called_once_with(cancel=True)
        self.assertFalse(self.window._captured)
        self.assertFalse(self.window._release_watch.isActive())

    def test_idle_never_queries_buttons_or_starts_a_grab(self):
        with patch('rw_creature_pet.interaction.desktop.left_button_down') as query:
            self.window.check_buttons()
            self.window.mouseMoveEvent(self.event(QEvent.Type.MouseMove,
                buttons=Qt.MouseButton.LeftButton))
        query.assert_not_called()
        self.adapter.press.assert_not_called()
        self.assertFalse(self.window._release_watch.isActive())

    def test_normal_release_and_cancel_both_stop_watch(self):
        self.press()
        self.window.mouseMoveEvent(self.event(QEvent.Type.MouseMove, buttons=Qt.MouseButton.LeftButton))
        self.adapter.move.assert_called_once()
        self.window.mouseReleaseEvent(self.event(QEvent.Type.MouseButtonRelease, Qt.MouseButton.LeftButton))
        self.adapter.release.assert_called_once_with()
        self.assertFalse(self.window._release_watch.isActive())
        self.press()
        self.window.cancel()
        self.assertFalse(self.window._release_watch.isActive())

    def test_windows_query_handles_swapped_buttons_and_ignores_pressed_since_last_query(self):
        user32 = Mock()
        with patch('rw_creature_pet.interaction.desktop.sys.platform', 'win32'), \
             patch('rw_creature_pet.interaction.desktop.QGuiApplication.platformName', return_value='windows'), \
             patch('ctypes.windll', SimpleNamespace(user32=user32), create=True):
            for swapped, button in ((False, 0x01), (True, 0x02)):
                user32.GetSystemMetrics.return_value = swapped
                user32.GetAsyncKeyState.return_value = -32768
                self.assertTrue(left_button_down())
                user32.GetAsyncKeyState.assert_called_with(button)
                user32.GetAsyncKeyState.return_value = 1
                self.assertFalse(left_button_down())
