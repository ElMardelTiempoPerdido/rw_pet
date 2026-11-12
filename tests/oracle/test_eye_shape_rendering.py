"""新版圆眼全角度保形、符号柔化、闭眼衔接与备用方案切换"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import unittest
from unittest.mock import patch

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication

from rw_creature_pet.oracle.graphics import eye_rendering
from rw_creature_pet.oracle.graphics.eyes_shape_aware import eye_stamp
from rw_creature_pet.oracle.graphics.render import OracleRenderer
from rw_creature_pet.shared.geometry import Vec2
from rw_creature_pet.shared.raster import pixel_density
from tests.oracle import test_eye_stability as stability_checks


def channels(image):
    return np.frombuffer(image.constBits(), dtype=np.uint8).reshape(
        image.height(), image.bytesPerLine()//4, 4).copy()


class EyeShapeRenderingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        mode = patch.object(eye_rendering, 'EYE_RENDER_MODE', 'shape_aware')
        mode.start()
        self.addCleanup(mode.stop)
        self.head = stability_checks.EyeStabilityTests().render

    def ink(self, kind='normal', *, angle=0., gx=0., gy=0., scale=1., dpr=1.,
            sign=-1, opened=1., height=2., lower=False):
        image = QImage(round(64*scale), round(64*scale), QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(0)
        image.setDevicePixelRatio(dpr)
        painter = QPainter(image)
        try:
            painter.scale(1/dpr, 1/dpr)
            painter.translate(32*scale+.5, 32*scale+.5)
            painter.scale(scale, scale)
            painter.rotate(angle)
            eye = Vec2(max(-5., min(5., gx*3+2.5*sign)), 2.-gy*3)
            if kind == 'fixed_open':
                height = 2.
            elif kind == 'fixed_closed':
                height = 1.
            command = eye_rendering.make_eye(eye, gx, sign, '#ff0000', kind, 2., height,
                                             max(0., min(1., (sign*gx-.5)*2)),
                                             opened, lower, 0 < opened < 1)
            command.replay(painter)
        finally:
            painter.end()
        image.setDevicePixelRatio(1.)
        return image

    def pattern(self, image):
        data = channels(image)
        y, x = np.where(data[:, :, 3] != 0)
        self.assertGreater(len(x), 0)
        return {(int(xx-x.min()), int(yy-y.min())): tuple(data[yy, xx]) for xx, yy in zip(x, y)}

    def test_round_types_keep_complete_pattern_at_every_angle_and_gaze(self):
        for kind in ('normal', 'fixed_open', 'round'):
            for scale in (1., 1.5, 2.):
                for sign in (-1, 1):
                    base = self.pattern(self.ink(kind, scale=scale, sign=sign))
                    for angle in (5, 35, 45, 89, 90, 135, 180, 240, 315):
                        for gx in (-1., .3, 1.):
                            with self.subTest(kind=kind, scale=scale, angle=angle, gx=gx, sign=sign):
                                actual = self.ink(kind, angle=angle, gx=gx, gy=.2, scale=scale, sign=sign)
                                self.assertEqual(base, self.pattern(actual))
        # 普通自定义眼高仍按配置保留，不会被当成固定 2×2 覆盖
        base = self.pattern(self.ink(height=4.))
        self.assertEqual(base, self.pattern(self.ink(angle=90, gx=1., height=4.)))

    def test_soft_shapes_keep_visible_strokes_with_fractional_coverage(self):
        for kind in ('squeezed', 'slant_in', 'slant_out', 'chevron_up', 'chevron_down', 'fixed_closed', 'normal'):
            opened = 0. if kind == 'normal' else 1.
            base = channels(self.ink(kind, opened=opened))[:, :, 3].sum()/255
            for angle in (5, 27, 45, 74):
                with self.subTest(kind=kind, angle=angle):
                    alpha = channels(self.ink(kind, angle=angle, opened=opened))[:, :, 3]
                    self.assertTrue(np.any((alpha > 0) & (alpha < 255)))
                    self.assertGreater(alpha.max(), 40)
                    self.assertGreater(alpha.sum()/255, base*.6)
                    self.assertLess(alpha.sum()/255, base*1.5)

    def test_mixed_closing_has_many_states_and_no_last_frame_angle_snap(self):
        for angle in (0, 45, 90, 179, -179):
            frames = [channels(self.ink(angle=angle, opened=1.-tick/32)) for tick in range(33)]
            self.assertEqual(len({frame.tobytes() for frame in frames}), 33)
            # 最后一步的透明度变化应小于半个像素，不能到闭合才骤然旋转整条眼线
            last_change = np.abs(frames[-1][:, :, 3].astype(int)-frames[-2][:, :, 3].astype(int)).sum()/255
            self.assertLess(last_change, .5, angle)
        a = channels(self.ink(angle=179.9, opened=.5))
        b = channels(self.ink(angle=-179.9, opened=.5))
        self.assertLess(np.abs(a.astype(int)-b.astype(int)).sum()/255, .2)

    def test_soft_sampling_is_local_and_preserves_painter_state_and_clip(self):
        image = QImage(64, 64, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(0)
        painter = QPainter(image)
        try:
            painter.setClipRect(0, 0, 33, 64)
            painter.translate(32, 32)
            painter.rotate(30)
            before = painter.worldTransform(), painter.renderHints(), painter.clipRegion()
            eye_rendering.make_eye(Vec2(0, 0), 0., 1, '#ff0000', 'squeezed', 2., 2., 0.).replay(painter)
            self.assertEqual(before, (painter.worldTransform(), painter.renderHints(), painter.clipRegion()))
        finally:
            painter.end()
        self.assertFalse(channels(image)[:, 33:, 3].any())

    def test_dpi_coarse_enlargement_and_head_cache_still_match(self):
        for kind in ('normal', 'round', 'slant_in'):
            for scale in (1., 1.5, 2.):
                self.assertEqual(self.ink(kind, angle=35, scale=scale),
                                 self.ink(kind, angle=35, scale=scale, dpr=1.5))
            renderer = OracleRenderer()
            for scale, coarse in ((2., True), (3., False), (4., False), (4., True)):
                density = pixel_density('adaptive', scale, coarse)
                base = self.head(kind, scale=density, density=density, angle=35, gx=.2, renderer=renderer)
                cached = renderer._head_image
                actual = self.head(kind, scale=scale, density=density, angle=35, gx=.2,
                                   dpr=1.5, renderer=renderer)
                self.assertEqual(actual, base.scaled(actual.size(), Qt.AspectRatioMode.IgnoreAspectRatio,
                                                     Qt.TransformationMode.FastTransformation))
                self.assertIs(renderer._head_image, cached)

    def test_mode_switch_invalidates_cache_and_previous_version_remains_available(self):
        renderer = OracleRenderer()
        current = self.head(angle=35, gx=.2, renderer=renderer)
        with patch.object(eye_rendering, 'EYE_RENDER_MODE', 'stable_pixels'):
            previous = self.head(angle=35, gx=.2, renderer=renderer)
            self.assertNotEqual(current, previous)
            self.assertEqual(previous, self.head(angle=35, gx=.2))
        self.assertEqual(current, self.head(angle=35, gx=.2, renderer=renderer))

    def test_turning_reuses_bounded_canonical_stamp_cache(self):
        eye_stamp.cache_clear()
        for angle in (0, 10, 30, 45, 90, 180):
            self.ink('chevron_up', angle=angle)
        self.assertEqual(eye_stamp.cache_info().misses, 1)
        self.assertEqual(eye_stamp.cache_info().maxsize, 256)


if __name__ == '__main__':
    unittest.main()
