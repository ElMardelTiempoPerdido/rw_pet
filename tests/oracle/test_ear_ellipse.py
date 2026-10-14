"""耳机椭圆的像素尺寸不依赖平移时的亚像素相位"""
from dataclasses import replace
from math import floor
import unittest
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter

from rw_creature_pet.oracle.config import CustomAppearance, OracleColors
from rw_creature_pet.oracle.ear_config import EarPart
from rw_creature_pet.oracle.graphics.earphones import draw_ear
from rw_creature_pet.oracle.graphics.pixel_ellipse import ellipse_image
from rw_creature_pet.oracle.graphics.render import PaintCommands


class EarEllipseTests(unittest.TestCase):
    def paint(self, part, *, scale=1., sign=1, gaze=(0., 0.), angle=0., recorded=False, dpr=1., slot='ear_body'):
        image = QImage(160, 160, QImage.Format.Format_ARGB32_Premultiplied)
        image.setDevicePixelRatio(dpr)
        image.fill(0)
        painter = QPainter(image)
        try:
            painter.translate(80/dpr, 80/dpr)
            painter.scale(scale/dpr, scale/dpr)
            painter.rotate(angle)
            shape = CustomAppearance(**{'ear_body': EarPart(enabled=False), slot: part})
            if recorded:
                commands = PaintCommands()
                draw_ear(commands, OracleColors(), shape, sign, *gaze)
                commands.replay(painter)
            else:
                draw_ear(painter, OracleColors(), shape, sign, *gaze)
        finally:
            painter.end()
        return image

    def ink(self, image):
        points = {(x, y): image.pixel(x, y) for y in range(image.height())
                  for x in range(image.width()) if image.pixelColor(x, y).alpha()}
        self.assertTrue(points)
        left, top = min(x for x, y in points), min(y for x, y in points)
        return {(x-left, y-top): color for (x, y), color in points.items()}

    def test_width_uses_whole_diameter_and_does_not_depend_on_offset(self):
        for scale in (1., 1.5, 2.):
            for width in (2., 2.5, 3., 3.5, 4., 5., 6., 7., 8.):
                with self.subTest(scale=scale, width=width):
                    part = EarPart(enabled=True, kind='ellipse', width=width, height=8.)
                    expected = self.ink(self.paint(part, scale=scale))
                    self.assertEqual(max(x for x, y in expected)+1, floor(width*scale+.5))
                    for offset in (.125, .25, .5, .75, 1., -1.25):
                        actual = self.ink(self.paint(replace(part, offset_x=offset, offset_y=offset/2), scale=scale))
                        self.assertEqual(actual, expected)

    def test_side_view_widens_core_but_preserves_attachment_shapes(self):
        texture = QImage(4, 8, QImage.Format.Format_ARGB32_Premultiplied)
        texture.fill(0xffffffff)
        with patch('rw_creature_pet.oracle.graphics.earphones.face_image', return_value=texture):
            for scale in (1., 1.5, 2.):
                core = EarPart(enabled=True, kind='ellipse', width=4., height=8.)
                front = self.ink(self.paint(core, scale=scale))
                side = self.ink(self.paint(core, scale=scale, gaze=(1., 0.)))
                self.assertEqual(max(x for x, y in front)+1, round(4*scale))
                self.assertEqual(max(x for x, y in side)+1, floor(7*scale+.5))
                for slot in ('ear_part_1', 'ear_part_2', 'ear_part_3'):
                    for kind in ('ellipse', 'rectangle', 'trapezoid', 'triangle', 'line', 'png'):
                        # 偏移量让测试落在相同像素相位，排除平移取整的一像素差异
                        part = EarPart(enabled=True, kind=kind, width=4., height=8., offset_x=8., rotation=23.)
                        for sign in (-1, 1):
                            expected = self.ink(self.paint(part, scale=scale, slot=slot, sign=sign))
                            for gx in (-1., -.5, .5, 1.):
                                with self.subTest(scale=scale, slot=slot, kind=kind, sign=sign, gx=gx):
                                    actual = self.ink(self.paint(part, scale=scale, slot=slot, sign=sign,
                                                                 gaze=(gx, 0.), recorded=True))
                                    self.assertEqual(actual, expected)

    def test_rotated_projected_split_ellipse_is_translation_invariant(self):
        for scale in (1., 1.5, 2.):
            for angle in (0., 31., 90., 180.):
                for sign in (-1, 1):
                    with self.subTest(scale=scale, angle=angle, sign=sign):
                        part = EarPart(enabled=True, kind='ellipse', width=5., height=9.,
                                       rotation=23., tone='split')
                        options = dict(scale=scale, sign=sign, angle=angle, gaze=(.7, -.8))
                        expected = self.ink(self.paint(part, **options))
                        self.assertEqual({color >> 24 for color in expected.values()}, {255})
                        self.assertEqual(len(set(expected.values())), 2)
                        for offset in (-.5, .25, 1.5):
                            actual = self.ink(self.paint(replace(part, offset_x=offset, offset_y=offset), **options))
                            self.assertEqual(actual, expected)

    def test_odd_even_diameters_stay_mirrored(self):
        for scale in (1., 1.5, 2.):
            for width in (3., 4., 5.):
                part = EarPart(enabled=True, kind='ellipse', width=width, height=8., offset_x=6.)
                right = self.paint(part, scale=scale)
                left = self.paint(part, scale=scale, sign=-1)
                self.assertEqual(left, right.flipped(Qt.Orientation.Horizontal))

    def test_flat_and_thin_ellipses_keep_the_requested_ink_bounds(self):
        for width in (.5, 1., 2., 3., 6., 7., 16., 32.):
            for height in (.5, 2., 4., 32.):
                with self.subTest(width=width, height=height):
                    part = EarPart(enabled=True, kind='ellipse', width=width, height=height)
                    pixels = self.ink(self.paint(part))
                    self.assertEqual(max(x for x, y in pixels)+1, max(1, floor(width+.5)))
                    self.assertEqual(max(y for x, y in pixels)+1, max(1, floor(height+.5)))

    def test_recorded_replay_uses_actual_device_scale_and_preserves_painter_transform(self):
        part = EarPart(enabled=True, kind='ellipse', width=5., height=8., tone='split')
        for scale in (1., 1.5, 2.):
            expected = self.paint(part, scale=scale, angle=19.)
            self.assertEqual(expected, self.paint(part, scale=scale, angle=19., recorded=True))
            self.assertEqual(self.ink(expected), self.ink(self.paint(part, scale=scale, angle=19., dpr=1.5)))

        image = QImage(160, 160, QImage.Format.Format_ARGB32_Premultiplied)
        painter = QPainter(image)
        try:
            painter.translate(80, 80)
            painter.scale(1.5, 1.5)
            painter.rotate(23)
            before = painter.deviceTransform()
            draw_ear(painter, OracleColors(), CustomAppearance(ear_body=part), 1, .5, -.5)
            self.assertEqual(painter.deviceTransform(), before)
        finally:
            painter.end()

    def test_offset_changes_reuse_cached_pixels_but_size_and_color_changes_do_not(self):
        ellipse_image.cache_clear()
        part = EarPart(enabled=True, kind='ellipse', width=5., height=8.)
        self.paint(part)
        self.paint(replace(part, offset_x=.25, offset_y=1.5))
        self.assertEqual(ellipse_image.cache_info().misses, 1)
        self.assertEqual(ellipse_image.cache_info().hits, 1)
        self.paint(replace(part, width=6.))
        self.paint(replace(part, tone='highlight'))
        self.assertEqual(ellipse_image.cache_info().misses, 3)
