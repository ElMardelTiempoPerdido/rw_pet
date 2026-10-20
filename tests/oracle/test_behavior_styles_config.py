"""漫游与鼠标风格参数：默认节奏、参数生效、极端组合与安全接管"""
from dataclasses import fields, replace
from math import exp
from random import Random
import unittest
from unittest.mock import patch

from rw_creature_pet.interaction.config import InteractionConfig
from rw_creature_pet.oracle.behavior.controller import Activity, OracleBehavior
from rw_creature_pet.oracle.config import OracleConfig
from rw_creature_pet.oracle.drift_config import DriftConfig
from rw_creature_pet.oracle.mouse_avoidance_config import MouseAvoidanceConfig
from rw_creature_pet.oracle.scene import OracleScene
from rw_creature_pet.oracle.ui.desktop import OracleDesktopMotion, OracleDesktopViewport
from rw_creature_pet.shared.geometry import Vec2


class BehaviorStyleConfigTests(unittest.TestCase):
    def test_rejects_invalid_types_nonfinite_ranges_and_empty_weights(self):
        for cls in (DriftConfig, MouseAvoidanceConfig):
            for field in fields(cls):
                for bad in (True, '1', None, float('nan'), float('inf'), -1.):
                    with self.subTest(cls=cls, field=field.name, bad=bad), self.assertRaises(ValueError):
                        cls(**{field.name: bad})
        for cls, kwargs in (
                (DriftConfig, {'short_pause_weight': 0, 'normal_pause_weight': 0, 'long_pause_weight': 0}),
                (DriftConfig, {'entry_min_seconds': 6}),
                (DriftConfig, {'normal_pause_min_seconds': 6}),
                (DriftConfig, {'speed_min_factor': 1.5}),
                (DriftConfig, {'long_bout_probability': 1.1}),
                (DriftConfig, {'duration_variation': .6}),
                (MouseAvoidanceConfig, {'enter_distance': 80}),
                (MouseAvoidanceConfig, {'lean_min_degrees': 70}),
                (MouseAvoidanceConfig, {'lean_max_degrees': 90}),
                (MouseAvoidanceConfig, {'retry_min_seconds': 0}),
                (MouseAvoidanceConfig, {'pointer_lag_seconds': 0}),
                (MouseAvoidanceConfig, {'speed_min': 4})):
            with self.subTest(cls=cls, kwargs=kwargs), self.assertRaises(ValueError):
                cls(**kwargs)
        for field in ('drift', 'mouse_avoidance'):
            with self.assertRaises(ValueError):
                OracleConfig(**{field: {}})

    def test_default_pause_draws_match_previous_sequence_without_extra_randomness(self):
        behavior = OracleBehavior()
        legacy = Random(623)
        last = 0
        for _ in range(3000):
            weights = [.5, .35, .15 if last < 280 else 0]
            band = legacy.choices(((14, 48), (72, 220), (280, 560)), weights)[0]
            last = legacy.randint(*band)
            self.assertEqual(behavior.sample_drift_pause(), last)
        self.assertEqual(behavior.timing_random.getstate(), legacy.getstate())

    def test_only_long_pauses_and_overlapping_ranges_remain_valid(self):
        only_long = DriftConfig(short_pause_weight=0, normal_pause_weight=0,
                                long_pause_min_seconds=2, long_pause_max_seconds=2)
        behavior = OracleBehavior(drift=only_long)
        self.assertEqual([behavior.sample_drift_pause() for _ in range(50)], [80]*50)
        behavior = OracleBehavior(drift=DriftConfig(short_pause_min_seconds=7, short_pause_max_seconds=7))
        with patch.object(behavior.timing_random, 'choices', side_effect=([0], [2], [0])) as choose:
            for _ in range(3):
                behavior.sample_drift_pause()
        self.assertGreater(choose.call_args_list[1].args[1][2], 0)
        self.assertEqual(choose.call_args_list[2].args[1][2], 0)

    def test_config_reaches_entry_resume_bouts_speed_distance_duration_and_cooldown(self):
        config = DriftConfig(cooldown_seconds=17, duration_variation=0,
            entry_min_seconds=.7, entry_max_seconds=.7, resume_min_seconds=.4, resume_max_seconds=.4,
            long_bout_min_seconds=3, long_bout_max_seconds=3, long_bout_probability=1,
            speed_min_factor=.5, speed_max_factor=.5, move_min_distance=80, move_max_distance=90)
        scene = OracleScene(OracleConfig(drift=config, hide_cords=True, physics_backend='python'))
        behavior = scene.behavior
        behavior.start_drift(scene)
        self.assertEqual(behavior.drift_duration, 12000)
        self.assertEqual(behavior.drift_next_move, 28)
        behavior.resume_or_idle(scene)
        self.assertEqual(behavior.drift_next_move, 16)
        behavior.drift_move_to(scene, scene.body.chunks[0].position+Vec2(90, 0))
        self.assertEqual(behavior.drift_bout_until, 120)
        self.assertEqual(scene.travel_speed, .5)
        with patch.object(behavior.random, 'uniform', side_effect=(85, .5)) as uniform:
            self.assertIsNotNone(behavior.drift_point(scene, scene.body.chunks[0].position, Vec2(1, 0)))
        self.assertEqual(uniform.call_args_list[0].args, (80, 90))
        behavior.end_drift(scene)
        self.assertEqual(behavior.drift_cooldown, 680)
        self.assertEqual(OracleBehavior().DRIFT_COOLDOWN, 4800)
        scene.reset()
        self.assertEqual(scene.behavior.DRIFT_ENTRY_TICKS, (28, 28))


