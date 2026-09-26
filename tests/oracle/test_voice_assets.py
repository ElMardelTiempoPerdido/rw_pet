"""语音冷启动、缓存恢复与自定义素材兼容；不读取本机游戏或播放声音。"""
from dataclasses import replace
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import wave

from rw_creature_pet.config import AppConfig
from rw_creature_pet.oracle.config import OracleConfig
from rw_creature_pet.oracle.voice import BELL_VOICE_CLIPS, BELL_VOICE_SOURCES
from rw_creature_pet.oracle.voice_processing import prepare_clips
from rw_creature_pet.oracle.voice_assets import (LEGACY_DIRECTORY, VoiceAssetError, _extract_interview,
                                                _find_source, ensure_bell_voice, make_bell_voice_player)
from rw_creature_pet.interaction.voice import VoiceCue, VoiceCueChannel


def interview_bytes():
    import numpy as np
    rate = 1000
    t = np.arange(rate*43)/rate
    left = np.rint(np.sin(t*137)*1000)
    ratio = np.where((t >= 9.) & (t < 13.8), .9, 1.6)
    samples = np.column_stack((left, np.rint(left*ratio))).astype('<i2')
    output = io.BytesIO()
    with wave.open(output, 'wb') as audio:
        audio.setparams((2, 2, rate, 0, 'NONE', 'not compressed'))
        audio.writeframes(samples.tobytes())
    return output.getvalue()


class VoiceAssetsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.wav = interview_bytes()

    def setUp(self):
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.game = self.root/'game'
        self.cache = self.root/'cache'
        self.streaming = self.game/'RainWorld_Data/StreamingAssets'
        self.bundle = self.streaming/'AssetBundles/loadedsoundeffects'
        self.bundle.parent.mkdir(parents=True)
        self.bundle.write_bytes(b'fake bundle identity')
        self.loose = self.streaming/'loadedsoundeffects/RWTW_ATalkShow.wav'
        self.loose.parent.mkdir()
        self.loose.touch()  # 复现游戏的空占位文件。

    def prepare(self):
        with patch('rw_creature_pet.oracle.voice_assets._extract_interview', return_value=self.wav) as extract:
            directory = ensure_bell_voice(self.game, cache_root=self.cache)
        return directory, extract.call_count

    def test_cold_prepare_matches_reviewed_ranges_and_hot_cache_does_no_processing(self):
        directory, calls = self.prepare()
        self.assertEqual(calls, 1)
        manifest = json.loads((directory/'manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(len(list(directory.glob('*.wav'))), 10)
        self.assertFalse((directory/'RWTW_ATalkShow.wav').exists())
        self.assertFalse((directory/'bell_04.wav').exists())
        self.assertEqual(manifest['source_clips'][3]['duration_seconds'], 10.3)
        self.assertEqual(manifest['source_clips'][3]['processing']['full_until_seconds'], 1.5)
        self.assertEqual(manifest['source_clips'][3]['processing']['crossfade_until_seconds'], 1.7)
        self.assertEqual(manifest['source_clips'][4]['processing']['crossfade_until_seconds'], .7)
        self.assertEqual([c['duration_seconds'] for c in manifest['clips']],
                         [2.5, 1.88, 1.7, 1.52, 1.37, 4.18, 3.97, 2.15, 3.07, 2.53])
        for clip in BELL_VOICE_CLIPS:
            with wave.open(str(directory/clip.filename), 'rb') as audio:
                self.assertEqual(audio.getnframes(), round(clip.duration*1000))
                self.assertEqual((audio.getnchannels(), audio.getsampwidth()), (2, 2))
        with patch('rw_creature_pet.oracle.voice_assets._extract_interview', side_effect=AssertionError('warm extract')), \
             patch('rw_creature_pet.oracle.voice_assets.prepare_clips', side_effect=AssertionError('warm processing')):
            self.assertEqual(ensure_bell_voice(self.game, cache_root=self.cache), directory)

    def test_corrupt_missing_or_partial_cache_is_rebuilt(self):
        directory, _ = self.prepare()
        target = directory/'bell_04_02.wav'
        expected = target.read_bytes()
        corrupt = bytearray(expected)
        corrupt[-1] ^= 1
        target.write_bytes(corrupt)
        self.assertEqual(self.prepare(), (directory, 1))
        self.assertEqual(target.read_bytes(), expected)
        target.unlink()
        self.assertEqual(self.prepare(), (directory, 1))
        for manifest in ('[]', '{broken'):
            (directory/'manifest.json').write_text(manifest, encoding='utf-8')
            self.assertEqual(self.prepare(), (directory, 1))

    def test_source_and_processing_version_invalidate_cache(self):
        old, _ = self.prepare()
        self.bundle.write_bytes(b'changed game bundle identity')
        new, calls = self.prepare()
        self.assertNotEqual(new, old)
        self.assertEqual(calls, 1)
        with patch('rw_creature_pet.oracle.voice_assets.PROCESSING_VERSION', 999):
            future, calls = self.prepare()
        self.assertNotEqual(future, new)
        self.assertEqual(calls, 1)

    def test_failed_processing_never_publishes_partial_cache_and_can_retry(self):
        def fail(source, output):
            output.mkdir()
            (output/'bell_01.wav').write_bytes(b'incomplete')
            raise ValueError('processing failed')
        with patch('rw_creature_pet.oracle.voice_assets._extract_interview', return_value=self.wav), \
             patch('rw_creature_pet.oracle.voice_assets.prepare_clips', side_effect=fail):
            with self.assertRaisesRegex(VoiceAssetError, 'processing failed'):
                ensure_bell_voice(self.game, cache_root=self.cache)
        self.assertEqual(list(self.cache.iterdir()), [])
        directory, calls = self.prepare()
        self.assertEqual(calls, 1)
        self.assertTrue((directory/'manifest.json').is_file())

    def test_zero_byte_or_truncated_loose_file_falls_back_to_bundle(self):
        self.assertEqual(_find_source(self.game), (self.bundle, 'bundle'))
        self.loose.write_bytes(self.wav[:100])
        self.assertEqual(_find_source(self.game), (self.bundle, 'bundle'))
        self.loose.write_bytes(self.wav)
        self.assertEqual(_find_source(self.game), (self.loose, 'wav'))
        self.assertEqual(_extract_interview(self.loose, 'wav'), self.wav)

    def test_extracts_only_named_clip_and_reports_missing_content(self):
        class Object:
            def read(obj):
                return SimpleNamespace(samples={'RWTW_ATalkShow.wav': self.wav})
        env = SimpleNamespace(container={'Assets/LoadedSoundEffects/RWTW_ATalkShow.wav': Object()}, objects=[])
        with patch('UnityPy.load', return_value=env):
            self.assertEqual(_extract_interview(self.bundle, 'bundle'), self.wav)
        with patch('UnityPy.load', return_value=SimpleNamespace(container={}, objects=[])):
            with self.assertRaisesRegex(VoiceAssetError, 'RWTW_ATalkShow'):
                _extract_interview(self.bundle, 'bundle')

    def test_custom_directory_is_never_overwritten_and_legacy_missing_uses_auto(self):
        config_path = self.root/'config.toml'
        custom = self.root/'custom'
        custom.mkdir()
        for clip in BELL_VOICE_CLIPS:
            (custom/clip.filename).write_bytes(b'user audio')
        config = AppConfig(game_dir=self.game, oracle=OracleConfig(voice_directory='custom'))
        with patch('rw_creature_pet.oracle.voice_assets.ensure_bell_voice', side_effect=AssertionError('custom extraction')):
            player = make_bell_voice_player(config, config_path)
            self.assertFalse(player.asset_error)
            self.assertEqual(player.clips['bell_04_02'].read_bytes(), b'user audio')
            (custom/'bell_04_02.wav').unlink()
            failed = make_bell_voice_player(config, config_path)
            self.assertIn('bell_04_02.wav', failed.asset_error)
        for directory in ('auto', LEGACY_DIRECTORY):
            with patch('rw_creature_pet.oracle.voice_assets.ensure_bell_voice', return_value=custom) as ensure:
                config = replace(config, oracle=OracleConfig(voice_directory=directory))
                player = make_bell_voice_player(config, config_path)
                ensure.assert_called_once_with(self.game)
                self.assertFalse(player.asset_error)

    def test_missing_game_nonfatal_and_failure_reason_survives_drag_requests(self):
        config = AppConfig(game_dir=self.root/'missing')
        player = make_bell_voice_player(config)
        self.assertIn('game_dir', player.asset_error)
        original_error = player.error
        channel = VoiceCueChannel()
        channel.request(VoiceCue('bell_01', 2.5, 'drag'))
        player.sync(channel)
        self.assertEqual(player.error, original_error)
        self.assertIsNone(player._backend)
        self.assertIsNone(channel.pending)

    def test_geometry_preview_skips_extraction_and_debug_handoff_reuses_paths(self):
        config = AppConfig(game_dir=self.game)
        with patch('rw_creature_pet.oracle.voice_assets.ensure_bell_voice', side_effect=AssertionError('preview extraction')):
            preview = make_bell_voice_player(config, initialize=False)
            self.assertTrue(preview.asset_error)
            preview.clips = {'bell_01': self.root/'prepared.wav'}
            preview.asset_error = preview.error = ''
            debug = make_bell_voice_player(config, initialize=False, source=preview)
            self.assertEqual(debug.clips, preview.clips)
            self.assertIsNot(debug.clips, preview.clips)
            self.assertFalse(debug.asset_error)

    def test_splits_keep_all_samples_except_short_fades_and_do_not_repeat_cancellation(self):
        import numpy as np

        source = self.root/'interview.wav'
        source.write_bytes(self.wav)
        output = self.root/'prepared'
        manifest = prepare_clips(source, output)

        def samples(path):
            with wave.open(str(path), 'rb') as audio:
                return np.frombuffer(audio.readframes(audio.getnframes()), '<i2').reshape(-1, 2)

        for parent in BELL_VOICE_SOURCES:
            processed = samples(output/'source-clips'/parent.filename)
            raw = samples(output/'raw'/parent.filename)
            if parent.clip_id not in ('bell_04', 'bell_05'):
                np.testing.assert_array_equal(processed, raw)
            else:
                end = 1700 if parent.clip_id == 'bell_04' else 700
                np.testing.assert_array_equal(processed[end:], raw[end:])
                self.assertTrue(np.any(processed[:end] != raw[:end]))
            offset = 0
            children = [entry for entry in manifest['clips'] if entry['source_clip_id'] == parent.clip_id]
            for index, entry in enumerate(children):
                actual = samples(output/entry['file'])
                expected = processed[offset:offset+len(actual)]
                self.assertEqual(round(entry['source_offset_seconds']*1000), offset)
                start = 5 if index else 0
                end = len(actual)-5 if index < len(children)-1 else len(actual)
                np.testing.assert_array_equal(actual[start:end], expected[start:end])
                if start:
                    np.testing.assert_array_equal(actual[0], [0, 0])
                    self.assertTrue(np.all(np.abs(actual[:5]) <= np.abs(expected[:5])))
                if end < len(actual):
                    np.testing.assert_array_equal(actual[-1], [0, 0])
                    self.assertTrue(np.all(np.abs(actual[-5:]) <= np.abs(expected[-5:])))
                offset += len(actual)
            self.assertEqual(offset, len(processed))


if __name__ == '__main__':
    unittest.main()
