"""内容级未保存判断、来源存储和原目录更新失败保护"""
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

from rw_creature_pet.config import AppConfig
from rw_creature_pet.oracle.face_config import FaceDecal
from rw_creature_pet.presets.appearance import apply_appearance, load_appearance
from rw_creature_pet.presets.editing import PresetEditingState, scope_paths
from rw_creature_pet.presets.library import AppearanceLibrary
from rw_creature_pet.presets.profile import load_profile
from rw_creature_pet.presets.profile_library import ProfileLibrary
from rw_creature_pet.settings_store import SettingsStore
from rw_creature_pet.ui_config import UiConfig


class PresetEditingTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.library = AppearanceLibrary(self.root/'appearances')
        self.profiles = ProfileLibrary(self.root/'profiles')
        self.config = AppConfig(ui=UiConfig('zh'))
        self.changed = replace(self.config, oracle=replace(self.config.oracle,
            colors=replace(self.config.oracle.colors, skin='#123456'), float_speed=1.2))

    def test_dirty_only_when_changed_and_about_to_be_overwritten(self):
        state = PresetEditingState()
        paths = scope_paths('appearance', 'bell')
        self.assertFalse(state.at_risk(self.config, self.changed, paths))
        self.assertEqual(state.at_risk(self.changed, self.config, paths), ('oracle.colors.skin',))
        self.assertFalse(state.at_risk(self.changed, self.changed, paths))
        state.record('appearance', self.library.export(self.changed, '外观'))
        self.assertFalse(state.at_risk(self.changed, self.config, paths))
        self.assertIn('oracle.float_speed', state.at_risk(self.changed, self.config, scope_paths('profile', 'bell')))

    def test_images_compare_content_not_absolute_cache_paths(self):
        png = self.root/'face.png'
        Image.new('RGBA', (4, 4), '#ff0000').save(png)
        custom = replace(self.config, oracle=replace(self.config.oracle, body_appearance='custom',
            custom_appearance=replace(self.config.oracle.custom_appearance, forehead=FaceDecal(True, str(png), 'face.png'))))
        preset = self.library.export(custom, '贴图')
        applied = apply_appearance(self.config, preset, self.root/'cache')
        state = PresetEditingState()
        state.record('appearance', preset)
        self.assertTrue(state.matches(custom, preset, 'appearance'))
        self.assertTrue(state.matches(applied, preset, 'appearance'))
        self.assertFalse(state.at_risk(applied, self.config, scope_paths('appearance', 'custom')))

    def test_update_replaces_selected_package_and_preserves_other_duplicate(self):
        first = self.library.export(self.config, '重复')
        second = self.library.export(self.config, '重复', preset_id=first.id)
        old = first.path.read_bytes()
        updated = self.library.update(self.changed, second)
        self.assertEqual(updated.path, second.path)
        self.assertEqual(updated.id, second.id)
        self.assertEqual(load_appearance(updated.path).oracle.colors.skin, '#123456')
        self.assertEqual(first.path.read_bytes(), old)
        self.assertEqual(self.library.scan().presets[0].path, second.path)
        self.assertEqual(len(self.library.scan().duplicates[0]), 2)
        self.assertTrue(second.path.with_suffix('.json.bak').is_file())

    def test_full_update_isolated_from_independent_appearance_and_backup_usable(self):
        source = self.library.export(self.config, '外观')
        preset = self.profiles.export(self.config, '角色', appearance_source=source)
        before = source.path.read_bytes()
        updated = self.profiles.update(self.changed, preset, appearance_source=source)
        self.assertEqual(updated.path, preset.path)
        self.assertEqual(updated.appearance.id, source.id)
        self.assertNotEqual(updated.appearance.path, preset.appearance.path)
        self.assertEqual(load_profile(updated.path).appearance.oracle.colors.skin, '#123456')
        self.assertEqual(load_profile(updated.path.with_suffix('.json.bak')).appearance.oracle.colors.skin,
                         self.config.oracle.colors.skin)
        self.assertEqual(source.path.read_bytes(), before)
        self.assertEqual(len(self.profiles.scan().presets), 1)

    def test_manifest_replace_failure_keeps_complete_previous_package(self):
        for library, loader in ((self.library, load_appearance), (self.profiles, load_profile)):
            target = library.export(self.config, '保留')
            before = target.path.read_bytes()
            original_replace = Path.replace
            def fail_manifest(path, dest):
                if Path(dest) == target.path:
                    raise PermissionError('locked')
                return original_replace(path, dest)
            with patch.object(Path, 'replace', fail_manifest):
                with self.assertRaises(PermissionError):
                    library.update(self.changed, target)
            self.assertEqual(target.path.read_bytes(), before)
            self.assertEqual(loader(target.path).revision, target.revision)
            self.assertEqual(list(library.directory.glob('.staging-*')), [])

    def test_stale_target_refused_even_if_id_and_date_stay_same(self):
        preset = self.library.export(self.config, '外观')
        data = json.loads(preset.path.read_text(encoding='utf-8'))
        data['config']['oracle']['colors']['skin'] = '#654321'
        preset.path.write_text(json.dumps(data), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, '已被修改'):
            self.library.update(self.changed, preset)
        self.assertEqual(load_appearance(preset.path).oracle.colors.skin, '#654321')

    def test_update_rejects_foreign_target_and_keeps_siblings_when_manifest_at_root(self):
        foreign = AppearanceLibrary(self.root/'foreign').export(self.config, '外部')
        with self.assertRaises(ValueError):
            self.library.update(self.changed, foreign)
        self.library.directory.mkdir()
        path = self.library.directory/'appearance.json'
        path.write_bytes(foreign.path.read_bytes())
        sibling = self.library.export(self.config, '相邻包')
        before = sibling.path.read_bytes()
        self.library.update(self.changed, load_appearance(path))
        self.assertEqual(load_appearance(path).oracle.colors.skin, '#123456')
        self.assertEqual(sibling.path.read_bytes(), before)

    def test_import_nonstandard_manifest_inside_library_becomes_discoverable(self):
        preset = self.library.export(self.config, '导入')
        name = preset.path.with_name('download.json')
        preset.path.rename(name)
        imported = self.library.import_file(name)
        self.assertEqual(imported.path.name, 'appearance.json')
        self.assertEqual(self.library.scan().presets[0].path, imported.path)

    def test_metadata_commits_with_settings_and_tray_save_preserves_it(self):
        state = PresetEditingState()
        preset = self.profiles.export(self.changed, '来源')
        state.record('profile', preset)
        store = SettingsStore(self.root/'user/settings.json')
        with store.preset_state(state.serialize()):
            store.save(self.changed)
        store.save(self.changed)
        restored = PresetEditingState(store.load_preset_state())
        self.assertEqual(restored.sources['profile'].id, preset.id)
        self.assertFalse(restored.at_risk(self.changed, self.config, scope_paths('profile', 'bell')))
        before = store.path.read_bytes()
        with store.preset_state(PresetEditingState().serialize()), patch.object(Path, 'replace', side_effect=OSError('locked')):
            with self.assertRaises(OSError):
                store.save(self.config)
        self.assertEqual(store.path.read_bytes(), before)
        self.assertIsNone(store._preset_state)


if __name__ == '__main__':
    unittest.main()
