"""外观包往返、字段边界、资源可移植性和重复版本选择"""
from dataclasses import replace
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

from rw_creature_pet.config import AppConfig, DesktopConfig
from rw_creature_pet.oracle.config import CustomAppearance, OracleColors
from rw_creature_pet.oracle.face_config import FaceDecal
from rw_creature_pet.presets.appearance import (MANIFEST, apply_appearance, appearance_mapping,
                                               load_appearance)
from rw_creature_pet.presets.library import AppearanceLibrary, default_appearance_directory
from rw_creature_pet.ui_config import UiConfig


class AppearancePresetTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.library = AppearanceLibrary(self.root/'预设库')
        self.png = self.root/'原图.png'
        Image.new('RGBA', (6, 8), (120, 60, 240, 128)).save(self.png)
        self.config = AppConfig(ui=UiConfig('zh'))
        shape = CustomAppearance(forehead=FaceDecal(True, str(self.png), '原图.png', 1.25, -2.5),
                                 face=FaceDecal(False, str(self.png), '关闭的贴图.png'))
        self.config = replace(self.config, oracle=replace(self.config.oracle,
            body_appearance='custom', outfit='maid', custom_appearance=shape,
            custom_colors=OracleColors(skin='#123456'), pearl_bubble_color='#987654'))

    def rewrite(self, preset, change):
        data = json.loads(preset.path.read_text(encoding='utf-8'))
        change(data)
        preset.path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')

    def test_roundtrip_copies_even_disabled_assets_and_preserves_other_fields(self):
        preset = self.library.export(self.config, '测试人偶')
        payload = json.loads(preset.path.read_text(encoding='utf-8'))
        self.assertNotIn('colors', payload['config']['oracle'])
        self.assertNotIn('float_speed', payload['config']['oracle'])
        shape = payload['config']['oracle']['custom_appearance']
        self.assertEqual(shape['forehead']['image_path'], shape['face']['image_path'])
        self.assertEqual(len(list((preset.path.parent/'images').glob('*.png'))), 1)
        self.assertNotIn(str(self.root), preset.path.read_text(encoding='utf-8'))
        self.png.unlink()
        target = replace(self.config, desktop=DesktopConfig(2, False), oracle=replace(
            self.config.oracle, body_appearance='bell', colors=OracleColors(skin='#abcdef'),
            arm_scale=.5, float_speed=.9, halo_enabled=False, pearl_matrix_count=8))
        result = apply_appearance(target, load_appearance(preset.path), self.root/'cache')
        self.assertEqual(result.desktop, target.desktop)
        self.assertEqual(result.oracle.colors, target.oracle.colors)
        for name in ('arm_scale', 'float_speed', 'halo_enabled', 'pearl_matrix_count'):
            self.assertEqual(getattr(result.oracle, name), getattr(target.oracle, name))
        self.assertEqual(result.oracle.outfit, 'maid')
        self.assertEqual(result.oracle.custom_colors.skin, '#123456')
        self.assertEqual(result.oracle.pearl_bubble_color, '#987654')
        actual = result.oracle.custom_appearance
        self.assertFalse(actual.face.enabled)
        self.assertEqual(actual.face.image_name, '关闭的贴图.png')
        self.assertEqual(actual.forehead.offset_x, 1.25)
        shutil.rmtree(preset.path.parent)
        self.assertTrue(Path(actual.forehead.image_path).is_file())

    def test_bell_export_does_not_read_inactive_custom_assets(self):
        self.png.unlink()
        bell = replace(self.config, oracle=replace(self.config.oracle, body_appearance='bell'))
        preset = self.library.export(bell, 'Bell')
        keys = appearance_mapping(preset.oracle)['oracle']
        self.assertEqual(set(keys), {'body_appearance', 'outfit', 'outfit_settings', 'colors', 'pearl_bubble_color'})
        result = apply_appearance(self.config, preset, self.root/'cache')
        self.assertEqual(result.oracle.custom_appearance, self.config.oracle.custom_appearance)
        self.assertEqual(result.oracle.custom_colors, self.config.oracle.custom_colors)

    def test_missing_fields_use_schema_defaults_not_previous_character(self):
        preset = self.library.export(self.config, '部分配置')
        self.rewrite(preset, lambda d: d['config']['oracle'].update(custom_appearance={}, custom_colors={}))
        preset = load_appearance(preset.path)
        result = apply_appearance(self.config, preset, self.root/'cache')
        self.assertEqual(result.oracle.custom_appearance, CustomAppearance())
        self.assertEqual(result.oracle.custom_colors, OracleColors())

    def test_import_is_self_contained_and_preserves_id_and_update_time(self):
        source = self.library.export(self.config, '可移动')
        dest = AppearanceLibrary(self.root/'其他位置')
        imported = dest.import_file(source.path)
        self.assertEqual((imported.id, imported.updated_at), (source.id, source.updated_at))
        shutil.rmtree(self.library.directory)
        load_appearance(imported.path)
        self.assertEqual(dest.import_file(imported.path).path, imported.path)
        self.assertEqual(len(dest.scan().presets), 1)

    def test_duplicate_selection_uses_metadata_time_and_reports_all_paths(self):
        first = self.library.export(self.config, '同一个人偶')
        second = self.library.export(self.config, '同一个人偶', preset_id=first.id)
        self.rewrite(first, lambda d: d.update(updated_at='2020-01-01T00:00:00Z'))
        self.rewrite(second, lambda d: d.update(updated_at='2021-01-01T00:00:00Z'))
        report = self.library.scan()
        self.assertEqual(report.presets[0].path, second.path)
        self.assertEqual(len(report.duplicates[0]), 2)
        self.assertEqual(len(report.presets), 1)
        self.rewrite(second, lambda d: d.update(version=999))
        report = self.library.scan()
        self.assertEqual(report.presets[0].path, first.path)
        self.assertEqual(len(report.errors), 1)

    def test_equal_dates_are_stable_and_same_names_with_different_ids_are_distinct(self):
        a = self.library.export(self.config, '重名')
        b = self.library.export(self.config, '重名', preset_id=a.id)
        c = self.library.export(self.config, '重名')
        for item in (a, b):
            self.rewrite(item, lambda d: d.update(updated_at='2020-01-01T00:00:00+00:00'))
        report = self.library.scan()
        chosen = next(p for p in report.presets if p.id == a.id)
        self.assertEqual(chosen.path, sorted((a.path, b.path), key=lambda p: (str(p).casefold(), str(p)))[0])
        self.assertEqual({p.id for p in report.presets}, {a.id, c.id})

    def test_disallowed_scope_inactive_branch_and_unknown_fields_are_rejected(self):
        for key, value in (('arm_scale', .5), ('halo_enabled', False), ('float_speed', 1.2),
                           ('colors', {}), ('new_parameter', 1)):
            with self.subTest(key=key):
                preset = self.library.export(self.config, '无效字段')
                self.rewrite(preset, lambda d: d['config']['oracle'].update({key: value}))
                with self.assertRaises(ValueError):
                    load_appearance(preset.path)

    def test_outside_asset_paths_and_corrupt_or_missing_images_are_rejected(self):
        preset = self.library.export(self.config, '无效贴图')
        for reference in ('../outside.png', str(self.png), 'C:/private.png', '//server/image.png',
                          'images\\outside.png', 'images/missing.png'):
            with self.subTest(reference=reference):
                self.rewrite(preset, lambda d: d['config']['oracle']['custom_appearance']['forehead'].update(image_path=reference))
                with self.assertRaises((OSError, ValueError)):
                    load_appearance(preset.path)
        broken = preset.path.parent/'bad.png'
        broken.write_bytes(b'not png')
        self.rewrite(preset, lambda d: d['config']['oracle']['custom_appearance']['forehead'].update(image_path='bad.png'))
        with self.assertRaises(ValueError):
            load_appearance(preset.path)

    def test_invalid_metadata_values_and_duplicate_keys_are_rejected(self):
        for changes in ({'version': True}, {'version': 2}, {'id': 'not-a-uuid'},
                        {'name': ''}, {'updated_at': '2020-01-01'}, {'extra': 'unknown'}):
            with self.subTest(changes=changes):
                preset = self.library.export(self.config, '错误信息')
                self.rewrite(preset, lambda d: d.update(changes))
                with self.assertRaises(ValueError):
                    load_appearance(preset.path)
        preset.path.write_text('{"version": 1, "version": 1}', encoding='utf-8')
        with self.assertRaises(ValueError):
            load_appearance(preset.path)

    def test_failed_export_cleans_staging_without_altering_existing_packages(self):
        preset = self.library.export(self.config, '已有配置')
        before = preset.path.read_bytes()
        self.png.unlink()
        with self.assertRaises(OSError):
            self.library.export(self.config, '失败的导出')
        self.assertEqual(preset.path.read_bytes(), before)
        self.assertEqual(list(self.library.directory.glob('.staging-*')), [])
        self.assertEqual(len(self.library.scan().presets), 1)

    def test_invalid_range_is_rejected_and_scan_continues(self):
        invalid = self.library.export(self.config, '过大袖口')
        valid = self.library.export(self.config, '正常')
        self.rewrite(invalid, lambda d: d['config']['oracle']['custom_appearance'].update(sleeve_cuff_width=1000))
        report = self.library.scan()
        self.assertEqual([p.id for p in report.presets], [valid.id])
        self.assertEqual(len(report.errors), 1)

    def test_packaged_library_is_beside_executable_not_extraction_or_cwd(self):
        with patch('sys.frozen', True, create=True), patch('sys.executable', str(self.root/'BellPet.exe')):
            self.assertEqual(default_appearance_directory(), self.root/'presets/appearances')


if __name__ == '__main__':
    unittest.main()
