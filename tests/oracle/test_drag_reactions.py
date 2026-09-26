"""交互反应的独立随机流、物理边界、释放收敛与静音请求回归。"""
from math import sin
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import wave

from rw_creature_pet.config import AppConfig
from rw_creature_pet.interaction.voice import VoiceCue, VoiceCueChannel
from rw_creature_pet.oracle.config import DragReactionConfig, OracleConfig
from rw_creature_pet.oracle.scene import OracleScene
from rw_creature_pet.oracle.voice import BELL_VOICE_CLIPS, BELL_VOICE_SOURCES
from rw_creature_pet.shared.geometry import Vec2
from tools.oracle.cut_bell_voice import cut_clips


class DragReactionsTests(unittest.TestCase):
    def make_scene(self, **kwargs):
        scene = OracleScene(OracleConfig(halo_enabled=False, pearl_fixed_count=0,
            drag_reactions=DragReactionConfig(**kwargs)))
        scene.drag.set_enabled(True)
        return scene

    def test_probabilities_validate_and_old_config_still_loads(self):
        self.assertTrue(OracleConfig.from_mapping({}).drag_reactions.enabled)
        self.assertEqual(OracleConfig.from_mapping({}).drag_reactions.flutter_probability, .85)
        legacy = OracleConfig.from_mapping({'drag_reactions': {'flutter_probability': .2}}).drag_reactions
        self.assertEqual(legacy.flutter_probability, .2)
        self.assertEqual(legacy.alternating_probability, .47)
        config = AppConfig.load(Path('config.toml')).oracle.drag_reactions
        self.assertEqual(config.gesture_probability, .9)
        for name in ('voice_probability', 'alternating_probability'):
            for value in (-.1, 1.1, float('nan'), True, '0.5'):
                with self.assertRaises(ValueError):
                    DragReactionConfig(**{name: value})

    def test_gesture_selection_preserves_single_hand_share_and_splits_two_hand_modes(self):
        s = self.make_scene()
        r = s.drag_reactions
        cases = (
            (.85, .47, [0., .84, .46], 'alternating'),
            (.85, .47, [0., .84, .47], 'flutter'),
            (.85, .47, [0., .85], 'protest'),
            (1., 0., [0., .99, 0.], 'flutter'),
            (1., 1., [0., .99, .99], 'alternating'),
            (0., 1., [0., 0.], 'protest'),
            (.85, .47, [.9], None),
        )
        for two_hands, alternating, draws, expected in cases:
            r.config = DragReactionConfig(flutter_probability=two_hands, alternating_probability=alternating)
            # 最后一个随机值供下一次机会的 uniform 间隔使用。
            with patch.object(r.random, 'random', side_effect=draws+[.5]), patch.object(r, 'start_gesture') as start:
                r._try_gesture(s)
                if expected is None:
                    start.assert_not_called()
                else:
                    start.assert_called_once_with(expected, s)

    def test_three_channels_are_independent_and_do_not_advance_autonomy_random(self):
        scenes = [self.make_scene(gesture_probability=p, eye_open_probability=.7,
                                 voice_probability=.8) for p in (0., 1.)]
        original = [s.behavior.random.getstate() for s in scenes]
        observations = [[], []]
        for index, scene in enumerate(scenes):
            scene.appearance.step = lambda _: None
            scene.drag.press(scene.head.position, lambda _: True)
            for tick in range(800):
                scene.step()
                r = scene.drag_reactions
                observations[index].append((scene.eyes.target, r.voice.request_count, r.voice.last_cue))
            self.assertEqual(scene.behavior.random.getstate(), original[index])
        self.assertEqual(observations[0], observations[1])
        self.assertGreater(scenes[0].drag_reactions.voice.request_count, 1)
        self.assertFalse(scenes[0].drag_reactions.gesturing)

    def test_first_gesture_waits_and_keeps_probability(self):
        for delay in (.15, .6, 1.5):
            for probability in (0., 1.):
                with self.subTest(delay=delay, probability=probability):
                    s = self.make_scene(gesture_probability=probability)
                    r = s.drag_reactions
                    with patch.object(r.random, 'uniform', return_value=delay):
                        s.drag.press(s.head.position, lambda _: True)
                    self.assertFalse(r.gesturing)
                    self.assertEqual(r.hand_forces(s.appearance, s.head.position), (Vec2(), Vec2()))
                    elapsed = 0.
                    while elapsed+r.DT < delay-1e-9:
                        r.step(s)
                        elapsed += r.DT
                        self.assertFalse(r.gesturing)
                    r.step(s)
                    r.step(s)
                    self.assertEqual(r.gesturing, bool(probability))

    def test_early_release_cancels_gesture_wait_and_regrab_restarts_it(self):
        for cancel in (False, True):
            s = self.make_scene(gesture_probability=1.)
            r = s.drag_reactions
            with patch.object(r.random, 'uniform', return_value=1.5):
                s.drag.press(s.head.position, lambda _: True)
            for _ in range(10):
                r.step(s)
            s.drag.release(cancel=cancel)
            self.assertEqual(r.gesture_wait, 0.)
            for _ in range(100):
                r.step(s)
                self.assertFalse(r.gesturing)
            with patch.object(r.random, 'uniform', return_value=.2):
                s.drag.press(s.head.position, lambda _: True)
            self.assertEqual(r.gesture_wait, .2)
            self.assertFalse(r.gesturing)
            for _ in range(9):
                r.step(s)
            self.assertTrue(r.gesturing)

    def test_flutter_varies_coordination_smoothly_and_force_reads_are_pure(self):
        s = self.make_scene(gesture_probability=0.)
        r = s.drag_reactions
        same_direction = opposed = 0
        largest_change = 0.
        for _ in range(16):
            s.drag.press(s.head.position, lambda _: True)
            r.start_gesture('flutter', s)
            previous = (Vec2(), Vec2())
            previous_heights = None
            while r.gesturing:
                r.step(s)
                state = r.random.getstate()
                forces = r.hand_forces(s.appearance, s.head.position)
                self.assertEqual(forces, r.hand_forces(s.appearance, s.head.position))
                self.assertEqual(state, r.random.getstate())
                for force, old in zip(forces, previous):
                    self.assertLessEqual(force.length(), 3.000001)
                    largest_change = max(largest_change, (force-old).length())
                targets = r.hand_targets(s.appearance, s.head.position)
                if all(target is not None for target in targets):
                    up = s.appearance.direction
                    heights = [(target-s.appearance.upper).x*up.x+(target-s.appearance.upper).y*up.y
                               for target in targets]
                    if previous_heights is not None:
                        a, b = [new-old for new, old in zip(heights, previous_heights)]
                        same_direction += a*b > .02
                        opposed += a*b < -.02
                    previous_heights = heights
                previous = forces
            s.drag.release(cancel=True)
        self.assertGreater(same_direction, 20, '需要出现双手同时抬起/放下，仍各自在肩外扇形内活动')
        self.assertGreater(opposed, 20, '同向划动之外仍保留两手各自的动作')
        self.assertLess(largest_change, 1.4, '随机节奏切换不能造成单帧驱动力跳变')

    def test_first_voice_waits_up_to_three_seconds_and_keeps_probability(self):
        for delay in (0., 1.5, 3.):
            for probability in (0., 1.):
                with self.subTest(delay=delay, probability=probability):
                    s = self.make_scene(gesture_probability=0., eye_open_probability=0.,
                                        voice_probability=probability)
                    r = s.drag_reactions
                    with patch.object(r.voice_random, 'uniform', return_value=delay):
                        s.drag.press(s.head.position, lambda _: True)
                    self.assertIsNone(r.voice.pending)
                    elapsed = 0.
                    while elapsed+r.DT < delay-1e-9:
                        r.step(s)
                        elapsed += r.DT
                        self.assertEqual(r.voice.request_count, 0)
                    # 40 Hz 的量化和浮点误差允许再经过至多两帧。
                    r.step(s)
                    r.step(s)
                    self.assertEqual(r.voice.request_count, int(probability))

    def test_release_cancels_wait_and_regrab_draws_a_new_delay(self):
        for cancel in (False, True):
            s = self.make_scene(gesture_probability=0., eye_open_probability=0., voice_probability=1.)
            r = s.drag_reactions
            with patch.object(r.voice_random, 'uniform', return_value=3.):
                s.drag.press(s.head.position, lambda _: True)
            for _ in range(10):
                r.step(s)
            s.drag.release(cancel=cancel)
            self.assertEqual(r.voice_wait, 0.)
            for _ in range(160):
                r.step(s)
            self.assertEqual(r.voice.request_count, 0)
            with patch.object(r.voice_random, 'uniform', return_value=.2):
                s.drag.press(s.head.position, lambda _: True)
            self.assertEqual(r.voice_wait, .2)
            for _ in range(9):
                r.step(s)
            self.assertEqual(r.voice.request_count, 1)

    def test_initial_wait_varies_between_grabs(self):
        s = self.make_scene()
        waits, hand_waits = [], []
        for _ in range(12):
            s.drag.press(s.head.position, lambda _: True)
            waits.append(s.drag_reactions.voice_wait)
            hand_waits.append(s.drag_reactions.gesture_wait)
            s.drag.release(cancel=True)
        self.assertTrue(all(0. <= delay <= 3. for delay in waits))
        self.assertGreater(max(waits)-min(waits), 1.)
        self.assertTrue(all(.15 <= delay <= 1.5 for delay in hand_waits))
        self.assertGreater(max(hand_waits)-min(hand_waits), .5)

    def test_static_hold_wakes_hands_then_release_returns_to_sleep(self):
        s = self.make_scene(gesture_probability=1., eye_open_probability=1., voice_probability=1.)
        for _ in range(650):
            s.step()
        self.assertTrue(s.appearance.sleeping)
        before = [p.position for p in s.appearance.hands]
        for gesture in ('flutter', 'alternating', 'protest'):
            self.assertTrue(s.drag.press(s.head.position, lambda _: True))
            s.drag_reactions.start_gesture(gesture, s)
            moved = 0.
            for _ in range(80):
                s.step()
                for i, (hand, old) in enumerate(zip(s.appearance.hands, before)):
                    shoulder = hand.shoulder(s.appearance.upper, s.appearance.direction, i)
                    anchor, maximum = hand.reach_limit(s.appearance.upper, shoulder)
                    self.assertLessEqual((hand.position-anchor).length(), maximum+1e-8)
                    moved = max(moved, (hand.position-old).length())
            self.assertGreater(moved, 8.)
            self.assertFalse(s.appearance.sleeping)
            self.assertGreater(s.eyes.openness, 0.)
            s.drag.release()
            for _ in range(1300):
                s.step()
            self.assertFalse(s.drag.controlling)
            self.assertFalse(s.drag_reactions.gesturing)
            self.assertIsNone(s.drag_reactions.voice.pending)
            self.assertEqual(s.eyes.openness, 0.)
            self.assertTrue(s.appearance.sleeping)

    def test_natural_inertia_and_navigation_are_preserved_with_reactions_disabled(self):
        off = self.make_scene(enabled=False)
        on = self.make_scene(gesture_probability=1.)
        largest_lag = 0.
        for s in (off, on):
            s.drag.press(s.head.position, lambda _: True)
        for tick in range(220):
            target = Vec2(500+90*sin(tick*.035), 200+80*sin(tick*.023))
            for s in (off, on):
                s.drag.move(target)
                s.step()
                for i, hand in enumerate(s.appearance.hands):
                    shoulder = hand.shoulder(s.appearance.upper, s.appearance.direction, i)
                    anchor, maximum = hand.reach_limit(s.appearance.upper, shoulder)
                    self.assertLessEqual((hand.position-anchor).length(), maximum+1e-8)
                    if s is off:
                        self.assertLessEqual((hand.position-s.appearance.upper).length(), 15.00001)
            self.assertEqual(off.body, on.body)
            self.assertEqual(off.arm.joints, on.arm.joints)
            natural = off.appearance
            equilibrium = natural.hand_forces()[0]
            equilibrium = equilibrium*(15/equilibrium.length())
            largest_lag = max(largest_lag, (natural.hands[0].position-natural.upper-equilibrium).length())
        self.assertGreater(largest_lag, 3., '关闭手势仍应保留真实受牵拉时的甩手')
        self.assertFalse(off.drag_reactions.gesturing)
        self.assertEqual(off.drag_reactions.voice.request_count, 0)

    def test_cancel_miss_regrab_and_reset_do_not_leave_reactions(self):
        s = self.make_scene(gesture_probability=1., eye_open_probability=1., voice_probability=1.)
        state = s.drag_reactions.random.getstate()
        self.assertFalse(s.drag.press(Vec2(), lambda _: False))
        self.assertEqual(state, s.drag_reactions.random.getstate())
        for _ in range(3):
            self.assertTrue(s.drag.press(s.head.position, lambda _: True))
            for _ in range(62):
                s.step()
                if s.drag_reactions.gesturing:
                    break
            self.assertTrue(s.drag_reactions.gesturing)
            s.drag.release(cancel=True)
            self.assertFalse(s.drag_reactions.active)
            self.assertFalse(s.drag_reactions.gesturing)
            self.assertIsNone(s.drag_reactions.voice.pending)
            self.assertEqual(s.eyes.target, 0.)
        s.reset()
        self.assertFalse(s.drag_reactions.active)
        self.assertEqual(s.drag_reactions.voice.request_count, 0)


