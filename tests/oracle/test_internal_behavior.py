"""隐藏行为参数在旧设置、角色恢复、风格与分享中的默认值边界"""
from dataclasses import asdict, replace
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from rw_creature_pet.config import AppConfig
from rw_creature_pet.oracle.internal_behavior import INTERNAL_BEHAVIOR_PATHS
from rw_creature_pet.presets.behavior_styles import BehaviorStyleLibrary, default_style_directory
from rw_creature_pet.presets.common import get_value, set_value
from rw_creature_pet.presets.personal import apply_values
from rw_creature_pet.presets.profile import profile_mapping, validate_config
from rw_creature_pet.presets.profile_library import ProfileLibrary
from rw_creature_pet.settings_store import SettingsStore


class InternalBehaviorTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.defaults = AppConfig()
        # 所有旧值合法，但与默认值不同，模拟既有角色和本地个人调整
        self.old = {path: get_value(self.defaults, path)*1.1 for path in INTERNAL_BEHAVIOR_PATHS}

    def assert_defaults(self, config):
        for path in INTERNAL_BEHAVIOR_PATHS:
            self.assertEqual(get_value(config, path), get_value(self.defaults, path), path)

    def test_old_settings_load_defaults_and_preserve_other_preferences(self):
        data = asdict(self.defaults)
        data['game_dir'] = str(self.defaults.game_dir)
        for path, value in self.old.items():
            set_value(data, path, value)
        data['oracle']['reading']['start_probability'] = .73
        data['oracle']['voice'] = 'custom:moon'
        store = SettingsStore(self.root/'settings.json')
        store.path.write_text(json.dumps({'version': 1, 'config': data}), encoding='utf-8')
        loaded = store.load()
        self.assert_defaults(loaded)
        self.assertEqual(loaded.oracle.reading.start_probability, .73)
        self.assertEqual(loaded.oracle.voice, 'custom:moon')
        store.save(loaded)
        self.assert_defaults(store.load())

    def test_character_import_and_saved_overrides_use_defaults_without_rewriting_source(self):
        raw = profile_mapping(self.defaults)
        for path, value in self.old.items():
            set_value(raw, path, value)
        raw['oracle']['reading']['eye_open_probability'] = .68
        before = json.dumps(raw, sort_keys=True)
        config = validate_config(raw)
        self.assert_defaults(config)
        self.assertEqual(json.dumps(raw, sort_keys=True), before)
        self.assertEqual(config.oracle.reading.eye_open_probability, .68)
        # 本地覆盖、恢复角色原始值、切换角色使用相同的个人调整入口
        restored = apply_values(config, {**self.old, 'oracle.float_speed': 1.23})
        self.assert_defaults(restored)
        self.assertEqual(restored.oracle.float_speed, 1.23)
        library = ProfileLibrary(self.root/'profiles')
        preset = library.export(restored, '内部默认值')
        archive = library.export_share(restored, self.root/'share.zip', name=preset.name, preset_id=preset.id)
        received = ProfileLibrary(self.root/'received').import_file(archive)
        self.assert_defaults(received.config)
        self.assertEqual(received.config.oracle.float_speed, 1.23)

    def test_legacy_style_fields_are_ignored_and_not_required_for_new_styles(self):
        shutil.copy2(default_style_directory()/'builtin.toml', self.root/'builtin.toml')
        (self.root/'local.toml').write_text('''format_version = 1
[[styles]]
id = "daily_activity.still"
[styles.values]
"oracle.daily_activity.move_lean_degrees" = 0.0
"oracle.float_speed" = 0.8
''', encoding='utf-8')
        library = BehaviorStyleLibrary.load(self.root)
        self.assertFalse(library.errors)
        for style in library.styles:
            self.assertFalse(set(style.values) & INTERNAL_BEHAVIOR_PATHS)
            self.assert_defaults(style.apply(self.defaults))
        style = library.find('daily_activity.still', 'daily_activity')
        self.assertEqual(style.apply(self.defaults).oracle.float_speed, .8)

    def test_direct_application_config_cannot_restore_hidden_values(self):
        oracle = replace(self.defaults.oracle, pearl_follow_width=720,
                         reading=replace(self.defaults.oracle.reading, notice_min_seconds=3, notice_max_seconds=5))
        self.assert_defaults(replace(self.defaults, oracle=oracle))
        # 底层仿真仍能用显式 OracleConfig 测试内部数值，不改变物理模块的输入契约
        self.assertEqual(oracle.pearl_follow_width, 720)
