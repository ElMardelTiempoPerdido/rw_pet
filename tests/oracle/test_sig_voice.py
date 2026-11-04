"""Sig 本地模组查找、缺失降级、角色持久化与独立对话池"""
from dataclasses import replace
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch
import wave

from rw_creature_pet.config import AppConfig
from rw_creature_pet.oracle.assets import prepare_oracle_assets
from rw_creature_pet.oracle.audio.assets import prepare_voice
from rw_creature_pet.oracle.audio.mod_assets import (
    HUNTER_EXPANSION_ID, HUNTER_EXPANSION_WORKSHOP_ID, prepare_sig_voice,
)
from rw_creature_pet.oracle.audio.playback import prepared_voice_error
from rw_creature_pet.oracle.audio.voice import SIG_VOICE_CLIPS
from rw_creature_pet.oracle.config import DragReactionConfig, OracleConfig
from rw_creature_pet.oracle.interaction.drag_reactions import OracleDragReactions
from rw_creature_pet.presets.profile import apply_profile, load_profile
from rw_creature_pet.presets.profile_library import ProfileLibrary
from rw_creature_pet.resources import Availability
from rw_creature_pet.settings_store import SettingsStore


class SigVoiceTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(TemporaryDirectory()))
        self.steam = self.root/'Steam'
        self.game = self.steam/'steamapps/common/Rain World'
        self.game.mkdir(parents=True)
        self.workshop = self.steam/'steamapps/workshop/content/312520'/HUNTER_EXPANSION_WORKSHOP_ID
        self.enterContext(patch('rw_creature_pet.shared.game_mods._system_steam_roots', return_value=[]))
        self.config = AppConfig(game_dir=self.game, oracle=OracleConfig(voice='sig'))
        buf = io.BytesIO()
        with wave.open(buf, 'wb') as wav:
            wav.setparams((2, 2, 48000, 0, 'NONE', 'not compressed'))
            wav.writeframes(b'\x01\x00\x02\x00'*4800)
        self.wav = buf.getvalue()

    def write_clips(self, root, clips=SIG_VOICE_CLIPS):
        folder = root/'soundeffects'
        folder.mkdir(parents=True, exist_ok=True)
        for clip in clips:
            (folder/(clip.asset_name+'.wav')).write_bytes(self.wav)
        return {clip.clip_id: folder/(clip.asset_name+'.wav') for clip in clips}

    def local_mod(self, name='自定义文件夹名', mod_id=HUNTER_EXPANSION_ID):
        root = self.game/'RainWorld_Data/StreamingAssets/mods'/name
        root.mkdir(parents=True)
        (root/'modinfo.json').write_text(json.dumps({'id': mod_id}), encoding='utf-8')
        return root

    def test_workshop_files_are_enough_without_subscription_or_enabled_list(self):
        paths = self.write_clips(self.workshop)
        for name in ('NSH-Attacked-1', 'NSH-Break-1', 'NSH-Recover-1'):
            (self.workshop/'soundeffects'/f'{name}.wav').write_bytes(self.wav)
        self.assertEqual(prepare_sig_voice(self.game), (paths, ''))
        self.assertEqual(len(paths), 5)
        self.assertTrue(all(path.is_relative_to(self.workshop) for path in paths.values()))

    def test_secondary_library_and_old_library_manifest(self):
        other = self.root/'Another Steam 库'
        paths = self.write_clips(other/'steamapps/workshop/content/312520'/HUNTER_EXPANSION_WORKSHOP_ID)
        value = str(other).replace('\\', '\\\\')
        manifest = self.steam/'steamapps/libraryfolders.vdf'
        for field in ('"path"', '"1"'):
            manifest.write_text(f'"libraryfolders"\n{{\n {field} "{value}"\n}}', encoding='utf-8')
            self.assertEqual(prepare_sig_voice(self.game), (paths, ''))

    def test_system_steam_roots_find_mod_for_non_steam_game_path(self):
        game = self.root/'manually selected game'
        paths = self.write_clips(self.workshop)
        with patch('rw_creature_pet.shared.game_mods._system_steam_roots', return_value=[self.steam]):
            self.assertEqual(prepare_sig_voice(game), (paths, ''))

    def test_manual_install_is_identified_by_id_and_works_when_disabled(self):
        unrelated = self.local_mod('unrelated', 'another.mod')
        self.write_clips(unrelated)
        root = self.local_mod(mod_id=HUNTER_EXPANSION_ID.upper())
        paths = self.write_clips(root)
        (self.game/'RainWorld_Data/StreamingAssets/enabledMods.txt').write_text('', encoding='utf-8')
        self.assertEqual(prepare_sig_voice(self.game), (paths, ''))

    def test_missing_or_corrupt_files_disable_only_the_voice_and_recover(self):
        self.assertTrue(prepare_sig_voice(self.game)[1])
        paths = self.write_clips(self.workshop)
        file = paths['sig_long_03']
        for data in (b'', self.wav[:-8], b'not audio'):
            file.write_bytes(data)
            loaded, error = prepare_sig_voice(self.game)
            self.assertEqual(loaded, {})
            self.assertIn(file.name, error)
        file.write_bytes(self.wav)
        self.assertEqual(prepare_sig_voice(self.game), (paths, ''))
        file.unlink()
        self.assertEqual(prepare_sig_voice(self.game)[0], {})

    def test_complete_copy_wins_but_incomplete_copies_are_not_combined(self):
        local = self.local_mod()
        self.write_clips(local, SIG_VOICE_CLIPS[:2])
        self.write_clips(self.workshop, SIG_VOICE_CLIPS[2:])
        self.assertEqual(prepare_sig_voice(self.game)[0], {})
        paths = self.write_clips(self.workshop)
        self.assertEqual(prepare_sig_voice(self.game), (paths, ''))

    def test_newest_file_overrides_root_without_reading_old_version_copy(self):
        paths = self.write_clips(self.workshop)
        newest = self.write_clips(self.workshop/'newest', SIG_VOICE_CLIPS[:1])
        self.write_clips(self.workshop/'v1.9.15b')
        self.assertEqual(prepare_sig_voice(self.game), ({**paths, **newest}, ''))
        next(iter(newest.values())).write_bytes(b'bad override')
        self.assertEqual(prepare_sig_voice(self.game)[0], {})

    def test_dispatch_does_not_use_bell_override_or_extract_bundles(self):
        paths = self.write_clips(self.workshop)
        config = replace(self.config, oracle=replace(self.config.oracle, voice_directory='missing Bell folder'))
        with patch('rw_creature_pet.oracle.audio.assets.ensure_bell_voice') as bell, \
             patch('rw_creature_pet.oracle.audio.chat_assets.prepare_chat_voices') as chats:
            self.assertEqual(prepare_voice(config), (paths, ''))
            self.assertTrue(prepare_voice(config, initialize=False)[1])
            self.assertEqual(prepare_voice(replace(config, oracle=replace(config.oracle, voice='none'))), ({}, ''))
            bell.assert_not_called()
            chats.assert_not_called()

    def test_startup_reports_sig_even_when_none_selected_and_refresh_rechecks_files(self):
        config = replace(self.config, oracle=replace(self.config.oracle, voice='none'))
        with patch('rw_creature_pet.oracle.assets.extract_atlas', return_value=self.root), \
             patch('rw_creature_pet.oracle.assets.Atlas', return_value=Mock()), \
             patch('rw_creature_pet.oracle.assets.load_pearl_glyphs', return_value=object()), \
             patch('rw_creature_pet.oracle.assets.prepare_pearl_playback', return_value=''), \
             patch('rw_creature_pet.oracle.assets.prepare_projection', return_value=''), \
             patch('rw_creature_pet.oracle.assets.prepare_voice', return_value=({}, 'missing Bell')) as prepare, \
             patch('rw_creature_pet.oracle.audio.chat_assets.prepare_chat_voices', return_value={}) as chats:
            missing = prepare_oracle_assets(config)
            self.assertEqual(missing.resources.states['sig_voice'], Availability.UNAVAILABLE)
            self.assertEqual(missing.voice_error, '')
            prepare.assert_not_called()
            paths = self.write_clips(self.workshop)
            available = prepare_oracle_assets(config, check_all_voices=True)
            self.assertEqual(available.resources.states['sig_voice'], Availability.AVAILABLE)
            self.assertEqual(available.voice_paths, paths)
            chats.assert_called_once()
            self.assertEqual(prepared_voice_error(available, 'sig'), '')
            next(iter(paths.values())).unlink()
            removed = prepare_oracle_assets(self.config)
            removed.include_checked_voices(available)
            self.assertEqual(removed.resources.states['sig_voice'], Availability.UNAVAILABLE)
            self.assertEqual(removed.voice_paths, {})
            self.assertTrue(removed.voice_error)
            self.assertEqual(removed.resources.states['main_atlas'], Availability.AVAILABLE)

    def test_sig_selection_roundtrips_settings_export_and_import_for_any_character(self):
        store = SettingsStore(self.root/'settings.json')
        library = ProfileLibrary(self.root/'profiles')
        config = replace(self.config, oracle=replace(self.config.oracle, body_appearance='custom'))
        with patch('rw_creature_pet.settings_store.load_defaults', return_value=AppConfig()):
            store.save(config)
            self.assertEqual(store.load().oracle.voice, 'sig')
        exported = library.export(config, '任意角色名')
        loaded = load_profile(exported.path)
        self.assertEqual(loaded.config.oracle.voice, 'sig')
        self.assertEqual(apply_profile(AppConfig(), loaded, self.root/'appearance').oracle.voice, 'sig')

    def test_drag_voice_pool_uses_only_dialogue_with_real_durations(self):
        reactions = OracleDragReactions(DragReactionConfig(voice_probability=1.))
        durations = {c.clip_id: c.duration for c in SIG_VOICE_CLIPS}
        previous, seen = None, set()
        for _ in range(50):
            reactions.voice.cancel()
            reactions._try_voice('sig')
            cue = reactions.voice.pending
            self.assertIn(cue.clip_id, durations)
            self.assertEqual(cue.duration_seconds, durations[cue.clip_id])
            self.assertNotEqual(cue.clip_id, previous)
            seen.add(cue.clip_id)
            previous = cue.clip_id
        self.assertEqual(seen, set(durations))


if __name__ == '__main__':
    unittest.main()
