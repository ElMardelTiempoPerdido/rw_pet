"""串联真实 ZIP 覆盖升级、目录迁移和跨进程分享；全部使用临时安装与用户目录"""
from copy import deepcopy
from dataclasses import asdict, replace
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from PIL import Image

from rw_creature_pet.config import AppConfig
from rw_creature_pet.presets.editing import ALL_PATHS, PresetLink, snapshot
from rw_creature_pet.presets.personal import PersonalEntry, apply_values
from rw_creature_pet.presets.profile import load_profile
from rw_creature_pet.presets.profile_library import ProfileLibrary
from rw_creature_pet.presets.startup import BELL_PROFILE_ID, prepare_character
from rw_creature_pet.presets.workspace import read_entry, values_from_profile
from rw_creature_pet.settings_store import SettingsStore
from tools.packaging.release import build_release, validate_release

ROOT = Path(__file__).resolve().parents[1]


def tree_hashes(directory):
    return {str(path.relative_to(directory)): sha256(path.read_bytes()).hexdigest()
            for path in directory.rglob('*') if path.is_file()}


def commit(store, initialized, config=None):
    key = initialized.state.active
    entry = deepcopy(initialized.state.entries[key])
    config = config or initialized.config
    entry.update(config, entry.source.path.parent/'appearance/images')
    with store.preset_state(initialized.state.serialize(key, entry)):
        store.save(apply_values(config, entry.values))


def receive(archive, root, expected_path):
    """另起进程，只拿分享包；安装、重启、修改再恢复，并删除原分享文件"""
    root, archive = Path(root), Path(archive)
    expected = json.loads(Path(expected_path).read_text(encoding='utf-8'))
    base = AppConfig(game_dir=root/'receiver-game')
    library = ProfileLibrary(root/'presets/profiles')
    store = SettingsStore(root/'user/settings.json')
    with patch('rw_creature_pet.settings_store.load_defaults', return_value=base), \
            patch('rw_creature_pet.presets.profile_library.default_profile_directory', return_value=library.directory):
        role = library.import_file(archive)
        archive.unlink()
        initialized = prepare_character(base, store, library=library, defaults=base)
        assert role.id == expected['id']
        assert snapshot(initialized.config, ALL_PATHS) == expected['values']
        current = initialized.state.entries[initialized.state.active]
        assert snapshot(apply_values(base, current.defaults), ALL_PATHS) == expected['values']
        assert not current.history
        commit(store, initialized)
        restarted = store.load()
        assert snapshot(restarted, ALL_PATHS) == expected['values']
        assert restarted.game_dir == base.game_dir
        assert restarted.desktop.scale == base.desktop.scale
        image = Path(restarted.oracle.custom_appearance.forehead.image_path)
        assert image.is_file() and image.is_relative_to(library.directory)
        commit(store, prepare_character(restarted, store, library=library, defaults=base),
               apply_values(restarted, {'oracle.colors.skin': '#000001', 'oracle.float_speed': .31}))
        changed = prepare_character(store.load(), store, library=library, defaults=base)
        entry = changed.state.entries[changed.state.active]
        commit(store, changed, apply_values(changed.config, entry.defaults))
        assert snapshot(store.load(), ALL_PATHS) == expected['values']
        assert len(library.scan().presets) == 1 and not library.scan().errors
        return {'ok': True, 'pid': os.getpid(), 'role_id': role.id,
                'all_fields_equal': True, 'restart': True, 'restore_defaults': True,
                'sender_files_absent': True, 'archive_removed': not archive.exists()}


