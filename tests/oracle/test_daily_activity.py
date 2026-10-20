"""日常活动配置的边界、旧节奏兼容性及真实行为入口"""
from dataclasses import fields, replace
from random import Random
import unittest
from unittest.mock import patch

from rw_creature_pet.oracle.behavior.controller import Activity, OracleBehavior
from rw_creature_pet.oracle.behavior_config import DailyActivityConfig, ReadingConfig
from rw_creature_pet.oracle.config import OracleConfig
from rw_creature_pet.oracle.scene import OracleScene
from rw_creature_pet.shared.geometry import Vec2


class DailyActivityTests(unittest.TestCase):
    def scene(self, **settings):
        return OracleScene(OracleConfig(**settings))

    def test_rejects_non_finite_values_wrong_types_and_inverted_ranges(self):
        for config in (DailyActivityConfig, ReadingConfig):
            for field in fields(config):
                for value in (True, '1', None, float('nan'), float('inf'), -.01):
                    with self.subTest(config=config, field=field.name, value=value):
                        with self.assertRaises(ValueError):
                            config(**{field.name: value})
        for kwargs in ({'idle_min_seconds': 7}, {'long_idle_min_seconds': 19},
                       {'move_min_distance': 161}, {'meditate_min_seconds': 61},
                       {'idle_weight': 0, 'move_weight': 0, 'meditate_weight': 0},
                       {'cross_edge_check_seconds': 0}, {'move_min_distance': 29},
                       {'move_lean_degrees': 26}, {'idle_max_seconds': 3601}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                DailyActivityConfig(**kwargs)
        with self.assertRaises(ValueError):
            ReadingConfig(start_probability=1.01)
        for field in ('reading', 'daily_activity'):
            with self.assertRaises(ValueError):
                OracleConfig(**{field: {}})

    def test_default_decisions_preserve_previous_random_stream_and_distribution(self):
        scene = self.scene()
        behavior = scene.behavior
        prior = Random()
        prior.setstate(behavior.random.getstate())
        for _ in range(10000):
            value = prior.random()
            if value < .05:
                expected = Activity.CROSS_EDGE
            else:
                value = (value-.05)/.95
                if value < .08:
                    expected = Activity.DRIFT
                else:
                    value = (value-.08)/.92
                    expected = (Activity.MEDITATE if value < .12 else Activity.IDLE if value < .40
                                else Activity.ROAM if value < .75 else Activity.NOTICE)
            self.assertEqual(behavior.choose_activity(scene), expected)
        self.assertEqual(behavior.random.getstate(), prior.getstate())

    def test_reading_and_relative_weights_are_independent(self):
        daily = DailyActivityConfig(idle_weight=1, move_weight=2, meditate_weight=1)
        scene = self.scene(daily_activity=daily, reading=ReadingConfig(.2),
                           cross_edge_probability=0, antigravity_probability=0)
        for draw, expected in ((.19, Activity.MEDITATE), (.21, Activity.IDLE),
                               (.41, Activity.ROAM), (.79, Activity.ROAM), (.81, Activity.NOTICE)):
            with patch.object(scene.behavior.random, 'random', return_value=draw):
                self.assertEqual(scene.behavior.choose_activity(scene), expected)
        scene.behavior.movement_enabled = False
        with patch.object(scene.behavior.random, 'random', return_value=.6):
            self.assertEqual(scene.behavior.choose_activity(scene), Activity.IDLE)
        with patch.object(scene.behavior.random, 'random', return_value=.9):
            self.assertEqual(scene.behavior.choose_activity(scene), Activity.NOTICE)
        for name, activity in (('idle_weight', Activity.IDLE), ('move_weight', Activity.ROAM),
                               ('meditate_weight', Activity.MEDITATE)):
            weights = dict(idle_weight=0, move_weight=0, meditate_weight=0)
            weights[name] = 10
            scene = self.scene(daily_activity=DailyActivityConfig(**weights), reading=ReadingConfig(0),
                               cross_edge_probability=0, antigravity_probability=0)
            self.assertEqual({scene.behavior.choose_activity(scene) for _ in range(100)}, {activity})
        scene.config = replace(scene.config, reading=ReadingConfig(1))
        self.assertEqual({scene.behavior.choose_activity(scene) for _ in range(100)}, {Activity.NOTICE})

    def test_duration_ranges_reach_initial_idle_resume_long_idle_and_meditation(self):
        scene = self.scene(daily_activity=DailyActivityConfig(
            idle_min_seconds=.5, idle_max_seconds=.5, long_idle_min_seconds=1.25,
            long_idle_max_seconds=1.25, meditate_min_seconds=2.5, meditate_max_seconds=2.5))
        behavior = scene.behavior
        self.assertEqual(behavior.duration, 20)
        scene.set_autonomous(True)
        self.assertEqual(behavior.duration, 20)
        behavior.resume_or_idle(scene)
        self.assertEqual(behavior.duration, 20)
        scene.appearance.step = lambda scene: None
        with patch.object(behavior, 'choose_activity', return_value=Activity.IDLE) as choose:
            for _ in range(800):
                scene.step()
                if choose.called:
                    break
        self.assertTrue(choose.called)
        self.assertEqual(behavior.duration, 50)
        behavior.start_meditation(scene, stationary=True)
        self.assertEqual(behavior.state, Activity.MEDITATE)
        self.assertEqual(behavior.duration, 100)
        # 另一个角色及重置后的角色都从各自的配置开始
        self.assertEqual(OracleBehavior().IDLE_TICKS, (120, 240))
        scene.reset()
        self.assertEqual(scene.behavior.duration, 20)

    def test_configured_distance_reaches_route_sampling(self):
        scene = self.scene(daily_activity=DailyActivityConfig(move_min_distance=80, move_max_distance=90))
        behavior = scene.behavior
        start = scene.body.chunks[0].position
        with patch.object(behavior.random, 'uniform', side_effect=(0, 85)) as uniform:
            target = behavior.short_point(scene)
        self.assertIsNotNone(target)
        self.assertAlmostEqual((target-start).length(), 85)
        self.assertEqual(uniform.call_args_list[1].args, (80, 90))

    def test_cross_edge_timing_is_shared_with_drift(self):
        scene = self.scene(daily_activity=DailyActivityConfig(
            cross_edge_cooldown_seconds=2.5, cross_edge_check_seconds=3.5))
        behavior = scene.behavior
        behavior.enter(Activity.CROSS_EDGE)
        behavior.step(scene)
        self.assertEqual(behavior.cross_cooldown, 100)
        behavior.start_drift(scene)
        self.assertEqual(behavior.drift_next_cross_check, 140)
        behavior.drift_ticks = 200
        behavior.enter(Activity.DRIFT_CROSS_EDGE)
        behavior.finish_drift_crossing(scene)
        self.assertEqual(behavior.cross_cooldown, 100)
        self.assertEqual(behavior.drift_next_cross_check, 340)
        behavior.cross_cooldown = 0
        behavior.drift_ticks = 340
        with patch.object(behavior.detail_random, 'random', return_value=.99):
            self.assertFalse(behavior.try_drift_crossing(scene))
        self.assertEqual(behavior.drift_next_cross_check, 480)

    def test_move_lean_changes_target_but_does_not_limit_mouse_avoidance(self):
        scene = self.scene(daily_activity=DailyActivityConfig(move_lean_degrees=7))
        scene.behavior.enter(Activity.ROAM)
        scene.navigator.velocity = Vec2(scene.config.float_speed, 0)
        scene.pose.step(scene)
        self.assertAlmostEqual(scene.pose.target, 7)
        scene.mouse_reaction.avoidance.lean = 50
        scene.pose.step(scene)
        self.assertAlmostEqual(scene.pose.target, 57)
        scene.config = replace(scene.config, daily_activity=DailyActivityConfig(move_lean_degrees=0))
        scene.pose.step(scene)
        self.assertAlmostEqual(scene.pose.target, 50)


if __name__ == '__main__':
    unittest.main()
