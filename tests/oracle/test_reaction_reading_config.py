"""拖动与读珠的可配置节奏，覆盖取消、物理边界、选珠和归位"""
from dataclasses import fields, replace
from math import atan2
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from rw_creature_pet.config import AppConfig
from rw_creature_pet.oracle.behavior.controller import Activity
from rw_creature_pet.oracle.behavior_config import ReadingConfig
from rw_creature_pet.oracle.config import DragReactionConfig, OracleConfig
from rw_creature_pet.oracle.scene import OracleScene
from rw_creature_pet.oracle.pearls.playback import SpectrumCurve
from rw_creature_pet.presets.fields import scope_for
from rw_creature_pet.presets.profile import apply_profile, profile_mapping
from rw_creature_pet.presets.profile_library import ProfileLibrary
from rw_creature_pet.shared.geometry import Vec2


def scene(**config):
    return OracleScene(OracleConfig(hide_cords=True, halo_enabled=False, physics_backend='python', **config))


class ReactionReadingConfigTests(unittest.TestCase):
    def test_invalid_types_ranges_and_weights_are_rejected(self):
        for cls in (DragReactionConfig, ReadingConfig):
            for f in fields(cls):
                if f.name == 'enabled':
                    continue
                for bad in (True, '1', None, float('nan'), float('inf'), -1.):
                    with self.subTest(cls=cls, name=f.name, bad=bad), self.assertRaises(ValueError):
                        cls(**{f.name: bad})
            for f in fields(cls):
                if '_min_' in f.name:
                    with self.subTest(name=f.name), self.assertRaises(ValueError):
                        cls(**{f.name: getattr(cls(), f.name.replace('_min_', '_max_'))+1})
        for cls, options in (
            (ReadingConfig, dict(approach_weight=0, recall_weight=0, orbit_weight=0)),
            (ReadingConfig, dict(recall_distance=29)), (ReadingConfig, dict(matrix_probability=1.1)),
            (DragReactionConfig, dict(gesture_speed=3.1)),
            (DragReactionConfig, dict(projection_frame_seconds=0)),
            (DragReactionConfig, dict(gesture_max_amplitude=1.1))):
            with self.assertRaises(ValueError):
                cls(**options)

    def test_default_template_and_profile_roundtrip_own_every_new_field(self):
        defaults = AppConfig.load(Path('config.toml'))
        self.assertEqual(defaults.oracle.drag_reactions, DragReactionConfig())
        self.assertEqual(defaults.oracle.reading, ReadingConfig())
        for prefix, cls in (('drag_reactions', DragReactionConfig), ('reading', ReadingConfig)):
            for f in fields(cls):
                self.assertEqual(scope_for('oracle.'+prefix+'.'+f.name).value, 'profile')
        config = replace(defaults, oracle=replace(defaults.oracle,
            reading=ReadingConfig(matrix_probability=.82, interval_min_seconds=17, interval_max_seconds=27,
                                  recall_weight=100, approach_weight=0, orbit_weight=0),
            drag_reactions=DragReactionConfig(gesture_speed=2.3, projection_frame_seconds=.2,
                                             voice_delay_min_seconds=1.2, voice_delay_max_seconds=1.7)))
        with tempfile.TemporaryDirectory() as root:
            library = ProfileLibrary(Path(root)/'library')
            entry = library.export(config, 'Timing')
            restored = apply_profile(AppConfig(), entry, entry.path.parent)
            self.assertEqual(restored.oracle.reading, config.oracle.reading)
            self.assertEqual(restored.oracle.drag_reactions, config.oracle.drag_reactions)
            self.assertEqual(profile_mapping(restored), profile_mapping(config))


