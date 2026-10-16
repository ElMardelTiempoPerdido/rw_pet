"""可选内搭、高领随身体与颈部变形，图形与围裙裁剪共用相同轮廓"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from dataclasses import replace
from math import radians
import unittest

from PySide6.QtCore import QPointF
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath

from rw_creature_pet.oracle.config import CustomAppearance, OracleConfig
from rw_creature_pet.oracle.graphics.appearance import perpendicular, rotate
from rw_creature_pet.oracle.graphics.inner_robe import COLLAR_BASE_RISE, inner_robe_path
from rw_creature_pet.oracle.graphics.render import OracleRenderer, point
from rw_creature_pet.oracle.scene import OracleScene
from rw_creature_pet.shared.geometry import Vec2


class InnerRobeTests(unittest.TestCase):
    @staticmethod
    def rotating_poses():
        # 连续运动中记录的闪烁帧：不能只在原点检查直立或倒立的静态形状
        upper = Vec2(878., 237.96000000000004)
        direction = Vec2(-.9958843986159706, .09063258019777848)
        waist = Vec2(-.9893507837473381, -.1455507701749729)
        head = Vec2(864.1056193996056, 239.63881251943977)
        yield upper, upper-waist*9, direction, waist, head
        for origin in (Vec2(), upper, Vec2(1920.13, 1080.27)):
            for degrees in range(0, 360, 5):
                direction = rotate(Vec2(0, -1), radians(degrees))
                waist = rotate(direction, .24)
                yield origin, origin-waist*9, direction, waist, origin+rotate(direction, .2)*14

    def test_rotating_inner_robe_keeps_chest_covered_at_all_raster_scales(self):
        renderer = OracleRenderer()
        shape = CustomAppearance(inner_collar_height=5., inner_collar_top_width=10., inner_collar_bottom_width=8.)
        cloth_color = QColor(renderer.colors.inner_robe)
        for upper, lower, direction, waist, head in self.rotating_poses():
            for density in (1., 1.5, 2.):
                image = QImage(120, 120, QImage.Format.Format_ARGB32_Premultiplied)
                image.fill(0)
                painter = QPainter(image)
                try:
                    painter.translate(60, 60)
                    painter.scale(density, density)
                    painter.translate(-upper.x, -upper.y)
                    renderer.draw_inner_robe(painter, upper, lower, direction, head,
                                             lower_direction=waist, shape=shape)
                finally:
                    painter.end()
                # 取躯干内部的小块像素，排除正常的领口、肩部和外轮廓阶梯
                for down in (0., 3., 6.):
                    for across in (-2., 0., 2.):
                        p = waist*(-down)+perpendicular(direction)*across
                        self.assertEqual(image.pixelColor(round(60+p.x*density), round(60+p.y*density)),
                                         cloth_color, (upper, direction, density, down, across))

    def test_rotating_apron_mask_keeps_torso_and_collar_without_exposing_neck(self):
        renderer = OracleRenderer()
        shape = CustomAppearance(inner_collar_height=5., inner_collar_top_width=10., inner_collar_bottom_width=8.)
        scene = OracleScene(OracleConfig(hide_cords=True, physics_backend='python', body_appearance='custom',
                                         custom_appearance=shape))
        for upper, lower, direction, waist, head in self.rotating_poses():
            scene.appearance.waist_angle = scene.appearance.previous_waist_angle = .23682676942042083
            mask, _, _ = renderer.clothing_geometry(scene, 1., upper, lower, direction, head,
                                                 QPainterPath(), QPainterPath(), Vec2())
            neck = (head-upper)*(1/(head-upper).length())
            for p in (upper, lower, upper+direction*COLLAR_BASE_RISE+neck*4.):
                self.assertTrue(mask.contains(point(p)), (upper, direction, p))
            self.assertFalse(mask.contains(point(head)), '围裙仍需避开高领以上的皮肤')

    def test_wide_tilted_collar_overlap_does_not_cut_holes_in_underlayer_mask(self):
        renderer = OracleRenderer()
        shape = CustomAppearance(inner_collar_height=.5, inner_collar_top_width=12., inner_collar_bottom_width=8.)
        for degrees in (0, 90, 180, 270):
            direction = rotate(Vec2(0, -1), radians(degrees))
            side = perpendicular(direction)
            upper = Vec2(878, 237.96)
            torso = renderer.torso_path(upper, upper-direction*9, direction)
            head = upper+rotate(direction, .6)*14
            mask = inner_robe_path(torso, upper, direction, head, shape)
            # 宽而矮的高领转动后会与胸部重叠，不能按奇偶填充挖掉重叠区
            self.assertTrue(mask.contains(point(upper+direction*2-side*2)))

    def test_collar_preserves_height_and_taper_in_rotated_and_bent_necks(self):
        renderer = OracleRenderer()
        shape = CustomAppearance(inner_collar_height=5., inner_collar_top_width=6., inner_collar_bottom_width=3.)
        for degrees in (0, 50, 90, 180):
            direction = rotate(Vec2(0, -1), radians(degrees))
            side = perpendicular(direction)
            upper, lower = Vec2(10, 20), Vec2(10, 20)-direction*9
            torso = renderer.torso_path(upper, lower, direction)
            for bend in (-.35, 0, .35):
                neck = rotate(direction, bend)
                head = upper+neck*13
                path = inner_robe_path(torso, upper, direction, head, shape)
                base = upper+direction*COLLAR_BASE_RISE
                top = base+neck*5
                self.assertTrue(path.contains(point(top-neck*.1)))
                self.assertFalse(path.contains(point(top+neck*.1)))
                self.assertTrue(path.contains(point(top-neck*.1+perpendicular(neck)*2.8)))
                self.assertFalse(path.contains(point(top-neck*.1+perpendicular(neck)*3.2)))
                self.assertTrue(path.contains(point(base+neck*.1+side*1.3)))
                self.assertFalse(path.contains(point(base+neck*.1+side*1.8)))

    def test_toggles_remove_collar_or_whole_underlayer_and_keep_flat_neckline(self):
        renderer = OracleRenderer()
        upper, lower, up, head = Vec2(), Vec2(0, 9), Vec2(0, -1), Vec2(0, -13)
        torso = renderer.torso_path(upper, lower, up)
        plain = inner_robe_path(torso, upper, up, head, CustomAppearance(inner_collar_enabled=False))
        self.assertTrue(plain.contains(QPointF(0, -2.9)))
        self.assertFalse(plain.contains(QPointF(0, -3.1)))
        self.assertEqual(plain, inner_robe_path(torso, upper, up, head, CustomAppearance(inner_collar_height=0.)))
        self.assertTrue(inner_robe_path(torso, upper, up, head, CustomAppearance(inner_robe_enabled=False)).isEmpty())

    def test_apron_cannot_paint_on_exposed_skin_when_underlayer_is_disabled(self):
        renderer = OracleRenderer()
        scene = OracleScene(OracleConfig(hide_cords=True, physics_backend='python', body_appearance='custom'))
        upper, lower, up, head = Vec2(), Vec2(0, 9), Vec2(0, -1), Vec2(0, -13)
        args = (scene, 1., upper, lower, up, head, QPainterPath(), QPainterPath(), Vec2())
        enabled, _, _ = renderer.clothing_geometry(*args)
        self.assertTrue(enabled.contains(QPointF(0, 0)))
        self.assertTrue(enabled.contains(QPointF(0, -5)))
        self.assertFalse(enabled.contains(QPointF(0, -8)))
        scene.config = replace(scene.config, custom_appearance=CustomAppearance(inner_robe_enabled=False))
        disabled, _, _ = renderer.clothing_geometry(*args)
        self.assertTrue(disabled.isEmpty())
