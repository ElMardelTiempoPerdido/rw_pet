"""离线频谱、缓存、矩阵阅读分支、收尾休眠和投影绘制。"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from dataclasses import replace
import io
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import wave

import numpy as np
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication
from rw_creature_pet.oracle.behavior import Activity
from rw_creature_pet.oracle.config import OracleConfig
from rw_creature_pet.oracle.pearl_playback import PearlPlayback, SpectrumCurve
from rw_creature_pet.oracle.pearl_playback_assets import load_pearl_playback, precompute_strength
from rw_creature_pet.oracle.render import OracleRenderer
from rw_creature_pet.oracle.scene import OracleScene
from rw_creature_pet.shared.timing import FixedStepper


def wav_bytes(silent=False):
    t = np.arange(44100)/44100
    signal = np.zeros_like(t) if silent else .5*np.sin(2*np.pi*1000*t)
    stereo = np.column_stack((signal, -signal))
    out = io.BytesIO()
    with wave.open(out, 'wb') as f:
        f.setnchannels(2)
        f.setsampwidth(2)
        f.setframerate(44100)
        f.writeframes((stereo*32767).astype('<i2').tobytes())
    return out.getvalue()


class PearlPlaybackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def scene(self, probability=1.):
        scene = OracleScene(OracleConfig(pearl_matrix_enabled=True, pearl_playback_probability=probability,
                                        halo_enabled=False))
        scene.pearl_playback_curve = SpectrumCurve((.8,)*800, 20.)
        scene.appearance.step = lambda _: None
        return scene

    def observe(self, scene):
        scene.observe_matrix_pearl()
        for _ in range(1800):
            scene.step()
            if scene.behavior.state == Activity.OBSERVE:
                return scene.observed_pearl
        self.fail('未到达阅读状态')

    def test_spectrum_is_silent_for_silence_and_uses_left_channel_not_stereo_average(self):
        silent, _ = precompute_strength(wav_bytes(True))
        self.assertEqual(silent.values, (0.,)*40)
        audible, meta = precompute_strength(wav_bytes())
        self.assertEqual(len(audible.values), 40)
        self.assertGreater(audible.sample(.5), .4)
        self.assertEqual(meta['channel'], 0)
        self.assertAlmostEqual(audible.sample(.5125), (audible.values[20]+audible.values[21])/2)

    def test_cache_hot_load_never_decodes_and_corruption_is_rebuilt(self):
        with TemporaryDirectory() as temp:
            game, cache = Path(temp)/'game', Path(temp)/'cache'
            source = game/'RainWorld_Data/StreamingAssets/AssetBundles/music_songs'
            source.parent.mkdir(parents=True)
            source.write_bytes(b'fixture')
            with patch('rw_creature_pet.oracle.pearl_playback_assets._decode_source', return_value=wav_bytes()) as decode:
                curve, root = load_pearl_playback(game, cache_root=cache)
                self.assertEqual(load_pearl_playback(game, cache_root=cache)[0], curve)
                self.assertEqual(decode.call_count, 1)
                (root/'strength.npy').write_bytes(b'broken')
                self.assertEqual(load_pearl_playback(game, cache_root=cache)[0], curve)
                self.assertEqual(decode.call_count, 2)
            self.assertEqual({p.name for p in root.iterdir()}, {'manifest.json', 'strength.npy'})

    def test_only_matrix_observation_triggers_once_and_returns_to_sleep(self):
        scene = self.scene()
        with patch.object(scene.behavior.playback_random, 'random', return_value=.1) as choose, \
                patch.object(scene.behavior.playback_random, 'uniform', return_value=2.):
            pearl = self.observe(scene)
            self.assertIsNotNone(pearl.playback)
            self.assertTrue(3600 <= scene.behavior.duration <= 4800)
            self.assertEqual(pearl.playback.duration, scene.behavior.duration)
            self.assertTrue(pearl.settled)
            revision = scene.pearl_matrix.revision
            for _ in range(50):
                scene.step()
            self.assertEqual(choose.call_count, 1)
            self.assertGreater(scene.pearl_matrix.revision, revision)
            self.assertGreater(pearl.playback.strength, 0.)
            for _ in range(scene.behavior.duration+2200):
                scene.step()
                if scene.behavior.state == Activity.IDLE and scene.pearl_matrix.settled:
                    break
            self.assertEqual(scene.behavior.state, Activity.IDLE)
            self.assertIsNone(scene.pearl_matrix.extracted)
            revision = scene.pearl_matrix.revision
            for _ in range(120):
                scene.step()
            self.assertEqual(scene.pearl_matrix.revision, revision)

    def test_zero_probability_or_missing_curve_keeps_plain_reading(self):
        for probability, curve in ((0., True), (1., False)):
            scene = self.scene(probability)
            if not curve:
                scene.pearl_playback_curve = None
            self.assertIsNone(self.observe(scene).playback)
            self.assertTrue(1600 <= scene.behavior.duration <= 2400)

    def test_long_playback_loops_curve_without_fading_at_each_track_end(self):
        curve = SpectrumCurve(tuple(i/79 for i in range(80)), 2.)
        playback = PearlPlayback(curve, 1.25, 4800)
        for tick in range(1, 4801):
            playback.step()
            self.assertAlmostEqual(playback.strength, curve.sample((1.25+tick/40) % 2.))
            if 20 <= tick <= 4780:
                self.assertEqual(playback.fade, 1.)
        self.assertEqual(playback.fade, 0.)

    def test_normal_pearl_reading_does_not_roll_playback(self):
        scene = self.scene()
        scene.observe_pearl('recall')
        with patch.object(scene.behavior.playback_random, 'random') as choose:
            for _ in range(1600):
                scene.step()
                if scene.behavior.state == Activity.OBSERVE:
                    break
            self.assertEqual(scene.behavior.state, Activity.OBSERVE)
            choose.assert_not_called()
            self.assertIsNone(scene.observed_pearl.playback)

    def test_cancel_drag_disable_and_reset_clear_playback(self):
        for action in ('cancel', 'drag', 'disable', 'reset'):
            with self.subTest(action=action):
                scene = self.scene()
                pearl = self.observe(scene)
                if action == 'cancel':
                    scene.stop()
                elif action == 'drag':
                    scene.drag.set_enabled(True)
                    scene.drag.press(scene.body.chunks[0].position, lambda _: True)
                elif action == 'disable':
                    scene.set_pearl_matrix(False)
                else:
                    scene.reset()
                if action in ('cancel', 'drag'):
                    self.assertIsNone(pearl.playback)
                self.assertTrue(scene.pearl_matrix is None or scene.pearl_matrix.extracted is None
                                or scene.pearl_matrix.extracted.playback is None)

    def test_projection_opacity_controls_effect_and_renderer_does_not_advance_time(self):
        scene = self.scene()
        pearl = self.observe(scene)
        for _ in range(30):
            scene.step()
        renderer = OracleRenderer()
        ticks = pearl.playback.ticks
        images = []
        for opacity in (0., .5, 1.):
            image = QImage(32, 32, QImage.Format.Format_ARGB32)
            image.fill(QColor('transparent'))
            painter = QPainter(image)
            painter.translate(16-pearl.position.x, 16-pearl.position.y)
            renderer.draw_pearl_playback(painter, pearl, opacity=opacity)
            painter.end()
            images.append(sum(image.pixelColor(x, y).alpha() for x in range(32) for y in range(32)))
        self.assertEqual(images[0], 0)
        self.assertGreater(images[1], 0)
        self.assertGreater(images[2], images[1])
        self.assertEqual(pearl.playback.ticks, ticks)

    def test_probability_validation(self):
        for value in (-.01, 1.01, True, float('nan')):
            with self.assertRaises(ValueError):
                replace(OracleConfig(), pearl_playback_probability=value)

    def test_pause_and_resume_freeze_playback_time(self):
        scene = self.scene()
        pearl = self.observe(scene)
        clock = FixedStepper(40)
        clock.paused = True
        ticks = pearl.playback.ticks
        clock.advance(1., scene.step)
        self.assertEqual(pearl.playback.ticks, ticks)
        clock.paused = False
        clock.advance(.025, scene.step)
        self.assertEqual(pearl.playback.ticks, ticks+1)

    def test_desktop_resize_preserves_curve_and_rng_but_clears_active_effect(self):
        from rw_creature_pet.oracle.desktop import OracleDesktopMotion, OracleDesktopViewport
        scene = self.scene()
        self.observe(scene)
        new = OracleDesktopMotion(scene.config, OracleDesktopViewport(0, 0, 1280, 720), scene).scene
        self.assertIs(new.pearl_playback_curve, scene.pearl_playback_curve)
        self.assertEqual(new.behavior.playback_random.getstate(), scene.behavior.playback_random.getstate())
        self.assertIsNone(new.pearl_matrix.extracted)
        new.reset()
        self.assertIs(new.pearl_playback_curve, scene.pearl_playback_curve)

    def test_pulse_alone_reuses_settled_body_cache(self):
        scene = OracleScene(OracleConfig(pearl_matrix_enabled=True, halo_enabled=False))
        for _ in range(900):
            scene.step()
        self.assertTrue(scene.appearance.sleeping)
        pearl = scene.pearl_matrix.extract(scene.pearl_matrix.pearls[0].slot)
        pearl.start_playback(SpectrumCurve((.8,)*800, 20.), 1., 200)
        renderer = OracleRenderer()
        image = QImage(960, 600, QImage.Format.Format_ARGB32_Premultiplied)
        painter = QPainter(image)
        try:
            renderer.draw(painter, scene)
            frame, revision = renderer._frame, scene.appearance.revision
            for _ in range(40):
                scene.step()
                renderer.draw(painter, scene)
                self.assertIs(renderer._frame, frame)
            self.assertEqual(scene.appearance.revision, revision)
        finally:
            painter.end()


if __name__ == '__main__':
    unittest.main()
