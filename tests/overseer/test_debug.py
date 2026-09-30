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
from rw_creature_pet.overseer.events import EventPhase


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

    def test_event_buttons_settings_fast_cycle_and_paused_timers(self):
        w, c, p = self.window, self.canvas, self.panel
        p.settings_button.click()
        settings = p.settings_dialog
        settings.preset_button.click()
        self.assertFalse(c.overseer.config.enabled)  # 填入尚未应用。
        settings.apply_button.click()
        self.assertTrue(c.overseer.config.enabled)
        self.assertEqual(c.overseer.config.appearance_probability, 1)
        p.close()  # 面板可见性不影响调度。
        with patch.object(c, 'overseer_mouse', return_value=None):
            w.clock.advance(5, w.step_scene)
            self.assertEqual(c.overseer_events.check_remaining, 1)
            for _ in range(40):
                w.step_scene()
            self.assertEqual(c.overseer_events.phase, EventPhase.ACTIVE)
            self.assertTrue(c.overseer.active)
            p.refresh_status()
            self.assertFalse(p.start_event_button.isEnabled())
            self.assertTrue(p.finish_event_button.isEnabled())
            p.finish_event_button.click()
            self.assertFalse(p.emerge_button.isEnabled())
            for _ in range(80):
                w.step_scene()
                if c.overseer_events.phase == EventPhase.COOLDOWN:
                    break
            p.refresh_status()
            self.assertTrue(p.skip_cooldown_button.isEnabled())
            p.skip_cooldown_button.click()
            p.check_event_button.click()
            self.assertEqual(c.overseer_events.phase, EventPhase.ACTIVE)
            self.assertEqual(c.overseer_events.event_count, 2)
            p.clear_button.click()
            settings.controls['enabled'].setChecked(False)
            settings.apply_button.click()
            for _ in range(50):
                w.step_scene()
            self.assertFalse(c.overseer.active)
            p.start_event_button.click()  # 关闭自动功能时仍可手动调试事件。
            self.assertTrue(c.overseer.active)

    def test_event_settings_validation_export_reload_and_cancel(self):
        from rw_creature_pet.config import AppConfig
        p, c = self.panel, self.canvas
        p.settings_button.click()
        settings = p.settings_dialog
        before = c.overseer.config
        settings.controls['reemerge_distance'].setValue(20)
        settings.apply_button.click()
        self.assertEqual(c.overseer.config, before)
        self.assertIn('未应用', settings.status.text())
        settings.controls['reemerge_distance'].setValue(130)
        settings.controls['puppet_withdraw_distance'].setValue(110)
        settings.controls['puppet_reemerge_distance'].setValue(170)
        settings.controls['relocation_probability'].setValue(70)
        with patch('rw_creature_pet.overseer.settings.QFileDialog.getSaveFileName', return_value=('', '')):
            settings.export_button.click()
        self.assertEqual(c.overseer.config, before)
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'saved.json'
            with patch('rw_creature_pet.overseer.settings.QFileDialog.getSaveFileName', return_value=(str(path), '')):
                settings.export_button.click()
            config = AppConfig.load(path)
            self.assertEqual(config.overseer.reemerge_distance, 130)
            self.assertEqual(config.overseer.puppet_reemerge_distance, 170)
            self.assertEqual(config.overseer.relocation_probability, .7)
            self.assertEqual(config.oracle, self.window.config.oracle)
            self.assertEqual(c.overseer.config, config.overseer)
            p.set_color('#123456')
            settings.source = path
            settings.controls['duration_min'].setValue(7)
            settings.reload_button.click()
            settings.apply_button.click()
            self.assertEqual(c.overseer.config.duration_min, config.overseer.duration_min)
            self.assertEqual(c.overseer.config.color, '#123456')
            saved = path.read_bytes()
            self.assertFalse(saved.startswith(b'\xef\xbb\xbf'))
            path.write_text('invalid', encoding='utf-8')
            settings.reload_button.click()
            self.assertIn('读取失败', settings.status.text())

    def test_spawn_obstacle_uses_puppet_only_and_ignores_avoidance_toggle(self):
        c = self.canvas
        c.overseer_avoidance = False
        mouse = Vec2(480, 300)
        with patch.object(c, 'overseer_mouse', return_value=mouse):
            context = c.overseer_spawn_context()
        self.assertEqual(context.mouse, mouse)
        self.assertIsNone(c.overseer_threat())
        self.assertEqual(context.edges, c.scene.config.allowed_edges)
        body = context.obstacles[0]
        for point in c.scene.appearance.body_points:
            self.assertTrue(body.contains(point.position))
        self.assertLess(body.right-body.left, c.scene.world.width/2)
        self.assertLess(body.bottom-body.top, c.scene.world.height/2)


if __name__ == '__main__':
    unittest.main()