class VoicePreparationTests(unittest.TestCase):
    def test_voice_pool_selects_short_clips_with_matching_reservation_duration(self):
        scene = OracleScene(OracleConfig(drag_reactions=DragReactionConfig(voice_probability=1.)))
        reaction = scene.drag_reactions
        clips = {clip.clip_id: clip for clip in BELL_VOICE_CLIPS}
        self.assertEqual(len(clips), 10)
        seen, previous = set(), None
        for _ in range(200):
            reaction.voice.cancel()
            reaction._try_voice()
            cue = reaction.voice.take_pending()
            self.assertIsNotNone(cue)
            self.assertNotEqual(cue.clip_id, previous)
            self.assertAlmostEqual(cue.duration_seconds, clips[cue.clip_id].duration)
            self.assertLessEqual(cue.duration_seconds, 4.18+1e-9)
            seen.add(cue.clip_id)
            previous = cue.clip_id
        self.assertEqual(seen, set(clips))

    def test_silent_channel_is_bounded_expires_and_cancels(self):
        channel = VoiceCueChannel()
        cue = VoiceCue('bell_01', 2.5, 'drag')
        self.assertTrue(channel.request(cue))
        for _ in range(100):
            self.assertFalse(channel.request(cue))
        self.assertEqual(channel.request_count, 1)
        self.assertEqual(channel.take_pending(), cue)
        self.assertIsNone(channel.take_pending())
        self.assertFalse(channel.request(cue))
        channel.step(3.)
        self.assertTrue(channel.request(cue))
        channel.step(3.)
        self.assertIsNone(channel.pending)
        channel.request(cue)
        channel.cancel()
        self.assertIsNone(channel.pending)
        self.assertEqual(channel.remaining, 0.)

    def test_clips_preserve_exact_samples_channels_and_subtitle_boundaries(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root/'source.wav'
            samples = bytes(range(256))*80
            with wave.open(str(source), 'wb') as audio:
                audio.setparams((2, 2, 100, 0, 'NONE', 'not compressed'))
                audio.writeframes(samples)
            cut_clips(source, root/'clips')
            for clip in BELL_VOICE_SOURCES:
                start, end = round(clip.start*100), round(clip.end*100)
                with wave.open(str(root/'clips'/clip.filename), 'rb') as audio:
                    self.assertEqual((audio.getnchannels(), audio.getsampwidth(), audio.getframerate()), (2, 2, 100))
                    self.assertEqual(audio.getnframes(), end-start)
                    self.assertEqual(audio.readframes(end-start), samples[start*4:end*4])


if __name__ == '__main__':
    unittest.main()
