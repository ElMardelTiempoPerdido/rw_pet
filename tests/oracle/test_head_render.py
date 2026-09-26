"""头部矢量轮廓、显示精度、遮挡与独立缓存。"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from dataclasses import replace
from math import cos, radians, sin
import unittest
from unittest.mock import Mock, patch

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

from rw_creature_pet.oracle.render import OracleRenderer
from rw_creature_pet.shared.geometry import Vec2


class OracleHeadRenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def paint(self, renderer, *, scale=1., density=1., dpr=1., tilt=0., gaze=(0., 0.),
              openness=0., offset=Vec2()):
        image = QImage(round(128*scale), round(128*scale), QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(0)
        image.setDevicePixelRatio(dpr)
        painter = QPainter(image)
        angle = radians(tilt)
        direction = Vec2(sin(angle), -cos(angle))
        side = Vec2(-direction.y, direction.x)
        look = side*gaze[0]+direction*gaze[1]
        head = Vec2(64., 64.)+offset
        try:
            painter.scale(scale/dpr, scale/dpr)
            renderer.draw_head(painter, head, head-direction*14, direction, look, openness,
                               pixelated=True, raster_scale=density)
        finally:
            painter.end()
        image.setDevicePixelRatio(1.)
        return image

    def test_head_is_texture_independent_and_binary_at_every_resolution(self):
        renderer = OracleRenderer()
        for tilt, gaze, openness in ((0, (0, 0), 0), (0, (0, 0), 1), (25, (.7, -.5), .5),
                                     (-25, (-1, .8), 0), (90, (1, 0), 1), (180, (-.4, -.7), 1)):
            for density in (1., 1.5, 2., 4.):
                reference = self.paint(renderer, tilt=tilt, gaze=gaze, openness=openness,
                                       scale=density, density=density)
                renderer.atlas = Mock()
                renderer.atlas.sprite.side_effect = AssertionError('头部不应读取任何游戏贴图')
                renderer._head_geometry_key = renderer._head_key = None
                actual = self.paint(renderer, tilt=tilt, gaze=gaze, openness=openness,
                                    scale=density, density=density)
                self.assertTrue(bytes(actual.constBits()) == bytes(reference.constBits()))
                self.assertEqual(set(bytes(actual.constBits())[3::4]), {0, 255})
                renderer.atlas = None

    def test_fine_resolution_adds_detail_and_dpi_does_not_multiply_it(self):
        renderer = OracleRenderer()
        classic = self.paint(renderer, scale=2, density=1, tilt=23, gaze=(.4, .2))
        fine = self.paint(renderer, scale=2, density=2, tilt=23, gaze=(.4, .2))
        self.assertNotEqual(bytes(classic.constBits())[3::4], bytes(fine.constBits())[3::4])
        cache = renderer._head_image
        for dpr in (1.25, 1.5, 2.):
            actual = self.paint(renderer, scale=2, density=2, dpr=dpr, tilt=23, gaze=(.4, .2))
            self.assertTrue(bytes(fine.constBits()) == bytes(actual.constBits()))
            self.assertIs(renderer._head_image, cache)

    def test_translation_and_magnifier_reuse_head_and_zoom_reuses_geometry(self):
        renderer = OracleRenderer()
        self.paint(renderer, scale=2, density=2, tilt=19, gaze=(.4, .3))
        original = renderer._head_image
        with patch.object(renderer, 'draw_head_parts', wraps=renderer.draw_head_parts) as geometry:
            with patch.object(renderer._head_frame, 'replay', wraps=renderer._head_frame.replay) as replay:
                self.paint(renderer, scale=4, density=2, tilt=19, gaze=(.4, .3), offset=Vec2(3.25, -2.5))
                self.assertIs(renderer._head_image, original)
                replay.assert_not_called()
                self.paint(renderer, scale=4, density=4, tilt=19, gaze=(.4, .3))
                self.assertIsNot(renderer._head_image, original)
                replay.assert_called_once()
            geometry.assert_not_called()
            renderer.colors = replace(renderer.colors, skin='#0088ff')
            self.paint(renderer, scale=4, density=4, tilt=19, gaze=(.4, .3))
            geometry.assert_called_once()

    def test_near_ear_covers_face_and_far_ear_stays_behind(self):
        renderer = OracleRenderer()
        for gx in (-1., 1.):
            image = self.paint(renderer, density=4, scale=4, gaze=(gx, 0))
            near = -1 if gx > 0 else 1
            front = image.pixelColor(round((64+near*5)*4), round((64+.8)*4))
            back = image.pixelColor(round((64-near*5)*4), round((64+.8)*4))
            self.assertEqual(front, QColor(renderer.colors.head_highlight))
            self.assertEqual(back, QColor(renderer.colors.skin))

    def test_eye_sizes_still_match_bell_and_rotating_head_is_not_clipped(self):
        renderer = OracleRenderer()
        for openness, height in ((0, 4), (1, 8)):
            image = self.paint(renderer, density=4, scale=4, openness=openness)
            eye = QColor(renderer.colors.eyes)
            left = [(x, y) for x in range(240, 256) for y in range(256, 272)
                    if image.pixelColor(x, y) == eye]
            self.assertEqual(max(x for x,y in left)-min(x for x,y in left)+1, 8)
            self.assertEqual(max(y for x,y in left)-min(y for x,y in left)+1, height)
        for tilt in range(-180, 181, 15):
            for gaze in ((-1, -1), (0, 0), (1, 1)):
                self.paint(renderer, density=4, scale=4, tilt=tilt, gaze=gaze)
                cache = renderer._head_image
                for i in range(cache.width()):
                    self.assertEqual(cache.pixelColor(i, 0).alpha(), 0)
                    self.assertEqual(cache.pixelColor(i, cache.height()-1).alpha(), 0)
                    self.assertEqual(cache.pixelColor(0, i).alpha(), 0)
                    self.assertEqual(cache.pixelColor(cache.width()-1, i).alpha(), 0)


if __name__ == '__main__':
    unittest.main()
