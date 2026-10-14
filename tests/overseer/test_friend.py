import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'

from dataclasses import replace
import unittest
from unittest.mock import patch

from PySide6.QtGui import QColor, QImage, QPainter

from rw_creature_pet.overseer.config import OverseerConfig, OverseerSlot
from rw_creature_pet.overseer.graphics.friend.body import ROOT_COLOR, PEAK_FRACTION, NECK_FRACTION, body_centers, body_color, body_radius
from rw_creature_pet.overseer.group import OverseerGroup
from rw_creature_pet.overseer.model import Anchor, Edge
from rw_creature_pet.overseer.graphics.render import OverseerRenderer
from rw_creature_pet.shared.geometry import Bounds, Vec2


class FriendTests(unittest.TestCase):
    def setUp(self):
        cfg = OverseerConfig(observation_probability=0, slots=(OverseerSlot(appearance='friend'),))
        self.group = OverseerGroup(cfg, Bounds(0, 0, 300, 300), seed=73)
        self.model = self.group.entries[1].model
        self.renderer = OverseerRenderer()

    def render(self, density=1):
        image = QImage(round(320*density), round(320*density), QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(0)
        p = QPainter(image)
        try:
            p.scale(density, density)
            self.renderer.draw(p, self.model, pixel_mode='adaptive', raster_scale=density)
        finally:
            p.end()
        return image

    def test_body_tapers_both_ends_and_root_color_does_not_follow_main_color(self):
        for size in (.5, .6, 1):
            widths = [body_radius(i/100, size) for i in range(101)]
            self.assertEqual(widths.index(max(widths)), round(PEAK_FRACTION*100))
            self.assertLess(widths[0], max(widths)*.5)
            self.assertLess(widths[-1], max(widths)*.5)
            self.assertLess(widths[35], (widths[0]+max(widths))*.5)
            self.assertLess(widths[round(NECK_FRACTION*100)], max(widths)*.5)
        for color in ('#000000', '#e97154', '#4baa97'):
            self.assertEqual(body_color(0, color).name(), ROOT_COLOR)
            self.assertEqual(body_color(1, color).name(), color)
            self.assertNotEqual(body_color(.3, color).name(), color)

    def test_added_neck_disc_and_lens_share_anchor_and_fit_local_bounds(self):
        for edge in Edge:
            self.model.show(anchor=Anchor(edge, .5))
            for _ in range(100):
                self.model.step(Vec2(150, 150))
            for target in (Vec2(150, 150), self.model.head.position,
                           self.model.root+self.model.tangent*300):
                self.model.look_at = self.model.previous_look = target
                for extension in (.01, .2, .5, 1.):
                    self.model.extended = self.model.last_extended = extension
                    centers = body_centers(self.model, 1.)
                    head = self.model.eye_position()
                    self.assertEqual(centers[-1], head)
                    self.assertLessEqual((head-self.model.stem(1.)).length(),
                                         self.model.head_extra_extent*extension+1e-8)
                    if extension == 1:
                        self.assertGreater((head-self.model.stem(1.)).length(), 1.)
                    self.model.lens.up = self.model.lens.previous_up = 1.
                    bounds = self.model.visual_bounds()
                    for point in centers:
                        self.assertTrue(bounds.contains(point))
                    self.assertTrue(bounds.contains(head+Vec2(5, 5)))
                    self.assertTrue(bounds.contains(head-Vec2(5, 5)))
                    gaze, _ = self.model.gaze()
                    for a, b, _ in self.model.lens.segments(head, gaze, extension, self.model.config.size):
                        self.assertTrue(bounds.contains(a))
                        self.assertTrue(bounds.contains(b))

    def test_recolor_preserves_pale_disc_and_pose_but_reaches_flower_and_filaments(self):
        self.model.show(anchor=Anchor(Edge.BOTTOM, .5))
        for _ in range(100):
            self.model.step(Vec2(170, 170))
        head = self.model.eye_position()
        with patch.object(self.renderer, 'sprite') as sprites, \
                patch.object(self.renderer, '_filaments', wraps=self.renderer._filaments) as filaments:
            image = self.render()
            sprites.assert_not_called()
            filaments.assert_called_once()
            self.assertEqual(filaments.call_args.args[3], (0, 1))
        self.assertEqual(image.pixelColor(round(head.x), round(head.y)), QColor('#E4E1CF'))
        before = self.model.root, self.model.head.position, self.model.extended
        self.model.set_color('#aa3322')
        from rw_creature_pet.overseer.graphics.friend import head as friend_head
        from rw_creature_pet.overseer.graphics import render
        with patch.object(friend_head, 'head_image', wraps=friend_head.head_image) as flower, \
                patch.object(render, 'friend_filament_colors', wraps=render.friend_filament_colors) as colors:
            changed = self.render()
        self.assertEqual(flower.call_args.args[-1], '#aa3322')
        colors.assert_called_once_with('#aa3322')
        self.assertNotEqual(image, changed)
        self.assertEqual(changed.pixelColor(round(head.x), round(head.y)), QColor('#E4E1CF'))
        self.assertEqual(before, (self.model.root, self.model.head.position, self.model.extended))
        self.assertEqual(changed, self.render())

    def test_filament_hue_preserves_light_dark_pair_and_achromatic_defaults(self):
        from rw_creature_pet.overseer.graphics.render import friend_filament_colors
        from rw_creature_pet.overseer.graphics.friend.filaments import COLORS
        defaults = tuple(QColor(c) for c in COLORS)
        for selected in ('#f06080', '#408060', '#437ad0', '#806020'):
            short, long = colors = friend_filament_colors(selected)
            self.assertGreater(short.lightnessF(), long.lightnessF())
            for original, tinted in zip(defaults, colors):
                self.assertAlmostEqual(tinted.hslHueF(), QColor(selected).hslHueF(), places=4)
                self.assertAlmostEqual(tinted.hslSaturationF(), original.hslSaturationF(), places=4)
                self.assertAlmostEqual(tinted.lightnessF(), original.lightnessF(), places=4)
            self.assertIs(colors, friend_filament_colors(selected))
        for selected in ('#000000', '#888888', '#ffffff'):
            self.assertEqual(friend_filament_colors(selected), defaults)

    def test_flower_and_observation_light_share_head_gaze_without_hologram(self):
        self.model.show(anchor=Anchor(Edge.BOTTOM, .5))
        for _ in range(100):
            self.model.step(Vec2(170, 170))
        self.model.lens.up = self.model.lens.previous_up = 1.
        from rw_creature_pet.overseer.graphics.friend import head as friend_head
        with patch.object(friend_head, 'head_image', wraps=friend_head.head_image) as flower, \
                patch.object(friend_head, 'view_matrix', wraps=friend_head.view_matrix) as matrices, \
                patch.object(self.renderer, '_lens') as lens:
            self.render()
        gaze, depth = self.model.head_gaze()
        self.assertEqual(flower.call_args.args[:2], (gaze, depth))
        self.assertGreaterEqual(matrices.call_count, 2)
        self.assertTrue(all(call.args[:2] == (gaze, depth) for call in matrices.call_args_list))
        lens.assert_not_called()

    def test_four_edges_scaling_withdraw_and_switch_back_to_standard(self):
        for edge in Edge:
            self.model.show(anchor=Anchor(edge, .5))
            for _ in range(100):
                self.model.step(Vec2(150, 150))
            for density in (1, 1.5, 2):
                image = self.render(density)
                self.assertTrue(any(bytes(image.constBits())))
                for rect in ((300, 0, 20, 320), (0, 300, 320, 20)):
                    outside = image.copy(*(round(v*density) for v in rect))
                    self.assertFalse(any(bytes(outside.constBits())))
            self.model.request_withdraw()
            for _ in range(120):
                self.model.step()
            hidden = self.render()
            self.assertFalse(any(bytes(hidden.constBits())))
        self.group.configure(replace(self.group.config, slots=(OverseerSlot(),)))
        self.assertEqual(self.model.appearance, 'standard')
        self.model.show()
        for _ in range(100):
            self.model.step(Vec2(150, 150))
        with patch.object(self.renderer, 'sprite', wraps=self.renderer.sprite) as sprites:
            self.render()
            self.assertTrue(sprites.called)


if __name__ == '__main__':
    unittest.main()