class ProfileLifecycleTests(unittest.TestCase):
    def test_legacy_upgrade_two_releases_share_and_receive_in_fresh_process(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            image = root/'external-face.png'
            Image.new('RGBA', (4, 4), '#12abcd').save(image)
            base = apply_values(AppConfig(game_dir=root/'sender-game'), {
                'oracle.body_appearance': 'custom', 'oracle.voice': 'none',
                'oracle.custom_appearance.forehead.enabled': True,
                'oracle.custom_appearance.forehead.image_path': str(image)})
            base = replace(base, desktop=replace(base.desktop, scale=2., autonomous=False))
            publisher = ProfileLibrary(root/'publisher/profiles')
            role = publisher.export(base, '角色 A', preset_id=BELL_PROFILE_ID)
            other = publisher.export(base, '角色 B')
            catalogue = root/'catalogue.json'
            catalogue.write_text(json.dumps({'version': 1, 'characters': [
                {'id': p.id, 'directory': p.path.parent.name} for p in (role, other)]}), encoding='utf-8')
            executable = root/'bin/BellPet.exe'
            executable.parent.mkdir()
            executable.write_bytes(b'MZ-lifecycle-fixture')
            output = root/'release'
            build_release(executable, output, profiles=publisher.directory, catalog=catalogue)
            install = root/'installed'
            with ZipFile(root/'release.zip') as archive:
                archive.extractall(install)
            library = ProfileLibrary(install/'presets/profiles')
            # 模拟旧版安装，保留原角色路径以复现覆盖更新时的同 ID 记录匹配
            shutil.copytree(publisher.directory, library.directory, dirs_exist_ok=True)
            current_role = load_profile(library.directory/role.path.parent.name/'profile.json')
            current_other = load_profile(library.directory/other.path.parent.name/'profile.json')
            active = PersonalEntry('profile', PresetLink.of(current_role), values_from_profile(current_role), {
                'oracle.body_appearance': 'bell', 'oracle.colors.skin': '#102030',
                'oracle.float_speed': 1.8})
            active.remember(base, root/'legacy-cache')
            old = deepcopy(active)
            old.overrides['oracle.colors.skin'] = '#000002'
            old.source = replace(old.source, revision='0'*64)
            deleted = publisher.export(base, '已删除角色')
            entries = {'active': active, 'older': old,
                'other': PersonalEntry('profile', PresetLink.of(current_other), values_from_profile(current_other)),
                'deleted': PersonalEntry('profile', PresetLink.of(deleted), values_from_profile(deleted)),
                'appearance': PersonalEntry('appearance', PresetLink.of(role.appearance), {}),
                'unlinked': PersonalEntry('profile', None, {})}
            store = SettingsStore(root/'sender-user/settings.json')
            store.path.parent.mkdir()
            mapping = asdict(base)
            mapping['game_dir'] = str(base.game_dir)
            store.path.write_text(json.dumps({'version': 1, 'config': mapping,
                'preset_state': {'version': 2, 'active': 'active', 'autosave': False,
                    'entries': {key: value.serialize() for key, value in entries.items()}}}), encoding='utf-8')
            legacy_bytes = store.path.read_bytes()
            with patch('rw_creature_pet.settings_store.load_defaults', return_value=base), \
                    patch('rw_creature_pet.presets.profile_library.default_profile_directory', return_value=library.directory):
                for index, opacity in enumerate((.2, .3)):
                    override = root/f'published-{index}.zip'
                    publisher.export_share(apply_values(base, {'oracle.projection_opacity': opacity}), override,
                        name=role.name, preset_id=role.id)
                    build_release(executable, output, profiles=publisher.directory,
                                  catalog=catalogue, overrides=[override])
                    self.assertEqual(len(validate_release(output)['characters']), 2)
                    with ZipFile(root/'release.zip') as archive:
                        archive.extractall(install)
                    loaded, first_run, message = store.startup()
                    self.assertFalse(first_run, str(message))
                    initialized = prepare_character(loaded, store, library=library, defaults=base)
                    self.assertEqual(initialized.config.oracle.colors.skin, '#102030')
                    self.assertEqual(initialized.config.oracle.float_speed, 1.8)
                    self.assertEqual(initialized.config.oracle.projection_opacity, .2)
                    self.assertEqual(initialized.config.desktop, base.desktop)
                    entry = initialized.state.entries[initialized.state.active]
                    self.assertEqual(entry.source.id, role.id)
                    self.assertEqual(entry.defaults['oracle.projection_opacity'], opacity)
                    self.assertEqual(len(library.scan().presets), 2)
                    self.assertEqual(len(initialized.state.entries), 2)
                    self.assertEqual(len(initialized.state.character_setup['directory_migration']['archived']), 4)
                    commit(store, initialized)
                document = store.read_document()
                self.assertEqual(document['preset_state']['version'], 3)
                self.assertNotIn('pending', document['preset_state'])
                self.assertNotIn('float_speed', document['config']['oracle'])
                self.assertTrue(any(p.read_bytes() == legacy_bytes
                    for p in (store.path.parent/'migrations').rglob('settings.json')))
                entry = read_entry(entry.source.path)
                restored = entry.restore(0, initialized.config, entry.source.path.parent/'appearance/images')
                self.assertEqual(restored.oracle.body_appearance, 'custom')
                self.assertTrue(Path(restored.oracle.custom_appearance.forehead.image_path).is_file())
                # 手动打包目录保留当前 .2 和新版恢复源 .3，两者都能正确读回
                manual = ProfileLibrary(root/'manual-receiver').import_file(entry.source.path.parent)
                manual_entry = read_entry(manual.path)
                self.assertEqual(manual_entry.values['oracle.projection_opacity'], .2)
                self.assertEqual(manual_entry.defaults['oracle.projection_opacity'], .3)
                # 未保存草稿也能分享；不提交源角色、历史或全局设置
                draft = apply_values(store.load(), {'oracle.colors.skin': '#fedcba',
                    'oracle.float_speed': .876543, 'oracle.projection_opacity': .77})
                expected = {'id': role.id, 'values': snapshot(draft, ALL_PATHS)}
                previous = tree_hashes(library.directory), store.path.read_bytes()
                shared = library.export_share(draft, root/'share.zip', name=role.name, preset_id=role.id)
                self.assertEqual(previous, (tree_hashes(library.directory), store.path.read_bytes()))
                with ZipFile(shared) as archive:
                    self.assertFalse(any('/history/' in p or p.endswith('.bak') for p in archive.namelist()))
                    for name in archive.namelist():
                        if name.endswith('.json'):
                            self.assertNotIn(str(root).encode(), archive.read(name))
                            self.assertNotIn(b'game_dir', archive.read(name))
            expected_path = root/'expected.json'
            expected_path.write_text(json.dumps(expected), encoding='utf-8')
            # 删除发送端所有安装、原图、缓存和设置，只留下 ZIP 与预期的像素指纹
            for directory in (install, root/'publisher', root/'sender-user', root/'legacy-cache', root/'manual-receiver', output):
                shutil.rmtree(directory)
            image.unlink()
            environment = {**os.environ, 'LOCALAPPDATA': str(root/'receiver-local'), 'QT_QPA_PLATFORM': 'offscreen'}
            for name in ('PYTHONPATH', 'PYTHONHOME'):
                environment.pop(name, None)
            completed = subprocess.run([sys.executable, '-m', 'tests.test_profile_lifecycle', '--receive',
                str(shared), str(root/'receiver'), str(expected_path)], cwd=ROOT, env=environment,
                capture_output=True, text=True, encoding='utf-8', timeout=60)
            self.assertEqual(completed.returncode, 0, completed.stdout+'\n'+completed.stderr)
            received = json.loads(completed.stdout)
            self.assertTrue(received['ok'])
            self.assertNotEqual(received['pid'], os.getpid())
            self.assertFalse(shared.exists())


if __name__ == '__main__':
    if sys.argv[1:2] == ['--receive']:
        print(json.dumps(receive(*sys.argv[2:]), ensure_ascii=False))
    else:
        unittest.main()
