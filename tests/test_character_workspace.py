"""角色目录的真实文件往返、旧记录迁移、失败回滚和资源可移植性"""
from copy import deepcopy
from dataclasses import asdict, replace
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

from rw_creature_pet.config import AppConfig
from rw_creature_pet.presets.editing import PresetLink
from rw_creature_pet.presets.personal import PersonalEntry, PersonalState, apply_values, capture
from rw_creature_pet.presets.profile import load_profile
from rw_creature_pet.presets.profile_library import ProfileLibrary
from rw_creature_pet.presets.startup import prepare_character
from rw_creature_pet.presets.workspace import (copy_snapshot, ensure_workspace, read_entry,
                                              values_from_profile)
from rw_creature_pet.settings_store import SettingsStore


class CharacterWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.library = ProfileLibrary(self.root/'roles')
        self.store = SettingsStore(self.root/'user/settings.json')
        self.config = AppConfig(game_dir=self.root/'game')
        self.enterContext(patch('rw_creature_pet.settings_store.load_defaults', return_value=self.config))

    def prepare(self):
        return prepare_character(self.config, self.store, library=self.library, defaults=self.config)

    def commit(self, result, changes=None):
        key = result.state.active
        entry = deepcopy(result.state.entries[key])
        if changes:
            entry.overrides.update(changes)
        with self.store.preset_state(result.state.serialize(key, entry)):
            self.store.save(apply_values(result.config, entry.values))
        return self.prepare()

    def legacy(self, entries, active):
        self.store.path.parent.mkdir(parents=True, exist_ok=True)
        config = asdict(self.config)
        config['game_dir'] = str(self.config.game_dir)
        self.store.path.write_text(json.dumps({'version': 1, 'config': config,
            'preset_state': {'version': 2, 'autosave': False, 'active': active,
                             'entries': {key: entry.serialize() for key, entry in entries.items()}}}), encoding='utf-8')
        return self.store.path.read_bytes()

    def old_entry(self, preset, overrides=None):
        return PersonalEntry('profile', PresetLink.of(preset), values_from_profile(preset), overrides or {})

    def test_original_only_initializes_once_and_scan_skips_nested_copies(self):
        source = self.library.export(self.config, 'A')
        root = source.path.parent
        copy_snapshot(source, root/'original')
        source.path.unlink()
        shutil.rmtree(source.appearance.path.parent)
        self.assertEqual(len(self.library.scan().presets), 1)
        first = self.prepare()
        current = self.commit(first, {'oracle.colors.skin': '#abcdef'})
        before = (root/'profile.json').read_bytes()
        ensure_workspace(root/'profile.json')
        self.assertEqual((root/'profile.json').read_bytes(), before)
        self.assertEqual(current.config.oracle.colors.skin, '#abcdef')
        shutil.copytree(root/'original', root/'history/snapshot')
        shutil.copytree(root/'original', root/'recovery/snapshot')
        self.assertEqual(len(self.library.scan().presets), 1)

    def test_save_persists_current_not_defaults_or_global_role_values(self):
        role = self.library.export(self.config, 'A')
        first = self.prepare()
        original = (role.path.parent/'original/profile.json').read_bytes()
        saved = self.commit(first, {'oracle.colors.skin': '#123456', 'oracle.float_speed': 1.2,
                                    'oracle.voice': 'none'})
        data = self.store.read_document()
        self.assertEqual(data['preset_state']['version'], 3)
        self.assertNotIn('pending', data['preset_state'])
        self.assertNotIn('defaults', str(data['preset_state']))
        self.assertNotIn('skin', str(data['config']))
        self.assertNotIn('float_speed', data['config']['oracle'])
        self.assertEqual(self.store.load().oracle.float_speed, 1.2)
        self.assertEqual(saved.config.oracle.voice, 'none')
        self.assertEqual((role.path.parent/'original/profile.json').read_bytes(), original)

    def test_two_release_updates_change_defaults_but_keep_current(self):
        self.library.export(self.config, 'A')
        result = self.commit(self.prepare(), {'oracle.colors.skin': '#123456'})
        entry = result.state.entries[result.state.active]
        for speed in (.8, 1.3):
            release = ProfileLibrary(self.root/str(speed)).export(
                replace(self.config, oracle=replace(self.config.oracle, float_speed=speed)),
                'A', preset_id=entry.source.id)
            copy_snapshot(release, entry.source.path.parent/'original')
            result = self.prepare()
            self.assertEqual(result.config.oracle.float_speed, self.config.oracle.float_speed)
            self.assertEqual(result.config.oracle.colors.skin, '#123456')
            self.assertEqual(result.state.entries[result.state.active].defaults['oracle.float_speed'], speed)

    def test_all_old_roles_merge_custom_values_and_migration_retries(self):
        first = self.library.export(self.config, 'A')
        second = self.library.export(self.config, 'B')
        entries = {'a': self.old_entry(first, {'oracle.colors.skin': '#123456'}),
                   'b': self.old_entry(second, {'oracle.float_speed': .9, 'oracle.voice': 'none'})}
        payload = self.legacy(entries, 'a')
        # 模拟 exe/presets 已覆盖为新版，而 settings 仍保留旧默认与调整
        self.library.update(replace(self.config, oracle=replace(self.config.oracle,
                            float_speed=1.3)), first)
        result = self.prepare()
        self.assertEqual(result.config.oracle.colors.skin, '#123456')
        self.assertEqual(result.config.oracle.float_speed, 1.3)
        self.assertEqual(len(result.state.entries), 2)
        self.assertFalse(result.state.autosave)
        self.assertEqual(self.store.path.read_bytes(), payload)
        self.assertEqual(len(self.prepare().state.entries), 2)
        with self.store.preset_state(result.state.serialize()):
            self.store.save(result.config)
        self.assertFalse(self.prepare().notice)
        b = next(e for e in self.prepare().state.entries.values() if e.source.id == second.id)
        self.assertEqual(b.values['oracle.float_speed'], .9)
        self.assertEqual(b.values['oracle.voice'], 'none')
        backups = list((self.store.path.parent/'migrations').rglob('settings.json'))
        self.assertTrue(any(p.read_bytes() == payload for p in backups))

    def test_deleted_role_is_only_retained_in_backup(self):
        role = self.library.export(self.config, 'My role')
        self.legacy({'old': self.old_entry(role, {'oracle.colors.skin': '#123456'})}, 'old')
        shutil.rmtree(role.path.parent)
        result = self.prepare()
        self.assertNotEqual(result.state.entries[result.state.active].source.id, role.id)
        self.assertEqual(result.config.oracle.colors.skin, self.config.oracle.colors.skin)
        self.assertFalse(any(p.id == role.id for p in self.library.scan().presets))
        self.assertEqual(result.state.character_setup['directory_migration']['archived'][0]['reason'], 'missing_character')
        self.assertEqual(len(self.prepare().state.entries), 1)

    def test_same_id_old_revisions_are_not_created_as_characters(self):
        role = self.library.export(self.config, 'A')
        self.legacy({'old': self.old_entry(role, {'oracle.colors.skin': '#abcdef'}),
                     'active': self.old_entry(role, {'oracle.colors.skin': '#123456'})}, 'active')
        result = self.prepare()
        self.assertEqual(result.config.oracle.colors.skin, '#123456')
        self.assertEqual(len(result.state.entries), 1)
        self.assertEqual(len(self.library.scan().presets), 1)
        self.assertEqual(result.state.character_setup['directory_migration']['archived'],
                         [{'key': 'old', 'reason': 'older_revision'}])

    def test_failed_settings_commit_rolls_back_current_pointer(self):
        self.library.export(self.config, 'A')
        result = self.commit(self.prepare())
        entry = result.state.entries[result.state.active]
        before = entry.source.path.read_bytes(), self.store.path.read_bytes()
        with patch.object(self.store, '_write', side_effect=OSError('locked')):
            with self.assertRaises(OSError):
                self.commit(result, {'oracle.colors.skin': '#abcdef'})
        self.assertEqual(before, (entry.source.path.read_bytes(), self.store.path.read_bytes()))
        self.assertEqual(self.prepare().config.oracle.colors.skin, self.config.oracle.colors.skin)
        self.assertEqual(self.commit(result, {'oracle.colors.skin': '#abcdef'}).config.oracle.colors.skin, '#abcdef')

    def test_damaged_or_missing_current_is_not_reinitialized(self):
        self.library.export(self.config, 'A')
        result = self.commit(self.prepare())
        path = result.state.entries[result.state.active].source.path
        payload = path.read_bytes()
        for content in (b'{}', None):
            if content is None:
                path.unlink()
            else:
                path.write_bytes(content)
            with self.assertRaises((ValueError, OSError)):
                ensure_workspace(path)
            with self.assertRaises((ValueError, OSError)):
                self.prepare()
            self.assertEqual(path.read_bytes() if path.exists() else None, content)
            path.write_bytes(payload)

    def test_png_history_and_inactive_appearance_survive_directory_copy(self):
        image = self.root/'face.png'
        Image.new('RGBA', (4, 4), 'red').save(image)
        custom = apply_values(self.config, {'oracle.body_appearance': 'custom',
            'oracle.custom_appearance.forehead.enabled': True,
            'oracle.custom_appearance.forehead.image_path': str(image)})
        role = self.library.export(custom, 'A')
        entry = self.old_entry(role, {'oracle.body_appearance': 'bell', 'oracle.colors.skin': '#123456'})
        entry.remember(custom, self.root/'old-cache')
        payload = self.legacy({'a': entry}, 'a')
        result = self.commit(self.prepare())
        root = result.state.entries[result.state.active].source.path.parent
        copied = self.root/'copied'
        shutil.copytree(root, copied)
        shutil.rmtree(root)
        shutil.rmtree(self.root/'old-cache')
        image.unlink()
        loaded = read_entry(copied/'profile.json')
        self.assertEqual(loaded.values['oracle.body_appearance'], 'bell')
        self.assertTrue(Path(loaded.values['oracle.custom_appearance.forehead.image_path']).is_file())
        old = loaded.restore(0, apply_values(self.config, loaded.values), copied/'appearance/images')
        self.assertEqual(old.oracle.body_appearance, 'custom')
        self.assertTrue(Path(old.oracle.custom_appearance.forehead.image_path).is_file())
        self.assertTrue(any(p.read_bytes() == payload for p in (self.store.path.parent/'migrations').rglob('settings.json')))

    def test_generation_cleanup_preserves_current_and_one_rollback(self):
        self.library.export(self.config, 'A')
        result = self.prepare()
        for i in range(5):
            result = self.commit(result, {'oracle.colors.skin': f'#{i+1:06x}'})
        root = result.state.entries[result.state.active].source.path.parent
        self.assertEqual(len(list((root/'history').glob('state-*.json'))), 2)
        self.assertTrue(load_profile(root/'profile.json.bak'))

    def test_concurrent_file_change_rejects_stale_save(self):
        self.library.export(self.config, 'A')
        first = self.commit(self.prepare())
        second = self.commit(self.prepare(), {'oracle.colors.skin': '#123456'})
        with self.assertRaisesRegex(ValueError, '已被修改'):
            self.commit(first, {'oracle.colors.skin': '#abcdef'})
        self.assertEqual(self.prepare().config.oracle.colors.skin, '#123456')

    def test_migration_interrupted_after_one_role_retries_without_duplicates(self):
        first = self.library.export(self.config, 'A')
        second = self.library.export(self.config, 'B')
        payload = self.legacy({'a': self.old_entry(first, {'oracle.colors.skin': '#123456'}),
                               'b': self.old_entry(second, {'oracle.float_speed': .9})}, 'a')
        from rw_creature_pet.presets.workspace import save_entry
        def save(entry, **kwargs):
            if entry.source.id == second.id:
                raise OSError('disk unavailable')
            return save_entry(entry, **kwargs)
        with patch('rw_creature_pet.presets.migration.save_entry', side_effect=save):
            with self.assertRaisesRegex(ValueError, '迁移未完成'):
                self.prepare()
        self.assertEqual(self.store.path.read_bytes(), payload)
        before = first.path.read_bytes()
        result = self.prepare()
        self.assertEqual(first.path.read_bytes(), before)
        self.assertEqual(len(result.state.entries), 2)
        self.assertEqual(len(self.library.scan().presets), 2)

    def test_missing_legacy_image_reports_error_and_preserves_backup(self):
        role = self.library.export(self.config, 'A')
        entry = self.old_entry(role, {'oracle.body_appearance': 'custom',
            'oracle.custom_appearance.forehead.enabled': True,
            'oracle.custom_appearance.forehead.image_path': str(self.root/'missing.png')})
        payload = self.legacy({'a': entry}, 'a')
        with self.assertRaisesRegex(ValueError, '迁移未完成'):
            self.prepare()
        self.assertEqual(self.store.path.read_bytes(), payload)
        self.assertTrue(any(p.read_bytes() == payload for p in (self.store.path.parent/'migrations').rglob('settings.json')))
        Image.new('RGBA', (4, 4), 'white').save(self.root/'missing.png')
        self.assertEqual(self.prepare().config.oracle.body_appearance, 'custom')

    def test_moved_character_directory_resolves_identity_and_preserves_changes(self):
        self.library.export(self.config, 'A')
        result = self.commit(self.prepare(), {'oracle.colors.skin': '#123456'})
        root = result.state.entries[result.state.active].source.path.parent
        moved = root.with_name('renamed-role')
        root.rename(moved)
        result = self.prepare()
        self.assertEqual(result.config.oracle.colors.skin, '#123456')
        self.assertEqual(result.state.entries[result.state.active].source.path.parent, moved)

    def test_legacy_appearance_session_stays_in_backup_without_creating_role(self):
        role = self.library.export(self.config, 'A')
        values = capture(self.config, 'appearance', self.root/'cache')
        appearance = PersonalEntry('appearance', PresetLink.of(role.appearance), values,
                                   {'oracle.colors.skin': '#123456'})
        appearance.remember(self.config, self.root/'cache')
        self.legacy({'appearance': appearance}, 'appearance')
        result = self.prepare()
        self.assertEqual(result.config.oracle.colors.skin, self.config.oracle.colors.skin)
        self.assertEqual(len(result.state.entries[result.state.active].history), 0)
        self.assertEqual(len(self.library.scan().presets), 1)
        self.assertEqual(result.state.character_setup['directory_migration']['archived'][0]['reason'], 'unlinked_or_appearance')

    def test_inactive_character_uses_matching_latest_record_only(self):
        active_role = self.library.export(self.config, 'Active')
        role = self.library.export(self.config, 'Other')
        older = self.old_entry(role, {'oracle.colors.skin': '#123456'})
        latest_role = self.library.update(self.config, role)
        newer = self.old_entry(latest_role, {'oracle.colors.skin': '#abcdef'})
        self.legacy({'a': self.old_entry(active_role), 'old': older, 'new': newer}, 'a')
        result = self.prepare()
        other = next(e for e in result.state.entries.values() if e.source.id == role.id)
        self.assertEqual(other.values['oracle.colors.skin'], '#abcdef')
        self.assertEqual(len(result.state.entries), 2)
        self.assertEqual(len(self.library.scan().presets), 2)

    def test_original_format_version_and_mismatched_identity_are_rejected(self):
        role = self.library.export(self.config, 'A')
        ensure_workspace(role.path)
        marker = role.path.parent/'character.json'
        data = json.loads(marker.read_text(encoding='utf-8'))
        data['version'] = 999
        marker.write_text(json.dumps(data), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, '格式'):
            ensure_workspace(role.path)

    def test_migration_keeps_valid_paired_bounds_when_new_default_conflicts(self):
        old = replace(self.config, oracle=replace(self.config.oracle,
            daily_activity=replace(self.config.oracle.daily_activity, idle_max_seconds=10)))
        role = self.library.export(old, 'A')
        self.legacy({'a': self.old_entry(role, {'oracle.daily_activity.idle_min_seconds': 8})}, 'a')
        self.library.update(self.config, role)
        result = self.prepare()
        self.assertEqual(result.config.oracle.daily_activity.idle_min_seconds, 8)
        self.assertEqual(result.config.oracle.daily_activity.idle_max_seconds, 10)

    def test_failed_role_pointer_replace_preserves_role_and_global_settings(self):
        self.library.export(self.config, 'A')
        result = self.commit(self.prepare())
        path = result.state.entries[result.state.active].source.path
        previous = path.read_bytes(), self.store.path.read_bytes()
        replace_path = Path.replace
        def locked(source, destination):
            if Path(destination) == path:
                raise OSError('manifest locked')
            return replace_path(source, destination)
        with patch.object(Path, 'replace', locked):
            with self.assertRaises(OSError):
                self.commit(result, {'oracle.colors.skin': '#abcdef'})
        self.assertEqual(previous, (path.read_bytes(), self.store.path.read_bytes()))
        self.assertFalse(self.library.scan().errors)


if __name__ == '__main__':
    unittest.main()
