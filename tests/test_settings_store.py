"""用户文件往返、默认值迁移与失败时的原文件保护。"""
from dataclasses import replace
import json
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

    def write_profile(self, config, *, version=1):
        self.store.path.parent.mkdir(parents=True, exist_ok=True)
        self.store.path.write_text(json.dumps({'version': version, 'config': config}), encoding='utf-8')
        return self.store.path.read_bytes()

    def template(self, text):
        source = self.root/'release/config.toml'
        source.parent.mkdir(exist_ok=True)
        source.write_text(text, encoding='utf-8')
        self.enterContext(patch('rw_creature_pet.settings_store.default_template_path', return_value=source))
        return source

    def test_upgrade_fills_nested_defaults_preserves_false_zero_and_user_values(self):
        source = self.template("""game_dir = 'default-game'
[desktop]
scale = 1.5
autonomous = true
[audio]
enabled = true
volume = 0.7
[oracle]
pearl_matrix_count = 7
halo_scale = 1.2
[oracle.colors]
skin = '#abcdef'
eyes = '#224466'
[oracle.drag_reactions]
voice_probability = 0.8
[overseer]
enabled = true
color = '#ff557f'
size = 0.8
""")
        user = {'game_dir': 'my-game', 'desktop': {'scale': 2., 'autonomous': False},
                'audio': {'enabled': False, 'volume': 0},
                'oracle': {'pearl_matrix_count': 0, 'antigravity_probability': 0,
                           'colors': {'skin': '#123456'}, 'drag_reactions': {'voice_probability': 0}},
                'overseer': {'enabled': False, 'cooldown_min': 0}}
        original = self.write_profile(user)
        config, first, message = self.store.startup()
        self.assertFalse(first)
        self.assertEqual(message, '')
        self.assertEqual(config.desktop, DesktopConfig(2., False))
        self.assertFalse(config.audio.enabled)
        self.assertEqual(config.audio.volume, 0)
        self.assertEqual(config.oracle.pearl_matrix_count, 0)
        self.assertEqual(config.oracle.antigravity_probability, 0)
        self.assertEqual(config.oracle.drag_reactions.voice_probability, 0)
        self.assertEqual(config.oracle.colors.skin, '#123456')
        self.assertEqual(config.oracle.colors.eyes, '#224466')
        self.assertEqual(config.oracle.halo_scale, 1.2)
        self.assertFalse(config.overseer.enabled)
        self.assertEqual(config.overseer.color, '#ff557f')
        self.assertEqual(config.overseer.size, .8)
        self.assertEqual(config.overseer.cooldown_min, 0)
        self.assertEqual(config.game_dir, self.store.path.parent/'my-game')
        stored = json.loads(self.store.path.read_text(encoding='utf-8'))['config']
        self.assertEqual(stored['game_dir'], 'my-game')
        self.assertEqual(stored['overseer']['color'], '#ff557f')
        self.assertEqual(stored['oracle']['colors']['skin'], '#123456')
        backup = self.store.path.with_suffix('.json.bak')
        self.assertEqual(backup.read_bytes(), original)
        upgraded = self.store.path.read_bytes()
        stamp = self.store.path.stat().st_mtime_ns
        source.write_text("[overseer]\ncolor = '#ffffff'\nsize = 0.5\n", encoding='utf-8')
        self.assertEqual(self.store.startup(), (config, False, ''))
        self.assertEqual(self.store.path.read_bytes(), upgraded)
        self.assertEqual(self.store.path.stat().st_mtime_ns, stamp)
        self.assertEqual(backup.read_bytes(), original)

    def test_load_merges_but_only_startup_writes_migration(self):
        self.template("[overseer]\ncolor = '#ff557f'\nsize = 0.8\n")
        original = self.write_profile({'audio': {'volume': 0.23}})
        config = self.store.load()
        self.assertEqual(config.audio.volume, .23)
        self.assertEqual(config.overseer.color, '#ff557f')
        self.assertEqual(self.store.path.read_bytes(), original)
        self.assertFalse(self.store.path.with_suffix('.json.bak').exists())
        self.assertEqual(AppConfig.load(self.store.path), config)
        self.assertEqual(self.store.startup()[0], config)
        self.assertNotEqual(self.store.path.read_bytes(), original)

    def test_upgrade_resolves_default_and_user_paths_at_their_own_origins(self):
        source = self.template("game_dir = 'template-game'\n[oracle]\nvoice_directory = 'template-voices'\n")
        self.write_profile({'game_dir': 'user-game'})
        config, _, _ = self.store.startup()
        self.assertEqual(config.game_dir, self.store.path.parent/'user-game')
        self.assertEqual(config.oracle.voice_directory, str(source.parent/'template-voices'))
        self.write_profile({'oracle': {'voice_directory': 'user-voices'}})
        config, _, _ = self.store.startup()
        self.assertEqual(config.game_dir, source.parent/'template-game')
        self.assertEqual(config.oracle.voice_directory, str(self.store.path.parent/'user-voices'))

    def test_upgrade_without_template_uses_code_defaults(self):
        self.enterContext(patch('rw_creature_pet.settings_store.default_template_path', return_value=None))
        original = self.write_profile({'audio': {'enabled': False}})
        config, first, message = self.store.startup()
        self.assertFalse(first)
        self.assertFalse(config.audio.enabled)
        self.assertEqual(config.overseer, AppConfig().overseer)
        self.assertEqual(message, '')
        self.assertEqual(self.store.path.with_suffix('.json.bak').read_bytes(), original)

    def test_explicit_config_does_not_migrate_or_modify_user_file(self):
        source = self.template('[desktop]\nscale = 1.5\n')
        original = self.write_profile({'desktop': {'scale': 2.}})
        config, first, message = self.store.startup(source)
        self.assertFalse(first)
        self.assertEqual(message, '')
        self.assertEqual(config.desktop.scale, 1.5)
        self.assertEqual(self.store.path.read_bytes(), original)
        self.assertFalse(self.store.path.with_suffix('.json.bak').exists())

    def test_upgrade_write_failure_keeps_user_values_and_reports_without_reset(self):
        self.template('[desktop]\nscale = 1.5\n[overseer]\nsize = 0.8\n')
        original = self.write_profile({'desktop': {'scale': 2.}, 'audio': {'enabled': False}})
        with patch.object(Path, 'replace', side_effect=PermissionError('locked')):
            config, first, message = self.store.startup()
        self.assertFalse(first)
        self.assertEqual(config.desktop.scale, 2.)
        self.assertFalse(config.audio.enabled)
        self.assertEqual(config.overseer.size, .8)
        self.assertIn('无法保存新增设置', message)
        self.assertEqual(self.store.path.read_bytes(), original)
        self.assertEqual(list(self.store.path.parent.glob('*.tmp')), [])
        self.assertEqual(self.store.path.with_suffix('.json.bak').read_bytes(), original)

    def test_invalid_or_future_user_values_are_not_silently_replaced(self):
        self.template('[audio]\nenabled = true\n')
        for version, data in ((2, {}), (1, {'audio': None}), (1, {'audio': {'volume': -1}}),
                              (1, {'unknown_option': True}), (1, {'oracle': {'allowed_edges': []}})):
            with self.subTest(version=version, data=data):
                original = self.write_profile(data, version=version)
                _, first, message = self.store.startup()
                self.assertTrue(first)
                self.assertIn('无法读取已保存设置', message)
                self.assertEqual(self.store.path.read_bytes(), original)
                self.assertFalse(self.store.path.with_suffix('.json.bak').exists())

    def test_invalid_release_template_does_not_touch_user_profile(self):
        self.template('[audio]\nvolume = -1\n')
        original = self.write_profile({'audio': {'volume': .4}})
        with self.assertRaises(ValueError):
            self.store.startup()
        self.assertEqual(self.store.path.read_bytes(), original)
        self.assertFalse(self.store.path.with_suffix('.json.bak').exists())

    def test_frozen_upgrade_uses_bundled_toml_without_sidecar_or_cwd_dependency(self):
        bundle = self.root/'unpacked'
        bundle.mkdir()
        (bundle/'config.toml').write_text("[overseer]\ncolor = '#ff557f'\nsize = 0.8\n", encoding='utf-8')
        original = self.write_profile({'desktop': {'scale': 2.}})
        with patch('sys.frozen', True, create=True), \
             patch('sys.executable', str(self.root/'installed/BellPet.exe')), \
             patch('sys._MEIPASS', str(bundle), create=True):
            config, first, message = self.store.startup()
        self.assertFalse(first)
        self.assertEqual(message, '')
        self.assertEqual(config.desktop.scale, 2.)
        self.assertEqual(config.overseer.color, '#ff557f')
        self.assertEqual(config.overseer.size, .8)
        self.assertEqual(self.store.path.with_suffix('.json.bak').read_bytes(), original)
