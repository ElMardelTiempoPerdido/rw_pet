"""套装定义替换、多部件缓存以及局部平移必须走相同的公共绘制入口"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from dataclasses import FrozenInstanceError, replace
import unittest
from unittest.mock import patch

from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication

from rw_creature_pet.oracle.config import OracleConfig
from rw_creature_pet.oracle.graphics.outfit_definition import BUILTIN_OUTFITS, MAID, Slot
from rw_creature_pet.oracle.graphics.render import OracleRenderer
from rw_creature_pet.oracle.interaction.input import PuppetHitMap
from rw_creature_pet.oracle.scene import OracleScene
from rw_creature_pet.shared.geometry import Vec2


class OutfitDefinitionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def paint(self, renderer, scene, scale=1., *, cached=True, complete=True):
        image = QImage(round(960*scale), round(600*scale), QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(0)
        painter = QPainter(image)
        try:
            painter.scale(scale, scale)
            if complete:
                renderer.draw(painter, scene, cords=False, raster_scale=scale)
            else:
                renderer.draw_geometry(painter, scene, arm=False, cords=False, pearl=False, halo=False,
                                       cache_body=cached, raster_scale=scale)
        finally:
            painter.end()
        return image

    def test_names_are_not_rendering_rules(self):
        scene = OracleScene(OracleConfig(outfit='maid', hide_cords=True, halo_enabled=False, glow_enabled=True))
        renamed = replace(MAID, id='different-outfit',
                          components=tuple(replace(part, id=f'part-{i}') for i, part in enumerate(MAID.components)))
        renderer = OracleRenderer()
        for scale in (1., 1.5, 2.):
            expected = self.paint(renderer, scene, scale)
            geometry = renderer._body_frame
            with patch.dict(BUILTIN_OUTFITS, maid=renamed):
                self.assertEqual(self.paint(renderer, scene, scale), expected)
                self.assertIs(renderer._body_frame, geometry)

    def test_definition_change_invalidates_head_frame_and_hit_map(self):
        scene = OracleScene(OracleConfig(outfit='maid', hide_cords=True, halo_enabled=False))
        renderer, hit = OracleRenderer(), PuppetHitMap()
        image = self.paint(renderer, scene)
        first_hit = hit.get(renderer, scene)
        body, head, frame = renderer._body_frame, renderer._head_image, renderer._frame
        no_head = replace(MAID, components=tuple(p for p in MAID.components
                                                if p.slot not in (Slot.FRONT_HEAD, Slot.BEHIND_HEAD)))
        with patch.dict(BUILTIN_OUTFITS, maid=no_head):
            self.assertNotEqual(self.paint(renderer, scene), image)
            self.assertIs(renderer._body_frame, body)
            self.assertIsNot(renderer._head_image, head)
            self.assertIsNot(renderer._frame, frame)
            self.assertIsNot(hit.get(renderer, scene), first_hit)
        self.assertEqual(self.paint(renderer, scene), image)

    def test_multiple_front_parts_keep_independent_images_and_glow(self):
        scene = OracleScene(OracleConfig(outfit='maid', hide_cords=True, halo_enabled=False, glow_enabled=True))
        ribbon = MAID.component('ribbon_down')
        variants = tuple(replace(v, offset=(6*v.density, v.offset[1])) for v in ribbon.variants)
        extra = replace(ribbon, id='extra', mirror=True, variants=variants)
        definition = replace(MAID, components=MAID.components+(extra,))
        renderer = OracleRenderer()
        with patch.dict(BUILTIN_OUTFITS, maid=definition):
            first = self.paint(renderer, scene)
            sprites = renderer._front_outfit_layers
            images = tuple(sprite.image for sprite in sprites)
            glows = tuple(sprite.glow.image for sprite in sprites)
            self.assertEqual(len(sprites), 3)
            self.assertEqual(len({sprite.target.x() for sprite in sprites}), 3)
            self.assertEqual(self.paint(renderer, scene), first)
            for sprite, image, glow in zip(renderer._front_outfit_layers, images, glows):
                self.assertIs(sprite.image, image)
                self.assertIs(sprite.glow.image, glow)
        self.paint(renderer, scene)
        self.assertEqual(len(renderer._front_outfit_layers), 1)
        self.assertNotIn(('extra', 0), renderer._outfit_sprites)
        scene.config = replace(scene.config, outfit='normal')
        self.paint(renderer, scene)
        self.assertEqual(renderer._front_outfit_layers, ())
        self.assertEqual(renderer._outfit_sprites, {})

    def test_cached_maid_translation_matches_direct_layers(self):
        scene = OracleScene(OracleConfig(outfit='maid', hide_cords=True, halo_enabled=False))
        renderer = OracleRenderer()
        for scale in (1., 1.5, 2.):
            self.paint(renderer, scene, scale, complete=False)
            frame = renderer._body_frame
            for offset in (Vec2(2., 3.), Vec2(.137, .293)):
                for part in (*scene.body.chunks, *scene.appearance.body_points):
                    part.position += offset
                    part.previous_position += offset
                scene.appearance.revision += 1
                cached = self.paint(renderer, scene, scale, complete=False)
                self.assertIs(renderer._body_frame, frame)
                direct = self.paint(renderer, scene, scale, complete=False, cached=False)
                self.assertEqual(cached, direct, (scale, offset))

    def test_invalid_and_mutable_definitions_are_rejected(self):
        with self.assertRaises(FrozenInstanceError):
            MAID.id = 'changed'
        with self.assertRaises(ValueError):
            replace(MAID, components=(MAID.components[0], MAID.components[0]))
        with self.assertRaises(ValueError):
            replace(MAID.components[0], slot=Slot.AFTER_SLEEVES)
        with self.assertRaises(ValueError):
            replace(MAID.components[0], variants=())


if __name__ == '__main__':
    unittest.main()
