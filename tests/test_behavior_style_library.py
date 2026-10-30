"""风格定义合并、作用域、版本和保存/分享兼容性"""
from itertools import product
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from rw_creature_pet.config import AppConfig
from rw_creature_pet.oracle.style_config import DIMENSIONS
from rw_creature_pet.presets.behavior_styles import (BehaviorStyleLibrary, DIMENSION_PATHS, SELECTION_PATHS,
                                                     default_style_directory)
from rw_creature_pet.presets.common import get_value
from rw_creature_pet.presets.fields import paths_for
from rw_creature_pet.presets.registry import FieldScope
from rw_creature_pet.presets.profile import profile_mapping, validate_config
from rw_creature_pet.presets.profile_library import ProfileLibrary
from rw_creature_pet.settings_store import SettingsStore


class BehaviorStyleLibraryTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        shutil.copy2(default_style_directory()/'builtin.toml', self.root/'builtin.toml')
        self.library = BehaviorStyleLibrary.load(self.root)

    def local(self, text):
        (self.root/'local.toml').write_text('format_version = 1\n'+text, encoding='utf-8')
        return BehaviorStyleLibrary.load(self.root)

    def test_complete_disjoint_profile_scope_and_all_combinations(self):
        self.assertFalse(self.library.errors)
        self.assertEqual(len(self.library.styles), 21)
        paths = [p for group in DIMENSION_PATHS.values() for p in group]
        self.assertEqual(len(paths), 140)
        self.assertEqual(len(set(paths)), 140)
        self.assertTrue(set(paths+list(SELECTION_PATHS)) <= set(paths_for(FieldScope.PROFILE)))
        config = AppConfig()
        for combination in product(*(self.library.for_dimension(d) for d in DIMENSIONS)):
            for style in combination:
                config = style.apply(config)
            for style in combination:
                for path, value in style.values.items():
                    self.assertEqual(get_value(config, path), value)

    def test_partial_local_override_rename_and_new_complete_style(self):
        original = self.library.find('mouse_attention.curious', 'mouse_attention')
        renamed = self.local('''[[styles]]
id = "mouse_attention.curious"
name_zh = "我的名称"
''').find(original.id, original.dimension)
        self.assertEqual(renamed.version, original.version)
        self.assertEqual(renamed.name_zh, '我的名称')
        changed = self.local('''[[styles]]
id = "mouse_attention.curious"
[styles.values]
"interaction.hover_radius" = 210
''').find(original.id, original.dimension)
        self.assertNotEqual(changed.version, original.version)
        self.assertEqual(changed.values['interaction.hover_dwell_seconds'], original.values['interaction.hover_dwell_seconds'])
        data = (self.root/'builtin.toml').read_text(encoding='utf-8')
        start = data.index('[[styles]]\nid = "mouse_attention.curious"')
        end = data.index('[[styles]]', start+10)
        custom = data[start:end].replace('mouse_attention.curious', 'local.curious')
        library = self.local(custom)
        self.assertFalse(library.errors)
        self.assertEqual(len(library.styles), 22)

    def test_bad_rows_do_not_erase_valid_builtins_or_other_overrides(self):
        for bad in ('"desktop.scale" = 3', '"interaction.hover_radius" = true',
                    '"interaction.hover_probability" = 1.5', '"interaction.hover_radius" = nan'):
            library = self.local('''[[styles]]
id = "mouse_attention.curious"
[styles.values]
'''+bad+'''
[[styles]]
id = "daily_activity.still"
name_zh = "有效调整"
''')
            self.assertEqual(len(library.styles), 21)
            self.assertTrue(library.errors)
            self.assertEqual(library.find('daily_activity.still', 'daily_activity').name_zh, '有效调整')
            self.assertEqual(library.find('mouse_attention.curious', 'mouse_attention'),
                             self.library.find('mouse_attention.curious', 'mouse_attention'))
        for text in ('styles = "bad"', '[[styles]]\nid = "new"',
                     '[[styles]]\nid = "daily_activity.still"\ndimension = "drift"',
                     '[[styles]]\nid = "mouse_attention.curious"\n[[styles]]\nid = "mouse_attention.curious"'):
            self.assertTrue(self.local(text).errors)

    def test_old_config_preserves_values_and_does_not_infer_markers(self):
        style = self.library.find('drift.continuous', 'drift')
        original = style.apply(AppConfig())
        data = profile_mapping(original)
        del data['oracle']['behavior_styles']
        loaded = validate_config(data)
        self.assertEqual(loaded.oracle.drift, original.oracle.drift)
        self.assertFalse(loaded.oracle.behavior_styles.drift.id)
        settings = SettingsStore(self.root/'settings.json')
        settings.save(loaded)
        self.assertEqual(settings.load().oracle.behavior_styles, loaded.oracle.behavior_styles)

    def test_snapshot_roundtrip_settings_profile_and_share_without_library(self):
        config = AppConfig()
        for dimension in DIMENSIONS:
            config = self.library.for_dimension(dimension)[-1].apply(config)
        store = SettingsStore(self.root/'settings.json')
        store.save(config)
        self.assertEqual(store.load().oracle.behavior_styles, config.oracle.behavior_styles)
        library = ProfileLibrary(self.root/'profiles')
        preset = library.export(config, '风格角色')
        archive = library.export_share(config, self.root/'share.zip', name=preset.name, preset_id=preset.id)
        (self.root/'builtin.toml').unlink()
        imported = ProfileLibrary(self.root/'received').import_file(archive)
        self.assertEqual(profile_mapping(imported.config), profile_mapping(config))

    def test_old_attention_library_adds_only_new_fields_and_preserves_optional_values(self):
        text = (self.root/'builtin.toml').read_text(encoding='utf-8')
        legacy = '\n'.join(line for line in text.splitlines() if not line.startswith('"interaction.petting_'))
        (self.root/'builtin.toml').write_text(legacy, encoding='utf-8')
        library = BehaviorStyleLibrary.load(self.root)
        self.assertFalse(library.errors)
        self.assertEqual(library.styles, self.library.styles)
        start = legacy.index('[[styles]]\nid = "mouse_attention.curious"')
        end = legacy.index('[[styles]]', start+10)
        custom = legacy[start:end].replace('mouse_attention.curious', 'local.curious')
        custom += '\n"interaction.petting_seconds" = 3.25\n'
        result = self.local(custom)
        self.assertFalse(result.errors)
        values = result.find('local.curious', 'mouse_attention').values
        self.assertEqual(values['interaction.petting_seconds'], 3.25)
        self.assertTrue(values['interaction.petting_enabled'])
        missing = '\n'.join(line for line in custom.splitlines() if not line.startswith('"interaction.hover_radius"'))
        self.assertTrue(self.local(missing).errors)

    def test_old_profile_retains_attention_values_and_style_marker(self):
        original = self.library.find('mouse_attention.curious', 'mouse_attention').apply(AppConfig())
        data = profile_mapping(original)
        for key in ('petting_enabled', 'petting_seconds', 'petting_grace_seconds'):
            del data['interaction'][key]
        data['oracle']['behavior_styles']['mouse_attention']['version'] = 'v1:'+'0'*64
        loaded = validate_config(data)
        self.assertEqual(loaded.interaction, original.interaction)
        self.assertEqual(loaded.oracle.behavior_styles.mouse_attention.id, 'mouse_attention.curious')
        self.assertEqual(loaded.oracle.behavior_styles.mouse_attention.version, 'v1:'+'0'*64)

    def test_single_executable_uses_bundled_defaults_and_external_local_file(self):
        bundled = self.root/'bundle/presets/behavior_styles'
        bundled.mkdir(parents=True)
        shutil.copy2(self.root/'builtin.toml', bundled/'builtin.toml')
        external = self.root/'installed/presets/behavior_styles'
        external.mkdir(parents=True)
        (external/'local.toml').write_text('''format_version = 1
[[styles]]
id = "mouse_attention.curious"
name_zh = "外部覆盖"
''', encoding='utf-8')
        with patch('sys.frozen', True, create=True), patch('sys._MEIPASS', str(self.root/'bundle'), create=True), \
                patch('sys.executable', str(self.root/'installed/BellPet.exe')):
            library = BehaviorStyleLibrary.load()
        self.assertFalse(library.errors)
        self.assertEqual(library.find('mouse_attention.curious', 'mouse_attention').name_zh, '外部覆盖')


if __name__ == '__main__':
    unittest.main()
