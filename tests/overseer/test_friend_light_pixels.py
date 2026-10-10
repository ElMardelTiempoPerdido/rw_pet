"""像素光的生命周期、独立随机状态、投影边界和逻辑像素缩放"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'

import copy
from dataclasses import replace
import unittest
from unittest.mock import patch

import numpy as np
from PySide6.QtGui import QImage, QPainter

from rw_creature_pet.overseer.config import OverseerConfig
from rw_creature_pet.overseer.friend_light import draw_pixels, light_extent
from rw_creature_pet.overseer.friend_light_pixels import FriendLightPixels, SPARK_COUNT, Spark
from rw_creature_pet.overseer.hologram import LensHologramRenderer
from rw_creature_pet.overseer.model import Anchor, Edge, Overseer
from rw_creature_pet.overseer.render import OverseerRenderer
from rw_creature_pet.shared.geometry import Bounds, Vec2


class FriendPixelLightTests(unittest.TestCase):
    def model(self, edge=Edge.BOTTOM):
        model = Overseer(Bounds(0, 0, 300, 300), replace(OverseerConfig(),
            observation_probability=1., observation_interval=.1), seed=17)
        model.set_appearance('friend')
        model.show(anchor=Anchor(edge, .5))
        for _ in range(95):
            model.step(model.root+model.normal*250)
        return model

    def paint(self, model, density=1):
        image = QImage(180*density, 180*density, QImage.Format.Format_RGBA8888)
        image.fill(0)
        painter = QPainter(image)
        try:
            painter.scale(density, density)
            with patch.object(model, 'eye_position', return_value=Vec2(90, 90)), \
                    patch.object(model, 'head_gaze', return_value=(Vec2(.8, .3), .3)):
                draw_pixels(painter, model, 1., LensHologramRenderer())
        finally:
            painter.end()
        return np.frombuffer(image.constBits(), np.uint8).reshape(180*density, 180*density, 4).copy()

    def test_four_frames_advance_once_then_respawn_elsewhere_with_bounded_count(self):
        state = FriendLightPixels(7)
        seen, positions, lifetimes = {}, set(), set()
        for _ in range(400):
            state.step(opening=1., visible=True, emitting=True, tick_rate=40)
            self.assertLessEqual(sum(s is not None for s in state.sparks), SPARK_COUNT)
            for spark in state.sparks:
                if spark is not None:
                    positions.add(spark.position)
                    lifetimes.add(spark.lifetime)
                    seen.setdefault(spark.position, set()).add(spark.frame(1.))
        self.assertGreater(len(positions), SPARK_COUNT*3)
        self.assertGreater(len(lifetimes), 4)
        self.assertGreater(sum(frames == {0, 1, 2, 3} for frames in seen.values()), 4)
        state.step(opening=0., visible=True, emitting=False, tick_rate=40)
        self.assertFalse(state.active)
        self.assertFalse(any(state.sparks))
        rng = state.random.getstate()
        for _ in range(100):
            state.step(opening=0., visible=True, emitting=False, tick_rate=40)
        self.assertEqual(rng, state.random.getstate())

    def test_drawing_does_not_advance_animation_or_rng_and_is_one_logical_pixel(self):
        model = self.model()
        state = model.friend_light_pixels
        snapshot = copy.deepcopy(state.__dict__)
        rng = state.random.getstate()
        one = self.paint(model)
        self.assertTrue(one.any())
        np.testing.assert_array_equal(one, self.paint(model))
        np.testing.assert_array_equal(np.repeat(np.repeat(one, 2, axis=0), 2, axis=1), self.paint(model, 2))
        self.assertEqual(rng, state.random.getstate())
        self.assertEqual(snapshot['sparks'], state.sparks)
        self.assertEqual(snapshot['tick'], state.tick)
        self.assertEqual(snapshot['rotation'], state.rotation)
        self.assertEqual(snapshot['signal'], state.signal)
        self.assertEqual(snapshot['noise_random'].getstate(), state.noise_random.getstate())
        model.lens.up = model.lens.previous_up = 0.
        self.assertFalse(self.paint(model).any())
        model.lens.up = model.lens.previous_up = 1.
        model.extended = model.last_extended = 0.
        self.assertFalse(self.paint(model).any())

    def test_light_randomness_cannot_change_observation_or_body_sequence(self):
        a, b = self.model(), self.model()
        with patch.object(b.friend_light_pixels, 'step'):
            for _ in range(400):
                target = a.root+a.normal*250
                a.step(target)
                b.step(target)
                self.assertEqual(a.head.position, b.head.position)
                self.assertEqual((a.lens.up, a.lens.remaining, a.lens.observation_count),
                                 (b.lens.up, b.lens.remaining, b.lens.observation_count))
        self.assertEqual(a.random.getstate(), b.random.getstate())
        self.assertEqual(a.lens.random.getstate(), b.lens.random.getstate())

    def test_full_open_signal_adds_local_gaps_without_dimming_or_changing_spark_rng(self):
        model = self.model()
        model.lens.up = model.lens.previous_up = 1.
        state = model.friend_light_pixels
        state.sparks = [None]*SPARK_COUNT
        state.line_show = (0.,)*5
        with patch('rw_creature_pet.overseer.friend_light_pixels.RAY_SIGNAL_RANGE', (1., 1.)):
            before = self.paint(model)[:, :, 3]
        after = self.paint(model)[:, :, 3]
        self.assertLess(np.count_nonzero(after), np.count_nonzero(before))
        self.assertTrue(np.all(after <= before))
        np.testing.assert_array_equal(after[after > 0], before[after > 0])
        a, b = FriendLightPixels(91), FriendLightPixels(91)
        signals = set()
        with patch.object(b, 'signal'):
            for _ in range(160):
                for item in (a, b):
                    item.step(opening=1., visible=True, emitting=True, tick_rate=40)
                signals.add(round(a.signal_strength(1.)*32))
        self.assertGreater(len(signals), 1)
        self.assertEqual(a.sparks, b.sparks)
        self.assertEqual(a.rotation, b.rotation)
        self.assertEqual(a.random.getstate(), b.random.getstate())
        a.step(opening=0., visible=False, emitting=False, tick_rate=40)
        rng = a.noise_random.getstate()
        for _ in range(40):
            a.step(opening=0., visible=False, emitting=False, tick_rate=40)
        self.assertEqual(rng, a.noise_random.getstate())

    def test_reset_switch_and_hidden_state_clear_sparks_without_spawning_on_close(self):
        model = self.model()
        self.assertTrue(model.friend_light_pixels.active)
        state = model.friend_light_pixels
        state.sparks = [None]*SPARK_COUNT
        state.waits = [0.]*SPARK_COUNT
        state.step(opening=.5, visible=True, emitting=False, tick_rate=40)
        self.assertFalse(any(state.sparks))
        model.clear()
        self.assertFalse(state.active)
        model.show()
        self.assertFalse(state.active)
        state.sparks[0] = Spark((0., 0., .5), 1.)
        model.place(Bounds(0, 0, 500, 400), Anchor(Edge.TOP, .5))
        self.assertFalse(any(state.sparks))
        model.set_appearance('standard')
        self.assertIsNone(model.friend_light_pixels)
        model.set_appearance('friend')
        self.assertFalse(model.friend_light_pixels.active)

    def test_rotating_cone_and_sparks_fit_extent_at_all_four_edges(self):
        from rw_creature_pet.overseer.friend_head import view_matrix
        from rw_creature_pet.overseer.friend_light import (
            BEAM_LENGTH, BEAM_ROOT_RADIUS, RAY_HALF_ANGLE, SPARK_HALF_ANGLE)
        for edge in Edge:
            model = self.model(edge)
            state = model.friend_light_pixels
            head = model.eye_position()
            matrix = view_matrix(*model.head_gaze(), head-model.root)
            original = None
            for _ in range(80):
                state.step(opening=1., visible=True, emitting=True, tick_rate=40)
                lines, sparks = state.project(head, matrix, 1., BEAM_LENGTH, BEAM_ROOT_RADIUS, 1.,
                                              ray_half_angle=RAY_HALF_ANGLE,
                                              spark_half_angle=SPARK_HALF_ANGLE)
                self.assertEqual(len(lines), 5)
                for start, end, _ in lines:
                    self.assertLess((start-head).length(), light_extent())
                    self.assertLess((end-head).length(), light_extent())
                for position, _ in sparks:
                    self.assertLess((position-head).length()+3, light_extent())
                if original is None:
                    original = lines
            self.assertNotEqual(lines, original)
            # 真正局部绘制仍受工作区裁剪，不把像素光投到屏幕外
            image = QImage(320, 320, QImage.Format.Format_RGBA8888)
            image.fill(0)
            painter = QPainter(image)
            try:
                OverseerRenderer().draw(painter, model)
            finally:
                painter.end()
            pixels = np.frombuffer(image.constBits(), np.uint8).reshape(320, 320, 4)
            self.assertFalse(pixels[300:].any())
            self.assertFalse(pixels[:, 300:].any())


if __name__ == '__main__':
    unittest.main()
