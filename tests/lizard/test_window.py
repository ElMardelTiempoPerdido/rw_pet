import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from pathlib import Path
from time import monotonic
import unittest

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from rw_creature_pet.config import AppConfig
from rw_creature_pet.shared.geometry import Vec2
from rw_creature_pet.lizard.debug_window import DebugWindow


class WindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)
        cls.app.setStyle("Fusion")
        # Windows offscreen 平台不枚举系统字体，显式加载供截图检查。
        for name in ("msyh.ttc", "msyhbd.ttc"):
            path = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / name
            if path.exists():
                QFontDatabase.addApplicationFont(str(path))
        cls.app.setFont(QFont("Microsoft YaHei UI", 10))

    def setUp(self):
        self.window = DebugWindow(AppConfig())
        self.window.timer.stop()
        self.window.gait_box.setChecked(False)
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        self.window.close()
        self.app.processEvents()

    def test_color_controls_pause_and_reset(self):
        w = self.window
        w.excitement_input.setValue(.7)
        self.assertEqual(w.scene.appearance.colors.excitement, .7)
        w.clock.set_paused(True)
        for key, button in w.effect_buttons.items():
            button.click()
        c = w.scene.appearance.colors
        self.assertEqual((c.flash, c.stun, c.dominance), (25, 15, 1))
        w.clock.advance(1, w.scene.step)
        self.assertEqual(c.flash, 25)
        w.clock.single_step(w.scene.step)
        self.assertEqual(c.flash, 24)
        w.scene.reset()
        w.refresh()
        self.assertEqual(w.scene.appearance.colors.flash, 0)
        self.assertEqual(w.scene.appearance.colors.excitement, .7)

    def test_flat_observation_right_click_and_posture(self):
        w = self.window
        w.posture_input.setCurrentIndex(w.posture_input.findData('raised'))
        w.chest_angle_input.setValue(20)
        self.assertEqual(w.scene.gait.posture, 'raised')
        self.assertEqual(w.scene.gait.chest_angle, 20)
        point = QPoint(w.canvas.width()//2, w.canvas.height()//3)
        scale, center = w.canvas.view_transform()
        QTest.mouseClick(w.canvas, Qt.MouseButton.RightButton, pos=point)
        expected = Vec2((point.x()-w.canvas.width()/2)/scale+center.x,
                        (point.y()-w.canvas.height()/2)/scale+center.y)
        self.assertEqual(w.scene.appearance.look_target, expected)
        self.assertIsNone(w.scene.background.goal)
        w.clock.set_paused(True)
        ticks = w.scene.appearance.look_ticks
        w.clock.advance(1, w.scene.step)
        self.assertEqual(w.scene.appearance.look_ticks, ticks)
        w.scene.reset()
        w.refresh()
        self.assertIsNone(w.scene.appearance.look_target)
        self.assertEqual(w.scene.gait.posture, 'raised')
        self.assertEqual(w.scene.gait.chest_angle, 20)
        w.background_box.setChecked(True)
        self.assertFalse(w.posture_input.isEnabled())
        self.assertFalse(w.chest_angle_input.isEnabled())

    def test_controls_and_readout(self):
        w = self.window
        QTest.mouseClick(w.pause_button, Qt.MouseButton.LeftButton)
        self.assertTrue(w.clock.paused)
        w.speed.setValue(0.75)
        QTest.mouseClick(w.apply_speed_button, Qt.MouseButton.LeftButton)
        start = w.scene.body.chunks[0].position.x
        QTest.mouseClick(w.step_button, Qt.MouseButton.LeftButton)
        self.assertEqual(w.scene.ticks, 1)
        self.assertAlmostEqual(w.scene.body.chunks[0].position.x, start + 0.75 * 0.999)
        self.assertGreater(w.scene.body.chunks[0].position.y, 152)
        self.assertIn("257.749", w.table.item(0, 1).text())
        QTest.keyClick(w, Qt.Key.Key_N)
        self.assertEqual(w.scene.ticks, 2)
        w.toggle_pause()
        for chunk in w.scene.body.chunks:
            self.assertEqual(chunk.previous_position, chunk.position)
        w.toggle_pause()
        w.layer_boxes["show_grid"].setChecked(False)
        self.assertFalse(w.canvas.show_grid)
        QTest.mouseClick(w.reset_button, Qt.MouseButton.LeftButton)
        self.assertEqual(w.scene.ticks, 0)
        self.assertTrue(w.clock.paused)
        self.assertEqual(w.speed.value(), 0)
        QTest.keyClick(w, Qt.Key.Key_Space)
        self.assertFalse(w.clock.paused)

    def test_wall_right_click_observes_without_retargeting(self):
        w = self.window
        w.background_box.setChecked(True)
        w.set_background_target(310, 90)
        goal = w.scene.background.goal
        point = QPoint(w.canvas.width()//2, w.canvas.height()//3)
        QTest.mouseClick(w.canvas, Qt.MouseButton.RightButton, pos=point)
        self.assertIsNotNone(w.scene.appearance.look_target)
        self.assertEqual(w.scene.background.goal, goal)
        self.assertFalse(w.posture_input.isEnabled())
        self.assertFalse(w.chest_angle_input.isEnabled())
        w.clock.set_paused(True)
        ticks = w.scene.appearance.look_ticks
        w.clock.advance(1, w.scene.step)
        self.assertEqual(w.scene.appearance.look_ticks, ticks)
        w.single_step()
        self.assertEqual(w.scene.appearance.look_ticks, ticks-1)
        w.scene.reset()
        self.assertIsNone(w.scene.appearance.look_target)
        self.assertEqual(w.scene.background.look_bend, 0)

    def test_timer_advances_and_pause_holds(self):
        w = self.window
        w.timer.start(16)
        deadline = monotonic() + 2
        while w.scene.ticks == 0 and monotonic() < deadline:
            QTest.qWait(20)
        self.assertGreater(w.scene.ticks, 0)
        w.toggle_pause()
        tick = w.scene.ticks
        QTest.qWait(80)
        self.assertEqual(w.scene.ticks, tick)

    def test_render_at_default_and_minimum_size(self):
        root = Path(__file__).resolve().parents[2] / "artifacts"
        root.mkdir(exist_ok=True)
        w = self.window
        w.speed.setValue(1.25)
        w.apply_speed()
        w.single_step()
        for name, width, height in (("debug-scene", 1040, 740), ("debug-scene-small", 720, 620)):
            w.resize(width, height)
            self.app.processEvents()
            image = w.grab()
            self.assertFalse(image.isNull())
            self.assertTrue(image.save(str(root / f"{name}.png")))
            self.assertGreaterEqual(w.canvas.width(), 480)

    def test_landing_is_visible_in_readout(self):
        w = self.window
        for _ in range(100):
            w.scene.step()
        w.clock.set_paused(True)
        w.refresh()
        self.assertIn("接地 3/3", w.physics_status.text())
        self.assertEqual(w.table.item(0, 5).text(), "是")
        self.app.processEvents()
        root = Path(__file__).resolve().parents[2] / "artifacts"
        root.mkdir(exist_ok=True)
        self.assertTrue(w.grab().save(str(root / "body-settled.png")))

    def test_gait_controls_and_render(self):
        w = self.window
        QTest.mouseClick(w.right_button, Qt.MouseButton.LeftButton)
        self.assertTrue(w.scene.gait.enabled)
        for _ in range(90):
            w.scene.step()
        self.assertGreater(w.scene.body.chunks[1].position.x, 280)
        w.clock.set_paused(True)
        w.refresh()
        self.assertIn("向右行走", w.gait_status.text())
        root = Path(__file__).resolve().parents[2] / "artifacts"
        root.mkdir(exist_ok=True)
        for name, width, height in (("gait", 1040, 740), ("gait-small", 720, 620)):
            w.resize(width, height)
            self.app.processEvents()
            self.assertTrue(w.grab().save(str(root / f"{name}.png")))
        QTest.mouseClick(w.stop_button, Qt.MouseButton.LeftButton)
        self.assertEqual(w.scene.gait.speed, 0)
        for _ in range(200):
            w.scene.step()
        self.assertLess(w.scene.body.chunks[1].velocity.length(), 1e-7)
        QTest.mouseClick(w.left_button, Qt.MouseButton.LeftButton)
        self.assertLess(w.scene.gait.speed, 0)
        QTest.mouseClick(w.reset_button, Qt.MouseButton.LeftButton)
        self.assertTrue(w.scene.gait.enabled)
        self.assertLess(w.scene.gait.speed, 0)
        self.assertEqual(w.scene.ticks, 0)

    def test_flat_pace_switch_preserves_direction_stop_and_scene_mode(self):
        w = self.window
        w.left_button.click()
        slow = w.scene.gait.speed
        w.walk_pace.setCurrentIndex(1)
        self.assertLess(w.scene.gait.speed, slow)
        active = w.scene.gait.speed
        w.reset_scene()
        self.assertEqual(w.scene.gait.speed, active)
        w.background_box.setChecked(True)
        self.assertFalse(w.walk_pace.isEnabled())
        w.background_box.setChecked(False)
        self.assertTrue(w.walk_pace.isEnabled())
        self.assertEqual(w.scene.gait.speed, active)
        w.stop_button.click()
        w.walk_pace.setCurrentIndex(0)
        self.assertEqual(w.scene.gait.speed, 0)
        w.right_button.click()
        self.assertAlmostEqual(w.scene.gait.speed, -slow)
        self.assertTrue(all(f.steps == 0 for f in w.scene.gait.feet))

    def test_turn_controls_and_render(self):
        w = self.window
        w.clock.set_paused(True)
        QTest.mouseClick(w.left_button, Qt.MouseButton.LeftButton)
        self.assertIn("减速待转", w.gait_status.text())
        for _ in range(27):
            w.single_step()
        self.assertTrue(w.scene.gait.turning)
        self.assertIn("转向左", w.gait_status.text())
        root = Path(__file__).resolve().parents[2] / "artifacts"
        root.mkdir(exist_ok=True)
        self.app.processEvents()
        self.assertTrue(w.grab().save(str(root / "turn-middle.png")))
        for _ in range(80):
            w.single_step()
        self.assertEqual(w.scene.gait.facing, -1)
        self.assertIn("向左行走", w.gait_status.text())
        self.app.processEvents()
        self.assertTrue(w.grab().save(str(root / "turn-left.png")))

    def test_missing_game_shows_explicit_debug_fallback(self):
        w = DebugWindow(AppConfig(game_dir=Path('Z:/missing-rainworld-install')))
        try:
            w.timer.stop()
            self.assertIsNotNone(w.asset_error)
            self.assertIsNone(w.canvas.renderer)
            self.assertIn('game_dir', w.asset_error)
            w.show()
            self.app.processEvents()
            self.assertFalse(w.grab().isNull())
        finally:
            w.close()

    def test_background_height_release_and_mode_switch(self):
        w = self.window
        w.clock.set_paused(True)
        w.background_box.setChecked(True)
        self.assertTrue(w.scene.background.attached)
        self.assertFalse(w.left_button.isEnabled())
        w.height_input.setValue(125)
        QTest.mouseClick(w.place_button, Qt.MouseButton.LeftButton)
        self.assertEqual(w.scene.body.chunks[1].position.y, 55)
        self.assertIn('背景抓附', w.gait_status.text())
        root = Path(__file__).resolve().parents[2] / 'artifacts'
        root.mkdir(exist_ok=True)
        for name, width, height in (('background', 1040, 740), ('background-small', 720, 660)):
            w.resize(width, height)
            self.app.processEvents()
            self.assertTrue(w.grab().save(str(root / f'{name}.png')))
        w.attach_box.setChecked(False)
        w.single_step()
        self.assertGreater(w.scene.body.chunks[1].position.y, 55)
        for _ in range(100):
            w.scene.step()
        w.refresh()
        self.assertIn('已落地', w.gait_status.text())
        w.background_box.setChecked(False)
        self.assertFalse(w.scene.background_mode)
        self.assertTrue(w.left_button.isEnabled())
        self.assertFalse(w.scene.gait.enabled)

    def test_background_direction_controls(self):
        w = self.window
        self.assertFalse(w.angle_button.isEnabled())

        w.background_box.setChecked(True)
        w.direction_angle.setValue(315)
        QTest.mouseClick(w.angle_button, Qt.MouseButton.LeftButton)
        self.assertGreater(w.scene.background.direction.x, 0)
        self.assertLess(w.scene.background.direction.y, 0)
        for _ in range(120):
            w.single_step()
        self.assertGreater(w.scene.body.chunks[1].position.x, 240)
        self.assertLess(w.scene.body.chunks[1].position.y, 90)
        root = Path(__file__).resolve().parents[2] / 'artifacts'
        w.resize(1040, 790)
        self.app.processEvents()
        self.assertTrue(w.grab().save(str(root / 'background-moving.png')))
        QTest.mouseClick(w.background_buttons[4], Qt.MouseButton.LeftButton)
        self.assertEqual(w.scene.background.direction.length(), 0)
        w.attach_box.setChecked(False)
        self.assertFalse(w.angle_button.isEnabled())

    def test_click_target_with_camera_and_cancel(self):
        w = self.window
        w.background_box.setChecked(True)
        w.clock.set_paused(True)
        self.app.processEvents()
        for follow in (False, True):
            w.follow_box.setChecked(follow)
            scale, center = w.canvas.view_transform()
            target = Vec2(285, 100)
            point = QPoint(round((target.x - center.x) * scale + w.canvas.width() / 2),
                           round((target.y - center.y) * scale + w.canvas.height() / 2))
            QTest.mouseClick(w.canvas, Qt.MouseButton.LeftButton, pos=point)
            self.assertLess((w.scene.background.goal - target).length(), 1)
            self.assertIn('追踪目标', w.gait_status.text())
        for _ in range(400):
            w.single_step()
        self.assertTrue(w.scene.background.arrived)
        root = Path(__file__).resolve().parents[2] / 'artifacts'
        self.app.processEvents()
        self.assertTrue(w.grab().save(str(root / 'tracking-target.png')))
        w.background_buttons[4].click()
        self.assertIsNone(w.scene.background.goal)



if __name__ == "__main__":
    unittest.main()
