"""用户文件往返、默认值迁移与失败时的原文件保护。"""
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from rw_creature_pet.config import AppConfig, DesktopConfig
from rw_creature_pet.settings_store import SettingsStore, absolute_paths


class SettingsStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.store = SettingsStore(self.root/'用户配置/settings.json')

    def test_roundtrip_keeps_colors_advanced_values_and_desktop_preferences(self):
        config = AppConfig(game_dir=self.root/'游戏', desktop=DesktopConfig(1.5, False))
        config = replace(config, oracle=replace(config.oracle, antigravity_probability=.123456,
            colors=replace(config.oracle.colors, skin='#123456'), voice_directory=str(self.root/'语音')))
        self.store.save(config)
        self.assertEqual(self.store.load(), config)
        self.assertEqual(AppConfig.load(self.store.path), config)
        self.assertFalse(self.store.path.read_bytes().startswith(b'\xef\xbb\xbf'))
        updated = replace(config, desktop=DesktopConfig(2., True))
        original = self.store.path.read_bytes()
        self.store.save(updated)
        self.assertEqual(self.store.load(), updated)
        self.assertEqual(self.store.path.with_suffix('.json.bak').read_bytes(), original)

    def test_atomic_replace_failure_keeps_previous_complete_file(self):
        self.store.save(AppConfig())
        original = self.store.path.read_bytes()
        with patch.object(Path, 'replace', side_effect=PermissionError('locked')):
            with self.assertRaises(PermissionError):
                self.store.save(AppConfig(desktop=DesktopConfig(2.)))
        self.assertEqual(self.store.path.read_bytes(), original)
        self.assertEqual(list(self.store.path.parent.glob('*.tmp')), [])

    def test_template_first_run_saved_precedence_and_explicit_override(self):
        source = self.root/'config.toml'
        source.write_text("game_dir = '游戏'\n[oracle.colors]\nskin = '#123456'\n", encoding='utf-8')
        with patch('rw_creature_pet.settings_store.default_template_path', return_value=source):
            initial, first, message = self.store.startup()
            self.assertTrue(first)
            self.assertEqual(initial.oracle.colors.skin, '#123456')
            self.assertEqual(initial.game_dir, self.root/'游戏')
            self.assertFalse(self.store.path.exists())
            stored = replace(initial, desktop=DesktopConfig(2.))
            self.store.save(stored)
            source.write_text("game_dir = '另一个游戏'", encoding='utf-8')
            self.assertEqual(self.store.startup(), (stored, False, ''))
            explicit, first, _ = self.store.startup(source)
            self.assertEqual(explicit.game_dir, self.root/'另一个游戏')
            self.assertFalse(first)
        self.assertEqual(source.read_text(encoding='utf-8'), "game_dir = '另一个游戏'")

    def test_corrupt_profile_is_reported_preserved_until_save_and_backed_up(self):
        self.store.path.parent.mkdir()
        self.store.path.write_text('{broken', encoding='utf-8')
        with patch('rw_creature_pet.settings_store.default_template_path', return_value=None):
            config, first, message = self.store.startup()
        self.assertTrue(first)
        self.assertIn('无法读取', message)
        self.assertEqual(self.store.path.read_text(), '{broken')
        self.store.save(config)
        self.assertEqual(self.store.path.with_suffix('.json.bak').read_text(), '{broken')

    def test_relative_voice_directory_follows_template_before_copy_to_user_folder(self):
        config = AppConfig(game_dir=Path('game'))
        config = replace(config, oracle=replace(config.oracle, voice_directory='voices'))
        resolved = absolute_paths(config, self.root/'config.toml')
        self.assertEqual(resolved.oracle.voice_directory, str(self.root/'voices'))
        self.store.save(resolved)
        self.assertEqual(self.store.load(), resolved)

    def test_missing_legacy_voice_directory_still_falls_back_to_game_resources(self):
        from rw_creature_pet.oracle.voice_assets import LEGACY_DIRECTORY
        config = AppConfig()
        config = replace(config, oracle=replace(config.oracle, voice_directory=LEGACY_DIRECTORY))
        self.assertEqual(absolute_paths(config, self.root/'config.toml').oracle.voice_directory, 'auto')

    def test_frozen_startup_reads_defaults_next_to_executable_without_cwd_dependency(self):
        from rw_creature_pet.settings_store import default_template_path
        path = self.root/'config.toml'
        path.write_text("game_dir = 'game'", encoding='utf-8')
        with patch('sys.frozen', True, create=True), patch('sys.executable', str(self.root/'Bell.exe')):
            self.assertEqual(default_template_path(), path)