class MouseStyleConfigTests(unittest.TestCase):
    def scene(self, **settings):
        scene = OracleScene(OracleConfig(mouse_avoidance=MouseAvoidanceConfig(**settings),
            edge_fraction=.3, physics_backend='python', hide_cords=True, halo_enabled=False, pearl_fixed_count=0))
        scene.appearance.step = lambda _: None
        for _ in range(300):
            scene.step()
        scene.set_autonomous(True)
        scene.behavior.duration = 100000
        scene.mouse_reaction.configure(scene, InteractionConfig(hover_radius=200, hover_dwell_seconds=0,
                                                                hover_probability=1, hover_open_probability=0))
        return scene

    def test_attention_precedes_configured_delay_and_zero_grace_only_releases_outside(self):
        scene = self.scene(delay_min_seconds=.2, delay_max_seconds=.2, probability=1,
            leave_grace_seconds=0, lean_min_degrees=12, lean_max_degrees=12,
            lean_move_probability=0, move_probability=0)
        scene.set_autonomous_movement(False)
        reaction = scene.mouse_reaction
        reaction.configure(scene, replace(reaction.config, hover_dwell_seconds=.25))
        reaction.pointer = scene.body.chunks[0].position+Vec2(30, 0)
        for _ in range(9):
            scene.step()
            self.assertFalse(reaction.attention.active)
        for _ in range(7):
            scene.step()
            self.assertFalse(reaction.avoidance.engaged)
        scene.step()
        self.assertTrue(reaction.avoidance.engaged)
        self.assertEqual(reaction.avoidance.amplitude, 12)
        for _ in range(10):
            scene.step()
            self.assertTrue(reaction.avoidance.engaged)
        reaction.pointer = scene.body.chunks[0].position+Vec2(400, 0)
        scene.step()
        self.assertFalse(reaction.avoidance.engaged)

    def test_lower_and_drift_escape_use_configured_speed_and_no_drift_lean(self):
        for drifting in (False, True):
            scene = self.scene(delay_min_seconds=0, delay_max_seconds=0, probability=1,
                move_min_distance=12, move_max_distance=12, move_angle_jitter=0,
                speed_min=.75, speed_max=.75)
            if drifting:
                scene.drift()
            a = scene.mouse_reaction.avoidance
            start = a.neutral_position(scene)
            pointer = scene.body.chunks[0].position+Vec2(30, 8)
            a.begin(scene, pointer)
            self.assertTrue(a.moving)
            self.assertAlmostEqual((scene.target-start).length(), 12)
            self.assertEqual(scene.travel_speed, .75)
            self.assertTrue(scene.body_region.contains(scene.target))
            if drifting:
                self.assertEqual((a.lean, a.lean_goal, a.amplitude), (0., 0., 0.))
            # 关闭自主移动仍然禁止位移，不能由高触发概率绕过
            a.cancel(scene, immediate=True)
            scene.behavior.movement_enabled = False
            self.assertFalse(a.start_move(scene, pointer))

    def test_lean_sampling_lag_retry_and_reconfigure_keep_random_streams_separate(self):
        scene = self.scene(lean_min_degrees=10, lean_max_degrees=50, lean_sample_power=3,
            pointer_lag_seconds=1., lean_speed=30., lean_move_probability=0, move_probability=0,
            retry_min_seconds=.6, retry_max_seconds=.6, impatience_min_seconds=4, impatience_max_seconds=4)
        scene.set_autonomous_movement(False)
        a = scene.mouse_reaction.avoidance
        pointer = scene.body.chunks[0].position+Vec2(30, 0)
        with patch.object(a.random, 'random', return_value=.5):
            a.begin(scene, pointer)
        self.assertEqual(a.amplitude, 15)
        self.assertEqual(a.impatience_threshold, 4)
        target = pointer+Vec2(-10, 0)
        a.step(scene, active=True, pointer=target, enabled=True)
        self.assertAlmostEqual(a.filtered_pointer.x, pointer.lerp(target, 1-exp(-.025)).x)
        self.assertLessEqual(abs(a.lean), .75)
        # 已经不耐烦时，每次抽签仍受重试间隔约束
        a.impatience = 10
        a.retry_seconds = 0
        a.step(scene, active=True, pointer=target, enabled=True)
        self.assertAlmostEqual(a.retry_seconds, .6)
        streams = (a.random.getstate(), scene.mouse_reaction.attention.random.getstate())
        scene.config = replace(scene.config, mouse_avoidance=replace(scene.config.mouse_avoidance, lean_sample_power=4))
        scene.mouse_reaction.configure(scene, scene.mouse_reaction.config)
        self.assertFalse(scene.mouse_reaction.avoidance.engaged)
        self.assertEqual(scene.mouse_reaction.avoidance.LEAN_SAMPLE_POWER, 4)
        self.assertEqual(streams, (scene.mouse_reaction.avoidance.random.getstate(),
                                   scene.mouse_reaction.attention.random.getstate()))
        resized = OracleDesktopMotion(scene.config, OracleDesktopViewport(0, 0, 1280, 720), scene).scene
        self.assertEqual(resized.mouse_reaction.avoidance.config, scene.config.mouse_avoidance)
        self.assertEqual(resized.mouse_reaction.avoidance.random.getstate(), streams[0])

    def test_fast_escape_and_long_requested_distance_stay_in_edge_band(self):
        for side in ('top', 'right', 'bottom', 'left'):
            scene = OracleScene(OracleConfig(base_side=side, edge_fraction=.3, physics_backend='python',
                hide_cords=True, halo_enabled=False, pearl_fixed_count=0,
                mouse_avoidance=MouseAvoidanceConfig(move_min_distance=1000, move_max_distance=1000,
                                                     speed_min=5, speed_max=5, move_angle_jitter=0)))
            scene.appearance.step = lambda _: None
            for _ in range(300):
                scene.step()
            scene.set_autonomous(True)
            scene.behavior.duration = 100000
            a = scene.mouse_reaction.avoidance
            pointer = scene.body.chunks[0].position-scene.base_normal()*30
            self.assertTrue(a.start_move(scene, pointer))
            for _ in range(400):
                scene.step()
                self.assertTrue(scene.body_region.contains(scene.body.chunks[0].position))
            self.assertFalse(a.moving)


if __name__ == '__main__':
    unittest.main()
