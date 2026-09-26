"""局部透明刷新不能残影；逻辑像素缓存复用倍率，随外观和唤醒失效。"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from dataclasses import replace
import unittest
from unittest.mock import patch

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication

from rw_creature_pet.shared.geometry import Vec2
from rw_creature_pet.oracle.config import OracleConfig
from rw_creature_pet.oracle.damage import visual_bounds
from rw_creature_pet.oracle.render import OracleRenderer
from rw_creature_pet.oracle.scene import OracleScene


class DamageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def paint(self, image, renderer, scene, scale=1., clip=None):
        painter = QPainter(image)
        try:
            if clip is not None:
                painter.setClipRect(clip)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
            painter.fillRect(QRectF(0, 0, image.width()/image.devicePixelRatio(),
                                   image.height()/image.devicePixelRatio()), Qt.GlobalColor.transparent)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.scale(scale/image.devicePixelRatio(), scale/image.devicePixelRatio())
            renderer.draw(painter, scene, .5)
        finally:
            painter.end()

    def test_partial_repaint_matches_full_after_movement_and_group_removal(self):
        scene = OracleScene(OracleConfig(pearl_matrix_enabled=True, pearl_orbits_enabled=True,
                                        pearl_satellite_count=2))
        scene.start_lap()
        snapshots = []
        import copy
        for tick in range(1050):
            scene.step()
            if tick % 210 == 0:
                snapshots.append(copy.deepcopy(scene))
        scene.set_pearl_matrix(False)
        scene.set_pearl_orbits(False)
        scene.set_halo_enabled(False)
        snapshots.append(scene)
        for scale, dpr in ((1., 1.), (1., 1.5), (.5, 1.25), (1.5, 1.25), (2., 2.)):
            renderer = OracleRenderer()
            images = [QImage(round(960*scale), round(600*scale), QImage.Format.Format_ARGB32_Premultiplied)
                      for _ in range(2)]
            for image in images:
                image.fill(0)
                image.setDevicePixelRatio(dpr)
            old = QRectF()
            for current in snapshots:
                box = visual_bounds(current)
                s = scale/dpr
                box = QRectF(box.x()*s, box.y()*s, box.width()*s, box.height()*s).toAlignedRect()
                self.paint(images[0], renderer, current, scale, QRectF(box).united(old).adjusted(-2, -2, 2, 2))
                self.paint(images[1], renderer, current, scale)
                actual, expected = (bytes(im.constBits()) for im in images)
                self.assertEqual(actual[3::4], expected[3::4], '透明覆盖必须完全一致，不能出现残影或漏画')
                if actual != expected:
                    # Qt 在 0.5x / 125% DPI 的裁剪路径中改变渐变颜色的
                    # 末位舍入；alpha 已严格比较，RGB 容许至多 4/255。
                    self.assertLessEqual(max(abs(a-b) for a,b in zip(actual, expected)), 4)
                old = QRectF(box)

    def test_sleeping_layer_reuses_and_invalidates(self):
        scene, renderer = OracleScene(), OracleRenderer()
        for _ in range(700):
            scene.step()
        self.assertTrue(scene.appearance.sleeping)
        image = QImage(960, 600, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(0)
        self.paint(image, renderer, scene)
        with patch.object(renderer._frame, 'replay', wraps=renderer._frame.replay) as replay:
            self.paint(image, renderer, scene)
            self.assertEqual(replay.call_count, 0)
            self.paint(image, renderer, scene, .5)
            self.assertEqual(replay.call_count, 0, '缩放复用同一张逻辑像素图')
        old = renderer._raster_image
        renderer.colors = replace(renderer.colors, robe_top='#11ff66')
        self.paint(image, renderer, scene)
        self.assertIsNot(old, renderer._raster_image)
        scene.set_target(scene.body.chunks[0].position+Vec2(50., 0.))
        scene.step()
        old = renderer._raster_image
        with patch.object(renderer, 'draw_pixel_layer', wraps=renderer.draw_pixel_layer) as cache:
            self.paint(image, renderer, scene)
            self.assertEqual(cache.call_count, 1)
            self.assertIsNot(old, renderer._raster_image)


if __name__ == '__main__':
    unittest.main()
