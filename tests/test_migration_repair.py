"""已迁移错误会话的只读诊断、三方合并、完整备份和失败回滚"""
from copy import deepcopy
from datetime import datetime, timedelta
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

from rw_creature_pet.config import AppConfig
from rw_creature_pet.presets.editing import PresetLink
from rw_creature_pet.presets.migration import _merge, backup_legacy, migration_marker
from rw_creature_pet.presets.migration_cleanup import directory_digest
from rw_creature_pet.presets.migration_repair import apply_repair, plan_repair
from rw_creature_pet.presets.personal import PersonalEntry, PersonalState, apply_values
from rw_creature_pet.presets.profile import load_profile
from rw_creature_pet.presets.profile_library import ProfileLibrary
from rw_creature_pet.presets.workspace import ensure_workspace, metadata, read_entry, save_entry, values_from_profile
from rw_creature_pet.settings_store import SettingsStore


class MigrationRepairTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.image = self.root/'forehead.png'
        Image.new('RGBA', (4, 4), '#fedcba').save(self.image)
        self.config = apply_values(AppConfig(game_dir=self.root/'game'), {
            'oracle.body_appearance': 'custom', 'oracle.custom_colors.skin': '#ffd778',
            'oracle.custom_appearance.forehead.enabled': True,
            'oracle.custom_appearance.forehead.image_path': str(self.image)})
        self.library = ProfileLibrary(self.root/'presets/profiles')
        self.store = SettingsStore(self.root/'user/settings.json')
        self.enterContext(patch('rw_creature_pet.settings_store.load_defaults', return_value=self.config))
        self.role = self.library.export(self.config, 'sunny')
        self.older = PersonalEntry('profile', PresetLink.of(self.role), values_from_profile(self.role), {
            'oracle.custom_colors.skin': '#66a0d3', 'oracle.custom_appearance.forehead.enabled': False,
            'oracle.custom_appearance.forehead.image_path': ''})
        self.role = self.library.update(self.config, self.role)
        self.latest = PersonalEntry('profile', PresetLink.of(self.role), values_from_profile(self.role), {
            'oracle.custom_appearance.forehead.image_path': str(self.image)})
        other = self.library.export(self.config, 'correct')
        self.other = PersonalEntry('profile', PresetLink.of(other), values_from_profile(other))
        self.store.path.parent.mkdir()
        self.store.path.write_text(json.dumps({'version': 1, 'config': {}, 'preset_state': {
            'version': 2, 'active': 'latest', 'entries': {'older': self.older.serialize(),
                'latest': self.latest.serialize(), 'other': self.other.serialize()}}}), encoding='utf-8')
        self.legacy_backup = backup_legacy(self.store)
        ensure_workspace(self.role.path)
        original = load_profile(self.role.path.parent/'original/profile.json')
        defaults, values = _merge(self.older, original)
        current = read_entry(self.role.path)
        current.defaults = defaults
        current.overrides = {key: value for key, value in values.items() if value != defaults.get(key)}
        current = save_entry(current, migration_key=migration_marker('older', self.older))
        ensure_workspace(other.path)
        unaffected = save_entry(read_entry(other.path), migration_key=migration_marker('other', self.other))
        state = PersonalState()
        state.workspace = True
        for entry in (current, unaffected):
            state.entries[state.key('profile', entry.source)] = entry
        state.active = state.key('profile', current.source)
        with self.store.preset_state(state.serialize()):
            self.store.save(self.config)

    def add_second_affected_role(self):
        file = self.legacy_backup/'settings.json'
        data = json.loads(file.read_text(encoding='utf-8'))
        newer = deepcopy(self.other.serialize())
        newer['source']['updated_at'] = (datetime.fromisoformat(newer['source']['updated_at'])+timedelta(seconds=1)).isoformat()
        newer['source']['revision'] = 'f'*64
        newer['overrides']['oracle.custom_colors.skin'] = '#ff1234'
        data['preset_state']['entries']['other-new'] = newer
        file.write_text(json.dumps(data), encoding='utf-8')

    def test_plan_is_read_only_and_matches_migration_fingerprint(self):
        before = directory_digest(self.library.directory), self.store.path.read_bytes()
        plan = plan_repair(self.store, self.library)
        candidates = [row for row in plan['rows'] if row['action'] == 'repair']
        self.assertEqual(len(candidates), 1)
        row = candidates[0]
        self.assertEqual(row['name'], 'sunny')
        self.assertEqual(row['old_key'], 'older')
        self.assertEqual(row['selected_key'], 'latest')
        self.assertIn('oracle.custom_colors.skin', row['corrected_fields'])
        self.assertEqual(before, (directory_digest(self.library.directory), self.store.path.read_bytes()))

    def test_repair_restores_appearance_preserves_new_changes_and_is_idempotent(self):
        entry = read_entry(self.role.path)
        entry.overrides['oracle.float_speed'] = 1.2
        save_entry(entry)
        original = directory_digest(self.role.path.parent/'original')
        correct = directory_digest(self.other.source.path.parent)
        previous = {path.parent.name: directory_digest(path.parent)
                    for path in (self.role.path, self.other.source.path)}
        state_before = self.store.load_preset_state()
        config_before = self.store.read_document()['config']
        result = apply_repair(self.store, self.library, plan_repair(self.store, self.library))
        restored = read_entry(self.role.path)
        self.assertEqual(restored.values['oracle.custom_colors.skin'], '#ffd778')
        self.assertTrue(restored.values['oracle.custom_appearance.forehead.enabled'])
        self.assertTrue(Path(restored.values['oracle.custom_appearance.forehead.image_path']).is_file())
        self.assertEqual(restored.values['oracle.float_speed'], 1.2)
        self.assertEqual(self.store.load().oracle.float_speed, 1.2)
        self.assertEqual(directory_digest(self.role.path.parent/'original'), original)
        self.assertEqual(directory_digest(self.other.source.path.parent), correct)
        self.assertEqual(self.store.read_document()['config'], config_before)
        self.assertEqual(self.store.load_preset_state()['active'], state_before['active'])
        self.assertEqual(result['repaired'], ['sunny'])
        for name, digest in previous.items():
            self.assertEqual(directory_digest(Path(result['backup_directory'])/'before'/name), digest)
        self.assertEqual(apply_repair(self.store, self.library, plan_repair(self.store, self.library))['repaired'], [])

    def test_settings_failure_rolls_back_every_role_and_both_settings_files(self):
        self.add_second_affected_role()
        before = directory_digest(self.library.directory), self.store.path.read_bytes(), self.store.path.with_suffix('.json.bak').read_bytes()
        with patch.object(self.store, '_write', side_effect=OSError('disk full')):
            with self.assertRaisesRegex(OSError, 'disk full'):
                apply_repair(self.store, self.library, plan_repair(self.store, self.library))
        self.assertEqual(before, (directory_digest(self.library.directory), self.store.path.read_bytes(),
                                 self.store.path.with_suffix('.json.bak').read_bytes()))

    def test_failed_second_manifest_commit_rolls_back_prior_roles(self):
        self.add_second_affected_role()
        before = directory_digest(self.library.directory), self.store.path.read_bytes()
        original_replace = Path.replace
        def locked(source, target):
            if Path(target) == self.role.path:
                raise OSError('manifest locked')
            return original_replace(source, target)
        with patch.object(Path, 'replace', locked):
            with self.assertRaisesRegex(OSError, 'manifest locked'):
                apply_repair(self.store, self.library, plan_repair(self.store, self.library))
        self.assertEqual(before, (directory_digest(self.library.directory), self.store.path.read_bytes()))

    def test_directory_in_use_does_not_require_moving_it(self):
        with patch.object(Path, 'rename', side_effect=PermissionError('directory in use')):
            result = apply_repair(self.store, self.library, plan_repair(self.store, self.library))
        self.assertEqual(result['repaired'], ['sunny'])
        self.assertEqual(read_entry(self.role.path).values['oracle.custom_colors.skin'], '#ffd778')

    def test_plan_rejects_changed_role_settings_or_backup(self):
        plan = plan_repair(self.store, self.library)
        (self.role.path.parent/'changed.txt').write_text('changed', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, '已改变'):
            apply_repair(self.store, self.library, plan)
        plan = plan_repair(self.store, self.library)
        self.store.path.write_bytes(self.store.path.read_bytes()+b'\n')
        with self.assertRaisesRegex(ValueError, '已改变'):
            apply_repair(self.store, self.library, plan)
        plan = plan_repair(self.store, self.library)
        file = self.legacy_backup/'settings.json'
        data = json.loads(file.read_text(encoding='utf-8'))
        data['preset_state']['entries']['latest']['overrides']['oracle.float_speed'] = .9
        file.write_text(json.dumps(data), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, '已改变'):
            apply_repair(self.store, self.library, plan)

    def test_backup_images_are_used_when_external_source_has_disappeared(self):
        self.image.unlink()
        result = apply_repair(self.store, self.library, plan_repair(self.store, self.library))
        image = Path(read_entry(self.role.path).values['oracle.custom_appearance.forehead.image_path'])
        self.assertTrue(image.is_file() and image.is_relative_to(self.role.path.parent))
        self.assertEqual(result['repaired'], ['sunny'])
        self.assertEqual(metadata(load_profile(self.role.path))['migration_key'], migration_marker('latest', self.latest))

    def test_explicit_discard_can_remove_post_migration_values(self):
        entry = read_entry(self.role.path)
        entry.overrides['oracle.float_speed'] = .9
        save_entry(entry)
        apply_repair(self.store, self.library, plan_repair(self.store, self.library, preserve_changes=False))
        self.assertEqual(read_entry(self.role.path).values['oracle.float_speed'], self.config.oracle.float_speed)

    def test_unknown_migration_marker_is_not_repaired_by_name(self):
        save_entry(read_entry(self.role.path), migration_key='unknown')
        plan = plan_repair(self.store, self.library)
        self.assertFalse(any(row['action'] == 'repair' for row in plan['rows']))
        self.assertEqual(apply_repair(self.store, self.library, plan)['repaired'], [])


if __name__ == '__main__':
    unittest.main()
