import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'

from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from rw_creature_pet.config import AppConfig
from rw_creature_pet.geometry import Vec2
from rw_creature_pet.oracle_window import OracleDebugWindow


class OracleWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.window = OracleDebugWindow(AppConfig(), load_atlas=False)
        self.window.timer.stop()
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        self.window.close()
        self.app.processEvents()

    def click_world(self, position, button):
        p = self.window.canvas.world_to_view(position)
        QTest.mouseClick(self.window.canvas, button, pos=QPoint(round(p.x), round(p.y)))

    def test_mouse_coordinates_resize_and_observation_isolation(self):
        w = self.window
        w.pause_button.setChecked(True)
        for size in ((1220, 830), (1030, 720)):
            w.resize(*size)
            self.app.processEvents()
            target = Vec2(610, 65)
            self.click_world(target, Qt.MouseButton.LeftButton)
            self.assertLess((w.scene.requested_target - target).length(), 1.5)
            movement = w.scene.target
            look = Vec2(320, 240)
            self.click_world(look, Qt.MouseButton.RightButton)
            self.assertLess((w.scene.look_target - look).length(), 1.5)
            self.assertEqual(w.scene.target, movement)
        w.clear_look_button.click()
        self.assertIsNone(w.scene.look_target)
        self.assertEqual(w.scene.target, movement)

    def test_fixed_zoom_resize_dpi_pan_and_mouse_mapping(self):
        w, c = self.window, self.window.canvas
        w.pause_button.setChecked(True)
        w.zoom_box.setChecked(False)
        self.assertEqual(c.view_scale, 1.)
        body = tuple(p.position for p in w.scene.body.chunks)
        for factor in (1., 2., 4.):
            w.scale_input.setCurrentIndex(w.scale_input.findData(factor))
            for dpr in (1., 1.25, 1.5, 2.):
                with patch.object(c, 'devicePixelRatioF', return_value=dpr):
                    for size in ((1220, 830), (1700, 1000)):
                        w.resize(*size)
                        self.app.processEvents()
                        scale, _ = c.view_transform()
                        self.assertAlmostEqual(scale*dpr, factor)
                        point = Vec2(480, 82)
                        self.assertLess((c.view_to_world(c.world_to_view(point))-point).length(), 1e-9)
        self.assertEqual(tuple(p.position for p in w.scene.body.chunks), body)
        w.scale_input.setCurrentIndex(w.scale_input.findData(2.))
        w.focus_button.click()
        before = c.world_to_view(body[0])
        target = w.scene.target
        QTest.mousePress(c, Qt.MouseButton.MiddleButton, pos=QPoint(120, 180))
        QTest.mouseMove(c, QPoint(160, 210))
        QTest.mouseRelease(c, Qt.MouseButton.MiddleButton, pos=QPoint(160, 210))
        after = c.world_to_view(body[0])
        self.assertLess((after-before-Vec2(40, 30)).length(), 1.)
        self.assertEqual(w.scene.target, target)
        destination = body[0]+Vec2(20, 0)
        self.click_world(destination, Qt.MouseButton.LeftButton)
        self.assertLess((w.scene.requested_target-destination).length(), 1.)
        look = body[0]+Vec2(-20, 10)
        self.click_world(look, Qt.MouseButton.RightButton)
        self.assertLess((w.scene.look_target-look).length(), 1.)
        self.assertEqual(w.scene.ticks, 0)

    def test_fit_view_shows_whole_world_and_zoom_does_not_reset_scene(self):
        w, c = self.window, self.window.canvas
        w.pause_button.setChecked(True)
        w.step_button.click()
        w.scale_input.setCurrentIndex(w.scale_input.findData(None))
        self.assertFalse(w.focus_button.isEnabled())
        for size in ((1220, 830), (1700, 1000)):
            w.resize(*size)
            self.app.processEvents()
            a = c.world_to_view(Vec2())
            b = c.world_to_view(Vec2(w.scene.world.width, w.scene.world.height))
            self.assertGreaterEqual(min(a.x, a.y), 13.)
            self.assertLessEqual(b.x, c.width()-13.)
            self.assertLessEqual(b.y, c.height()-13.)
        self.assertEqual(w.scene.ticks, 1)

    def test_pause_reset_anchor_and_color_preview(self):
        w = self.window
        w.pause_button.click()
        self.assertTrue(w.clock.paused)
        w.clock.advance(1, w.scene.step)
        self.assertEqual(w.scene.ticks, 0)
        w.step_button.click()
        self.assertEqual(w.scene.ticks, 1)
        w.set_colors(replace(w.renderer.colors, skin='#8844aa'))
        w.side_input.setCurrentIndex(w.side_input.findData('right'))
        w.base_input.setValue(0)
        w.place_button.click()
        self.assertEqual(w.scene.anchor.side.value, 'right')
        self.assertEqual(w.scene.anchor.fraction, 0)
        self.assertEqual(w.scene.ticks, 0)
        self.assertTrue(w.clock.paused)
        self.assertEqual(w.renderer.colors.skin, '#8844aa')
        self.assertEqual(w.color_buttons['skin'].text(), '#8844aa')
        w.look_pearl_button.click()
        self.assertEqual(w.scene.look_target, w.scene.pearl.position)
        w.reset_button.click()
        self.assertIsNone(w.scene.look_target)
        self.assertFalse(w.grab().isNull())

    def test_reload_failure_preserves_colors_and_missing_game_falls_back(self):
        w = self.window
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'test.toml'
            w.config_path = path
            path.write_text("[oracle.colors]\nrobe_top='#112233'\n", encoding='utf-8')
            w.reload_colors()
            self.assertEqual(w.renderer.colors.robe_top, '#112233')
            path.write_text("[oracle.colors]\nrobe_top='bad'\n", encoding='utf-8')
            w.reload_colors()
            self.assertEqual(w.renderer.colors.robe_top, '#112233')
            fallback = OracleDebugWindow(AppConfig(game_dir=Path(temp)))
            try:
                fallback.timer.stop()
                self.assertIsNone(fallback.renderer.atlas)
                fallback.single_step()
                self.assertEqual(fallback.scene.ticks, 1)
            finally:
                fallback.close()

    def test_lap_controls_mode_switch_and_paused_path_display(self):
        w = self.window
        w.pause_button.setChecked(True)
        w.clockwise_button.click()
        self.assertGreater(w.scene.navigator.route.length, 1000)
        route = w.scene.navigator.route
        w.step_button.click()
        self.assertGreater(w.scene.navigator.distance, 0)
        w.pick_look(300, 240)
        self.assertIs(w.scene.navigator.route, route)
        w.path_box.setChecked(False)
        self.assertFalse(w.canvas.show_path)
        w.sliding_box.setChecked(False)
        self.assertIsNone(w.scene.navigator)
        self.assertFalse(w.clockwise_button.isEnabled())
        self.assertTrue(w.clock.paused)
        w.sliding_box.setChecked(True)
        w.counterclockwise_button.click()
        self.assertTrue(w.counterclockwise_button.isEnabled())
        self.assertGreater(w.scene.navigator.route.length, 1000)
        self.assertFalse(w.grab().isNull())


if __name__ == '__main__':
    unittest.main()
