"""清理只处理有旧迁移指纹的生成目录，保留内容并验证设置失败的回滚"""
from copy import deepcopy
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch
from uuid import NAMESPACE_URL, uuid5

from rw_creature_pet.config import AppConfig
from rw_creature_pet.presets.editing import PresetLink
from rw_creature_pet.presets.migration import backup_legacy, migration_marker
from rw_creature_pet.presets.migration_cleanup import apply_cleanup, directory_digest, plan_cleanup
from rw_creature_pet.presets.personal import PersonalEntry, PersonalState, apply_values
from rw_creature_pet.presets.profile_library import ProfileLibrary
from rw_creature_pet.presets.workspace import ensure_workspace, read_entry, save_entry, values_from_profile
from rw_creature_pet.settings_store import SettingsStore


class MigrationCleanupTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.library = ProfileLibrary(self.root/'presets/profiles')
        self.store = SettingsStore(self.root/'user/settings.json')
        self.config = AppConfig(game_dir=self.root)
        self.enterContext(patch('rw_creature_pet.settings_store.load_defaults', return_value=self.config))
        self.role = self.library.export(self.config, 'A')
        old = PersonalEntry('profile', PresetLink.of(self.role), values_from_profile(self.role))
        self.older = deepcopy(old)
        self.older.overrides['oracle.colors.skin'] = '#123456'
        self.store.path.parent.mkdir(parents=True)
        self.store.path.write_text(json.dumps({'version': 1, 'config': {}, 'preset_state': {
            'version': 2, 'active': 'current', 'entries': {'current': old.serialize(), 'older': self.older.serialize()}}}), encoding='utf-8')
        backup_legacy(self.store)
        ensure_workspace(self.role.path)
        normal = read_entry(self.role.path)
        normal = save_entry(normal, migration_key=migration_marker('current', old))
        generated = self.library.export(self.config, 'A（旧版恢复）',
            preset_id=str(uuid5(NAMESPACE_URL, 'rw-creature-pet:recovery:older')))
        ensure_workspace(generated.path)
        recovered = read_entry(generated.path)
        recovered.overrides.update(self.older.overrides)
        recovered = save_entry(recovered, migration_key=migration_marker('older', self.older))
        self.generated = recovered.source.path.parent
        state = PersonalState()
        state.workspace = True
        for entry in (normal, recovered):
            key = state.key('profile', entry.source)
            state.entries[key] = entry
        state.active = state.key('profile', normal.source)
        with self.store.preset_state(state.serialize()):
            self.store.save(self.config)

    def test_plan_is_read_only_and_does_not_use_name_matching(self):
        custom = self.library.export(self.config, 'Another（旧版恢复）')
        before = self.store.path.read_bytes(), directory_digest(self.generated)
        plan = plan_cleanup(self.store, self.library)
        archived = [r for r in plan['rows'] if r['action'] == 'archive']
        self.assertEqual(len(archived), 1)
        self.assertEqual(Path(archived[0]['path']), self.generated)
        self.assertTrue(any(r['action'] == 'keep' and r['id'] == custom.id for r in plan['rows']))
        self.assertEqual(before, (self.store.path.read_bytes(), directory_digest(self.generated)))

    def test_archive_preserves_full_folder_and_removes_only_its_reference(self):
        normal = directory_digest(self.role.path.parent)
        expected = directory_digest(self.generated)
        result = apply_cleanup(self.store, self.library, plan_cleanup(self.store, self.library))
        archived = Path(result['archive_directory'])/self.generated.name
        self.assertFalse(self.generated.exists())
        self.assertEqual(directory_digest(archived), expected)
        self.assertEqual(directory_digest(self.role.path.parent), normal)
        self.assertEqual(len(self.library.scan().presets), 1)
        self.assertEqual(len(self.store.load_preset_state()['entries']), 1)
        self.assertTrue(Path(result['settings_backup']).is_file())
        self.assertEqual(apply_cleanup(self.store, self.library, plan_cleanup(self.store, self.library))['archived'], 0)

    def test_modified_recovery_is_archived_with_its_latest_values(self):
        entry = read_entry(self.generated/'profile.json')
        entry.overrides['oracle.colors.skin'] = '#abcdef'
        save_entry(entry)
        plan = plan_cleanup(self.store, self.library)
        self.assertTrue(next(r for r in plan['rows'] if r['action'] == 'archive')['changed_values'])
        result = apply_cleanup(self.store, self.library, plan)
        moved = Path(result['archive_directory'])/self.generated.name/'profile.json'
        self.assertEqual(read_entry(moved).values['oracle.colors.skin'], '#abcdef')

    def test_settings_failure_rolls_back_all_directory_moves(self):
        before = self.store.path.read_bytes(), directory_digest(self.generated)
        plan = plan_cleanup(self.store, self.library)
        with patch.object(self.store, '_write', side_effect=OSError('locked')):
            with self.assertRaises(OSError):
                apply_cleanup(self.store, self.library, plan)
        self.assertEqual(before, (self.store.path.read_bytes(), directory_digest(self.generated)))
        self.assertEqual(len(self.library.scan().presets), 2)

    def test_changed_settings_or_role_invalidates_plan(self):
        plan = plan_cleanup(self.store, self.library)
        self.store.path.write_bytes(self.store.path.read_bytes()+b'\n')
        with self.assertRaisesRegex(ValueError, 'settings 已改变'):
            apply_cleanup(self.store, self.library, plan)
        plan = plan_cleanup(self.store, self.library)
        (self.generated/'extra.txt').write_text('new data', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, '角色目录已改变'):
            apply_cleanup(self.store, self.library, plan)
        self.assertTrue(self.generated.exists())

    def test_active_recovery_switches_to_original_character(self):
        data = self.store.read_document()
        state = data['preset_state']
        state['active'] = next(key for key, value in state['entries'].items() if value['source']['path'] == str(self.generated/'profile.json'))
        self.store._write(data)
        result = apply_cleanup(self.store, self.library, plan_cleanup(self.store, self.library))
        state = self.store.load_preset_state()
        self.assertEqual(state['entries'][state['active']]['source']['id'], self.role.id)
        self.assertEqual(result['archived'], 1)

    def test_scope_check_prevents_moving_library_root(self):
        plan = plan_cleanup(self.store, self.library)
        row = next(r for r in plan['rows'] if r['action'] == 'archive')
        row['path'] = str(self.library.directory)
        with self.assertRaisesRegex(ValueError, '清理范围'):
            apply_cleanup(self.store, self.library, plan)
        self.assertTrue(self.generated.exists())

    def test_active_appearance_session_generated_by_old_migration_is_identified(self):
        from rw_creature_pet.presets.library import AppearanceLibrary
        from rw_creature_pet.presets.personal import capture
        from rw_creature_pet.presets.profile import load_profile
        look = AppearanceLibrary(self.root/'looks').export(self.config, 'Old look')
        old = PersonalEntry('appearance', PresetLink.of(look), capture(self.config, 'appearance', self.root/'images'))
        raw = {'version': 1, 'config': {}, 'preset_state': {'version': 2, 'active': 'ap',
            'directory_migration': {'raw_values': {'oracle.float_speed': .9}},
            'entries': {'ap': old.serialize()}}}
        path = self.store.path.parent/'migrations/characters-v1/active-appearance/settings.json'
        path.parent.mkdir()
        path.write_text(json.dumps(raw), encoding='utf-8')
        defaults = values_from_profile(load_profile(self.role.path.parent/'original/profile.json'))
        converted = PersonalEntry('profile', old.source, {**defaults, **old.defaults}, {'oracle.float_speed': .9})
        preset = self.library.export(self.config, 'Old look', preset_id=look.id)
        ensure_workspace(preset.path)
        entry = read_entry(preset.path)
        entry.overrides['oracle.float_speed'] = .9
        save_entry(entry, migration_key=migration_marker('ap', converted))
        row = next(r for r in plan_cleanup(self.store, self.library)['rows'] if r['id'] == look.id)
        self.assertEqual(row['action'], 'archive')

    def test_receipt_failure_does_not_report_rolled_back_committed_cleanup(self):
        from rw_creature_pet.presets.common import write_document
        def write(path, data):
            if data.get('status') == 'complete':
                raise OSError('receipt unavailable')
            return write_document(path, data)
        with patch('rw_creature_pet.presets.migration_cleanup.write_document', side_effect=write):
            result = apply_cleanup(self.store, self.library, plan_cleanup(self.store, self.library))
        self.assertEqual(result['archived'], 1)
        self.assertTrue(result['receipt_errors'])
        self.assertEqual(len(self.store.load_preset_state()['entries']), 1)
        self.assertFalse(self.generated.exists())


if __name__ == '__main__':
    unittest.main()
