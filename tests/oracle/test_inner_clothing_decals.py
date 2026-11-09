"""内搭贴图共用躯干及高领轮廓，验证原尺寸、变形、遮挡和缓存"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

import numpy as np
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

from rw_creature_pet.oracle.clothing_config import ClothingDecal
from rw_creature_pet.oracle.config import CustomAppearance, OracleConfig
from rw_creature_pet.oracle.graphics.appearance import rotate
from rw_creature_pet.oracle.graphics.clothing_decals import inner_clothing_mesh
from rw_creature_pet.oracle.graphics.inner_robe import COLLAR_BASE_RISE
from rw_creature_pet.oracle.graphics.render import OracleRenderer
from rw_creature_pet.oracle.scene import OracleScene
from rw_creature_pet.shared.geometry import Vec2
from tests.oracle.test_cape import paint
from tests.oracle.test_clothing_decals import pixels
from tools.oracle.review_cape import pose_scene


class InnerClothingDecalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.renderer = OracleRenderer()

    def decal(self, color, name='texture'):
        image = QImage(128, 128, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(QColor(color))
        path = self.root/(name+'.png')
        image.save(str(path))
        return ClothingDecal(enabled=True, image_path=str(path), part='inner_robe', offset_y=-32)

    def render_inner(self, shape, angle=0., bend=.35, density=2.):
        scene = OracleScene(OracleConfig(hide_cords=True, body_appearance='custom', custom_appearance=shape))
        upper = Vec2(878., 237.96)
        direction = rotate(Vec2(0, -1), angle)
        waist = rotate(direction, bend)
        image = QImage(180, 180, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(0)
        painter = QPainter(image)
        try:
            painter.translate(90, 90)
            painter.scale(density, density)
            painter.translate(-upper.x, -upper.y)
            self.renderer.draw_inner_robe(painter, upper, upper-waist*9, direction,
                upper+rotate(direction, -.45)*14, lower_direction=waist, shape=shape, scene=scene)
        finally:
            painter.end()
        return pixels(image)

    def test_reference_scale_and_independent_neck_and_waist_deformation(self):
        upper, lower, direction, head = Vec2(), Vec2(0, 9), Vec2(0, -1), Vec2(0, -14)
        for enabled in (True, False):
            shape = CustomAppearance(inner_collar_height=5., inner_collar_enabled=enabled)
            frame = upper, lower, direction, direction, head
            height = 5 if enabled else 0
            origin = Vec2(0, -COLLAR_BASE_RISE-height)
            for collar in (False, True):
                coords, vertices, triangles = inner_clothing_mesh(self.renderer, shape, *frame, collar=collar)
                for a, b in zip(coords, vertices):
                    self.assertLess((b-a-origin).length(), 1e-8)
                turned = inner_clothing_mesh(self.renderer, shape, *frame[:-1], Vec2(6, -12), collar=collar)
                bent = inner_clothing_mesh(self.renderer, shape, upper, Vec2(4, 8), direction,
                                           rotate(direction, .5), head, collar=collar)
                self.assertIs(coords, turned[0])
                if collar and enabled:
                    self.assertNotEqual(vertices, turned[1])
                    self.assertEqual(vertices, bent[1])
                    self.assertEqual(vertices[0], turned[1][0])  # 高领下口留在胸肩
                elif not collar:
                    self.assertEqual(vertices, turned[1])
                    self.assertNotEqual(vertices, bent[1])
                else:
                    self.assertEqual(triangles, ())

    def test_full_texture_covers_both_surfaces_without_leaks_or_double_alpha(self):
        decal = self.decal('#80ff0000')
        shape = CustomAppearance(inner_collar_height=5., inner_collar_top_width=10.,
                                 inner_collar_bottom_width=8., clothing_decal_1=decal)
        plain_shape = replace(shape, clothing_decal_1=ClothingDecal())
        expected = QImage(1, 1, QImage.Format.Format_ARGB32_Premultiplied)
        expected.fill(QColor(self.renderer.colors.inner_robe))
        painter = QPainter(expected)
        painter.fillRect(0, 0, 1, 1, QColor('#80ff0000'))
        painter.end()
        cloth = QColor(self.renderer.colors.inner_robe)
        cloth_rgba = (cloth.red(), cloth.green(), cloth.blue(), 255)
        for angle in (0., .7, 1.57, 2.4, 3.14, 4.3, 5.6):
            for density in (1., 1.5, 2., 4.):
                with self.subTest(angle=angle, density=density):
                    plain = self.render_inner(plain_shape, angle, density=density)
                    textured = self.render_inner(shape, angle, density=density)
                    self.assertTrue(np.array_equal(plain[:, :, 3], textured[:, :, 3]))
                    covered = np.all(plain == cloth_rgba, axis=2)
                    self.assertTrue(np.all(textured[covered] == pixels(expected)[0, 0]))
                    self.assertTrue(np.array_equal(plain[~covered], textured[~covered]))

    def test_toggles_and_later_slot_win_on_collar_and_torso(self):
        first = self.decal('#ff0000', 'red')
        last = self.decal('#0000ff', 'blue')
        for collar in (True, False):
            for enabled in (True, False):
                shape = CustomAppearance(inner_robe_enabled=enabled, inner_collar_enabled=collar,
                                         clothing_decal_1=first, clothing_decal_3=last)
                actual = self.render_inner(shape)
                only_last = replace(shape, clothing_decal_1=ClothingDecal())
                self.assertTrue(np.array_equal(actual, self.render_inner(only_last)))
                no_texture = replace(only_last, clothing_decal_3=ClothingDecal())
                self.assertEqual(np.array_equal(actual, self.render_inner(no_texture)), not enabled)

    def test_full_body_occlusion_pixel_scales_and_cache(self):
        decal = self.decal('#00ff00')
        for angle in (0, 65, 160):
            scene, _, _ = pose_scene(pose='single', angle=angle)
            shape = replace(scene.config.custom_appearance, clothing_decal_1=decal,
                            inner_collar_height=5., inner_collar_top_width=8.,
                            inner_collar_bottom_width=8.)
            for outfit in ('normal', 'maid'):
                scene.config = replace(scene.config, custom_appearance=shape, outfit=outfit)
                for density in (1., 1.5, 2., 4.):
                    cached = paint(self.renderer, scene, scale=density)
                    self.assertEqual(cached, paint(self.renderer, scene, scale=density, cached=False))
                frame = self.renderer._body_frame
                scene.appearance.head.position += Vec2(1, 0)
                paint(self.renderer, scene, scale=4.)
                self.assertIsNot(frame, self.renderer._body_frame)


if __name__ == '__main__':
    unittest.main()
