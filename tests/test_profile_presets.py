"""完整预设的归属边界、外观引用、副本可移植性和失败保护"""
from dataclasses import replace
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from PIL import Image

from rw_creature_pet.config import AppConfig, DesktopConfig
from rw_creature_pet.interaction.config import InteractionConfig
from rw_creature_pet.oracle.config import CustomAppearance, DragReactionConfig, OracleColors
from rw_creature_pet.oracle.face_config import FaceDecal
from rw_creature_pet.presets.appearance import load_appearance
from rw_creature_pet.presets.common import get_value
from rw_creature_pet.presets.fields import paths_for
from rw_creature_pet.presets.library import AppearanceLibrary
from rw_creature_pet.presets.profile import apply_profile, load_profile, profile_mapping
from rw_creature_pet.presets.profile_library import ProfileLibrary, default_profile_directory
from rw_creature_pet.presets.registry import FieldScope
from rw_creature_pet.ui_config import UiConfig


class ProfilePresetTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.library = ProfileLibrary(self.root/'profiles')
        self.appearances = AppearanceLibrary(self.root/'appearances')
        self.png = self.root/'face.png'
        Image.new('RGBA', (5, 5), (60, 70, 80, 180)).save(self.png)
        self.config = AppConfig(ui=UiConfig('zh'), interaction=InteractionConfig(
            hover_probability=.345678, hover_avoidance_enabled=False))
        self.config = replace(self.config, oracle=replace(self.config.oracle,
            body_appearance='custom', outfit='maid', custom_colors=OracleColors(skin='#123456'),
            custom_appearance=CustomAppearance(forehead=FaceDecal(True, str(self.png), 'face.png')),
            base_speed=3.123456, pearl_follow_width=432.123, pearl_follow_height=321.123,
            pearl_matrix_count=0, pearl_matrix_enabled=False, float_speed=1.3,
            drag_reactions=DragReactionConfig(voice_probability=0., alternating_probability=.654321)))

    def rewrite(self, preset, change):
        data = json.loads(preset.path.read_text(encoding='utf-8'))
        change(data)
        preset.path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')

    def test_roundtrip_contains_all_registered_behavior_and_preserves_every_local_field(self):
        preset = self.library.export(self.config, '完整角色')
        document = json.loads(preset.path.read_text(encoding='utf-8'))
        self.assertEqual(document['config'], profile_mapping(self.config))
        self.assertEqual(document['appearance']['id'], preset.appearance.id)
        self.assertEqual(document['appearance']['path'], 'appearance/appearance.json')
        target = replace(self.config, desktop=DesktopConfig(2, False, 'monitor'),
            interaction=InteractionConfig(drag_enabled=True), oracle=replace(self.config.oracle,
                body_appearance='bell', colors=OracleColors(skin='#abcdef'), arm_scale=.5,
                hide_cords=True, halo_enabled=False, halo_arcs_enabled=False, glow_enabled=True,
                voice_directory='local-voices', base_fraction=.3, edge_fraction=.4))
        actual = apply_profile(target, preset, self.root/'cache')
        for path in paths_for(FieldScope.LOCAL):
            if '[]' not in path:
                with self.subTest(local=path):
                    self.assertEqual(get_value(actual, path), get_value(target, path))
        self.assertEqual(actual.overseer, target.overseer)
        for path in paths_for(FieldScope.PROFILE):
            with self.subTest(profile=path):
                self.assertEqual(get_value(actual, path), get_value(self.config, path))
        self.assertEqual(actual.oracle.colors, target.oracle.colors)
        self.assertEqual(actual.oracle.custom_colors, self.config.oracle.custom_colors)
        self.assertEqual(actual.oracle.outfit, 'maid')

    def test_reference_uses_bundled_snapshot_even_with_newer_same_id_in_appearance_library(self):
        appearance = self.appearances.export(self.config, '共享外观')
        preset = self.library.export(self.config, '第一版角色', appearance_source=appearance)
        changed = replace(self.config, oracle=replace(self.config.oracle,
            custom_colors=OracleColors(skin='#ff0000')))
        newer = self.appearances.export(changed, '修改后的外观', preset_id=appearance.id)
        self.assertEqual(self.appearances.scan().presets[0].path, newer.path)
        self.assertEqual(preset.appearance.id, appearance.id)
        self.assertEqual(load_profile(preset.path).appearance.oracle.custom_colors.skin, '#123456')
        shutil.rmtree(self.appearances.directory)
        self.png.unlink()
        loaded = load_profile(preset.path)
        self.assertEqual(loaded.appearance.oracle.custom_colors.skin, '#123456')
        self.assertTrue(loaded.appearance.image(loaded.appearance.oracle.custom_appearance.forehead.image_path).is_file())

    def test_export_uses_current_edits_not_stale_appearance_source_values(self):
        source = self.appearances.export(self.config, '基础外观')
        changed = replace(self.config, oracle=replace(self.config.oracle,
            custom_colors=OracleColors(skin='#987654'), outfit='normal'))
        preset = self.library.export(changed, '微调版', appearance_source=source)
        self.assertEqual(preset.appearance.id, source.id)
        self.assertEqual(preset.appearance.oracle.custom_colors.skin, '#987654')
        self.assertEqual(preset.appearance.oracle.outfit, 'normal')
        self.assertEqual(load_appearance(source.path).oracle.custom_colors.skin, '#123456')

    def test_import_moves_complete_bundle_preserving_both_identities_and_dates(self):
        source = self.library.export(self.config, '可迁移')
        dest = ProfileLibrary(self.root/'other-device/profiles')
        imported = dest.import_file(source.path)
        self.assertEqual((imported.id, imported.updated_at), (source.id, source.updated_at))
        self.assertEqual((imported.appearance.id, imported.appearance.updated_at),
                         (source.appearance.id, source.appearance.updated_at))
        shutil.rmtree(self.library.directory)
        self.png.unlink()
        applied = apply_profile(AppConfig(ui=UiConfig('en')), load_profile(imported.path), self.root/'cache')
        shutil.rmtree(dest.directory)
        self.assertTrue(Path(applied.oracle.custom_appearance.forehead.image_path).is_file())

    def test_missing_behavior_uses_code_defaults_not_previous_character(self):
        preset = self.library.export(self.config, '精简配置')
        self.rewrite(preset, lambda data: data.update(config={}))
        loaded = load_profile(preset.path)
        actual = apply_profile(self.config, loaded, self.root/'cache')
        self.assertEqual(profile_mapping(actual), profile_mapping(AppConfig(ui=UiConfig('en'))))
        self.assertEqual(actual.oracle.custom_colors.skin, '#123456')

    def test_local_appearance_and_unknown_behavior_fields_are_rejected(self):
        for extra in ({'desktop': {'scale': 2}}, {'audio': {'enabled': False}},
                      {'oracle': {'halo_enabled': False}}, {'oracle': {'arm_scale': .5}},
                      {'oracle': {'colors': {'skin': '#ffffff'}}}, {'overseer': {'enabled': True}},
                      {'interaction': {'drag_enabled': True}}, {'oracle': {'unknown': .5}}):
            with self.subTest(extra=extra):
                preset = self.library.export(self.config, '无效字段')
                self.rewrite(preset, lambda data: data.update(config=extra))
                with self.assertRaises(ValueError):
                    load_profile(preset.path)

    def test_wrong_reference_id_escaping_or_missing_file_never_falls_back_to_library(self):
        source = self.appearances.export(self.config, '库中存在')
        for reference in ({'id': str(uuid4()), 'path': 'appearance/appearance.json'},
                          {'id': source.id, 'path': '../appearance.json'},
                          {'id': source.id, 'path': str(source.path)},
                          {'id': source.id, 'path': 'missing.json'}, {'id': source.id}):
            with self.subTest(reference=reference):
                preset = self.library.export(self.config, '错误引用', appearance_source=source)
                self.rewrite(preset, lambda data: data.update(appearance=reference))
                with self.assertRaises((OSError, ValueError)):
                    load_profile(preset.path)

    def test_numeric_types_ranges_and_nonfinite_values_are_rejected(self):
        for key, value in (('float_speed', True), ('base_speed', '3'), ('float_speed', 50),
                           ('base_speed', float('inf')), ('pearl_matrix_count', 1.5)):
            with self.subTest(value=value):
                preset = self.library.export(self.config, '错误数值')
                self.rewrite(preset, lambda data: data['config']['oracle'].update({key: value}))
                with self.assertRaises(ValueError):
                    load_profile(preset.path)

    def test_duplicate_profile_versions_and_invalid_newer_snapshot(self):
        first = self.library.export(self.config, '重复')
        second = self.library.export(self.config, '重复', preset_id=first.id)
        self.assertEqual(self.library.scan().presets[0].path, second.path)
        self.assertEqual(len(self.library.scan().duplicates[0]), 2)
        second.appearance.path.unlink()
        report = self.library.scan()
        self.assertEqual(report.presets[0].path, first.path)
        self.assertEqual(len(report.errors), 1)

    def test_failed_write_never_publishes_partial_profile_or_changes_other_packages(self):
        preset = self.library.export(self.config, '保留')
        before = preset.path.read_bytes()
        self.png.unlink()
        with self.assertRaises(OSError):
            self.library.export(self.config, '失败')
        self.assertEqual(preset.path.read_bytes(), before)
        self.assertEqual(list(self.library.directory.glob('.staging-*')), [])
        self.assertEqual(len(self.library.scan().presets), 1)

    def test_manifest_types_and_versions_do_not_mix(self):
        preset = self.library.export(self.config, '类型')
        with self.assertRaises(ValueError):
            load_profile(preset.appearance.path)
        with self.assertRaises(ValueError):
            load_appearance(preset.path)
        self.rewrite(preset, lambda data: data.update(version=2))
        with self.assertRaises(ValueError):
            load_profile(preset.path)

    def test_packaged_profile_directory_is_beside_exe(self):
        with patch('sys.frozen', True, create=True), patch('sys.executable', str(self.root/'BellPet.exe')):
            self.assertEqual(default_profile_directory(), self.root/'presets/profiles')


if __name__ == '__main__':
    unittest.main()