class DragTimingTests(unittest.TestCase):
    def held(self, **options):
        s = scene(pearl_fixed_count=0, drag_projection_probability=1,
                  drag_reactions=DragReactionConfig(**options))
        s.drag.set_enabled(True)
        s.drag.press(s.head.position, lambda _: True)
        return s

    def test_each_initial_delay_and_release_cancel_pending_reactions(self):
        for cancel in (False, True):
            s = self.held(gesture_delay_min_seconds=2, gesture_delay_max_seconds=2,
                eye_delay_min_seconds=3, eye_delay_max_seconds=3,
                voice_delay_min_seconds=4, voice_delay_max_seconds=4,
                projection_delay_min_seconds=5, projection_delay_max_seconds=5,
                gesture_probability=1, eye_open_probability=1, voice_probability=1)
            r = s.drag_reactions
            self.assertEqual((r.gesture_wait, r.eye_wait, r.voice_wait, r.projection_wait), (2, 3, 4, 5))
            s.projection.available = True
            s.appearance.step = lambda _: None
            for _ in range(60):
                s.step()
            self.assertFalse(r.gesturing)
            self.assertFalse(s.eyes.observing)
            self.assertEqual(r.voice.request_count, 0)
            self.assertFalse(s.projection.busy)
            s.drag.release(cancel=cancel)
            for _ in range(240):
                s.step()
            self.assertEqual((r.gesture_wait, r.eye_wait, r.voice_wait, r.projection_wait), (0, 0, 0, 0))
            self.assertFalse(r.gesturing)
            self.assertIsNone(r.voice.pending)
            self.assertFalse(s.eyes.observing)
            self.assertEqual(s.projection.starts, 0)

    def test_channels_keep_independent_clocks_and_parameterized_intervals(self):
        traces = []
        for speed in (.25, 3.):
            s = self.held(gesture_speed=speed, gesture_probability=1, eye_open_probability=1,
                voice_probability=1, eye_delay_min_seconds=.2, eye_delay_max_seconds=.2,
                eye_duration_min_seconds=.3, eye_duration_max_seconds=.3,
                eye_interval_min_seconds=.4, eye_interval_max_seconds=.4,
                voice_delay_min_seconds=.5, voice_delay_max_seconds=.5,
                voice_interval_min_seconds=.6, voice_interval_max_seconds=.6,
                gesture_interval_min_seconds=.7, gesture_interval_max_seconds=.7)
            r = s.drag_reactions
            s.appearance.step = lambda _: None
            trace = []
            for _ in range(180):
                s.step()
                trace.append((s.eyes.target, r.voice.request_count))
            traces.append(trace)
            self.assertAlmostEqual(r.gesture_wait, .7)
            self.assertGreater(r.voice.request_count, 0)
            self.assertAlmostEqual(r.voice_wait-r.voice.remaining, .6)
        self.assertEqual(*traces)

    def test_amplitude_speed_and_sync_never_escape_shoulder_sector(self):
        for speed in (.25, 3.):
            s = self.held(gesture_speed=speed, gesture_min_amplitude=.4, gesture_max_amplitude=.4,
                          gesture_duration_min_seconds=5, gesture_duration_max_seconds=5,
                          flutter_sync_probability=1)
            r = s.drag_reactions
            for kind in r.LABELS:
                r.start_gesture(kind, s)
                self.assertEqual(r.duration, 5)
                self.assertEqual(r.hand_lifts, [.4, .4])
                self.assertTrue(1.15*speed <= r.frequency <= 1.65*speed)
                r._choose_flutter_rhythm()
                self.assertEqual(r.flutter_shared_target, 1)
                for _ in range(75):
                    s.step()
                    direction = s.appearance.direction
                    side = Vec2(-direction.y, direction.x)
                    for i, target in enumerate(r.hand_targets(s.appearance, s.drag.controller.pointer)):
                        if target is None:
                            continue
                        hand = s.appearance.hands[i]
                        shoulder = hand.shoulder(s.appearance.upper, direction, i)
                        ray, out = target-shoulder, side*(-1 if i == 0 else 1)
                        angle = atan2(ray.x*direction.x+ray.y*direction.y, ray.x*out.x+ray.y*out.y)
                        self.assertGreaterEqual(angle, hand.SWING_MIN)
                        self.assertLessEqual(angle, hand.SWING_MAX)
                        anchor, length = hand.reach_limit(s.appearance.upper, shoulder)
                        self.assertLessEqual((hand.position-anchor).length(), length+1e-7)

    def test_projection_independent_wait_duration_frames_and_release(self):
        s = self.held(gesture_probability=0, projection_delay_min_seconds=.2, projection_delay_max_seconds=.2,
            projection_interval_min_seconds=.5, projection_interval_max_seconds=.5,
            projection_duration_min_seconds=.8, projection_duration_max_seconds=.8,
            projection_frame_seconds=.1, projection_lift_delay_seconds=.2,
            projection_move_min_seconds=.3, projection_move_max_seconds=.3)
        r, p = s.drag_reactions, s.projection
        p.available = True
        s.appearance.step = lambda _: None
        for _ in range(7):
            s.step()
            self.assertFalse(p.busy)
        s.step()
        self.assertTrue(p.busy)
        self.assertEqual(p.DURATION, .8)
        self.assertEqual(p.FRAME_TICKS, 4)
        for tick in range(1, 33):
            s.step()
            self.assertEqual(p.frame_index, tick//4 % 2)
            if tick < 8:
                self.assertEqual(p.weight, 0)
        self.assertEqual(p.alpha, 0)
        self.assertGreater(p.cooldown, 0)
        s.drag.release(cancel=True)
        self.assertFalse(p.busy)
        self.assertEqual(r.projection_wait, 0)


class ReadingTimingTests(unittest.TestCase):
    def ready(self, **options):
        s = scene(**options)
        s.appearance.step = lambda _: None
        self.until(s, lambda: s.arrived and s.pose.settled and s.observation_pearls_settled)
        return s

    def until(self, s, predicate, budget=2500):
        for _ in range(budget):
            s.step()
            if predicate():
                return
        self.fail(f'Unsettled: {s.behavior.state}')

    def test_stationary_fixed_and_matrix_complete_short_reads_and_return(self):
        for matrix in (False, True):
            s = self.ready(pearl_matrix_enabled=matrix, pearl_fixed_count=0 if matrix else 1,
                pearl_playback_probability=0, reading=ReadingConfig(
                    notice_min_seconds=.2, notice_max_seconds=.2, observe_min_seconds=.3, observe_max_seconds=.3,
                    interval_min_seconds=5, interval_max_seconds=5, eye_open_probability=1,
                    matrix_probability=0 if matrix else 1, approach_weight=100, recall_weight=0, orbit_weight=0))
            b = s.behavior
            b.movement_enabled = False
            origin = s.target
            self.assertTrue(b.notice(s))
            pearl = b.observation_pearl
            identity = (pearl.color_slot, pearl.glyph_id)
            self.assertEqual(b.mode, 'recall')
            self.assertEqual(b.duration, 8)
            self.assertEqual(s.eyes.target, 1)
            self.until(s, lambda: b.state == Activity.OBSERVE)
            self.assertEqual(b.duration, 12)
            self.until(s, lambda: b.completed_cycles == 1)
            self.assertEqual(s.target, origin)
            self.assertEqual((pearl.color_slot, pearl.glyph_id), identity)
            self.assertTrue(s.observation_returned)
            self.assertEqual(b.reading_wait, 200)
            self.assertEqual(s.eyes.target, 0)
            if matrix:
                self.assertIsNone(s.pearl_matrix.extracted)

    def test_matrix_share_fixed_modes_and_missing_groups(self):
        for share, matrix in ((0, False), (1, True)):
            s = scene(pearl_matrix_enabled=True, pearl_fixed_count=2, reading=ReadingConfig(matrix_probability=share,
                      approach_weight=0, recall_weight=0, orbit_weight=100))
            self.assertTrue(s.behavior.notice(s))
            self.assertEqual(s.behavior.matrix_observation, matrix)
            self.assertEqual(s.behavior.mode, 'recall' if matrix else 'orbit')
        s = scene(pearl_matrix_enabled=False, pearl_fixed_count=0, pearl_inner_count=4, pearl_satellite_count=2)
        self.assertFalse(s.behavior.notice(s))
        self.assertEqual(s.behavior.state, Activity.IDLE)

    def test_interval_blocks_automatic_but_not_manual_and_drift_attempts_have_probability(self):
        s = self.ready(pearl_fixed_count=1, cross_edge_probability=0, antigravity_probability=0,
            reading=ReadingConfig(start_probability=1, drift_probability=.2,
                drift_delay_min_seconds=.2, drift_delay_max_seconds=.2,
                drift_interval_min_seconds=.4, drift_interval_max_seconds=.4))
        b = s.behavior
        b.reading_wait = 100
        self.assertNotIn(Activity.NOTICE, {b.choose_activity(s) for _ in range(100)})
        self.assertTrue(b.notice(s, mode='recall'))
        b.cancel(s)
        b.start_drift(s)
        self.assertEqual(b.drift_next_observation, 8)
        b.drift_ticks = 8
        b.drift_next_move = 1000
        b.reading_wait = 0
        with patch.object(b, 'notice') as notice, patch.object(b.reading_timing_random, 'random', return_value=.8):
            b.step_drift(s)
        notice.assert_not_called()
        self.assertEqual(b.drift_next_observation, 24)

    def test_distances_reach_planning_and_no_space_returns_pearl(self):
        s = self.ready(pearl_fixed_count=1, reading=ReadingConfig(observe_distance=85, recall_distance=65))
        b = s.behavior
        b.notice(s, mode='recall')
        self.assertEqual((b.OBSERVE_DISTANCE, b.RECALL_DISTANCE), (85, 65))
        point = b.recall_point(s)
        self.assertIsNotNone(point)
        self.assertTrue(30 <= (point-s.body.chunks[0].position).length() <= 65+24)
        b.RECALL_DISTANCE = 38
        self.assertNotEqual(b.recall_point(s), point)
        with patch.object(b, 'recall_point', return_value=None):
            b.start_recall(s)
        self.assertEqual(b.state, Activity.RETURN)
        self.until(s, lambda: b.completed_cycles == 1)
        self.assertTrue(s.observation_returned)

    def test_playback_duration_is_separate_from_plain_reading_and_returns_to_slot(self):
        s = self.ready(pearl_matrix_enabled=True, pearl_fixed_count=0, pearl_playback_probability=1,
            reading=ReadingConfig(notice_min_seconds=.1, notice_max_seconds=.1,
                observe_min_seconds=.2, observe_max_seconds=.2, playback_min_seconds=.8, playback_max_seconds=.8))
        s.pearl_playback_curve = SpectrumCurve((.8,)*80, 2.)
        b = s.behavior
        b.notice(s, matrix=True)
        self.until(s, lambda: b.state == Activity.OBSERVE)
        self.assertEqual(b.duration, 32)
        self.assertEqual(s.observed_pearl.playback.duration, 32)
        self.until(s, lambda: b.completed_cycles == 1)
        self.assertIsNone(s.pearl_matrix.extracted)

    def test_zero_drift_reading_probability_does_not_interrupt_roaming_routes(self):
        s = self.ready(pearl_fixed_count=1, reading=ReadingConfig(drift_probability=0))
        b = s.behavior
        b.start_drift(s)
        b.drift_next_observation = 0
        b.drift_next_move = 0
        with patch.object(b, 'notice') as notice, patch.object(b, 'drift_move_to') as move:
            b.step_drift(s)
        notice.assert_not_called()
        move.assert_called_once()


if __name__ == '__main__':
    unittest.main()
