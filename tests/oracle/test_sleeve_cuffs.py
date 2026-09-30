"""袖口圆角只裁去末端，缩放/DPI 保持几何比例，前景手掌使用同一遮挡。"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from math import radians
import unittest

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication

from rw_creature_pet.oracle.appearance import perpendicular, rotate
from rw_creature_pet.oracle.config import OracleColors, OracleConfig
from rw_creature_pet.oracle.render import OracleRenderer, mixed, point, unit
from rw_creature_pet.oracle.scene import OracleScene
from rw_creature_pet.shared.geometry import Vec2


class SquareCuffRenderer(OracleRenderer):
    SLEEVE_CUFF_RADIUS = 0.

    def draw_sleeve(self, painter, edges):
        c = self.colors
        self.transverse_strip(painter, edges, mixed(c.robe_top, c.robe_bottom, .4**2), c.robe_top)


class CenteredCuffRenderer(OracleRenderer):
    SLEEVE_CUFF_DROP = 0.


class SleeveCuffTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def paint(self, renderer, edges, scale, dpr=1.):
        image = QImage(round(64*scale), round(64*scale), QImage.Format.Format_RGBA8888)
        image.fill(0)
        image.setDevicePixelRatio(dpr)
        painter = QPainter(image)
        painter.scale(scale/dpr, scale/dpr)
        painter.translate(32, 32)
        renderer.draw_sleeve(painter, edges)
        painter.end()
        return bytes(image.constBits())

    def test_only_cuff_corners_are_trimmed_in_rotated_and_mirrored_poses(self):
        renderer = OracleRenderer()
        for tilt in (0, 31, 90, 180):
            up = rotate(Vec2(0, -1), radians(tilt))
            for sign in (-1, 1):
                outward = perpendicular(up)*sign
                for end in (outward+up*(-16), outward*14+up*6):
                    edges = renderer.sleeve_edges(Vec2(), end, up, sign)
                    before, after = renderer.strip_path(edges), renderer.sleeve_path(edges)
                    a, b = edges[-1]
                    forward = unit(a.lerp(b, .5)-edges[-2][0].lerp(edges[-2][1], .5))
                    for corner, inward in ((a, unit(b-a)), (b, unit(a-b))):
                        removed = corner-forward*.08+inward*.08
                        retained = corner-forward*.8+inward*.8
                        self.assertTrue(before.contains(point(removed)))
                        self.assertFalse(after.contains(point(removed)))
                        self.assertTrue(after.contains(point(retained)))
                    self.assertTrue(after.contains(point(a.lerp(b, .5)-forward*.1)), '圆角保留袖口中央')
                    # 在几何网格上只允许删除靠近末端两角的区域，不能扩大外轮廓。
                    for x in range(-24, 25):
                        for y in range(-24, 25):
                            p = Vec2(x+.37, y+.23)
                            old, new = before.contains(point(p)), after.contains(point(p))
                            self.assertFalse(new and not old)
                            if old and not new:
                                self.assertLess(min((p-a).length(), (p-b).length()),
                                                renderer.SLEEVE_CUFF_RADIUS*1.5)

    def test_raster_corners_scale_with_geometry_without_blur_or_double_dpi(self):
        rounded, square = OracleRenderer(), SquareCuffRenderer()
        for scale in (.75, 1., 1.25, 1.5, 2., 3., 4.):
            removed = 0
            for tilt in (0, 17, 43, 90):
                up = rotate(Vec2(0, -1), radians(tilt))
                edges = rounded.sleeve_edges(Vec2(), perpendicular(up)*15+up*3, up, 1)
                original = self.paint(square, edges, scale)
                actual = self.paint(rounded, edges, scale)
                self.assertEqual(set(actual[3::4]), {0, 255})
                for index, (old, new) in enumerate(zip(original[3::4], actual[3::4])):
                    self.assertLessEqual(new, old)
                    removed += old > new
                    if old > new:
                        p = Vec2((index % round(64*scale)+.5)/scale-32,
                                 (index // round(64*scale)+.5)/scale-32)
                        distance = min((p-c).length() for c in edges[-1])
                        if distance >= rounded.SLEEVE_CUFF_RADIUS*1.5+1/scale:
                            # 路径布尔运算可能改变恰落在开口直线上的像素
                            # 归属（浮点误差）；离开该直线不能有额外削切。
                            center = edges[-1][0].lerp(edges[-1][1], .5)
                            forward = unit(center-edges[-2][0].lerp(edges[-2][1], .5))
                            self.assertLess(abs((p-center).x*forward.x+(p-center).y*forward.y), 1e-8)
                for dpr in (1.25, 1.5, 2.):
                    self.assertEqual(actual, self.paint(rounded, edges, scale, dpr), (scale, tilt, dpr))
            self.assertGreater(removed, 0, (scale, '至少部分朝向应出现圆角像素变化'))

    def test_raised_cuff_drapes_below_wrist_without_changing_relaxed_sleeve_or_shoulder(self):
        renderer, centered = OracleRenderer(), CenteredCuffRenderer()
        up = Vec2(0, -1)
        for sign in (-1, 1):
            relaxed = Vec2(sign, 16)
            self.assertEqual(renderer.sleeve_edges(Vec2(), relaxed, up, sign),
                             centered.sleeve_edges(Vec2(), relaxed, up, sign))
            for end in (Vec2(sign*15, 0), Vec2(sign*13, -7)):
                before = centered.sleeve_edges(Vec2(), end, up, sign)
                after = renderer.sleeve_edges(Vec2(), end, up, sign)
                self.assertEqual(before[:6], after[:6], '领边覆盖使用的袖根不动')
                cuff = after[-1][0].lerp(after[-1][1], .5)
                self.assertGreater(cuff.y-end.y, 1., '手掌应位于袖口偏上方')
                self.assertLessEqual((cuff-end).length(), renderer.SLEEVE_CUFF_DROP+1e-9)
                forward = unit(end-before[-2][0].lerp(before[-2][1], .5))
                self.assertAlmostEqual((cuff-end).x*forward.x+(cuff-end).y*forward.y, 0.,
                                       msg='只让衣料横向下垂，不改变手腕处的开口平面')

    def test_drape_stays_continuous_through_vertical_arm_and_body_rotations(self):
        renderer = OracleRenderer()
        for tilt in (0, 35, 90, 180):
            up = rotate(Vec2(0, -1), radians(tilt))
            for sign in (-1, 1):
                previous = None
                for angle in range(-180, 181):
                    end = rotate(Vec2(0, 15), radians(angle))
                    edges = renderer.sleeve_edges(Vec2(), end, up, sign)
                    cuff = edges[-1][0].lerp(edges[-1][1], .5)
                    self.assertGreaterEqual(cuff.y-end.y, -1e-9)
                    self.assertLessEqual((cuff-end).length(), renderer.SLEEVE_CUFF_DROP+1e-9)
                    if previous is not None:
                        self.assertLess((cuff-previous).length(), .4, '经过竖直方向不能翻边跳动')
                    previous = cuff

    def test_front_hand_redraw_does_not_cover_the_rounded_sleeve(self):
        renderer = OracleRenderer(colors=OracleColors(skin='#00ff00', robe_top='#ff0000', robe_bottom='#ff0000'))
        scene = OracleScene(OracleConfig(halo_enabled=False))
        app = scene.appearance
        for raised, scale in ((raised, scale) for raised in (False, True) for scale in (1., 1.5, 2., 4.)):
            if raised:
                for i, hand in enumerate(app.hands):
                    shoulder = hand.shoulder(app.upper, app.direction, i)
                    hand.pin(shoulder+perpendicular(app.direction)*((2*i-1)*14)+app.direction*5)
            image = QImage(round(64*scale), round(64*scale), QImage.Format.Format_RGBA8888)
            image.fill(0)
            painter = QPainter(image)
            painter.scale(scale, scale)
            painter.translate(32-app.upper.x, 24-app.upper.y)
            renderer.draw_limbs(painter, scene, 1., app.upper, app.lower, app.direction, hands=True)
            before = bytes(image.constBits())
            renderer.draw_body_front(painter, scene, 1., app.upper, app.lower, app.direction,
                                     app.head.position, scene.look_direction, include_head=False)
            painter.end()
            self.assertEqual(before, bytes(image.constBits()), (raised, scale, '重画手掌不能盖回袖口'))


if __name__ == '__main__':
    unittest.main()
