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
from rw_creature_pet.oracle.config import OracleConfig
from rw_creature_pet.oracle.input import PuppetHitMap
from rw_creature_pet.shared.geometry import Vec2
from PySide6.QtCore import QPoint


class PixelRenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def paint(self, renderer, scene, alpha=.5, scale=1, dpr=1, *, direct=False, cords=True,
              raster_scale=None):
        image = QImage(round(960*scale), round(600*scale), QImage.Format.Format_ARGB32_Premultiplied)
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
                renderer.draw(painter, scene, alpha, cords=cords, raster_scale=raster_scale)
        finally:
            painter.end()
        image.setDevicePixelRatio(1.)
        return image

    def test_zoom_and_dpi_preserve_logical_pixels_and_reuse_layer(self):
        scene, renderer = OracleScene(OracleConfig(pixel_mode='classic')), OracleRenderer()
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

    def test_adaptive_body_rasterizes_geometry_at_physical_resolution(self):
        scene = OracleScene(OracleConfig(halo_enabled=False))
        scene.start_lap()
        for _ in range(33):
            scene.step()
        renderer = OracleRenderer()
        with patch.object(renderer, 'draw_pearl'), patch.object(renderer, 'draw_scene_head'):
            for scale, dpr in ((1., 1.5), (1.5, 1.25), (2., 2.), (4., 1.5)):
                cached = self.paint(renderer, scene, scale=scale, dpr=dpr)
                direct = self.paint(renderer, scene, scale=scale, dpr=dpr, direct=True)
                a, b = bytes(cached.constBits()), bytes(direct.constBits())
                self.assertTrue(a[3::4] == b[3::4], (scale, dpr, 'geometry coverage'))
                if a != b:
                    self.assertLessEqual(max(abs(x-y) for x,y in zip(a,b)), 1, (scale, dpr))
                self.assertEqual(set(a[3::4]), {0, 255}, '不引入抗锯齿或模糊边缘')
                if scale == 2:
                    scene.config = replace(scene.config, pixel_mode='classic')
                    coarse = self.paint(renderer, scene, scale=scale, dpr=dpr)
                    self.assertNotEqual(a[3::4], bytes(coarse.constBits())[3::4])
                    scene.config = replace(scene.config, pixel_mode='adaptive')

    def test_one_x_unchanged_and_resolution_change_preserves_sleep_and_geometry(self):
        scene, renderer = OracleScene(), OracleRenderer()
        for _ in range(700):
            scene.step()
        self.assertTrue(scene.appearance.sleeping)
        fine = self.paint(renderer, scene)
        scene.config = replace(scene.config, pixel_mode='classic')
        original = self.paint(renderer, scene)
        self.assertTrue(bytes(fine.constBits()) == bytes(original.constBits()))
        scene.config = replace(scene.config, pixel_mode='adaptive')
        revision = scene.appearance.revision
        points = [p.position for p in scene.appearance.points]
        with patch.object(renderer, 'draw_geometry', wraps=renderer.draw_geometry) as geometry:
            self.paint(renderer, scene, scale=2, dpr=1.25)
            body, halo, head = renderer._raster_image, renderer._halo_image, renderer._head_image
            # 不同 DPR、重复重绘、4× 放大镜都复用主画面同一份 2× 像素。
            with patch.object(renderer._frame, 'replay', wraps=renderer._frame.replay) as replay:
                self.paint(renderer, scene, scale=2, dpr=2.)
                self.paint(renderer, scene, scale=4, raster_scale=2.)
                replay.assert_not_called()
            self.assertIs(renderer._raster_image, body)
            self.assertIs(renderer._halo_image, halo)
            self.assertIs(renderer._head_image, head)
            geometry.assert_not_called()
        self.assertEqual(scene.appearance.revision, revision)
        self.assertEqual([p.position for p in scene.appearance.points], points)
        self.assertTrue(scene.appearance.sleeping)

    def test_adaptive_halo_keeps_transparent_hole_and_single_layer_opacity(self):
        scene, renderer = OracleScene(), OracleRenderer()
        for _ in range(40):
            scene.step()
        scene.halo.white = scene.halo.previous_white = 0.
        with patch.object(renderer, 'draw_pixel_layer'), patch.object(renderer, 'draw_scene_head'), \
                patch.object(renderer, 'draw_pearl'):
            base = self.paint(renderer, scene)
            fine = self.paint(renderer, scene, scale=2, dpr=1.5)
            classic = base.scaled(fine.size(), Qt.AspectRatioMode.IgnoreAspectRatio,
                                  Qt.TransformationMode.FastTransformation)
            self.assertNotEqual(bytes(fine.constBits())[3::4], bytes(classic.constBits())[3::4])
            self.assertEqual(set(bytes(fine.constBits())[3::4]), {0, 127})
            center = scene.halo.center_at(.5)
            self.assertEqual(fine.pixelColor(int(center.x*2), int(center.y*2)).alpha(), 0)

    def test_invalid_pixel_mode_rejected(self):
        for mode in ('smooth', '', None, True):
            with self.assertRaises(ValueError):
                OracleConfig(pixel_mode=mode)

    def test_hit_mask_matches_fine_puppet_and_maps_back_to_world_and_dip(self):
        scene, renderer = OracleScene(OracleConfig(halo_enabled=False)), OracleRenderer()
        for _ in range(20):
            scene.step()
        cache = PuppetHitMap()
        with patch.object(renderer, 'draw_pearl'), patch.object(renderer, 'draw_arm'):
            for density in (1., 1.5, 2., 4.):
                visible = self.paint(renderer, scene, scale=density, cords=False)
                hit = cache.get(renderer, scene, .5, raster_scale=density)
                crop = visible.copy(round(hit.origin.x*density), round(hit.origin.y*density),
                                    hit.image.width(), hit.image.height())
                self.assertTrue(bytes(crop.constBits())[3::4] == bytes(hit.image.constBits())[3::4],
                                (density, '可拖拽轮廓与可见轮廓一致'))
                self.assertIs(cache.get(renderer, scene, .5, raster_scale=density), hit)
                head = scene.appearance.head.sample(.5)
                self.assertTrue(hit.contains(head))
                self.assertFalse(hit.contains(scene.base))
                for dpr in (1., 1.25, 1.5, 2.):
                    scale, offset = density/dpr, Vec2(20, 30)
                    region = hit.region(scale, offset)
                    view = head*scale+offset
                    self.assertTrue(region.contains(QPoint(round(view.x), round(view.y))))

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
