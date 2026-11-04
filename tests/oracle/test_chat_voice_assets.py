"""本体 Chat / Prince Talk 语音、独立缓存、惰性准备和角色选择"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
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
from rw_creature_pet.oracle.assets import OracleAssets, resource_key
from rw_creature_pet.oracle.audio.assets import prepare_voice
from rw_creature_pet.oracle.audio.chat_assets import prepare_chat_voices
from rw_creature_pet.oracle.audio.playback import prepared_voice_error
from rw_creature_pet.oracle.audio.voice import CHAT_VOICE_CLIPS, GAME_VOICE_CLIPS, VOICE_CLIPS
from rw_creature_pet.oracle.config import DragReactionConfig, OracleConfig
from rw_creature_pet.oracle.interaction.drag_reactions import OracleDragReactions
from rw_creature_pet.presets.profile import load_profile
from rw_creature_pet.presets.profile_library import ProfileLibrary
from rw_creature_pet.resources.status import ResourceReport
from rw_creature_pet.settings_store import SettingsStore


class ChatVoiceAssetsTests(unittest.TestCase):
    def setUp(self):
        temp = self.enterContext(TemporaryDirectory())
        self.root = Path(temp)
        self.game = self.root/'game'
        self.cache = self.root/'cache'
        self.streaming = self.game/'RainWorld_Data/StreamingAssets'
        self.loose = self.streaming/'loadedsoundeffects'
        self.loose.mkdir(parents=True)
        self.bundle = self.streaming/'AssetBundles/loadedsoundeffects'
        self.bundle.parent.mkdir()
        self.bundle.write_bytes(b'bundle fixture')
        buf = io.BytesIO()
        with wave.open(buf, 'wb') as wav:
            wav.setparams((2, 2, 44100, 0, 'NONE', 'not compressed'))
            wav.writeframes(b'\x01\x00\x02\x00'*4410)
        self.wav = buf.getvalue()
        self.read_names = []
        test = self
        class Clip:
            def __init__(self, name):
                self.name = name
            def read(self):
                test.read_names.append(self.name)
                return SimpleNamespace(samples={self.name+'.wav': test.wav})
        self.env = SimpleNamespace(container={f'Assets/LoadedSoundEffects/{c.asset_name}.wav': Clip(c.asset_name)
            for clips in GAME_VOICE_CLIPS.values() for c in clips}, objects=[])

    def prepare(self, voices=('moon', 'pebbles')):
        with patch('UnityPy.load', return_value=self.env) as load:
            result = prepare_chat_voices(self.game, voices, cache_root=self.cache)
        return result, load.call_count

    def test_both_voices_load_bundle_once_and_warm_cache_never_decodes(self):
        result, loads = self.prepare()
        self.assertEqual(loads, 1)
        self.assertEqual(len(self.read_names), 10)
        for name, (paths, error) in result.items():
            self.assertFalse(error)
            self.assertEqual(set(paths), {c.clip_id for c in VOICE_CLIPS[name]})
            root = next(iter(paths.values())).parent
            self.assertEqual(len(list(root.glob('*.wav'))), 5)
            manifest = json.loads((root/'manifest.json').read_text(encoding='utf-8'))
            self.assertTrue(all('Chat' in c['asset'] for c in manifest['clips']))
            self.assertTrue(all(p.read_bytes() == self.wav for p in paths.values()))
        self.read_names.clear()
        self.assertEqual(self.prepare(), (result, 0))
        self.assertEqual(self.read_names, [])

    def test_missing_one_voice_does_not_disable_the_other_or_publish_partial_cache(self):
        del self.env.container['Assets/LoadedSoundEffects/MoonChat4.wav']
        result, loads = self.prepare()
        self.assertEqual(loads, 1)
        self.assertEqual(result['moon'][0], {})
        self.assertIn('MoonChat4', result['moon'][1])
        self.assertEqual(len(result['pebbles'][0]), 5)
        self.assertFalse(list(self.cache.glob('moon-*')))

    def test_prince_extracts_only_confirmed_22_clips_and_reuses_validated_cache(self):
        result, loads = self.prepare(('prince',))
        paths, error = result['prince']
        self.assertFalse(error)
        self.assertEqual(loads, 1)
        self.assertEqual(self.read_names, [f'RWTW_PrinceTalk1_{i:02}' for i in range(1, 23)])
        self.assertEqual(set(paths), {f'prince_talk_{i:02}' for i in range(1, 23)})
        self.assertTrue(all(p.read_bytes() == self.wav for p in paths.values()))
        self.read_names.clear()
        self.assertEqual(self.prepare(('prince',)), (result, 0))
        self.assertFalse(self.read_names)
        paths['prince_talk_22'].write_bytes(b'broken')
        self.assertEqual(self.prepare(('prince',))[1], 1)
        self.assertEqual(paths['prince_talk_22'].read_bytes(), self.wav)

    def test_missing_watcher_clip_does_not_block_base_game_voices(self):
        del self.env.container['Assets/LoadedSoundEffects/RWTW_PrinceTalk1_22.wav']
        with patch('UnityPy.load', return_value=self.env) as load:
            result = prepare_chat_voices(self.game, cache_root=self.cache)
        load.assert_called_once()
        self.assertEqual(set(result), set(GAME_VOICE_CLIPS))
        self.assertEqual(result['prince'][0], {})
        self.assertIn('RWTW_PrinceTalk1_22', result['prince'][1])
        self.assertFalse(list(self.cache.glob('prince-*')))
        for name in CHAT_VOICE_CLIPS:
            self.assertEqual(len(result[name][0]), 5)
            self.assertFalse(result[name][1])

    def test_prince_loose_audio_works_without_bundle_but_empty_placeholders_do_not(self):
        self.bundle.unlink()
        for clip in GAME_VOICE_CLIPS['prince']:
            (self.loose/(clip.asset_name+'.wav')).write_bytes(self.wav)
        result, loads = self.prepare(('prince',))
        self.assertEqual(loads, 0)
        self.assertEqual(len(result['prince'][0]), 22)
        self.assertFalse(result['prince'][1])
        (self.loose/'RWTW_PrinceTalk1_01.wav').write_bytes(b'')
        result, loads = self.prepare(('prince',))
        self.assertEqual(loads, 0)
        self.assertEqual(result['prince'][0], {})
        self.assertIn('RWTW_PrinceTalk1_01', result['prince'][1])

    def test_valid_loose_files_and_zero_byte_fallback(self):
        for clips in CHAT_VOICE_CLIPS.values():
            for clip in clips:
                (self.loose/(clip.asset_name+'.wav')).write_bytes(self.wav)
        (self.loose/'MoonChat1.wav').write_bytes(b'')
        result, loads = self.prepare()
        self.assertEqual(loads, 1)
        self.assertEqual(self.read_names, ['MoonChat1'])
        self.assertFalse(result['moon'][1])
        self.assertFalse(result['pebbles'][1])
        (self.loose/'MoonChat1.wav').write_bytes(self.wav)
        self.assertEqual(self.prepare()[1], 0)

    def test_corrupt_cache_and_source_change_rebuild(self):
        result, _ = self.prepare(('moon',))
        paths, _ = result['moon']
        path = paths['moon_chat_01']
        path.write_bytes(b'broken')
        self.assertEqual(self.prepare(('moon',))[1], 1)
        self.assertEqual(path.read_bytes(), self.wav)
        (path.parent/'manifest.json').write_text('[]', encoding='utf-8')
        self.assertEqual(self.prepare(('moon',))[1], 1)
        self.bundle.write_bytes(b'updated bundle fixture')
        new, calls = self.prepare(('moon',))
        self.assertEqual(calls, 1)
        self.assertNotEqual(new['moon'][0]['moon_chat_01'].parent, path.parent)

    def test_only_selected_voice_is_prepared_and_bell_directory_does_not_affect_chat(self):
        for name in GAME_VOICE_CLIPS:
            config = AppConfig(game_dir=self.game, oracle=OracleConfig(voice=name, voice_directory='missing bell override'))
            with patch('rw_creature_pet.oracle.audio.chat_assets.prepare_chat_voices',
                       return_value={name: ({name: Path('chat.wav')}, '')}) as prepare, \
                 patch('rw_creature_pet.oracle.audio.assets.ensure_bell_voice') as bell:
                self.assertFalse(prepare_voice(config)[1])
                prepare.assert_called_once_with(self.game, (name,))
                bell.assert_not_called()
                self.assertTrue(prepare_voice(config, initialize=False)[1])
                prepare.reset_mock()
                self.assertEqual(prepare_voice(replace(config, oracle=replace(config.oracle, voice='none'))), ({}, ''))
                prepare.assert_not_called()

    def test_selected_clip_pool_is_independent_and_avoids_immediate_repetition(self):
        reactions = OracleDragReactions(DragReactionConfig(voice_probability=1.))
        for name in GAME_VOICE_CLIPS:
            previous = None
            for _ in range(20):
                reactions.voice.cancel()
                reactions._try_voice(name)
                cue = reactions.voice.pending
                self.assertIn(cue.clip_id, {c.clip_id for c in VOICE_CLIPS[name]})
                self.assertNotEqual(cue.clip_id, previous)
                previous = cue.clip_id

    def test_profile_and_settings_roundtrip_preserve_new_choices(self):
        store = SettingsStore(self.root/'settings.json')
        library = ProfileLibrary(self.root/'profiles')
        with patch('rw_creature_pet.settings_store.load_defaults', return_value=AppConfig()):
            for name in GAME_VOICE_CLIPS:
                config = AppConfig(oracle=OracleConfig(voice=name, body_appearance='custom'))
                store.save(config)
                self.assertEqual(store.load().oracle.voice, name)
                exported = library.export(config, 'Any name')
                self.assertEqual(load_profile(exported.path).config.oracle.voice, name)

    def test_cached_voice_results_merge_without_leaking_another_voice_error(self):
        config = AppConfig(oracle=OracleConfig(voice='moon'))
        def assets(name, error=''):
            report = ResourceReport()
            report.record(name+'_voice', error=error)
            paths = {} if error else {c.clip_id: Path(c.filename) for c in VOICE_CLIPS[name]}
            return OracleAssets(None, '', paths, error, report, resource_key(config))
        moon, pebbles = assets('moon'), assets('pebbles', 'missing pebbles')
        self.assertFalse(pebbles.reusable(config))
        pebbles.include_checked_voices(moon)
        self.assertTrue(pebbles.reusable(config))
        self.assertEqual(prepared_voice_error(pebbles, 'moon'), '')
        self.assertEqual(prepared_voice_error(pebbles, 'pebbles'), 'missing pebbles')
        self.assertEqual(prepared_voice_error(pebbles, 'none'), '')
        other = assets('moon')
        other.source_key = ('another game', 'auto')
        self.assertNotIn('pebbles_voice', other.include_checked_voices(pebbles).resources.items)


if __name__ == '__main__':
    unittest.main()
