"""逻辑像素密度、局部画布完整性及独立眼睛动画的回归。"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from dataclasses import replace
import unittest
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication

from rw_creature_pet.oracle.render import OracleRenderer
from rw_creature_pet.oracle.scene import OracleScene


class PixelRenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def paint(self, renderer, scene, alpha=.5, scale=1, dpr=1, *, direct=False, cords=True):
        image = QImage(960*scale, 600*scale, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(0)
        image.setDevicePixelRatio(dpr)
        painter = QPainter(image)
        try:
            painter.scale(scale/dpr, scale/dpr)
            if direct:
                # 完整世界画布作为独立参照，验证局部缓存未裁掉线缆或改变网格。
                renderer.draw_geometry(painter, scene, alpha, cords=cords,
                                       pearl=False, include_head=False)
            else:
                painter.setRenderHint(QPainter.RenderHint.Antialiasing)
                painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
                renderer.draw(painter, scene, alpha, cords=cords)
        finally:
            painter.end()
        image.setDevicePixelRatio(1.)
        return image

    def test_zoom_and_dpi_preserve_logical_pixels_and_reuse_layer(self):
        scene, renderer = OracleScene(), OracleRenderer()
        scene.start_lap()
        for _ in range(25):
            scene.step()
        # 珍珠有独立的贴图/投影通道；本项检查人偶、头部、衣袍、臂和线缆。
        with patch.object(renderer, 'draw_pearl'):
            for alpha in (0., .5, 1.):
                base = self.paint(renderer, scene, alpha)
                with patch.object(renderer._frame, 'replay', wraps=renderer._frame.replay) as replay:
                    for scale, dpr in ((1, 1.5), (2, 1.25), (4, 2.)):
                        actual = self.paint(renderer, scene, alpha, scale, dpr)
                        expected = base.scaled(actual.size(), Qt.AspectRatioMode.IgnoreAspectRatio,
                                               Qt.TransformationMode.FastTransformation)
                        self.assertEqual(bytes(actual.constBits()), bytes(expected.constBits()),
                                         (alpha, scale, dpr))
                    replay.assert_not_called()

    def test_local_layer_matches_uncropped_world_and_respects_cords_toggle(self):
        scene, renderer = OracleScene(), OracleRenderer()
        scene.start_lap()
        with patch.object(renderer, 'draw_pearl'), patch.object(renderer, 'draw_scene_head'):
            for count in (0, 30, 180):
                for _ in range(count):
                    scene.step()
                for cords in (True, False):
                    for alpha in (0., .5, 1.):
                        cached = self.paint(renderer, scene, alpha, cords=cords)
                        direct = self.paint(renderer, scene, alpha, direct=True, cords=cords)
                        a, b = bytes(cached.constBits()), bytes(direct.constBits())
                        self.assertEqual(a[3::4], b[3::4], (count, cords, alpha))
                        if a != b:
                            # Qt 渐变在不同画布原点的浮点舍入允许一个色阶；覆盖必须相同。
                            self.assertLessEqual(max(abs(x-y) for x,y in zip(a,b)), 1)
        self.assertLess(renderer._raster_image.width()*renderer._raster_image.height(), 960*600)

    def test_eye_animation_does_not_repaint_sleeping_body_and_colors_invalidate(self):
        scene, renderer = OracleScene(), OracleRenderer()
        for _ in range(700):
            scene.step()
        self.assertTrue(scene.appearance.sleeping)
        before = self.paint(renderer, scene)
        old = renderer._raster_image
        revision = scene.appearance.revision
        scene.eyes.OPEN_PROBABILITY = 1.
        scene.eyes.begin_observation()
        with patch.object(renderer._frame, 'replay', wraps=renderer._frame.replay) as replay:
            for _ in range(12):
                scene.step()
                after = self.paint(renderer, scene)
            replay.assert_not_called()
        self.assertIs(renderer._raster_image, old)
        self.assertEqual(scene.appearance.revision, revision)
        self.assertNotEqual(bytes(before.constBits()), bytes(after.constBits()))
        renderer.colors = replace(renderer.colors, robe_top='#11ff66')
        self.paint(renderer, scene)
        self.assertIsNot(renderer._raster_image, old)
        scene.reset()
        old = renderer._raster_image
        self.paint(renderer, scene)
        self.assertIsNot(renderer._raster_image, old)


if __name__ == '__main__':
    unittest.main()
