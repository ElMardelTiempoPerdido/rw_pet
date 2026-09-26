"""缓存必须保持像素结果、颜色/插值/重置失效与静止后的窗口唤醒。"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from dataclasses import replace
import unittest
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from rw_creature_pet.config import AppConfig
from rw_creature_pet.shared.geometry import Vec2
from rw_creature_pet.oracle.scene import OracleScene
from rw_creature_pet.oracle.debug_window import OracleDebugWindow
from rw_creature_pet.oracle.render import OracleRenderer


class OracleRenderCacheTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def render(self, renderer, scene, alpha, scale=1, direct=False):
        image = QImage(960, 600, QImage.Format.Format_RGBA8888)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.scale(scale, scale)
        if scale > 1:
            painter.translate(-scene.appearance.upper.x+120, 0)
        if direct:
            renderer.draw_geometry(painter, scene, alpha)
        else:
            renderer.draw(painter, scene, alpha, pixelated=False)
        painter.end()
        return bytes(image.constBits())

    def test_replay_matches_direct_and_invalidates_for_visual_changes(self):
        scene, renderer = OracleScene(), OracleRenderer()
        scene.start_lap()
        for _ in range(30):
            scene.step()
        for alpha in (0., .5, 1.):
            for scale in (1, 4):
                self.assertEqual(self.render(renderer, scene, alpha, scale),
                                 self.render(renderer, scene, alpha, scale, direct=True))
        with patch.object(renderer, 'draw_geometry', wraps=renderer.draw_geometry) as draw:
            self.render(renderer, scene, .5)
            self.render(renderer, scene, .5, 4)
            self.assertEqual(draw.call_count, 1)
            renderer.colors = replace(renderer.colors, skin='#00ff00')
            self.render(renderer, scene, .5)
            self.assertEqual(draw.call_count, 2)
            scene.reset()
            self.render(renderer, scene, .5)
            self.assertEqual(draw.call_count, 3)

    def test_idle_stops_repainting_and_observation_wakes_it(self):
        window = OracleDebugWindow(AppConfig(), load_atlas=False)
        window.timer.stop()
        try:
            for _ in range(650):
                window.scene.step()
            self.assertTrue(window.scene.appearance.sleeping)
            window.show()
            window.refresh()
            QTest.qWait(30)
            old = window.renderer.draw
            paints = []
            def measured(*args, **kwargs):
                paints.append(True)
                old(*args, **kwargs)
            with patch.object(window.renderer, 'draw', measured):
                for _ in range(10):
                    window.refresh(force=False)
                    self.app.processEvents()
                self.assertEqual(len(paints), 0)
                window.pick_look(700, 20)
                window.scene.step()
                self.assertFalse(window.scene.appearance.sleeping)
                window.refresh()
                QTest.qWait(30)
                self.assertGreater(len(paints), 0)
                before = len(paints)
                window.set_colors(replace(window.renderer.colors, skin='#00ff00'))
                QTest.qWait(30)
                self.assertGreater(len(paints), before)
                window.set_paused(True)
                QTest.qWait(30)
                before = len(paints)
                for _ in range(10):
                    window.refresh(force=False)
                    self.app.processEvents()
                self.assertEqual(len(paints), before, '暂停后不应持续重画相同画面')
        finally:
            window.close()

    def test_translation_reuses_body_but_local_shape_changes_rebuild_it(self):
        scene, renderer = OracleScene(), OracleRenderer()
        with patch.object(renderer, 'draw_body', wraps=renderer.draw_body) as draw:
            self.render(renderer, scene, 1.)
            self.assertEqual(draw.call_count, 1)
            offset = Vec2(2., 3.)
            for p in (*scene.body.chunks, scene.appearance.head, *scene.appearance.hands,
                      *scene.appearance.feet, *scene.appearance.cloth):
                p.position += offset
                p.previous_position += offset
            scene.appearance.revision += 1
            cached = self.render(renderer, scene, 1.)
            self.assertEqual(draw.call_count, 1)
            direct = self.render(renderer, scene, 1., direct=True)
            self.assertEqual(cached, direct)
            before = draw.call_count
            scene.appearance.cloth[-1].position += Vec2(.01, 0)
            scene.appearance.revision += 1
            self.render(renderer, scene, 1.)
            self.assertEqual(draw.call_count, before+1)


if __name__ == '__main__':
    unittest.main()
