"""线缆隐藏时停止求解，重新显示以当前连接点重建，局部刷新不留残影。"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from dataclasses import replace
import unittest
from unittest.mock import patch

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication

from rw_creature_pet.oracle.config import OracleConfig
from rw_creature_pet.oracle.damage import visual_bounds
from rw_creature_pet.oracle.render import OracleRenderer
from rw_creature_pet.oracle.scene import OracleScene


class CordVisibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_hidden_startup_does_not_construct_or_solve_cords_and_can_sleep(self):
        with patch('rw_creature_pet.oracle.appearance.OracleCords', side_effect=AssertionError('hidden cords')):
            scene = OracleScene(OracleConfig(hide_cords=True, halo_enabled=False))
            scene.start_lap()
            start = scene.body.chunks[0].position
            for _ in range(150):
                scene.step()
            self.assertGreater((scene.body.chunks[0].position-start).length(), 10.)
            scene.stop()
            for _ in range(900):
                scene.step()
            self.assertTrue(scene.appearance.sleeping)
            self.assertIsNone(scene.appearance.cords)
            self.assertIs(scene.appearance.points, scene.appearance.body_points)
            scene.reset()
            self.assertIsNone(scene.appearance.cords)

    def test_reenable_after_movement_reanchors_without_resetting_body(self):
        scene = OracleScene()
        app, old_cords = scene.appearance, scene.appearance.cords
        scene.config = replace(scene.config, hide_cords=True)
        scene.start_lap()
        with patch.object(old_cords, 'step', side_effect=AssertionError('hidden solver')):
            for _ in range(250):
                scene.step()
        self.assertIsNone(app.cords)
        before = [(p.position, p.previous_position, p.velocity) for p in app.body_points]
        navigator, state = scene.navigator, scene.behavior.state
        scene.config = replace(scene.config, hide_cords=False)
        app.sync_cords(scene)
        self.assertIs(scene.navigator, navigator)
        self.assertEqual(scene.behavior.state, state)
        self.assertEqual(before, [(p.position, p.previous_position, p.velocity) for p in app.body_points])
        self.assertIsNot(app.cords, old_cords)
        self.assertEqual(app.main_cord[0].position, scene.base)
        self.assertEqual(app.main_cord[60].position, app.cords.guide)
        for cord in app.small_cords:
            self.assertEqual(cord[0].position, app.main_cord[-1].position)
            self.assertEqual(cord[-1].position, app.head.position)
        self.assertTrue(all(p.position == p.previous_position for p in app.main_cord))
        self.assertTrue(all(p.position == p.previous_position for c in app.small_cords for p in c))
        with patch.object(app.cords, 'step', wraps=app.cords.step) as solve:
            scene.step()
            solve.assert_called_once()

    @staticmethod
    def paint(image, renderer, scene, clip=None):
        p = QPainter(image)
        try:
            if clip is not None:
                p.setClipRect(clip)
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
            p.fillRect(image.rect(), Qt.GlobalColor.transparent)
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            renderer.draw(p, scene)
        finally:
            p.end()

    def test_hidden_geometry_and_glow_clear_old_pixels_when_paused(self):
        for glow in (False, True):
            scene = OracleScene(OracleConfig(glow_enabled=glow, halo_enabled=False))
            for _ in range(700):
                scene.step()
            renderer = OracleRenderer()
            actual = QImage(960, 600, QImage.Format.Format_ARGB32_Premultiplied)
            expected = QImage(actual.size(), actual.format())
            actual.fill(0)
            old = QRectF()
            for hidden in (False, True, False):
                scene.config = replace(scene.config, hide_cords=hidden)
                scene.appearance.sync_cords(scene)  # 暂停时也不依赖下一次物理更新。
                bounds = visual_bounds(scene).toAlignedRect()
                with patch.object(renderer, 'draw_cords', wraps=renderer.draw_cords) as draw:
                    self.paint(actual, renderer, scene, QRectF(bounds).united(old).adjusted(-2, -2, 2, 2))
                    if hidden:
                        draw.assert_not_called()
                self.paint(expected, renderer, scene)
                self.assertEqual(bytes(actual.constBits()), bytes(expected.constBits()))
                old = QRectF(bounds)


if __name__ == '__main__':
    unittest.main()
