"""发行包只含 original；新安装、旧配置升级和重复更新均保留用户设置"""
from copy import deepcopy
from dataclasses import asdict, replace
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from rw_creature_pet.config import AppConfig
from rw_creature_pet.presets.editing import PresetLink
from rw_creature_pet.presets.personal import PersonalEntry, apply_values
from rw_creature_pet.presets.profile import load_profile
from rw_creature_pet.presets.profile_library import ProfileLibrary
from rw_creature_pet.presets.sharing import write_snapshot
from rw_creature_pet.presets.startup import prepare_character
from rw_creature_pet.presets.workspace import ensure_workspace, read_entry, save_entry, values_from_profile
from rw_creature_pet.settings_store import SettingsStore
from tools.packaging.release import build_release, load_catalog, validate_release
from tools.packaging.verify_bell import stage_release


class ReleasePackageTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.config = AppConfig(game_dir=self.root/'game')
        self.library = ProfileLibrary(self.root/'profiles')
        self.role = self.library.export(self.config, 'A')
        self.catalog = self.root/'catalog.json'
        self.catalog.write_text(json.dumps({'version': 1, 'characters': [
            {'id': self.role.id, 'directory': self.role.path.parent.name}]}), encoding='utf-8')
        self.exe = self.root/'bin/BellPet.exe'
        self.exe.parent.mkdir()
        self.exe.write_bytes(b'MZ-fixture')
        self.output = self.root/'release'
        self.enterContext(patch('rw_creature_pet.settings_store.load_defaults', return_value=self.config))

    def build(self, *, output=None, overrides=()):
        return build_release(self.exe, output or self.output, profiles=self.library.directory,
                             catalog=self.catalog, overrides=overrides)

    def path(self, output=None):
        return (output or self.output)/'presets/profiles'/self.role.path.parent.name

    def override(self, color, name):
        source = ProfileLibrary(self.root/name)
        archive = self.root/(name+'.zip')
        source.export_share(apply_values(self.config, {'oracle.colors.skin': color}), archive,
                            name='A', preset_id=self.role.id)
        return archive

    def test_release_contains_only_registered_originals_and_executable(self):
        ensure_workspace(self.role.path)
        before = {p: p.read_bytes() for p in self.role.path.parent.rglob('*') if p.is_file()}
        self.library.export(self.config, 'Private recovery')
        result = self.build()
        self.assertEqual(validate_release(result)['characters'][0]['id'], self.role.id)
        self.assertFalse((self.path()/'profile.json').exists())
        self.assertFalse((self.path()/'appearance').exists())
        self.assertFalse((self.path()/'character.json').exists())
        self.assertEqual(len(list((result/'presets/profiles').iterdir())), 1)
        self.assertEqual(before, {p: p.read_bytes() for p in self.role.path.parent.rglob('*') if p.is_file()})
        with ZipFile(result.with_name(result.name+'.zip')) as archive:
            self.assertIn('BellPet.exe', archive.namelist())
            styles = ('presets/behavior_styles/builtin.toml', 'presets/behavior_styles/README.md')
            self.assertTrue(all(name in archive.namelist() for name in styles))
            self.assertNotIn('presets/behavior_styles/local.toml', archive.namelist())
            self.assertTrue(all(name.startswith('presets/profiles/'+self.role.path.parent.name+'/original/')
                for name in archive.namelist() if name not in ('BellPet.exe', 'release.json', *styles)))

    def test_local_current_changes_are_excluded_until_explicit_share_override(self):
        ensure_workspace(self.role.path)
        entry = read_entry(self.role.path)
        entry.overrides['oracle.colors.skin'] = '#123456'
        save_entry(entry)
        self.build()
        self.assertEqual(load_profile(self.path()/'original/profile.json').appearance.oracle.colors.skin,
                         self.config.oracle.colors.skin)
        archive = self.override('#abcdef', 'edited')
        self.build(overrides=[archive])
        self.assertEqual(load_profile(self.path()/'original/profile.json').appearance.oracle.colors.skin, '#abcdef')
        self.assertEqual(read_entry(self.role.path).values['oracle.colors.skin'], '#123456')

    def test_fresh_install_initializes_from_originals(self):
        self.build()
        library = ProfileLibrary(self.output/'presets/profiles')
        store = SettingsStore(self.root/'user/settings.json')
        initialized = prepare_character(self.config, store, library=library, defaults=self.config)
        self.assertEqual(initialized.state.entries[initialized.state.active].source.id, self.role.id)
        self.assertTrue((self.path()/'profile.json').is_file())

    def test_two_overlay_updates_keep_current_values_and_change_restore_source(self):
        self.build()
        install = self.root/'installed'
        shutil.copytree(self.output, install)
        library = ProfileLibrary(install/'presets/profiles')
        store = SettingsStore(self.root/'user/settings.json')
        initialized = prepare_character(self.config, store, library=library, defaults=self.config)
        key = initialized.state.active
        entry = deepcopy(initialized.state.entries[key])
        entry.overrides['oracle.colors.skin'] = '#123456'
        with store.preset_state(initialized.state.serialize(key, entry)):
            store.save(apply_values(initialized.config, entry.values))
        for index, color in enumerate(('#abcdef', '#654321')):
            self.build(overrides=[self.override(color, 'update-'+str(index))])
            shutil.copytree(self.output, install, dirs_exist_ok=True)
            initialized = prepare_character(store.load(), store, library=library, defaults=self.config)
            current = initialized.state.entries[initialized.state.active]
            self.assertEqual(initialized.config.oracle.colors.skin, '#123456')
            self.assertEqual(current.defaults['oracle.colors.skin'], color)
            self.assertEqual(current.source.id, self.role.id)

    def test_old_settings_merge_survives_overlay_of_new_originals(self):
        install = self.root/'installed'
        target = install/'presets/profiles'/self.role.path.parent.name
        write_snapshot(self.role, target)
        old = PersonalEntry('profile', PresetLink.of(load_profile(target/'profile.json')),
                            values_from_profile(self.role), {'oracle.colors.skin': '#123456'})
        store = SettingsStore(self.root/'user/settings.json')
        store.path.parent.mkdir()
        config = asdict(self.config)
        config['game_dir'] = str(self.config.game_dir)
        store.path.write_text(json.dumps({'version': 1, 'config': config,
            'preset_state': {'version': 2, 'active': 'old', 'entries': {'old': old.serialize()}}}), encoding='utf-8')
        self.build(overrides=[self.override('#abcdef', 'update')])
        shutil.copytree(self.output, install, dirs_exist_ok=True)
        initialized = prepare_character(self.config, store,
            library=ProfileLibrary(install/'presets/profiles'), defaults=self.config)
        current = initialized.state.entries[initialized.state.active]
        self.assertEqual(initialized.config.oracle.colors.skin, '#123456')
        self.assertEqual(current.defaults['oracle.colors.skin'], '#abcdef')

    def test_validator_rejects_current_config_and_unreferenced_files(self):
        self.build()
        for path in (self.path()/'profile.json', self.path()/'original/settings.json'):
            path.write_text('{}', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, '多余文件'):
                validate_release(self.output)
            path.unlink()

    def test_failed_archive_generation_keeps_previous_release(self):
        self.build()
        before = (self.output/'release.json').read_bytes(), self.output.with_suffix('.zip').read_bytes()
        with patch('tools.packaging.release.write_zip', side_effect=OSError('full disk')):
            with self.assertRaises(OSError):
                self.build()
        self.assertEqual(before, ((self.output/'release.json').read_bytes(), self.output.with_suffix('.zip').read_bytes()))

    def test_unknown_override_and_duplicate_catalog_are_rejected(self):
        other = self.library.export(self.config, 'Not published')
        with self.assertRaisesRegex(ValueError, '未登记'):
            self.build(overrides=[other.path])
        data = json.loads(self.catalog.read_text(encoding='utf-8'))
        data['characters'].append(data['characters'][0])
        self.catalog.write_text(json.dumps(data), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, '重复'):
            load_catalog(self.catalog)

    def test_refuses_to_replace_arbitrary_existing_directory(self):
        self.output.mkdir()
        keep = self.output/'user.txt'
        keep.write_text('preserve', encoding='utf-8')
        with self.assertRaises(OSError):
            self.build()
        self.assertEqual(keep.read_text(encoding='utf-8'), 'preserve')

    def test_verifier_stages_actual_zip_and_checks_executable(self):
        self.build()
        staged, manifest = stage_release(self.root/'release.zip', self.root/'verified', self.exe)
        self.assertEqual(staged.read_bytes(), self.exe.read_bytes())
        self.assertEqual(manifest['characters'][0]['id'], self.role.id)
        self.exe.write_bytes(b'MZ-different')
        with self.assertRaisesRegex(ValueError, 'EXE'):
            stage_release(self.root/'release.zip', self.root/'wrong-version', self.exe)

    def test_verifier_rejects_zip_escape_and_extra_files(self):
        bad = self.root/'bad.zip'
        with ZipFile(bad, 'w') as package:
            package.writestr('../outside.txt', 'bad')
        with self.assertRaises(ValueError):
            stage_release(bad, self.root/'rejected', self.exe)
        self.assertFalse((self.root/'outside.txt').exists())
        self.build()
        with ZipFile(self.root/'release.zip', 'a') as package:
            package.writestr('settings.json', '{}')
        with self.assertRaisesRegex(ValueError, '多余文件'):
            stage_release(self.root/'release.zip', self.root/'extra-files', self.exe)


if __name__ == '__main__':
    unittest.main()
