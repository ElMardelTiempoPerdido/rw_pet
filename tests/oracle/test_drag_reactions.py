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
from rw_creature_pet.oracle.voice import BELL_VOICE_CLIPS
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
        config = AppConfig.load(Path('config.toml')).oracle.drag_reactions
        self.assertEqual(config.gesture_probability, .9)
        for value in (-.1, 1.1, float('nan'), True, '0.5'):
            with self.assertRaises(ValueError):
                DragReactionConfig(voice_probability=value)

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
        waits = []
        for _ in range(12):
            s.drag.press(s.head.position, lambda _: True)
            waits.append(s.drag_reactions.voice_wait)
            s.drag.release(cancel=True)
        self.assertTrue(all(0. <= delay <= 3. for delay in waits))
        self.assertGreater(max(waits)-min(waits), 1.)

    def test_static_hold_wakes_hands_then_release_returns_to_sleep(self):
        s = self.make_scene(gesture_probability=1., eye_open_probability=1., voice_probability=1.)
        for _ in range(650):
            s.step()
        self.assertTrue(s.appearance.sleeping)
        before = [p.position for p in s.appearance.hands]
        for gesture in ('flutter', 'protest'):
            self.assertTrue(s.drag.press(s.head.position, lambda _: True))
            s.drag_reactions.start_gesture(gesture, s)
            moved = 0.
            for _ in range(80):
                s.step()
                for hand, old in zip(s.appearance.hands, before):
                    self.assertLessEqual((hand.position-s.appearance.upper).length(), 15.00001)
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
                for hand in s.appearance.hands:
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
            for _ in range(15):
                s.step()
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
            for clip in BELL_VOICE_CLIPS:
                start, end = round(clip.start*100), round(clip.end*100)
                with wave.open(str(root/'clips'/clip.filename), 'rb') as audio:
                    self.assertEqual((audio.getnchannels(), audio.getsampwidth(), audio.getframerate()), (2, 2, 100))
                    self.assertEqual(audio.getnframes(), end-start)
                    self.assertEqual(audio.readframes(end-start), samples[start*4:end*4])


if __name__ == '__main__':
    unittest.main()
