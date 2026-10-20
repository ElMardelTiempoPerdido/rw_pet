"""锚点换部位、图层遮挡、前景蒙版及其外发光必须使用同一份有效轮廓"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from dataclasses import replace
from math import radians
import unittest
from unittest.mock import patch

from PySide6.QtCore import QRectF
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication

from rw_creature_pet.oracle.config import OracleConfig
from rw_creature_pet.oracle.graphics.appearance import OracleAppearance, rotate
from rw_creature_pet.oracle.graphics.damage import body_bounds
from rw_creature_pet.oracle.graphics.outfit_definition import Clip, MAID, Sampling, outfit_definition
from rw_creature_pet.oracle.graphics.render import OracleRenderer
from rw_creature_pet.oracle.outfit_config import OutfitSettings
from rw_creature_pet.oracle.outfit_layout import Anchor, Slot, allowed_slots
from rw_creature_pet.oracle.scene import OracleScene
from rw_creature_pet.shared.geometry import Vec2


def settings_for(part_id, **values):
    defaults = OutfitSettings()
    parts = {part.id: replace(getattr(defaults.maid, part.id), enabled=part.id == part_id)
             for part in MAID.components}
    parts[part_id] = replace(parts[part_id], **values)
    return replace(defaults, maid=replace(defaults.maid, **parts))


def paint(renderer, scene, scale=1., *, front_only=False, cached=True):
    image = QImage(round(960*scale), round(600*scale), QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(0)
    painter = QPainter(image)
    try:
        painter.scale(scale, scale)
        if front_only:
            renderer.draw_front_outfit(painter, scene, raster_scale=scale)
        else:
            renderer.draw_geometry(painter, scene, arm=False, cords=False, pearl=False, halo=False,
                                   cache_body=cached, raster_scale=scale)
    finally:
        painter.end()
    return image


class OutfitPlacementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_all_valid_regions_and_layers_have_renderable_sampling_and_clips(self):
        for part in MAID.components:
            for anchor in Anchor:
                for layer in allowed_slots(anchor):
                    with self.subTest(part=part.id, anchor=anchor, layer=layer):
                        settings = settings_for(part.id, anchor=anchor, layer=layer)
                        effective = outfit_definition('maid', settings).component(part.id)
                        self.assertEqual(effective.region, anchor.region)
                        if anchor.region == 'head':
                            self.assertEqual(effective.clip, Clip.NONE)
                            self.assertEqual(effective.sampling, Sampling.LOCAL)
                        else:
                            self.assertEqual(effective.clip, part.clip)
                            if layer == Slot.FRONT:
                                self.assertEqual(effective.sampling, Sampling.ALIGNED)
                        scene = OracleScene(OracleConfig(outfit='maid', outfit_settings=settings,
                                                        hide_cords=True, physics_backend='python'))
                        renderer = OracleRenderer()
                        self.assertEqual(paint(renderer, scene), paint(renderer, scene, cached=False))

    def test_foreground_clothing_mask_is_baked_into_glow_source(self):
        settings = settings_for('apron', layer=Slot.FRONT, offset_x=7, mirror=True)
        scene = OracleScene(OracleConfig(outfit='maid', outfit_settings=settings,
                                        hide_cords=True, glow_enabled=True, physics_backend='python'))
        for angle in (0, 37, 180):
            origin = Vec2(400, 300)
            direction = rotate(Vec2(0, -1), radians(angle))
            for part, position in zip((*scene.body.chunks, scene.head),
                                     (origin, origin-direction*9, origin+direction*14)):
                part.position = part.previous_position = position
            scene.appearance = OracleAppearance(scene)
            for scale in (1., 1.5, 2.):
                with self.subTest(angle=angle, scale=scale):
                    renderer = OracleRenderer()
                    visible = paint(renderer, scene, scale, front_only=True)
                    sprites = renderer._front_outfit_layers
                    source = QImage(visible.size(), visible.format())
                    source.fill(0)
                    painter = QPainter(source)
                    try:
                        painter.scale(scale, scale)
                        for sprite in sprites:
                            painter.drawImage(sprite.target, sprite.image)
                    finally:
                        painter.end()
                    self.assertEqual(visible, source, '发光源不得包含被衣物蒙版裁掉的像素')
                    self.assertTrue(any(s.image != s.source for s in sprites))
                    images = tuple(s.image for s in sprites)
                    with patch.object(renderer, 'gown_geometry', wraps=renderer.gown_geometry) as geometry:
                        self.assertEqual(visible, paint(renderer, scene, scale, front_only=True))
                        geometry.assert_not_called()
                    for sprite, image in zip(renderer._front_outfit_layers, images):
                        self.assertIs(sprite.image, image)

    def test_after_cape_overlays_after_sleeves_independent_of_part_order(self):
        # 同一张素材染黑/染白并重叠，验证真实合成顺序而不依赖部件名称
        defaults = OutfitSettings()
        settings = replace(defaults, maid=replace(defaults.maid,
            head=replace(defaults.maid.head, enabled=False),
            lace=replace(defaults.maid.lace, enabled=False),
            apron=replace(defaults.maid.apron, enabled=False),
            ribbon_up=replace(defaults.maid.ribbon_up, anchor=Anchor.GOWN_COLLAR,
                              layer=Slot.AFTER_CAPE, brightness=-100, offset_y=20),
            ribbon_down=replace(defaults.maid.ribbon_down, layer=Slot.AFTER_SLEEVES,
                                brightness=100, offset_y=20)))
        upper = MAID.component('ribbon_up')
        lower = replace(upper, id='ribbon_down')
        definition = replace(MAID, components=(upper, lower))
        with patch.dict('rw_creature_pet.oracle.graphics.outfit_definition.BUILTIN_OUTFITS', maid=definition):
            scene = OracleScene(OracleConfig(outfit='maid', outfit_settings=settings, physics_backend='python'))
            combined = paint(OracleRenderer(), scene)
            scene.config = replace(scene.config, outfit_settings=replace(settings,
                maid=replace(settings.maid, ribbon_down=replace(settings.maid.ribbon_down, enabled=False))))
            self.assertEqual(combined, paint(OracleRenderer(), scene))

    def test_foreground_clip_keeps_coarse_pixels_at_high_display_scales(self):
        settings = settings_for('apron', layer=Slot.FRONT, offset_x=7.3, offset_y=.7)
        scene = OracleScene(OracleConfig(outfit='maid', outfit_settings=settings, physics_backend='python'))
        renderer = OracleRenderer()
        for scale, density, coarse in ((3., 1., False), (4., 2., False), (4., 1., True)):
            with self.subTest(scale=scale, coarse=coarse):
                scene.config = replace(scene.config, coarse_pixels_4x=coarse)
                base = paint(renderer, scene, density, front_only=True)
                large = paint(renderer, scene, scale, front_only=True)
                self.assertEqual(large, base.scaled(large.size()))

    def test_large_head_attachment_stays_inside_damage_bounds(self):
        settings = settings_for('apron', anchor=Anchor.HEAD_CROWN, layer=Slot.FRONT_HEAD,
                                offset_x=32, offset_y=32, mirror=True)
        scene = OracleScene(OracleConfig(outfit='maid', outfit_settings=settings, hide_cords=True,
                                        physics_backend='python'))
        renderer = OracleRenderer()
        paint(renderer, scene)
        # 头部小图包括旋转余量，检查其中实际非透明像素，而非正方形画布的空角
        image, target = renderer._head_image, renderer._head_target
        bounds = body_bounds(scene)
        for y in range(image.height()):
            for x in range(image.width()):
                if image.pixelColor(x, y).alpha():
                    self.assertTrue(bounds.contains(QRectF(target.x()+x, target.y()+y, 1, 1)))


if __name__ == '__main__':
    unittest.main()
