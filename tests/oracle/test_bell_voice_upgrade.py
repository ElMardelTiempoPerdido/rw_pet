"""Bell 增益升级、重复调用与失败恢复，使用隔离的游戏和缓存目录"""
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import wave

import numpy as np

from rw_creature_pet.config import AppConfig
from rw_creature_pet.oracle.audio import assets
from rw_creature_pet.oracle.audio.bell_cache import cache_directory
from rw_creature_pet.oracle.audio.processing import prepare_clips
from rw_creature_pet.oracle.audio.voice import BELL_VOICE_CLIPS
from tests.oracle.test_voice_assets import interview_bytes


def pcm(path):
    with wave.open(str(path), 'rb') as audio:
        return audio.getparams(), np.frombuffer(audio.readframes(audio.getnframes()), dtype='<i2')


class BellVoiceUpgradeTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(TemporaryDirectory()))
        self.enterContext(patch.dict('os.environ', {'LOCALAPPDATA': str(self.root/'local')}))
        self.game = self.root/'game'
        self.bundle = self.game/'RainWorld_Data/StreamingAssets/AssetBundles/loadedsoundeffects'
        self.bundle.parent.mkdir(parents=True)
        self.bundle.write_bytes(b'fixture source fingerprint')
        self.cache = self.root/'local/rw_creature_pet/voices'
        base = AppConfig()
        self.config = replace(base, game_dir=self.game, oracle=replace(base.oracle, voice='bell', voice_directory='auto'))
        self.wav = interview_bytes()
        self.addCleanup(assets.forget_prepared_bell_voice, self.game)

    def make_v2(self, version=2):
        # 用旧配方生成已量化的完整十段，清单结构保持发布过的 v2 格式
        stat = self.bundle.stat()
        identity = dict(source=str(self.bundle.resolve()), size=stat.st_size, mtime_ns=stat.st_mtime_ns,
            kind='bundle', processing_version=version,
            clips=[[c.clip_id, c.start, c.end] for c in BELL_VOICE_CLIPS])
        root = cache_directory(self.cache, identity)
        source = self.root/'source.wav'
        source.write_bytes(self.wav)
        with patch('rw_creature_pet.oracle.audio.processing.BELL_VOICE_GAIN', 1.):
            manifest = prepare_clips(source, root)
        for name in ('processing_version', 'linear_gain', 'gain_db'):
            manifest.pop(name, None)
        manifest['cache_identity'] = identity
        for entry in manifest['clips']:
            entry['sha256'] = sha256((root/entry['file']).read_bytes()).hexdigest()
        (root/'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
        return root

    def test_v2_upgrade_matches_fresh_prepare_without_unpacking_or_touching_old_files(self):
        old = self.make_v2()
        original = {p.name: p.read_bytes() for p in old.iterdir() if p.is_file()}
        with patch.object(assets, '_extract_interview', side_effect=AssertionError('must reuse v2')), \
             patch.object(assets, 'prepare_clips', side_effect=AssertionError('must only apply gain')):
            upgraded = assets.ensure_bell_voice(self.game)
        self.assertNotEqual(old, upgraded)
        self.assertEqual(original, {p.name: p.read_bytes() for p in old.iterdir() if p.is_file()})
        with patch.object(assets, '_extract_interview', return_value=self.wav):
            fresh = assets.ensure_bell_voice(self.game, cache_root=self.root/'fresh')
        for clip in BELL_VOICE_CLIPS:
            self.assertEqual((upgraded/clip.filename).read_bytes(), (fresh/clip.filename).read_bytes())
            before_params, before = pcm(old/clip.filename)
            after_params, after = pcm(upgraded/clip.filename)
            self.assertEqual(before_params, after_params)
            np.testing.assert_array_equal(after, np.rint(before.astype(np.float64)*.2).astype('<i2'))
        manifest = json.loads((upgraded/'manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(manifest['processing_version'], 3)
        self.assertEqual(manifest['linear_gain'], .2)
        self.assertEqual(manifest['upgraded_from']['processing_version'], 2)
        self.assertEqual(manifest['cache_identity']['linear_gain'], .2)

    def test_restart_validates_new_cache_without_reapplying_gain(self):
        self.make_v2()
        paths, error = assets.prepare_bell_voice(self.config)
        self.assertFalse(error)
        expected = {name: path.read_bytes() for name, path in paths.items()}
        assets.forget_prepared_bell_voice(self.game)  # 模拟新进程
        with patch.object(assets, '_extract_interview', side_effect=AssertionError('warm extract')), \
             patch.object(assets, 'prepare_clips', side_effect=AssertionError('warm processing')), \
             patch.object(assets, 'upgrade_v2_cache', side_effect=AssertionError('warm upgrade')):
            again, error = assets.prepare_bell_voice(self.config)
        self.assertFalse(error)
        self.assertEqual(expected, {name: path.read_bytes() for name, path in again.items()})

    def test_switching_reuses_memory_but_explicit_refresh_repairs_corruption(self):
        self.make_v2()
        paths, error = assets.prepare_bell_voice(self.config)
        self.assertFalse(error)
        expected = paths['bell_01'].read_bytes()
        with patch.object(assets, '_find_source', side_effect=AssertionError('switch source check')), \
             patch.object(assets, '_cache_ready', side_effect=AssertionError('switch cache check')), \
             patch.object(assets, 'ensure_bell_voice', side_effect=AssertionError('switch preparation')):
            for _ in range(4):
                again, error = assets.prepare_bell_voice(self.config)
                self.assertFalse(error)
                self.assertEqual(again, paths)
                again.clear()  # 调用方不能改坏保存的路径表
        paths['bell_01'].write_bytes(b'corrupt')
        assets.forget_prepared_bell_voice(self.game)
        repaired, error = assets.prepare_bell_voice(self.config)
        self.assertFalse(error)
        self.assertEqual(repaired['bell_01'].read_bytes(), expected)

    def test_other_character_initializes_existing_bell_and_absent_cache_stays_lazy(self):
        other = replace(self.config, oracle=replace(self.config.oracle, voice='none'))
        with patch.object(assets, 'ensure_bell_voice', side_effect=AssertionError('unused voice extraction')):
            self.assertIsNone(assets.prepare_existing_bell_voice(other))
        with patch.object(assets, '_find_source', side_effect=AssertionError('repeat startup probe')):
            self.assertIsNone(assets.prepare_existing_bell_voice(other))
        # 首次主动选择仍能创建缓存，不把先前的未初始化状态视为失败
        with patch.object(assets, '_extract_interview', return_value=self.wav):
            paths, error = assets.prepare_bell_voice(self.config)
        self.assertFalse(error)
        assets.forget_prepared_bell_voice(self.game)
        existing, error = assets.prepare_existing_bell_voice(other)
        self.assertFalse(error)
        self.assertEqual(existing, paths)

    def test_existing_v2_is_upgraded_for_other_character(self):
        old = self.make_v2()
        other = replace(self.config, oracle=replace(self.config.oracle, voice='prince'))
        with patch.object(assets, '_extract_interview', side_effect=AssertionError('v2 reuse')):
            paths, error = assets.prepare_existing_bell_voice(other)
        self.assertFalse(error)
        self.assertNotEqual(paths['bell_01'].parent, old)
        self.assertEqual(other.oracle.voice, 'prince')

    def test_v1_corrupt_or_source_mismatched_cache_rebuilds(self):
        for case in ('v1', 'corrupt', 'changed source', 'already attenuated'):
            with self.subTest(case=case), TemporaryDirectory() as directory:
                self.cache = Path(directory)
                old = self.make_v2(version=1 if case == 'v1' else 2)
                if case == 'corrupt':
                    (old/'bell_01.wav').write_bytes(b'broken')
                elif case == 'changed source':
                    self.bundle.write_bytes(b'updated game bundle')
                elif case == 'already attenuated':
                    manifest = json.loads((old/'manifest.json').read_text(encoding='utf-8'))
                    manifest['linear_gain'] = .2
                    (old/'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
                with patch.object(assets, '_extract_interview', return_value=self.wav) as extract:
                    new = assets.ensure_bell_voice(self.game, cache_root=self.cache)
                extract.assert_called_once()
                self.assertNotEqual(new, old)

    def test_failed_upgrade_publishes_nothing_and_explicit_retry_succeeds(self):
        old = self.make_v2()
        def fail(*args, **kwargs):
            output = args[2]
            output.mkdir(parents=True)
            (output/'bell_01.wav').write_bytes(b'partial')
            raise OSError('upgrade interrupted')
        with patch.object(assets, 'upgrade_v2_cache', side_effect=fail):
            paths, error = assets.prepare_bell_voice(self.config)
        self.assertEqual(paths, {})
        self.assertIn('upgrade interrupted', error)
        self.assertEqual(list(self.cache.iterdir()), [old])
        with patch.object(assets, 'ensure_bell_voice', side_effect=AssertionError('no automatic retry loop')):
            self.assertEqual(assets.prepare_bell_voice(self.config), (paths, error))
        assets.forget_prepared_bell_voice(self.game)
        paths, error = assets.prepare_bell_voice(self.config)
        self.assertFalse(error)
        self.assertEqual(len(paths), 10)

    def test_known_v2_override_upgrades_but_user_files_are_not_attenuated(self):
        old = self.make_v2()
        config = replace(self.config, oracle=replace(self.config.oracle, voice_directory=str(old)))
        with patch.object(assets, '_extract_interview', side_effect=AssertionError('v2 reuse')):
            paths, error = assets.prepare_bell_voice(config)
        self.assertFalse(error)
        self.assertNotEqual(paths['bell_01'].parent, old)
        with patch.object(assets, '_is_managed_v2', side_effect=AssertionError('repeat managed check')), \
             patch.object(assets, 'ensure_bell_voice', side_effect=AssertionError('repeat managed upgrade')):
            self.assertEqual(assets.prepare_bell_voice(config), (paths, ''))
        custom = self.root/'custom'
        custom.mkdir()
        for clip in BELL_VOICE_CLIPS:
            (custom/clip.filename).write_bytes(paths[clip.clip_id].read_bytes())
        config = replace(self.config, oracle=replace(self.config.oracle, voice_directory=str(custom)))
        with patch.object(assets, 'ensure_bell_voice', side_effect=AssertionError('user files')):
            selected, error = assets.prepare_bell_voice(config)
        self.assertFalse(error)
        self.assertEqual(selected['bell_01'].parent, custom)
        self.assertEqual(selected['bell_01'].read_bytes(), paths['bell_01'].read_bytes())

    def test_partial_publish_is_not_valid_and_retry_completes_all_files(self):
        old = self.make_v2()
        original_replace = Path.replace
        def fail_second_file(path, target):
            if path.name == 'bell_02_01.wav':
                raise OSError('interrupted publish')
            return original_replace(path, target)
        with patch.object(Path, 'replace', fail_second_file):
            with self.assertRaisesRegex(assets.VoiceAssetError, 'interrupted publish'):
                assets.ensure_bell_voice(self.game)
        _, _, identity = assets._source_identity(self.game)
        partial = cache_directory(self.cache, identity)
        self.assertFalse(assets._cache_ready(partial, identity))
        self.assertFalse((partial/'manifest.json').exists())
        with patch.object(assets, '_extract_interview', side_effect=AssertionError('reuse v2 on retry')):
            repaired = assets.ensure_bell_voice(self.game)
        self.assertEqual(repaired, partial)
        self.assertTrue(assets._cache_ready(repaired, identity))
        self.assertTrue((old/'manifest.json').is_file())

    def test_switching_game_directory_does_not_reuse_another_games_cache(self):
        self.make_v2()
        first, error = assets.prepare_bell_voice(self.config)
        self.assertFalse(error)
        other_game = self.root/'other-game'
        bundle = other_game/'RainWorld_Data/StreamingAssets/AssetBundles/loadedsoundeffects'
        bundle.parent.mkdir(parents=True)
        bundle.write_bytes(self.bundle.read_bytes())
        other = replace(self.config, game_dir=other_game)
        with patch.object(assets, '_extract_interview', return_value=self.wav) as extract:
            second, error = assets.prepare_bell_voice(other)
        self.assertFalse(error)
        extract.assert_called_once()
        self.assertNotEqual(first['bell_01'].parent, second['bell_01'].parent)
        assets.forget_prepared_bell_voice(other_game)

    def test_gain_is_part_of_disk_and_memory_identity(self):
        self.make_v2()
        paths, error = assets.prepare_bell_voice(self.config)
        self.assertFalse(error)
        with patch.object(assets, 'BELL_VOICE_GAIN', .3):
            changed, error = assets.prepare_bell_voice(self.config)
        self.assertFalse(error)
        self.assertNotEqual(paths['bell_01'], changed['bell_01'])
        old = self.make_v2()
        _, before = pcm(old/'bell_01.wav')
        _, after = pcm(changed['bell_01'])
        np.testing.assert_array_equal(after, np.rint(before.astype(np.float64)*.3).astype('<i2'))


if __name__ == '__main__':
    unittest.main()
