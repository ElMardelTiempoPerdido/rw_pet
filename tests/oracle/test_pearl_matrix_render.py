"""矩阵显示开关、桌面重建、独立绘制及静止缓存。"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from dataclasses import replace
import unittest
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication

from rw_creature_pet.config import AppConfig
from rw_creature_pet.shared.geometry import Vec2
from rw_creature_pet.oracle.config import OracleConfig
from rw_creature_pet.oracle.debug_window import OracleDebugWindow
from rw_creature_pet.oracle.desktop import OracleDesktopMotion, OracleDesktopViewport
from rw_creature_pet.oracle.render import OracleRenderer
from rw_creature_pet.oracle.scene import OracleScene


class PearlMatrixRenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_resize_preserves_runtime_choice_and_stable_glyphs(self):
        scene = OracleScene(OracleConfig())
        scene.set_pearl_matrix(True)
        glyphs = [p.glyph_id for p in scene.pearl_matrix.pearls]
        for side in ('top', 'right', 'bottom', 'left'):
            scene.set_anchor(side, .72)
            for viewport in (OracleDesktopViewport(-800, 30, 640, 480),
                             OracleDesktopViewport(0, -1080, 1080, 1920, 1.5),
                             OracleDesktopViewport(0, 0, 1920, 1040)):
                new = OracleDesktopMotion(OracleConfig(), viewport, scene).scene
                self.assertTrue(new.pearl_matrix_enabled)
                m = new.pearl_matrix
                self.assertEqual(glyphs, [p.glyph_id for p in m.pearls])
                self.assertTrue(m.settled)
                self.assertEqual(m.anchor.position, m.anchor.previous_position)
                self.assertTrue(m.region.contains(m.anchor.position))
        scene.set_pearl_matrix(False)
        new = OracleDesktopMotion(replace(OracleConfig(), pearl_matrix_enabled=True), viewport, scene).scene
        self.assertIsNone(new.pearl_matrix)

    def test_independent_motion_reuses_body_cache_and_render_is_read_only(self):
        scene = OracleScene(replace(OracleConfig(), pearl_matrix_enabled=True))
        renderer = OracleRenderer()
        for _ in range(900):
            scene.step()
        self.assertTrue(scene.appearance.sleeping)
        matrix = scene.pearl_matrix
        image = QImage(960, 600, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        try:
            renderer.draw(painter, scene)
            frame, revision = renderer._frame, scene.appearance.revision
            # 移动矩阵而保持身体停留，覆盖珍珠独立于人偶缓存的更新分支。
            matrix.anchor.home += Vec2(60, 0)
            for _ in range(30):
                scene.step()
                renderer.draw(painter, scene)
                self.assertIs(renderer._frame, frame)
            self.assertEqual(scene.appearance.revision, revision)
            state = (scene.ticks, matrix.anchor.position, matrix.revision)
            for alpha in (0., .5, 1.):
                renderer.draw(painter, scene, alpha)
            self.assertEqual(state, (scene.ticks, matrix.anchor.position, matrix.revision))
        finally:
            painter.end()
        for _ in range(600):
            scene.step()
        self.assertTrue(scene.pearls_settled)
        revisions = (scene.appearance.revision, scene.pearl_visual_revision)
        for _ in range(200):
            scene.step()
        self.assertEqual(revisions, (scene.appearance.revision, scene.pearl_visual_revision))

    def test_debug_toggle_preserves_pause_behavior_reset_and_stops_idle_refresh(self):
        window = OracleDebugWindow(AppConfig(), load_atlas=False)
        window.timer.stop()
        try:
            window.set_paused(True)
            window.set_autonomous(True)
            window.matrix_box.setChecked(True)
            self.assertTrue(window.scene.behavior.enabled)
            self.assertTrue(window.clock.paused)
            self.assertIsNotNone(window.scene.pearl_matrix)
            window.reset_scene()
            self.assertIsNotNone(window.scene.pearl_matrix)
            window.set_paused(False)
            for _ in range(900):
                window.scene.step()
            self.assertTrue(window.scene.appearance.sleeping)
            window.refresh()
            window._next_render_time = 0
            with patch.object(window.canvas, 'update') as update:
                window.refresh(force=False)
                update.assert_not_called()
            window.matrix_box.setChecked(False)
            self.assertIsNone(window.scene.pearl_matrix)
        finally:
            window.close()


if __name__ == '__main__':
    unittest.main()
