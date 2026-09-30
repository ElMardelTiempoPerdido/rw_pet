import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'

import unittest
from pathlib import Path
import tempfile
from unittest.mock import patch

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from rw_creature_pet.config import AppConfig
from rw_creature_pet.shared.geometry import Vec2
from rw_creature_pet.oracle.debug_window import OracleDebugWindow
from rw_creature_pet.overseer.model import Edge


class OverseerDebugTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.window = OracleDebugWindow(AppConfig(), load_atlas=False)
        self.window.timer.stop()
        self.window.show()
        self.window.pause_button.setChecked(True)
        self.window.open_overseer_debug()
        self.app.processEvents()
        self.canvas = self.window.canvas
        self.panel = self.window.overseer_panel

    def tearDown(self):
        self.window.close()
        self.app.processEvents()

    def test_show_edge_pause_single_step_and_clear(self):
        w, c, p = self.window, self.canvas, self.panel
        p.show_button.click()
        self.assertTrue(c.overseer.active)
        self.assertFalse(c.overseer.visible)  # 下一次仿真才从墙内探出。
        self.assertEqual(c.view_scale, 1)
        for edge in Edge:
            p.edge.setCurrentIndex(p.edge.findData(edge.value))
            self.assertEqual(c.overseer.anchor.edge, edge)
            revision = c.overseer.revision
            w.clock.advance(.1, w.step_scene)
            self.assertEqual(c.overseer.revision, revision)
            w.step_button.click()
            self.assertEqual(c.overseer.revision, revision+1)
        p.clear_button.click()
        revision = c.overseer.revision
        w.step_button.click()
        self.assertEqual(c.overseer.revision, revision)
        self.assertFalse(c.overseer.visible)
        p.show_button.click()
        w.reset_button.click()
        self.assertFalse(c.overseer.visible)

    def test_mouse_coordinate_mapping_and_fixed_target_are_isolated(self):
        w, c, p = self.window, self.canvas, self.panel
        p.show_button.click()
        c.magnifier = False
        target = c.overseer.root+c.overseer.normal*100
        movement, look = w.scene.target, w.scene.look_target
        for dpr in (1., 1.5, 2.):
            with patch.object(c, 'devicePixelRatioF', return_value=dpr):
                for scale in (1., 1.5, 2.):
                    c.view_scale = scale
                    view = c.world_to_view(target)
                    self.assertLess((c.overseer_target_at(view)-target).length(), 1e-7)
        self.assertIsNone(c.overseer_target_at(Vec2(-10, -10)))
        view = c.world_to_view(target)
        global_pos = c.mapToGlobal(QPoint(round(view.x), round(view.y)))
        with patch('rw_creature_pet.oracle.debug_window.QCursor.pos', return_value=global_pos):
            w.step_button.click()
        self.assertLess((c.overseer.target-target).length(), 2)
        c.magnifier = True
        magnifier = c.magnifier_rect().center()
        self.assertIsNone(c.overseer_target_at(Vec2(magnifier.x(), magnifier.y())))
        c.magnifier = False
        p.look_mode.setCurrentIndex(p.look_mode.findData('fixed'))
        view = c.world_to_view(target)
        QTest.mouseClick(c, Qt.MouseButton.RightButton, pos=QPoint(round(view.x), round(view.y)))
        self.assertLess((c.overseer_fixed_target-target).length(), 2)
        w.step_button.click()
        self.assertEqual(c.overseer.target, c.overseer_fixed_target)
        self.assertEqual(w.scene.target, movement)
        self.assertEqual(w.scene.look_target, look)
        p.look_mode.setCurrentIndex(p.look_mode.findData('idle'))
        self.assertIsNone(c.overseer_target())

    def test_visible_preview_invalidates_host_frame_and_close_keeps_it(self):
        w, c, p = self.window, self.canvas, self.panel
        p.show_button.click()
        w.refresh()
        p.close()
        self.assertTrue(c.overseer.active)
        c.overseer.step()
        w._next_render_time = 0
        with patch.object(c, 'update') as update:
            w.refresh(force=False)
            update.assert_called_once()

    def test_render_is_read_only_cached_and_small(self):
        c, p = self.canvas, self.panel
        p.show_button.click()
        image = QImage(960, 600, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(0)
        painter = QPainter(image)
        try:
            for edge in Edge:
                p.edge.setCurrentIndex(p.edge.findData(edge.value))
                for _ in range(40):
                    c.overseer.step(Vec2(480, 300))
                rng, revision = c.overseer.random.getstate(), c.overseer.revision
                c.overseer_renderer.draw(painter, c.overseer)
                raster = c.overseer_renderer.image
                c.overseer_renderer.draw(painter, c.overseer)
                self.assertIs(c.overseer_renderer.image, raster)
                self.assertEqual(c.overseer.random.getstate(), rng)
                self.assertEqual(c.overseer.revision, revision)
                self.assertLess(raster.width()*raster.height(), 15000)
                self.assertTrue(any(bytes(raster.constBits())[3::4]))
        finally:
            painter.end()
        self.assertFalse(self.window.grab().isNull())

    def test_mouse_avoidance_is_independent_of_fixed_gaze(self):
        w, c, p = self.window, self.canvas, self.panel
        p.show_button.click()
        p.look_mode.setCurrentIndex(p.look_mode.findData('fixed'))
        c.magnifier = False
        p.avoidance.setChecked(False)
        for _ in range(64):
            w.step_scene()
        self.assertEqual(c.overseer.extended, 1)
        p.avoidance.setChecked(True)
        pos = c.world_to_view(c.overseer.root+c.overseer.normal*10)
        mouse = c.mapToGlobal(QPoint(round(pos.x), round(pos.y)))
        with patch('rw_creature_pet.oracle.debug_window.QCursor.pos', return_value=mouse):
            for _ in range(40):
                w.step_scene()
            self.assertTrue(c.overseer.scared)
            self.assertFalse(c.overseer.visible)
            self.assertTrue(c.overseer.active)
            self.assertEqual(c.overseer.target, c.overseer_fixed_target)
            # 切换为扫视仍会避让鼠标。
            p.look_mode.setCurrentIndex(p.look_mode.findData('idle'))
            w.step_scene()
            self.assertTrue(c.overseer.scared)
        p.avoidance.setChecked(False)
        for _ in range(80):
            w.step_scene()
        self.assertEqual(c.overseer.extended, 1)
        p.withdraw_button.click()
        for _ in range(40):
            w.step_scene()
        self.assertEqual(c.overseer.extended, 0)
        p.emerge_button.click()
        for _ in range(64):
            w.step_scene()
        self.assertEqual(c.overseer.extended, 1)

    def test_color_preview_reload_and_cancel_preserve_motion(self):
        from PySide6.QtGui import QColor
        p, c = self.panel, self.canvas
        p.show_button.click()
        for _ in range(64):
            c.overseer.step()
        old = c.overseer.root, c.overseer.head.position, c.overseer.extended
        with patch('rw_creature_pet.overseer.debug.QColorDialog.getColor', return_value=QColor('#ff7788')):
            p.color_button.click()
        self.assertEqual(c.overseer.config.color, '#ff7788')
        self.assertEqual((c.overseer.root, c.overseer.head.position, c.overseer.extended), old)
        with patch('rw_creature_pet.overseer.debug.QColorDialog.getColor', return_value=QColor()):
            p.color_button.click()
        self.assertEqual(c.overseer.config.color, '#ff7788')
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'config.toml'
            p.config_path = path
            path.write_text("[overseer]\ncolor='#123456'\n", encoding='utf-8')
            before = path.read_bytes()
            p.reload_color_button.click()
            self.assertEqual(c.overseer.config.color, '#123456')
            self.assertEqual(path.read_bytes(), before)
            path.write_text("[overseer]\ncolor='invalid'\n", encoding='utf-8')
            p.reload_color_button.click()
            self.assertEqual(c.overseer.config.color, '#123456')
            self.assertIn('读取失败', p.color_hint.text())

    def test_hidden_draw_is_empty_and_extension_interpolation_stays_clipped(self):
        c = self.canvas
        c.overseer.show()
        c.overseer.request_withdraw()
        image = QImage(960, 600, QImage.Format.Format_ARGB32_Premultiplied)
        def render(alpha):
            image.fill(0)
            painter = QPainter(image)
            try:
                c.overseer_renderer.draw(painter, c.overseer, alpha)
            finally:
                painter.end()
        render(1.)
        self.assertFalse(any(bytes(image.constBits())))
        c.overseer.request_emerge()
        for i in range(100):
            if i == 40:
                c.overseer.request_withdraw()
            c.overseer.step()
            for alpha in (0., .5, 1.):
                render(alpha)
                # 当前附着下边，绘制不能越过边框；原地缩回时也不残留在墙外。
                row = int(c.overseer.bounds.bottom)
                self.assertFalse(any(bytes(image.constBits())[row*image.bytesPerLine():]))
        render(1.)
        self.assertFalse(any(bytes(image.constBits())))


if __name__ == '__main__':
    unittest.main()
