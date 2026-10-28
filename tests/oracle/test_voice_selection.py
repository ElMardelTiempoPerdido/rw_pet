"""语音属于角色行为，旧配置补齐不能让原本静音的角色开始发声"""
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from rw_creature_pet.config import AppConfig
from rw_creature_pet.oracle.config import OracleConfig
from rw_creature_pet.presets.personal import PersonalEntry
from rw_creature_pet.presets.profile import apply_profile, load_profile
from rw_creature_pet.presets.profile_library import ProfileLibrary
from rw_creature_pet.presets.startup import BELL_PROFILE_ID, default_bell, default_custom, default_prince
from rw_creature_pet.settings_store import SettingsStore


class VoiceSelectionTests(unittest.TestCase):
    def test_legacy_mapping_defaults_and_explicit_choices(self):
        for body, expected in (('bell', 'bell'), ('custom', 'none'), ('prince', 'none')):
            with self.subTest(body=body):
                self.assertEqual(OracleConfig.from_mapping({'body_appearance': body}).voice, expected)
                for source in ('bell', 'none'):
                    config = OracleConfig.from_mapping({'body_appearance': body, 'voice': source})
                    self.assertEqual(config.voice, source)
        for source in ('moon', '', None, [], True):
            with self.subTest(source=source), self.assertRaises(ValueError):
                OracleConfig(voice=source)

    def test_defaults_for_new_characters(self):
        self.assertEqual(default_bell(default_custom(AppConfig())).oracle.voice, 'bell')
        self.assertEqual(default_custom(AppConfig()).oracle.voice, 'none')
        self.assertEqual(default_prince(AppConfig()).oracle.voice, 'none')

    def test_existing_profiles_declare_voice_explicitly(self):
        profiles = list((Path(__file__).resolve().parents[2]/'presets/profiles').glob('*/profile.json'))
        self.assertGreater(len(profiles), 1)
        for path in profiles:
            data = json.loads(path.read_text(encoding='utf-8'))
            expected = 'bell' if data['id'] == BELL_PROFILE_ID else 'none'
            with self.subTest(profile=data['name']):
                self.assertEqual(data['config']['oracle']['voice'], expected)

    def test_settings_upgrade_and_restart_preserve_explicit_choice(self):
        with tempfile.TemporaryDirectory() as temp, patch(
                'rw_creature_pet.settings_store.load_defaults', return_value=AppConfig()):
            store = SettingsStore(Path(temp)/'settings.json')
            for body, expected in (('bell', 'bell'), ('custom', 'none'), ('prince', 'none')):
                store.path.write_text(json.dumps({'version': 1, 'config': {'oracle': {
                    'body_appearance': body, 'float_speed': 1.234}}}), encoding='utf-8')
                loaded = store.load()
                self.assertEqual(loaded.oracle.voice, expected)
                self.assertEqual(loaded.oracle.float_speed, 1.234)
                selected = 'none' if body == 'bell' else 'bell'
                store.save(replace(loaded, oracle=replace(loaded.oracle, voice=selected)))
                self.assertEqual(store.load().oracle.voice, selected)

    def test_personal_snapshots_upgrade_and_keep_overrides(self):
        for body, expected in (('bell', 'bell'), ('custom', 'none'), ('prince', 'none')):
            data = {'kind': 'profile', 'defaults': {'oracle.body_appearance': body},
                    'overrides': {'oracle.float_speed': 1.234}}
            entry = PersonalEntry.read(data)
            self.assertEqual(entry.values['oracle.voice'], expected)
            self.assertEqual(entry.values['oracle.float_speed'], 1.234)
            data['overrides']['oracle.voice'] = 'bell'
            self.assertEqual(PersonalEntry.read(data).values['oracle.voice'], 'bell')
        old_customized_bell = {'kind': 'profile', 'defaults': {'oracle.body_appearance': 'bell'},
                              'overrides': {'oracle.body_appearance': 'custom'}}
        entry = PersonalEntry.read(old_customized_bell)
        self.assertEqual(entry.defaults['oracle.voice'], 'bell')
        self.assertEqual(entry.values['oracle.voice'], 'none')

    def test_profile_roundtrip_and_legacy_import_ignore_character_name(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            library = ProfileLibrary(root/'profiles')
            for body, expected in (('bell', 'bell'), ('custom', 'none'), ('prince', 'none')):
                config = AppConfig(oracle=OracleConfig(body_appearance=body, voice='bell'))
                preset = library.export(config, '任意角色名')
                loaded = load_profile(preset.path)
                actual = apply_profile(AppConfig(oracle=OracleConfig(voice='none')), loaded, root/'cache')
                self.assertEqual(actual.oracle.voice, 'bell')
                document = json.loads(preset.path.read_text(encoding='utf-8'))
                del document['config']['oracle']['voice']
                preset.path.write_text(json.dumps(document, ensure_ascii=False), encoding='utf-8')
                self.assertEqual(load_profile(preset.path).config.oracle.voice, expected)


if __name__ == '__main__':
    unittest.main()
