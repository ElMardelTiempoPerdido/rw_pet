"""摸摸闭眼在原始像素尺寸下连续可见，普通表情和头部其他像素保持原样"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from dataclasses import replace
import unittest

import numpy as np
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication

from rw_creature_pet.oracle.behavior.eyes import OracleEyes
from rw_creature_pet.oracle.config import CustomAppearance, OracleColors
from rw_creature_pet.oracle.eye_config import EyeAppearance
from rw_creature_pet.oracle.graphics.eyes import EyeLidTransition
from rw_creature_pet.oracle.graphics.render import OracleRenderer
from rw_creature_pet.shared.geometry import Vec2


def channels(image):
    return np.frombuffer(image.constBits(), dtype=np.uint8).reshape(image.height(), image.width(), 4).copy()


class PettingEyesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def mask(self, amount, *, density=1., dpr=1., angle=0., lower=False, smooth=True):
        image = QImage(64, 64, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(0)
        image.setDevicePixelRatio(dpr)
        painter = QPainter(image)
        part = EyeLidTransition(QRectF(-3.5, 1.5+float(lower), 2., 1.),
                                QRectF(-3.5, 1., 2., 2.), amount, '#ffffff')
        try:
            painter.scale(1/dpr, 1/dpr)
            painter.translate(32, 32)
            painter.scale(density, density)
            painter.rotate(angle)
            if smooth:
                part.replay(painter)
            else:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(Qt.GlobalColor.white)
                painter.drawRect(part.rect(amount))
        finally:
            painter.end()
        return channels(image)

    def test_native_two_pixel_eye_has_linear_edge_coverage_and_opaque_core(self):
        opened, closed = self.mask(1.), self.mask(0.)
        core = (opened[:, :, 3] == 255) & (closed[:, :, 3] == 255)
        frames = []
        for tick in range(33):
            amount = 1-tick/32
            frame = self.mask(amount)
            frames.append(frame.tobytes())
            self.assertAlmostEqual(frame[:, :, 3].sum()/255, 2+2*amount, delta=.005)
            self.assertTrue(np.all(frame[:, :, 3][core] == 255))
        self.assertEqual(len(set(frames)), 33, '不能只在睁眼和闭眼两个像素高度之间跳变')

    def test_endpoints_and_dpi_match_original_pixels_at_each_scale_and_angle(self):
        for density in (1., 1.5, 2., 4.):
            for angle in (0., 37., 90., 157.):
                for lower in (False, True):
                    for amount in (0., 1.):
                        with self.subTest(density=density, angle=angle, lower=lower, amount=amount):
                            kw = dict(density=density, angle=angle, lower=lower)
                            hard = self.mask(amount, **kw, smooth=False)
                            np.testing.assert_array_equal(self.mask(amount, **kw), hard)
                            almost = self.mask(.0001 if amount == 0 else .9999, **kw)
                            np.testing.assert_array_equal(almost, hard)
                    for amount in (.15, .45, .8):
                        np.testing.assert_array_equal(self.mask(amount, **kw, dpr=1.5),
                                                      self.mask(amount, **kw))

    def head(self, renderer, shape, openness, closure):
        image = QImage(64, 64, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(0)
        painter = QPainter(image)
        try:
            renderer.draw_head(painter, Vec2(32, 32), Vec2(32, 42), Vec2(0, -1), Vec2(),
                               openness, pixelated=True, shape=shape, eye_closure=closure)
        finally:
            painter.end()
        return image

    def test_temporary_open_and_default_open_close_at_the_same_linear_rate(self):
        renderer = OracleRenderer(colors=OracleColors(skin='#ffffff'))
        shape = CustomAppearance(eye_1=EyeAppearance('#000000', default_open=True),
                                 eye_2=EyeAppearance('#000000', default_open=False))
        eyes = OracleEyes()
        eyes.begin_reaction(True)
        for _ in range(eyes.OPEN_TICKS):
            eyes.step()
        eyes.forced_closed = True
        images = []
        for tick in range(eyes.PETTING_CLOSE_TICKS+1):
            image = self.head(renderer, shape, eyes.sample(1.), eyes.sample_closure(1.))
            pixels = channels(image)
            left, right = pixels[34:36, 29:31, 0], pixels[34:36, 34:36, 0]
            amount = 1-tick/eyes.PETTING_CLOSE_TICKS
            self.assertAlmostEqual((255-left.astype(float)).sum()/255, 2+2*amount, delta=.005)
            self.assertAlmostEqual((255-right.astype(float)).sum()/255, 2+2*amount, delta=.005)
            images.append(pixels)
            self.assertEqual(image, self.head(OracleRenderer(colors=renderer.colors), shape,
                                              eyes.sample(1.), eyes.sample_closure(1.)))
            eyes.step()
        changed = np.any(images[0] != images[-1], axis=2)
        for frame in images:
            np.testing.assert_array_equal(frame[~changed], images[0][~changed])
        self.assertEqual(self.head(renderer, shape, 1., 0.),
                         self.head(OracleRenderer(colors=renderer.colors), shape, 1., 0.))

    def test_ordinary_eye_animation_remains_binary_and_hidden_eye_is_untouched(self):
        renderer = OracleRenderer(colors=OracleColors(skin='#ffffff'))
        shape = CustomAppearance(eye_1=EyeAppearance('#000000'), eye_2=EyeAppearance(visible=False))
        for openness in (.15, .5, .85):
            image = self.head(renderer, shape, openness, 0.)
            eye = channels(image)[34:36, 29:31, :3]
            self.assertEqual(set(eye.flat), {0, 255})
        disabled = replace(shape, eye_1=replace(shape.eye_1, visible=False))
        self.assertEqual(self.head(renderer, disabled, 1., .5), self.head(renderer, disabled, 1., 0.))


if __name__ == '__main__':
    unittest.main()
