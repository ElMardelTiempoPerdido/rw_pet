"""角色 ZIP 分享和导入的跨目录往返、冲突选择与失败保护"""
from dataclasses import replace
import json
from pathlib import Path
import shutil
import stat
import tempfile
import unittest
from zipfile import ZipFile, ZipInfo

from PIL import Image

from rw_creature_pet.config import AppConfig
from rw_creature_pet.presets.personal import apply_values
from rw_creature_pet.presets.profile import load_profile
from rw_creature_pet.presets.profile_library import ProfileLibrary
from rw_creature_pet.presets.sharing import content_key, open_profile, write_snapshot
from rw_creature_pet.presets.workspace import ensure_workspace, read_entry, save_entry


class ProfileSharingTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.image = self.root/'source.png'
        Image.new('RGBA', (4, 4), 'red').save(self.image)
        self.config = apply_values(AppConfig(game_dir=self.root/'private-game'), {
            'oracle.body_appearance': 'custom', 'oracle.voice': 'bell',
            'oracle.custom_colors.skin': '#123456', 'oracle.colors.skin': '#abcdef',
            'oracle.float_speed': 1.234567,
            'oracle.custom_appearance.forehead.enabled': True,
            'oracle.custom_appearance.forehead.image_path': str(self.image)})
        self.library = ProfileLibrary(self.root/'profiles')
        self.role = self.library.export(self.config, 'A')
        ensure_workspace(self.role.path)
        self.incoming = ProfileLibrary(self.root/'incoming')

    def changed(self):
        return self.incoming.export(apply_values(self.config, {'oracle.custom_colors.skin': '#654321',
                                                             'oracle.float_speed': .9}),
                                    'New name', preset_id=self.role.id)

    def share(self, config=None):
        return self.library.export_share(config or self.config, self.root/'share.zip',
            name='A', preset_id=self.role.id)

    def test_share_preserves_id_and_current_effect_as_new_defaults_without_local_edits(self):
        previous = {p: p.read_bytes() for p in self.role.path.parent.rglob('*') if p.is_file()}
        archive = self.share()
        with open_profile(archive) as preset:
            self.assertEqual(preset.id, self.role.id)
            self.assertEqual(preset.config.oracle.voice, 'bell')
            self.assertEqual(preset.config.oracle.float_speed, 1.234567)
            self.assertEqual(preset.appearance.oracle.colors.skin, '#abcdef')
            self.assertEqual(content_key(preset)[1], content_key(preset)[2])
        self.assertEqual(previous, {p: p.read_bytes() for p in self.role.path.parent.rglob('*') if p.is_file()})
        with ZipFile(archive) as package:
            self.assertFalse(any('/history/' in name or name.endswith('.bak') for name in package.namelist()))
            for name in package.namelist():
                if name.endswith('.json'):
                    payload = package.read(name)
                    self.assertNotIn(str(self.root).encode(), payload)
                    self.assertNotIn(b'game_dir', payload)

    def test_import_after_removing_all_sender_resources_and_restore_default(self):
        archive = self.share()
        shutil.rmtree(self.library.directory)
        self.image.unlink()
        destination = ProfileLibrary(self.root/'receiver')
        imported = destination.import_file(archive)
        archive.unlink()
        entry = read_entry(imported.path)
        self.assertEqual(entry.values['oracle.custom_colors.skin'], '#123456')
        self.assertTrue(Path(entry.values['oracle.custom_appearance.forehead.image_path']).is_file())
        entry.overrides['oracle.custom_colors.skin'] = '#111111'
        saved = save_entry(entry)
        self.assertEqual(saved.defaults['oracle.custom_colors.skin'], '#123456')

    def test_manual_folder_keeps_current_effect_and_its_original_baseline(self):
        entry = read_entry(self.role.path)
        entry.overrides['oracle.custom_colors.skin'] = '#654321'
        save_entry(entry)
        copied = ProfileLibrary(self.root/'receiver').import_file(self.role.path.parent)
        received = read_entry(copied.path)
        self.assertEqual(received.values['oracle.custom_colors.skin'], '#654321')
        self.assertEqual(received.defaults['oracle.custom_colors.skin'], '#123456')

    def test_same_id_different_content_requires_explicit_choice(self):
        incoming = self.changed()
        before = self.role.path.read_bytes()
        with self.assertRaisesRegex(ValueError, '同 ID'):
            self.library.import_file(incoming.path)
        self.assertEqual(self.role.path.read_bytes(), before)

    def test_same_id_keep_preserves_current_and_original_bytes(self):
        incoming = self.changed()
        before = self.role.path.read_bytes(), (self.role.path.parent/'original/profile.json').read_bytes()
        kept = self.library.import_file(incoming.path, conflict='keep')
        self.assertEqual(kept.path, self.role.path)
        self.assertEqual(before, (kept.path.read_bytes(), (kept.path.parent/'original/profile.json').read_bytes()))

    def test_replace_accepts_older_incoming_and_backs_up_previous_role(self):
        incoming = self.changed()
        data = json.loads(incoming.path.read_text(encoding='utf-8'))
        data['updated_at'] = '2000-01-01T00:00:00+00:00'
        incoming.path.write_text(json.dumps(data), encoding='utf-8')
        replaced = self.library.import_file(incoming.path, conflict='replace')
        self.assertEqual(replaced.path, self.role.path)
        self.assertEqual(replaced.name, 'New name')
        self.assertEqual(read_entry(replaced.path).defaults['oracle.custom_colors.skin'], '#654321')
        self.assertEqual(replaced.appearance.oracle.custom_colors.skin, '#654321')
        backups = list((replaced.path.parent/'history/imports').glob('*/profile.json'))
        self.assertEqual(len(backups), 1)
        self.assertEqual(load_profile(backups[0]).appearance.oracle.custom_colors.skin, '#123456')
        self.assertEqual(len(self.library.scan().presets), 1)

    def test_new_character_forks_identity_and_keeps_existing_role(self):
        incoming = self.changed()
        original = self.role.path.read_bytes()
        copied = self.library.import_file(incoming.path, conflict='new')
        self.assertNotEqual(copied.id, self.role.id)
        self.assertEqual(self.role.path.read_bytes(), original)
        self.assertEqual(read_entry(copied.path).defaults['oracle.custom_colors.skin'], '#654321')
        self.assertEqual(len(self.library.scan().presets), 2)

    def test_identical_import_reuses_existing_without_creating_duplicate(self):
        copied = self.incoming.import_file(self.role.path)
        result = self.library.import_file(copied.path)
        self.assertEqual(result.path, self.role.path)
        self.assertEqual(len(self.library.scan().presets), 1)

    def test_failed_apply_rolls_back_replacement_and_original(self):
        incoming = self.changed()
        previous = self.role.path.read_bytes(), (self.role.path.parent/'original/profile.json').read_bytes()
        with self.assertRaisesRegex(ValueError, 'failed apply'):
            with self.library.import_transaction(incoming.path, conflict='replace'):
                raise ValueError('failed apply')
        self.assertEqual(previous, (self.role.path.read_bytes(), (self.role.path.parent/'original/profile.json').read_bytes()))
        self.assertFalse(self.library.scan().errors)

    def test_failed_apply_removes_only_newly_created_import(self):
        archive = self.share()
        receiver = ProfileLibrary(self.root/'receiver')
        with self.assertRaises(ValueError):
            with receiver.import_transaction(archive):
                raise ValueError('failed apply')
        self.assertFalse(receiver.scan().presets)
        self.assertTrue(self.role.path.exists())

    def test_original_only_package_is_importable(self):
        package = self.root/'original-only'
        write_snapshot(load_profile(self.role.path), package/'original')
        copied = ProfileLibrary(self.root/'receiver').import_file(package)
        self.assertEqual(copied.id, self.role.id)
        self.assertEqual(read_entry(copied.path).defaults['oracle.custom_colors.skin'], '#123456')

    def test_mismatched_original_identity_is_rejected(self):
        incoming = self.changed()
        ensure_workspace(incoming.path)
        original = incoming.path.parent/'original/profile.json'
        data = json.loads(original.read_text(encoding='utf-8'))
        from uuid import uuid4
        data['id'] = str(uuid4())
        original.write_text(json.dumps(data), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'ID 不一致'):
            self.library.import_file(incoming.path, conflict='replace')

    def test_zip_traversal_absolute_duplicate_and_device_paths_are_rejected(self):
        for index, names in enumerate((('../escape.txt',), ('/absolute.txt',), ('C:/absolute.txt',),
                                       ('a\\b.txt',), ('A.txt', 'a.txt'), ('NUL.txt',), ('a. /x',))):
            with self.subTest(names=names):
                archive = self.root/f'bad-{index}.zip'
                with ZipFile(archive, 'w') as package:
                    for name in names:
                        package.writestr(name, 'bad')
                with self.assertRaises(ValueError):
                    with open_profile(archive):
                        pass
        self.assertFalse((self.root/'escape.txt').exists())

    def test_zip_links_and_multiple_characters_are_rejected(self):
        link = ZipInfo('link')
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive = self.root/'link.zip'
        with ZipFile(archive, 'w') as package:
            package.writestr(link, 'outside')
        with self.assertRaises(ValueError):
            with open_profile(archive):
                pass
        folder = self.root/'many'
        write_snapshot(self.role, folder/'a')
        write_snapshot(self.role, folder/'b')
        with self.assertRaises(ValueError):
            with open_profile(folder):
                pass


if __name__ == '__main__':
    unittest.main()
