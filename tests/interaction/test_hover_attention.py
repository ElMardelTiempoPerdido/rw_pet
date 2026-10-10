import unittest
from dataclasses import replace
from unittest.mock import patch

from rw_creature_pet.interaction.config import InteractionConfig
from rw_creature_pet.interaction.hover_attention import HoverAttention
from rw_creature_pet.shared.geometry import Vec2


class HoverAttentionTests(unittest.TestCase):
    def test_continuous_dwell_tracks_moving_pointer_then_requires_new_entry(self):
        attention = HoverAttention(160, 1., 1., 1.)
        origin = Vec2(40, 50)
        for i in range(39):
            attention.step(.025, origin+Vec2(i, 5), origin)
            self.assertFalse(attention.active)
        self.assertTrue(attention.step(.025, origin+Vec2(40, 5), origin))
        self.assertTrue(attention.opened)
        rng = attention.random.getstate()
        for i in range(200):
            point = origin+Vec2(i % 100, 15)
            attention.step(.025, point, origin)
            self.assertEqual(attention.target, point)
        self.assertEqual(attention.random.getstate(), rng)
        attention.step(.025, origin+Vec2(161, 0), origin)
        self.assertFalse(attention.active)
        attention.step(.9, origin, origin)
        self.assertFalse(attention.active)
        self.assertTrue(attention.step(.1, origin, origin))

    def test_failed_roll_stays_failed_until_exit_and_no_partial_dwell_is_carried(self):
        attention = HoverAttention(100, 1., .5, .25)
        with patch.object(attention.random, 'random', side_effect=[.9, .1, .9]) as random:
            attention.step(.8, Vec2(), Vec2())
            attention.step(.1, None, Vec2())
            attention.step(.8, Vec2(), Vec2())
            random.assert_not_called()
            attention.step(.2, Vec2(), Vec2())
            for _ in range(500):
                attention.step(.1, Vec2(), Vec2())
            self.assertEqual(random.call_count, 1)
            self.assertFalse(attention.active)
            attention.step(.1, Vec2(200, 0), Vec2())
            self.assertTrue(attention.step(1., Vec2(), Vec2()))
            self.assertFalse(attention.opened)
            self.assertEqual(random.call_count, 3)

    def test_cancel_disable_zero_chance_and_radius_follow_creature(self):
        attention = HoverAttention(50, .5, 1., 1.)
        attention.step(.4, Vec2(50, 0), Vec2())
        attention.step(.2, Vec2(50, 0), Vec2(-5, 0))
        self.assertEqual(attention.elapsed, 0.)
        attention.step(.5, Vec2(50, 0), Vec2(10, 0))
        self.assertTrue(attention.active)
        attention.step(.1, Vec2(50, 0), Vec2(10, 0), enabled=False)
        self.assertFalse(attention.active)
        attention.probability = 0
        rng = attention.random.getstate()
        for _ in range(100):
            attention.step(1., Vec2(), Vec2())
        self.assertFalse(attention.attempted)
        self.assertEqual(attention.random.getstate(), rng)

    def test_configuration_rejects_invalid_values_and_accepts_endpoints(self):
        config = InteractionConfig()
        for value in (0, 1, 'true', None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                replace(config, hover_avoidance_enabled=value)
        replace(config, hover_avoidance_enabled=False)
        for name, bad_values in (
            ('hover_radius', (0, -1, 2001)), ('hover_dwell_seconds', (-1, 61)),
            ('hover_probability', (-.01, 1.01)), ('hover_open_probability', (-.01, 1.01))):
            for value in (*bad_values, True, '1', None, float('nan'), float('inf')):
                with self.subTest(name=name, value=value), self.assertRaises(ValueError):
                    replace(config, **{name: value})
        replace(config, hover_radius=1, hover_dwell_seconds=0, hover_probability=0, hover_open_probability=1)


if __name__ == '__main__':
    unittest.main()
