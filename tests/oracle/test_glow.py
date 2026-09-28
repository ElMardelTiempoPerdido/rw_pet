"""外发光按实体分层、缓存、缩放、命中区域及局部清屏的回归。"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import copy
from dataclasses import replace
import unittest
from unittest.mock import patch

import numpy as np
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

from rw_creature_pet.oracle.config import OracleConfig
from rw_creature_pet.oracle.damage import visual_bounds
from rw_creature_pet.oracle.glow import GlowLayer
from rw_creature_pet.oracle.input import PuppetHitMap
from rw_creature_pet.oracle.render import OracleRenderer
from rw_creature_pet.oracle.scene import OracleScene
from rw_creature_pet.shared.geometry import Vec2


def rgba(image):
    image = image.convertToFormat(QImage.Format.Format_RGBA8888)
    return np.frombuffer(bytes(image.constBits()), dtype=np.uint8).reshape(image.height(), image.width(), 4)


class Glyphs:
    def sprite(self, index, color):
        image = QImage(15, 15, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(QColor(color))
        return image


class GlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def paint(self, renderer, scene, scale=1., image=None, clip=None, alpha=.5):
        if image is None:
            image = QImage(round(960*scale), round(600*scale), QImage.Format.Format_ARGB32_Premultiplied)
            image.fill(0)
        painter = QPainter(image)
        try:
            if clip is not None:
                painter.setClipRect(clip)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
            painter.fillRect(image.rect(), Qt.GlobalColor.transparent)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.scale(scale, scale)
            renderer.draw(painter, scene, alpha)
        finally:
            painter.end()
        return image

    def test_config_defaults_and_invalid_values(self):
        self.assertFalse(OracleConfig.from_mapping({}).glow_enabled)
        for changes in ({'glow_enabled': 1}, {'glow_color': '#gg1122'}, {'glow_radius': 0},
                        {'glow_radius': float('nan')}, {'glow_radius': True}, {'glow_radius': 25}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                OracleConfig(**changes)

    def test_disabled_does_not_prepare_glow_and_opaque_pixels_keep_original_colors(self):
        scene, renderer = OracleScene(), OracleRenderer()
        with patch.object(GlowLayer, 'prepare', side_effect=AssertionError('默认关闭不应计算模糊')):
            before = rgba(self.paint(renderer, scene))
        scene.config = replace(scene.config, glow_enabled=True)
        after = rgba(self.paint(renderer, scene))
        opaque = before[:, :, 3] == 255
        self.assertTrue(np.array_equal(before[opaque], after[opaque]))
        self.assertGreater(np.count_nonzero((before[:, :, 3] == 0) & (after[:, :, 3] > 0)), 300)

    def test_projection_and_halo_are_excluded_even_when_fully_opaque(self):
        scene = OracleScene(OracleConfig(glow_enabled=True, projection_opacity=1.,
                                       pearl_matrix_enabled=True, pearl_orbits_enabled=True))
        first = OracleRenderer(glyphs=Glyphs())
        self.paint(first, scene)
        scene.config = replace(scene.config, projection_opacity=0., halo_enabled=False)
        second = OracleRenderer(glyphs=Glyphs())
        self.paint(second, scene)
        for name in ('_body_glow', '_head_glow', '_pearl_glow'):
            a, b = getattr(first, name), getattr(second, name)
            self.assertEqual(a.offset, b.offset)
            self.assertTrue(np.array_equal(rgba(a.image), rgba(b.image)), name)

    def test_sleep_and_moving_pearls_reuse_large_blur_and_do_not_expand_mouse_hit_map(self):
        scene = OracleScene(OracleConfig(glow_enabled=True, pearl_orbits_enabled=True))
        renderer = OracleRenderer()
        for _ in range(700):
            scene.step()
        self.assertTrue(scene.appearance.sleeping)
        self.paint(renderer, scene, alpha=.2)
        body, pearl = renderer._body_glow.image, renderer._pearl_glow.image
        hit = PuppetHitMap()
        before = hit.get(renderer, scene)
        for _ in range(3):
            scene.step()
            self.paint(renderer, scene, alpha=.8)
        self.assertIs(body, renderer._body_glow.image)
        self.assertIs(pearl, renderer._pearl_glow.image)
        scene.config = replace(scene.config, glow_enabled=False)
        self.assertIs(before, hit.get(renderer, scene))

    def test_color_radius_and_density_change_only_glow_cache(self):
        source = QImage(9, 9, QImage.Format.Format_ARGB32_Premultiplied)
        source.fill(0)
        source.setPixelColor(4, 4, QColor('white'))
        glow = GlowLayer()
        glow.prepare(source, 1, '#ff0000', 3., 1.)
        red = rgba(glow.image)
        visible = red[:, :, 3] > 0
        self.assertTrue(np.all(red[:, :, 0][visible] == 255))
        self.assertTrue(np.all(red[:, :, 1:3][visible] == 0))
        self.assertGreater(len(np.unique(red[:, :, 3])), 3)
        old = glow.image
        glow.prepare(source, 1, '#ff0000', 3., 1.)
        self.assertIs(glow.image, old)
        glow.prepare(source, 1, '#00ff00', 12., 2.)
        self.assertGreater(glow.image.width(), old.width())
        self.assertGreater(glow.offset.width(), old.width())

    def test_partial_repaint_clears_movement_radius_reduction_and_switch_off(self):
        scene = OracleScene(OracleConfig(glow_enabled=True, glow_radius=24., pearl_orbits_enabled=True))
        snapshots = [copy.deepcopy(scene)]
        scene.set_target(scene.target+Vec2(90, 0))
        for _ in range(90):
            scene.step()
        snapshots.append(copy.deepcopy(scene))
        scene.config = replace(scene.config, glow_radius=2.)
        snapshots.append(copy.deepcopy(scene))
        scene.config = replace(scene.config, glow_enabled=False)
        snapshots.append(scene)
        for scale in (1., 1.5, 2.):
            renderer, old, partial = OracleRenderer(), QRectF(), None
            for scene in snapshots:
                rect = visual_bounds(scene)
                box = QRectF(rect.x()*scale, rect.y()*scale, rect.width()*scale, rect.height()*scale)
                clip = QRectF(box.toAlignedRect()).united(old).adjusted(-2, -2, 2, 2)
                partial = self.paint(renderer, scene, scale, partial, clip)
                complete = self.paint(renderer, scene, scale)
                self.assertTrue(np.array_equal(rgba(partial), rgba(complete)))
                old = QRectF(box.toAlignedRect())
