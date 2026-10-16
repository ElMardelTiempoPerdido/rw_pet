"""柔性附件的倍率、发光缓存、桌面局部清屏与鼠标穿透"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np
from PySide6.QtCore import QRectF
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication

from rw_creature_pet.oracle.graphics.damage import visual_bounds
from rw_creature_pet.oracle.graphics.glow import GlowLayer
from rw_creature_pet.oracle.graphics.render import OracleRenderer
from rw_creature_pet.oracle.interaction.input import PuppetHitMap
from rw_creature_pet.oracle.scene import OracleScene
from rw_creature_pet.shared.geometry import Vec2
from tests.oracle import test_glow as glow_tests
from tests.oracle import test_soft_parts as base_tests
from tests.oracle import test_desktop as desktop_tests
from tests.oracle.test_soft_part_render import pixels, straight


def config():
    return base_tests.SoftPartsTests.config(None)


def render(renderer, scene, scale=1., *, dpr=1., raster_scale=None, alpha=.5):
    image = QImage(400, 400, QImage.Format.Format_ARGB32_Premultiplied)
    image.setDevicePixelRatio(dpr)
    image.fill(0)
    painter = QPainter(image)
    try:
        painter.translate(200/dpr, 130/dpr)
        painter.scale(scale/dpr, scale/dpr)
        painter.translate(-scene.appearance.upper.x, -scene.appearance.upper.y)
        renderer.draw(painter, scene, alpha, raster_scale=raster_scale)
    finally:
        painter.end()
    return image


class SoftPartIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def test_pixel_density_tracks_body_including_dpr_and_magnifier(self):
        scene, renderer = OracleScene(config()), OracleRenderer()
        images = {}
        for coarse in (False, True):
            scene.config = replace(scene.config, coarse_pixels_4x=coarse)
            for scale, expected in ((1., 1.), (1.5, 1.5), (2., 2.), (3., 1.), (4., 1. if coarse else 2.)):
                for dpr in (1., 1.5, 2.):
                    with self.subTest(coarse=coarse, scale=scale, dpr=dpr):
                        render(renderer, scene, scale, dpr=dpr)
                        key, image, rect = renderer._soft_parts_renderer.cache[0]
                        self.assertEqual(key[3], expected)
                        self.assertEqual(renderer._raster_key[1], expected)
                        self.assertTrue(np.isin(pixels(image)[:, :, 3], (0, 255)).all())
                        # 高倍率复用相同基础像素图，不让系统 DPR 再次细分
                        if expected in images:
                            self.assertEqual(image, images[expected])
                        images[expected] = image
                        self.assertAlmostEqual(image.width()/rect.width(), expected)
        render(renderer, scene, 8., raster_scale=1.5)
        self.assertEqual(renderer._soft_parts_renderer.cache[0][0][3], 1.5)
        scene.config = replace(scene.config, pixel_mode='classic')
        render(renderer, scene, 2.)
        self.assertEqual(renderer._soft_parts_renderer.cache[0][0][3], 1.)

    def test_glow_preserves_solids_and_reuses_mesh_when_opacity_color_or_radius_change(self):
        scene, renderer = OracleScene(config()), OracleRenderer()
        with patch.object(GlowLayer, 'prepare', side_effect=AssertionError('关闭时不计算模糊')):
            base = pixels(render(renderer, scene))
        scene.config = replace(scene.config, glow_enabled=True, glow_opacity=1.)
        full = pixels(render(renderer, scene))
        soft = renderer._soft_parts_renderer
        mesh, blur = soft.cache[0][1], soft.glows[0].image
        self.assertIsNotNone(blur)
        solid = base[:, :, 3] == 255
        self.assertTrue(np.array_equal(base[solid], full[solid]))
        scene.config = replace(scene.config, glow_opacity=.4)
        faded = pixels(render(renderer, scene))
        self.assertIs(soft.glows[0].image, blur)
        empty = base[:, :, 3] == 0
        self.assertLess(faded[:, :, 3][empty].sum(), full[:, :, 3][empty].sum())
        self.assertGreater(faded[:, :, 3][empty].sum(), 0)
        scene.config = replace(scene.config, glow_color='#00ff00', glow_radius=24.)
        render(renderer, scene)
        self.assertIs(soft.cache[0][1], mesh)
        self.assertIsNot(soft.glows[0].image, blur)
        tinted = pixels(soft.glows[0].image)
        self.assertTrue((tinted[:, :, :3][tinted[:, :, 3] > 0] == (0, 255, 0)).all())
        scene.config = replace(scene.config, glow_opacity=0.)
        with patch.object(GlowLayer, 'prepare', side_effect=AssertionError('0% 不计算模糊')):
            self.assertTrue(np.array_equal(pixels(render(renderer, scene)), base))

    def test_only_moving_slot_rebuilds_blur_and_hit_map_excludes_attachment(self):
        scene, renderer, hits = OracleScene(replace(config(), glow_enabled=True)), OracleRenderer(), PuppetHitMap()
        for _ in range(900):
            scene.step()
        self.assertTrue(scene.appearance.sleeping and scene.soft_parts.sleeping)
        render(renderer, scene, alpha=.2)
        soft = renderer._soft_parts_renderer
        mesh, blur = soft.cache[0][1], soft.glows[0].image
        other, body = soft.glows[1].image, renderer._body_glow.image
        hit = hits.get(renderer, scene)
        self.assertTrue(hit.contains(scene.appearance.head.position))
        render(renderer, scene, alpha=.8)
        self.assertIs(soft.cache[0][1], mesh)
        self.assertIs(soft.glows[0].image, blur)
        part = scene.soft_parts.parts[0]
        part.sleeping = False
        part.points[-1].velocity = Vec2(3, 0)
        part.quiet_ticks = 0
        scene.soft_parts.step(scene)
        render(renderer, scene, alpha=.8)
        self.assertIsNot(soft.glows[0].image, blur)
        self.assertIs(soft.glows[1].image, other)
        self.assertIs(renderer._body_glow.image, body)
        self.assertIs(hits.get(renderer, scene), hit)
        # 独立延伸到原有人偶之外的可见部分不能截获鼠标
        scene.soft_parts.parts[0] = straight(part.config, root=Vec2(780, 480))
        image = glow_tests.GlowTests.paint(None, renderer, scene)
        self.assertEqual(image.pixelColor(780, 490).alpha(), 255)
        self.assertFalse(hit.contains(Vec2(780, 490)))
        self.assertGreater(image.pixelColor(777, 490).alpha(), 0)  # 外发光也不增加命中区
        self.assertFalse(hit.contains(Vec2(777, 490)))
        self.assertIs(hits.get(renderer, scene), hit)

    def test_partial_repaint_clears_motion_resize_png_removal_and_character_switch(self):
        scene = OracleScene(replace(config(), glow_enabled=True, glow_radius=24.))
        part = replace(scene.config.custom_appearance.soft_part_1, width=24., length=64.)
        shape = replace(scene.config.custom_appearance, soft_part_1=part,
                        soft_part_2=replace(scene.config.custom_appearance.soft_part_2, enabled=False))
        scene.config = replace(scene.config, custom_appearance=shape)
        scene.soft_parts.sync(scene)
        scene.soft_parts.parts[0] = straight(part, root=Vec2(780, 460))
        snapshots = [deepcopy(scene)]
        moving = scene.soft_parts.parts[0]
        for i, point in enumerate(moving.points):
            point.previous_position = point.position
            point.position += Vec2(i*4, -i)
        moving.revision += 1
        snapshots.append(deepcopy(scene))
        for changes in ({'width': .5, 'layer': 'back'}, {'kind': 'png', 'image_path': ''},
                        {'kind': 'rectangle'}, {'enabled': False}, {'enabled': True}):
            shape = replace(shape, soft_part_1=replace(shape.soft_part_1, **changes))
            scene.config = replace(scene.config, custom_appearance=shape)
            scene.soft_parts.sync(scene)
            snapshots.append(deepcopy(scene))
        for changes in ({'glow_radius': 1.}, {'glow_enabled': False}, {'body_appearance': 'bell'}):
            scene.config = replace(scene.config, **changes)
            scene.soft_parts.sync(scene)
            snapshots.append(deepcopy(scene))
        for scale in (1., 1.5, 4.):
            renderer, old, partial = OracleRenderer(), QRectF(), None
            for current in snapshots:
                bounds = visual_bounds(current)
                box = QRectF(bounds.x()*scale, bounds.y()*scale, bounds.width()*scale,
                             bounds.height()*scale).toAlignedRect()
                clip = QRectF(box).united(old).adjusted(-2, -2, 2, 2)
                partial = glow_tests.GlowTests.paint(None, renderer, current, scale, partial, clip)
                complete = glow_tests.GlowTests.paint(None, renderer, current, scale)
                self.assertTrue(np.array_equal(pixels(partial), pixels(complete)), scale)
                old = QRectF(box)
            self.assertEqual(renderer._soft_parts_renderer.cache, [None, None])
            self.assertTrue(all(g.image is None for g in renderer._soft_parts_renderer.glows))

    def test_paused_desktop_applies_slot_switch_without_waiting_for_physics(self):
        fixture = desktop_tests.OracleDesktopWindowTests()
        fixture.app = self.app
        fixture.setUp()
        window = fixture.window
        try:
            window.config_store = Mock(path=Path('unused-settings.toml'))
            window.set_paused(True)
            scene = window.motion.scene
            current = window.current_settings()
            selected = replace(current, oracle=replace(current.oracle, body_appearance='custom',
                                                        custom_appearance=config().custom_appearance))
            assets = SimpleNamespace(renderer=window.renderer, message='', voice_paths={}, voice_error='')
            window.apply_settings(selected, assets)
            self.assertIs(window.motion.scene, scene)
            self.assertTrue(window.clock.paused)
            self.assertTrue(all(scene.soft_parts.parts))
            window.apply_settings(replace(selected, oracle=replace(selected.oracle, body_appearance='bell')), assets)
            self.assertIs(window.motion.scene, scene)
            self.assertEqual(scene.soft_parts.parts, [None, None])
            self.assertTrue(window.clock.paused)
        finally:
            fixture.tearDown()


if __name__ == '__main__':
    unittest.main()
