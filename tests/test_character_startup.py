"""首次角色选择与旧 settings 的一次性、可回退升级"""
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from rw_creature_pet.config import AppConfig
from rw_creature_pet.presets.profile_library import ProfileLibrary
from rw_creature_pet.presets.startup import BELL_PROFILE_ID, prepare_character
from rw_creature_pet.settings_store import SettingsStore


class CharacterStartupTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.store = SettingsStore(self.root/'user/settings.json')
        self.library = ProfileLibrary(self.root/'profiles')
        self.defaults = AppConfig()
        self.bell_config = replace(self.defaults, oracle=replace(self.defaults.oracle,
            float_speed=1.3, pearl_matrix_count=7, colors=replace(self.defaults.oracle.colors, skin='#123456')))

    def prepare(self, config=None):
        return prepare_character(config or self.defaults, self.store,
                                 library=self.library, defaults=self.defaults)

    def save(self, result):
        key = result.state.active
        with self.store.preset_state(result.state.serialize(key, result.state.entries[key])):
            self.store.save(result.config)

    def test_fresh_install_selects_bundled_bell_by_id_even_if_renamed(self):
        other = replace(self.defaults, oracle=replace(self.defaults.oracle, body_appearance='custom'))
        self.library.export(other, 'AAA')
        bell = self.library.export(self.bell_config, '重命名后的铃', preset_id=BELL_PROFILE_ID)
        result = self.prepare()
        self.assertEqual(result.state.entries[result.state.active].source.id, bell.id)
        self.assertEqual(result.config.oracle.float_speed, 1.3)
        self.assertEqual(result.config.oracle.colors.skin, '#123456')
        self.assertFalse(result.notice)
        self.assertFalse(self.store.path.exists())
        self.save(result)
        self.assertFalse(self.prepare(self.store.load()).notice)

    def test_empty_library_creates_one_bell_from_defaults_and_selects_it(self):
        result = self.prepare()
        self.assertEqual(len(self.library.scan().presets), 1)
        self.assertEqual(result.config.oracle.body_appearance, 'bell')
        self.assertEqual(result.state.entries[result.state.active].source.id, BELL_PROFILE_ID)
        self.prepare()
        self.assertEqual(len(self.library.scan().presets), 1)

    def test_only_explicit_legacy_role_fields_become_overrides_and_only_once(self):
        bell = self.library.export(self.bell_config, 'Bell', preset_id=BELL_PROFILE_ID)
        original = bell.path.read_bytes(), bell.appearance.path.read_bytes()
        self.store.path.parent.mkdir(parents=True)
        self.store.path.write_text(json.dumps({'version': 1, 'config': {
            'oracle': {'pearl_matrix_count': 0, 'drag_reactions': {'voice_probability': 0.},
                       'colors': {'skin': '#abcdef'}},
            'interaction': {'hover_avoidance_enabled': False},
            'desktop': {'scale': 2.}, 'audio': {'volume': .17},
        }}), encoding='utf-8')
        with patch('rw_creature_pet.settings_store.load_defaults', return_value=self.defaults):
            loaded, first, _ = self.store.startup()
            self.assertFalse(first)
            pending = self.store.load_preset_state()['directory_migration']['raw_values']
            self.assertEqual(set(pending), {'oracle.pearl_matrix_count',
                'oracle.drag_reactions.voice_probability', 'interaction.hover_avoidance_enabled',
                'oracle.colors.skin'})
            # 模拟在配置自动补齐后退出，再启动时仍使用原始字段集合
            loaded, _, _ = SettingsStore(self.store.path).startup()
        result = self.prepare(loaded)
        self.assertTrue(result.notice)
        self.assertEqual(result.config.oracle.pearl_matrix_count, 0)
        self.assertEqual(result.config.oracle.drag_reactions.voice_probability, 0.)
        self.assertFalse(result.config.interaction.hover_avoidance_enabled)
        self.assertEqual(result.config.oracle.float_speed, 1.3)  # 未提供的字段采用角色默认值
        self.assertEqual(result.config.oracle.colors.skin, '#abcdef')  # 当前迁移同时保留旧外观
        self.assertEqual(result.config.desktop.scale, 2.)
        self.assertEqual(result.config.audio.volume, .17)
        entry = result.state.entries[result.state.active]
        self.assertEqual(entry.defaults['oracle.pearl_matrix_count'], 7)
        self.assertEqual(entry.overrides['oracle.pearl_matrix_count'], 0)
        self.assertEqual(entry.overrides['oracle.colors.skin'], '#abcdef')
        self.save(result)
        second = self.prepare(self.store.load())
        self.assertFalse(second.notice)
        entry = second.state.entries[second.state.active]
        entry.overrides.pop('oracle.pearl_matrix_count')
        second.config = replace(second.config, oracle=replace(second.config.oracle, pearl_matrix_count=7))
        self.save(second)
        self.assertEqual(self.prepare(self.store.load()).config.oracle.pearl_matrix_count, 7)
        from rw_creature_pet.presets.profile import load_profile
        baseline = load_profile(bell.path.parent/'original/profile.json')
        self.assertEqual(baseline.appearance.oracle.colors.skin, '#123456')
        self.assertEqual(baseline.config.oracle.pearl_matrix_count, 7)

    def test_saved_character_and_overrides_take_priority_over_bell(self):
        self.library.export(self.bell_config, 'Bell', preset_id=BELL_PROFILE_ID)
        other = self.library.export(replace(self.defaults, oracle=replace(self.defaults.oracle,
            body_appearance='custom', float_speed=.9)), 'Other')
        result = self.prepare()
        key, entry = result.state.from_preset('profile', other, result.config, self.root/'images')
        entry.overrides['oracle.float_speed'] = 1.1
        result.state.committed(key, entry)
        self.save(result)
        restored = self.prepare(self.store.load())
        self.assertEqual(restored.state.entries[restored.state.active].source.id, other.id)
        self.assertEqual(restored.config.oracle.float_speed, 1.1)

    def test_corrupt_current_is_reported_without_replacing_user_character(self):
        result = self.prepare()
        self.save(result)
        source = self.library.scan().presets[0].path
        source.write_text('{}', encoding='utf-8')
        with self.assertRaises(ValueError):
            self.prepare(self.store.load())
        self.assertEqual(source.read_text(encoding='utf-8'), '{}')
        self.assertEqual(len(self.library.scan().errors), 1)

    def test_failed_save_does_not_mark_pending_upgrade_complete(self):
        self.store.path.parent.mkdir(parents=True)
        self.store.path.write_text(json.dumps({'version': 1, 'config': {
            'oracle': {'float_speed': .9}}}), encoding='utf-8')
        result = self.prepare()
        before = self.store.path.read_bytes()
        with patch.object(self.store, '_write', side_effect=OSError('locked')):
            with self.assertRaises(OSError):
                self.save(result)
        self.assertEqual(self.store.path.read_bytes(), before)
        self.assertTrue(self.prepare().notice)
