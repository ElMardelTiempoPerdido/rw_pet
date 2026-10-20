"""Prince 花冠的素材像素、奇数尺寸采样、转头遮挡和渲染密度"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from dataclasses import replace
from math import atan2, degrees, sqrt
import unittest

import numpy as np
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

from rw_creature_pet.oracle.graphics import prince
from rw_creature_pet.oracle.graphics.render import OracleRenderer
from rw_creature_pet.shared.geometry import Vec2
from rw_creature_pet.shared import petal_head


def rgba(image):
    image = image.convertToFormat(QImage.Format.Format_RGBA8888)
    return np.frombuffer(image.constBits(), dtype=np.uint8).reshape(image.height(), image.width(), 4).copy()


class PrinceHeadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_turn_response_stays_frontward_and_diagonals_do_not_saturate_early(self):
        def angle(gx, gy):
            gaze, depth = prince.head_view_gaze(gx, gy)
            self.assertAlmostEqual(gaze.length()**2+depth**2, 1.)
            return degrees(atan2(gaze.length(), depth))
        for axis in ((1., 0.), (0., 1.)):
            angles = [angle(axis[0]*i/100, axis[1]*i/100) for i in range(101)]
            self.assertEqual(angles, sorted(angles))
            self.assertEqual(angles[0], 0.)
            self.assertLess(angles[50], 25.)
            self.assertLess(angles[-1], 80.)
        self.assertLess(angle(0., 1.), angle(1., 0.))
        self.assertLess(angle(1/sqrt(2), 1/sqrt(2)), angle(1., 0.))
        self.assertAlmostEqual(angle(-.7, 0), angle(.7, 0))
        self.assertAlmostEqual(angle(0, -.7), angle(0, .7))

    def test_turn_curve_and_front_crossing_are_continuous(self):
        near = prince.HEAD_GAZE_NEAR_FRACTION
        delta = 1e-6
        left, center, right = [prince.head_tilt_angle(t, prince.HEAD_GAZE_MAX_YAW)
                               for t in (near-delta, near, near+delta)]
        self.assertLess(abs((center-left)/delta-(right-center)/delta), 1e-4)
        a = prince.head_view_gaze(-delta, 0.)
        b = prince.head_view_gaze(delta, 0.)
        self.assertLess((a[0]-b[0]).length(), 1e-5)
        self.assertAlmostEqual(a[1], b[1])
        # 饱和处不再具有 asin 在 1 附近的陡增
        before = prince.head_tilt_angle(1.-delta, prince.HEAD_GAZE_MAX_YAW)
        after = prince.head_tilt_angle(1., prince.HEAD_GAZE_MAX_YAW)
        self.assertLess(abs(after-before)/delta, 4.)

    def test_native_pixels_remain_exact_despite_odd_source_height(self):
        source = rgba(QImage(str(prince.TEXTURE_PATH)))
        height, width = source.shape[:2]
        self.assertEqual((width, height), (26, 25))
        for density in (1, 2):
            image, half = prince.head_image(0., 0., density)
            result = rgba(image)
            expected = np.repeat(np.repeat(source, density, axis=0), density, axis=1)
            x, y = round((half-width//2)*density), round((half-height//2)*density)
            mask = expected[:, :, 3] > 0
            # 素材透明留白可能比实际曲面画布大，只比较有内容的素材像素
            ys, xs = np.nonzero(mask)
            np.testing.assert_array_equal(result[y+ys, x+xs], expected[mask])
            black = (result[:, :, 3] > 0) & np.all(result[:, :, :3] == 0, axis=-1)
            self.assertEqual(np.count_nonzero(black), np.count_nonzero(mask))
            center = result[round(half*density), round(half*density)]
            self.assertEqual(tuple(center), QColor(petal_head.PALE_DISC_COLOR).getRgb())

    def test_curved_projection_changes_occlusion_and_fits_head_canvas(self):
        triangles, colors, extent = prince._surface()
        flat = triangles.copy()
        flat[:, :, 2] = 0.
        matrix = petal_head.view_matrix(Vec2(.8, 0.), .6, Vec2(0., -1.))
        curved = petal_head.project((triangles, colors, extent), matrix, 2., prince.DISC_RADIUS, prince.DISC_COLOR)[0]
        plane = petal_head.project((flat, colors, extent), matrix, 2., prince.DISC_RADIUS, prince.DISC_COLOR)[0]
        self.assertFalse(np.array_equal(rgba(curved), rgba(plane)))
        for density in (1., 1.5, 2.):
            for gx, gy in ((0., 0.), (.7, 0.), (-.7, 0.), (0., .8), (.6, .8), (1., 0.)):
                image, half = prince.head_image(gx, gy, density)
                pixels = rgba(image)
                self.assertLessEqual(half, OracleRenderer.HEAD_PIXELS/2)
                self.assertEqual(set(np.unique(pixels[:, :, 3])), {0, 255})
                self.assertFalse(np.any(pixels[[0, -1], :, 3]))
                self.assertFalse(np.any(pixels[:, [0, -1], 3]))
                self.assertIs(image, prince.head_image(gx, gy, density)[0])

    def test_renderer_uses_current_density_and_fixed_pale_disc(self):
        renderer = OracleRenderer()
        outputs = {}
        for scale, expected_density in ((1., 1.), (1.5, 1.5), (2., 2.), (3., 1.), (4., 2.)):
            image = QImage(256, 256, QImage.Format.Format_ARGB32_Premultiplied)
            image.fill(0)
            painter = QPainter(image)
            try:
                painter.translate(128, 128)
                painter.scale(scale, scale)
                renderer.draw_head(painter, Vec2(), Vec2(0, 10), Vec2(0, -1), Vec2(),
                                   body_appearance='prince', raster_scale=scale)
            finally:
                painter.end()
            pixels = rgba(image)
            self.assertEqual(tuple(pixels[128, 128]), QColor(prince.DISC_COLOR).getRgb())
            outputs[scale] = renderer._head_image.copy()
            self.assertAlmostEqual(renderer._head_target.width(), renderer._head_image.width()/expected_density)
        self.assertEqual(outputs[1.], outputs[3.])
        self.assertEqual(outputs[2.], outputs[4.])
        renderer.colors = replace(renderer.colors, skin='#ff0000')
        image = QImage(80, 80, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(0)
        painter = QPainter(image)
        try:
            renderer.draw_head(painter, Vec2(40, 40), Vec2(40, 50), Vec2(0, -1), Vec2(),
                               body_appearance='prince')
        finally:
            painter.end()
        self.assertEqual(outputs[1.], renderer._head_image)


if __name__ == '__main__':
    unittest.main()
