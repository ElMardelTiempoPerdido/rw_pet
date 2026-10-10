"""观察光束的投影、范围、退出和缓存，不修改用户外观参数"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'

from dataclasses import replace
from math import cos, pi, sin
import unittest
from unittest.mock import patch

import numpy as np
from PySide6.QtGui import QImage, QPainter

from rw_creature_pet.overseer.config import OverseerConfig
from rw_creature_pet.overseer.friend_light import draw_light, light_extent, light_images
from rw_creature_pet.overseer.lens import ObservationLens
from rw_creature_pet.overseer.model import Anchor, Edge, Overseer
from rw_creature_pet.overseer.render import OverseerRenderer
from rw_creature_pet.shared.geometry import Bounds, Vec2


class FriendLightTests(unittest.TestCase):
    def make_model(self, edge=Edge.BOTTOM):
        model = Overseer(Bounds(0, 0, 300, 300), OverseerConfig(observation_probability=0), seed=73)
        model.set_appearance('friend')
        model.show(anchor=Anchor(edge, .5))
        for _ in range(100):
            model.step(model.root+model.normal*180)
        model.lens.up = model.lens.previous_up = 1.
        return model

    def paint(self, model, gaze=Vec2(.9, 0), depth=.43589, density=2):
        side = round(120*density)
        image = QImage(side, side, QImage.Format.Format_RGBA8888)
        image.fill(0)
        p = QPainter(image)
        try:
            p.scale(density, density)
            with patch.object(model, 'eye_position', return_value=Vec2(60, 60)), \
                    patch.object(model, 'head_gaze', return_value=(gaze, depth)):
                draw_light(p, model, 1., density)
        finally:
            p.end()
        return np.frombuffer(image.constBits(), dtype=np.uint8).reshape(side, side, 4).copy()

    def test_closed_light_does_not_allocate_images_or_leave_pixels(self):
        model = self.make_model()
        model.lens.up = model.lens.previous_up = 0.
        light_images.cache_clear()
        self.assertFalse(self.paint(model).any())
        self.assertEqual(light_images.cache_info().misses, 0)

    def test_front_view_is_local_and_side_view_projects_forward_in_all_directions(self):
        model = self.make_model()
        front = self.paint(model, Vec2(), 1.)[:, :, 3]
        yy, xx = np.indices(front.shape)
        radius = np.hypot((xx+.5)/2-60, (yy+.5)/2-60)
        self.assertFalse(front[radius > 13].any())
        self.assertGreater(front.sum(), 0)
        for direction in (Vec2(1, 0), Vec2(-1, 0), Vec2(0, 1), Vec2(0, -1)):
            alpha = self.paint(model, direction, 0.)[:, :, 3]
            forward = ((xx+.5)/2-60)*direction.x+((yy+.5)/2-60)*direction.y
            self.assertGreater(alpha[forward > 13].sum(), 0)
            self.assertFalse(alpha[forward < -13].any())
            self.assertFalse(alpha[radius > light_extent()].any())

    def test_fade_and_withdraw_are_continuous_and_do_not_mutate_state(self):
        model = self.make_model()
        before = model.revision, model.random.getstate(), model.lens.random.getstate()
        intensities = []
        for opening in (0., .1, .3, .7, 1.):
            model.lens.up = model.lens.previous_up = opening
            intensities.append(self.paint(model)[:, :, 3].sum())
        self.assertTrue(all(b > a for a, b in zip(intensities, intensities[1:])))
        self.assertEqual(before, (model.revision, model.random.getstate(), model.lens.random.getstate()))
        model.extended = model.last_extended = 0.
        self.assertFalse(self.paint(model).any())

    def test_direction_changes_reuse_texture_cache_and_front_crossing_is_continuous(self):
        model = self.make_model()
        light_images.cache_clear()
        for i in range(24):
            self.paint(model, Vec2(.8*cos(i*pi/12), .8*sin(i*pi/12)), .6)
        info = light_images.cache_info()
        self.assertEqual(info.misses, 1)
        self.assertEqual(info.currsize, 1)
        self.assertEqual(info.hits, 23)
        np.testing.assert_array_equal(self.paint(model, Vec2(-1e-7, 0), 1.),
                                      self.paint(model, Vec2(1e-7, 0), 1.))

    def test_observation_schedule_is_shared_but_unused_hologram_animation_is_skipped(self):
        config = replace(OverseerConfig(), observation_probability=1., observation_interval=.1)
        normal, friend = ObservationLens(config, 42), ObservationLens(config, 42)
        untouched = friend.visual_random.getstate(), friend.flicker_random.getstate()
        for tick in range(650):
            eligible = tick < 500
            normal.step(eligible=eligible, visible=True, tick_rate=40)
            friend.step(eligible=eligible, visible=True, tick_rate=40, animate_hologram=False)
            self.assertEqual((normal.up, normal.remaining, normal.check_count, normal.random.getstate()),
                             (friend.up, friend.remaining, friend.check_count, friend.random.getstate()))
        self.assertGreater(friend.observation_count, 0)
        self.assertEqual(friend.up, 0.)
        self.assertEqual(friend.effect_tick, 0)
        self.assertEqual(untouched, (friend.visual_random.getstate(), friend.flicker_random.getstate()))

    def test_four_edges_scaled_render_stays_clipped_cached_and_switches_back(self):
        for edge in Edge:
            model = self.make_model(edge)
            for density in (1., 1.5, 2.):
                renderer = OverseerRenderer()
                side = round(320*density)
                image = QImage(side, side, QImage.Format.Format_RGBA8888)
                image.fill(0)
                p = QPainter(image)
                try:
                    p.scale(density, density)
                    renderer.draw(p, model, pixel_mode='adaptive', raster_scale=density)
                    cached = renderer.image
                    renderer.draw(p, model, pixel_mode='adaptive', raster_scale=density)
                    self.assertIs(cached, renderer.image)
                    # 跟随用户可调光束长度和光点余量，不固定旧版 34 像素光束的面积
                    self.assertLess(renderer.target.width()*renderer.target.height(),
                                    (2*light_extent()+26)**2)
                finally:
                    p.end()
                pixels = np.frombuffer(image.constBits(), dtype=np.uint8).reshape(side, side, 4)
                self.assertTrue(pixels.any())
                self.assertFalse(pixels[round(300*density):].any())
                self.assertFalse(pixels[:, round(300*density):].any())
            model.set_appearance('standard')
            with patch.object(renderer, '_lens') as lens:
                p = QPainter(image)
                try:
                    renderer.draw(p, model)
                finally:
                    p.end()
            lens.assert_called_once()


if __name__ == '__main__':
    unittest.main()
