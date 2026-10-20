"""斗篷的独立领口、静态姿态、旋转、图层与缓存"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from dataclasses import replace
import unittest
from unittest.mock import patch

from PySide6.QtCore import QPointF
from PySide6.QtGui import QImage, QPainter, QPainterPathStroker
from PySide6.QtWidgets import QApplication

from rw_creature_pet.oracle.cape_config import Cape
from rw_creature_pet.oracle.graphics.cape import cape_geometry
from rw_creature_pet.oracle.graphics.damage import body_bounds
from rw_creature_pet.oracle.graphics.render import OracleRenderer
from rw_creature_pet.oracle.graphics.outfit_definition import Slot
from rw_creature_pet.oracle.outfit_config import OutfitSettings
from rw_creature_pet.shared.geometry import Vec2
from tools.oracle.review_cape import pose_scene


def geometry(renderer, scene, upper, direction):
    sleeves = tuple(renderer.body_sleeve_edges(scene, 1., upper, direction, i) for i in range(2))
    return cape_geometry(upper, direction, tuple(h.position for h in scene.appearance.hands),
                         sleeves, scene.config.custom_appearance)


def paint(renderer, scene, *, scale=2., cached=True, complete=False):
    image = QImage(round(160*scale), round(160*scale), QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(0)
    painter = QPainter(image)
    renderer.colors = scene.config.active_colors
    try:
        painter.scale(scale, scale)
        painter.translate(80-400, 60-300)
        if complete:
            renderer.draw(painter, scene, cords=False, raster_scale=scale)
        else:
            renderer.draw_geometry(painter, scene, arm=False, cords=False, pearl=False, halo=False,
                                   cache_body=cached, raster_scale=scale)
    finally:
        painter.end()
    return image


class CapeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_validation_and_disabled_bell_are_independent(self):
        for values in ({'enabled': 1}, {'length': float('nan')}, {'length': 49}, {'color': 'red'},
                       {'hem_trim_gap': -1}, {'neckline_shape': 'square'}):
            with self.assertRaises(ValueError):
                Cape(**values)
        scene, _, _ = pose_scene()
        scene.config = replace(scene.config, body_appearance='bell')
        enabled = paint(OracleRenderer(), scene)
        scene.config = replace(scene.config, custom_appearance=replace(scene.config.custom_appearance, cape=Cape()))
        self.assertEqual(enabled, paint(OracleRenderer(), scene))

    def test_six_poses_shorten_and_move_low_point_toward_lower_arm(self):
        shrink = []
        for length in (18., 34.):
            shapes = {}
            for pose in ('rest', 'both', 'single'):
                scene, upper, direction = pose_scene(length, pose)
                g = shapes[pose] = geometry(OracleRenderer(), scene, upper, direction)
                self.assertFalse(g.fill.isEmpty())
                self.assertFalse(g.trim.isEmpty())
                self.assertLess(abs(g.outer.boundingRect().bottom()-g.lowest.y), .01)
                self.assertTrue(body_bounds(scene).contains(g.outer.boundingRect()))
                self.assertTrue(g.trim.subtracted(g.fill).isEmpty())
            self.assertAlmostEqual(shapes['rest'].lowest.x, upper.x)
            self.assertAlmostEqual(shapes['both'].lowest.x, upper.x)
            self.assertLess(shapes['single'].lowest.x, upper.x-2)
            self.assertLess(shapes['both'].lowest.y, shapes['single'].lowest.y)
            self.assertLess(shapes['single'].lowest.y, shapes['rest'].lowest.y)
            shrink.append(shapes['rest'].lowest.y-shapes['both'].lowest.y)
        self.assertGreater(shrink[1], shrink[0])

    def test_neckline_does_not_follow_or_cut_the_gown(self):
        scene, upper, direction = pose_scene(34., neckline_width=18., neckline_depth=10.)
        renderer = OracleRenderer()
        before = geometry(renderer, scene, upper, direction)
        gown_before = renderer.gown_geometry(scene, 1.)[2:]
        shape = scene.config.custom_appearance
        scene.config = replace(scene.config, custom_appearance=replace(shape,
            neckline_shape='arc', neckline_width=2., neckline_height=-2., neckline_depth=15.))
        self.assertEqual(before, geometry(renderer, scene, upper, direction))
        scene.config = replace(scene.config, custom_appearance=replace(shape,
            cape=replace(shape.cape, neckline_shape='v', neckline_width=4., neckline_depth=2.)))
        after = geometry(renderer, scene, upper, direction)
        self.assertNotEqual(before.fill, after.fill)
        self.assertEqual(before.outer, after.outer)
        self.assertEqual(gown_before, renderer.gown_geometry(scene, 1.)[2:])

    def test_inset_trim_meets_both_sides_without_changing_bottom_spacing(self):
        outline = QPainterPathStroker()
        outline.setWidth(.04)
        for length in (18., 34.):
            for pose in ('rest', 'both', 'single'):
                for gap in (.5, 1.5, 4.):
                    for width in (.8, 2.4):
                        with self.subTest(length=length, pose=pose, gap=gap, width=width):
                            scene, upper, direction = pose_scene(length, pose,
                                hem_trim_gap=gap, hem_trim_width=width)
                            g = geometry(OracleRenderer(), scene, upper, direction)
                            # 内缩彩边必须接触左右侧边；不能只靠底弧中段满足非空判断
                            contact = g.trim.intersected(outline.createStroke(g.outer))
                            self.assertFalse(contact.isEmpty())
                            self.assertLess(contact.boundingRect().left(), upper.x-2.)
                            self.assertGreater(contact.boundingRect().right(), upper.x+2.)
                            self.assertTrue(g.trim.subtracted(g.fill).isEmpty())
                            # 对称姿态的最低处法线竖直，可直接检查内缩距离和带宽
                            # 单侧抬手时较陡的侧弧也可能投射到这条竖线上
                            if pose != 'single':
                                x, y = g.lowest.x, g.lowest.y
                                self.assertTrue(g.trim.contains(QPointF(x, y-gap-width/2)))
                                self.assertFalse(g.trim.contains(QPointF(x, y-gap/2)))
                                self.assertFalse(g.trim.contains(QPointF(x, y-gap-width-.3)))

    def test_cached_translation_matches_direct_and_idle_reuses_commands(self):
        scene, upper, direction = pose_scene(34., 'single')
        renderer = OracleRenderer()
        for scale in (1., 1.5, 2.):
            expected = paint(renderer, scene, scale=scale)
            frame = renderer._cape_frame
            self.assertEqual(expected, paint(renderer, scene, scale=scale, cached=False))
            with patch('rw_creature_pet.oracle.graphics.render.draw_cape') as build:
                self.assertEqual(expected, paint(renderer, scene, scale=scale))
                build.assert_not_called()
            for delta in (Vec2(2, 3), Vec2(.17, .23)):
                for p in (*scene.body.chunks, *scene.appearance.body_points):
                    p.position += delta
                    p.previous_position += delta
                scene.appearance.revision += 1
                cached = paint(renderer, scene, scale=scale)
                self.assertIs(frame, renderer._cape_frame)
                self.assertEqual(cached, paint(renderer, scene, scale=scale, cached=False))

    def test_rotated_extremes_and_pixel_scales_keep_bounds_and_glow(self):
        for length in (8., 48.):
            for angle in (0., 60., 180., 270.):
                for pose in ('rest', 'both', 'single'):
                    scene, upper, direction = pose_scene(length, pose, angle)
                    renderer = OracleRenderer()
                    g = geometry(renderer, scene, upper, direction)
                    self.assertTrue(body_bounds(scene).contains(g.outer.boundingRect()))
                    self.assertFalse(g.fill.isEmpty())
        scene, _, _ = pose_scene(34., 'single')
        renderer = OracleRenderer()
        for scale, source, coarse in ((3., 1., False), (4., 2., False), (4., 1., True)):
            scene.config = replace(scene.config, coarse_pixels_4x=coarse)
            small = paint(renderer, scene, scale=source, complete=True)
            large = paint(renderer, scene, scale=scale, complete=True)
            self.assertEqual(large, small.scaled(large.size()))
        scene.config = replace(scene.config, glow_enabled=True)
        glowing = paint(renderer, scene, complete=True)
        self.assertFalse(renderer._body_glow.image.isNull())
        frame = renderer._cape_frame
        self.assertEqual(glowing, paint(renderer, scene, complete=True))
        self.assertIs(frame, renderer._cape_frame)

    def test_cape_is_between_outfit_slots(self):
        scene, _, _ = pose_scene(34.)
        defaults = OutfitSettings()
        parts = {name: replace(getattr(defaults.maid, name), enabled=False)
                 for name in ('head', 'lace', 'apron', 'ribbon_up', 'ribbon_down')}
        parts['ribbon_down'] = replace(defaults.maid.ribbon_down, offset_y=5, brightness=100,
                                       layer=Slot.AFTER_SLEEVES)
        scene.config = replace(scene.config, outfit='maid', outfit_settings=replace(
            defaults, maid=replace(defaults.maid, **parts)))
        under = paint(OracleRenderer(), scene)
        parts['ribbon_down'] = replace(parts['ribbon_down'], layer=Slot.AFTER_CAPE)
        scene.config = replace(scene.config, outfit_settings=replace(defaults, maid=replace(defaults.maid, **parts)))
        above = paint(OracleRenderer(), scene)
        self.assertNotEqual(under, above)
        parts['ribbon_down'] = replace(parts['ribbon_down'], enabled=False)
        scene.config = replace(scene.config, outfit_settings=replace(defaults, maid=replace(defaults.maid, **parts)))
        self.assertEqual(under, paint(OracleRenderer(), scene))


if __name__ == '__main__':
    unittest.main()
