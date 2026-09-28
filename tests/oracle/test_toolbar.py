"""桌面工具栏的真实按钮、暂停、场景重建及窗口生命周期。"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import unittest
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QEvent, QRect, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from rw_creature_pet.config import AppConfig
from rw_creature_pet.oracle.desktop import OracleDesktopWindow
from rw_creature_pet.oracle.render import OracleRenderer
from rw_creature_pet.shared.geometry import Vec2
from tests.oracle.test_desktop import FakeScreen


class OracleToolbarTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        with patch('rw_creature_pet.oracle.desktop.QSystemTrayIcon.isSystemTrayAvailable', return_value=True):
            self.window = OracleDesktopWindow(AppConfig(), renderer=OracleRenderer())
        self.window.timer.stop()
        self.screen = FakeScreen(QRect(0, 0, 1280, 720), 1.5)
        self.window.bind_screen(self.screen)
        self.window.toolbar_action.trigger()
        self.app.processEvents()

    def tearDown(self):
        self.window.close()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()

    def click(self, key):
        QTest.mouseClick(self.window.action_toolbar.buttons[key], Qt.MouseButton.LeftButton)

    def test_tray_open_close_reuse_preserves_overlay_and_running_state(self):
        w, toolbar = self.window, self.window.action_toolbar
        self.assertTrue(toolbar.isVisible())
        self.assertFalse(w.clock.paused)
        self.assertTrue(w.windowFlags() & Qt.WindowType.WindowTransparentForInput)
        self.assertFalse(toolbar.windowFlags() & Qt.WindowType.WindowTransparentForInput)
        self.assertFalse(toolbar.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents))
        toolbar.close()
        self.assertFalse(w.toolbar_action.isChecked())
        self.assertFalse(w.clock.paused)
        w.toolbar_action.trigger()
        self.assertIs(w.action_toolbar, toolbar)
        self.assertTrue(toolbar.isVisible())

    def test_six_buttons_act_on_scene_without_disabling_autonomy(self):
        w, s = self.window, self.window.motion.scene
        self.assertFalse(w.action_toolbar.buttons['matrix'].isEnabled())
        w.set_pearl_matrix(not w.config.oracle.pearl_matrix_enabled)
        self.click('drift')
        self.assertTrue(s.behavior.drift_active)
        self.assertTrue(s.behavior.enabled)
        self.click('matrix')
        self.assertTrue(s.behavior.matrix_observation)
        self.assertTrue(s.behavior.enabled)
        self.click('pulse')
        self.assertGreater(s.halo.pulse_ticks, 0)
        self.click('flash')
        self.assertTrue(all(bit.blink_counter == 20 for bit in s.halo.bits[2]))
        self.click('fill')
        self.assertEqual(s.halo.target_white, 1.)
        self.click('arcs')
        self.assertTrue(1 <= len(s.halo_arcs.arcs) <= 3)
        self.assertFalse(w.action_toolbar.buttons['arcs'].isEnabled())

    def test_pause_and_debug_block_actions_then_restore(self):
        w, s = self.window, self.window.motion.scene
        w.set_paused(True)
        self.assertTrue(all(not button.isEnabled() for button in w.action_toolbar.buttons.values()))
        self.click('pulse')
        self.assertEqual(s.halo.pulse_ticks, 0)
        w.set_paused(False)
        self.assertTrue(w.action_toolbar.buttons['pulse'].isEnabled())
        w.open_debug()
        self.assertTrue(all(not button.isEnabled() for button in w.action_toolbar.buttons.values()))
        w.debug_window.close()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()
        self.assertTrue(w.action_toolbar.buttons['pulse'].isEnabled())

    def test_resize_rebinds_buttons_and_repositions_toolbar(self):
        w = self.window
        old = w.motion.scene
        old.trigger_halo_arcs()
        wait = old.halo_arcs.wait
        w.action_toolbar.move(5000, 5000)
        self.screen.rect = QRect(-900, 30, 800, 600)
        w.rebuild()
        self.app.processEvents()
        self.assertIsNot(w.motion.scene, old)
        self.assertEqual(w.motion.scene.halo_arcs.wait, wait)
        self.assertFalse(w.motion.scene.halo_arcs.arcs)
        self.assertTrue(self.screen.rect.contains(w.action_toolbar.frameGeometry()))
        self.click('pulse')
        self.assertGreater(w.motion.scene.halo.pulse_ticks, 0)
        self.assertEqual(old.halo.pulse_ticks, 0)

    def test_failed_arc_reports_reason_and_cleanup_closes_toolbar(self):
        w = self.window
        s = w.motion.scene
        s.halo.center = s.halo.previous_center = Vec2(s.world.width/2, s.world.height/2)
        self.click('arcs')
        self.assertFalse(s.halo_arcs.arcs)
        self.assertIn('没有符合', w.action_toolbar.status.text())
        w.cleanup()
        self.assertFalse(w.action_toolbar.isVisible())


if __name__ == '__main__':
    unittest.main()
