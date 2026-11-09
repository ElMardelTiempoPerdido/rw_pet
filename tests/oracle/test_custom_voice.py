"""自定义目录与 NPC 名称隔离、WAV 元数据、刷新快照及完整播放入口"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from dataclasses import replace
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import Mock, patch
import wave

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QLabel

from rw_creature_pet.config import AppConfig
from rw_creature_pet.i18n import language_manager
from rw_creature_pet.oracle.assets import OracleAssets, resource_key
from rw_creature_pet.oracle.audio import custom
from rw_creature_pet.oracle.audio.assets import prepare_voice
from rw_creature_pet.oracle.audio.playback import prepared_voice_error
from rw_creature_pet.oracle.audio.voice import voice_clips
from rw_creature_pet.oracle.config import OracleConfig, DragReactionConfig
from rw_creature_pet.oracle.graphics.render import OracleRenderer
from rw_creature_pet.oracle.interaction.drag_reactions import OracleDragReactions
from rw_creature_pet.oracle.ui.debug_window import OracleDebugWindow
from rw_creature_pet.oracle.ui.desktop import OracleDesktopWindow
from rw_creature_pet.oracle.ui.settings import OracleSettingsDialog
from rw_creature_pet.oracle.ui.settings_style import NOTE_STYLE
from rw_creature_pet.presets.profile import apply_profile
from rw_creature_pet.presets.profile_library import ProfileLibrary
from rw_creature_pet.settings_store import SettingsStore
from tests.interaction.test_audio import FakeSound
from tests.oracle.character_fixture import isolate_characters, geometry_assets


class CustomVoiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.voices = self.root/'voices'
        self.voices.mkdir()
        self.enterContext(patch.object(custom, 'voice_directory', return_value=self.voices))
        self.enterContext(patch('rw_creature_pet.interaction.audio.voice_event'))
        self.config = AppConfig(oracle=OracleConfig(voice='custom:moon', hide_cords=True,
            halo_enabled=False, pearl_fixed_count=0, drag_reactions=DragReactionConfig(voice_probability=1.)))
        self.dialogs = []
        language_manager().set_language('zh')

    def tearDown(self):
        for d in self.dialogs:
            d.shutdown()
            d.close()
            d.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()
        language_manager().set_language('zh')

    def wav(self, folder='moon', filename='hello.wav', frames=2000):
        path = self.voices/folder/filename
        path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(path), 'wb') as stream:
            stream.setparams((1, 2, 8000, 0, 'NONE', 'not compressed'))
            stream.writeframes(b'\0\0'*frames)
        return path

    def test_names_metadata_and_partial_invalid_files(self):
        self.wav()
        self.wav(filename='two.WAV', frames=4000)
        self.wav('none')
        self.wav('中文 空格')
        self.wav('moon/nested')
        (self.voices/'empty').mkdir()
        (self.voices/'moon/broken.wav').write_bytes(b'broken')
        packs = custom.scan_custom_voices()
        self.assertEqual(set(packs), {'custom:moon', 'custom:none', 'custom:中文 空格', 'custom:empty'})
        self.assertEqual([c.duration for c in packs['custom:moon'].clips], [.25, .5])
        self.assertTrue(packs['custom:empty'].error)
        self.assertTrue(all(c.clip_id.startswith('custom:moon/') for c in voice_clips('custom:moon')))
        self.assertTrue(all(c.clip_id.startswith('moon_chat_') for c in voice_clips('moon')))
        self.assertEqual(voice_clips('none'), ())
        for value in ('custom:', 'custom:..', 'custom:../moon', 'custom:a/b', 'custom:C:\\moon', 'custom:a\0'):
            with self.assertRaises(ValueError):
                OracleConfig(voice=value)
        self.assertEqual(OracleConfig(voice='custom:missing').voice, 'custom:missing')

    def test_float_wav_and_refresh_invalidates_durations_without_rechecking_per_cue(self):
        path = self.wav()
        float_path = self.voices/'moon/float.wav'
        fmt = struct.pack('<HHIIHH', 3, 1, 8000, 32000, 4, 32)
        body = b'fmt '+struct.pack('<I', len(fmt))+fmt+b'data'+struct.pack('<I', 8000)+b'\0'*8000
        float_path.write_bytes(b'RIFF'+struct.pack('<I', len(body)+4)+b'WAVE'+body)
        packs = custom.scan_custom_voices()
        self.assertEqual(len(packs['custom:moon'].clips), 2)
        with patch.object(custom, 'scan_custom_voices', side_effect=AssertionError('不应在抽签时扫描目录')):
            reactions = OracleDragReactions(self.config.oracle.drag_reactions)
            for _ in range(6):
                reactions.voice.cancel()
                reactions._try_voice('custom:moon')
                self.assertEqual(reactions.voice.pending.duration_seconds, .25)
        self.wav(frames=8000)
        newer = custom.scan_custom_voices()['custom:moon']
        self.assertNotEqual(packs['custom:moon'].signature, newer.signature)
        self.assertEqual(next(c.duration for c in newer.clips if c.path == path), 1.)

    def test_prepare_and_assets_never_substitute_builtin_or_require_dlc(self):
        path = self.wav()
        with patch('rw_creature_pet.oracle.audio.chat_assets.prepare_chat_voices') as builtin:
            paths, error = prepare_voice(self.config, initialize=False)
            builtin.assert_not_called()
        self.assertEqual(paths, {'custom:moon/hello.wav': path})
        self.assertFalse(error)
        base = OracleAssets(OracleRenderer(), '', {'moon_chat_01': self.root/'builtin.wav'}, 'missing bell',
                            source_key=resource_key(self.config))
        assets = base.with_custom_voices(custom.scan_custom_voices(), self.config.oracle.voice)
        self.assertTrue(assets.reusable(self.config))
        self.assertEqual(prepared_voice_error(assets, 'custom:moon'), '')
        path.unlink()
        packs = custom.scan_custom_voices()
        self.assertFalse(assets.reusable(self.config))
        refreshed = assets.with_custom_voices(packs, 'custom:moon')
        self.assertEqual(refreshed.voice_paths, base.voice_paths)
        self.assertTrue(prepared_voice_error(refreshed, 'custom:moon'))

    def test_profile_and_settings_keep_missing_voice_identifier(self):
        library = ProfileLibrary(self.root/'profiles')
        exported = library.export(self.config, 'Custom')
        imported = ProfileLibrary(self.root/'received').import_file(exported.path)
        applied = apply_profile(AppConfig(), imported, self.root/'images')
        self.assertEqual(applied.oracle.voice, 'custom:moon')
        store = SettingsStore(self.root/'settings.json')
        with patch('rw_creature_pet.settings_store.load_defaults', return_value=AppConfig()):
            store.save(applied)
            self.assertEqual(store.load().oracle.voice, 'custom:moon')

    def test_both_windows_consume_custom_clip_and_release_cancels_pending(self):
        path = self.wav()
        for window_type in (OracleDesktopWindow, OracleDebugWindow):
            with self.subTest(window=window_type.__name__), patch(
                    'rw_creature_pet.oracle.ui.desktop.QSystemTrayIcon.isSystemTrayAvailable', return_value=True):
                w = (window_type(self.config, renderer=OracleRenderer()) if window_type is OracleDesktopWindow
                     else window_type(self.config, load_atlas=False))
                try:
                    w.timer.stop()
                    sound = FakeSound()
                    w.voice_player._factory = lambda _: sound
                    scene = w.motion.scene if window_type is OracleDesktopWindow else w.scene
                    scene.drag_reactions._try_voice('custom:moon')
                    w.voice_player.sync(scene.drag_reactions.voice)
                    self.assertEqual(sound.paths, [path])
                    w.voice_player.stop()
                    scene.drag_reactions._try_voice('custom:moon')
                    scene.drag_reactions.end(scene, cancel=True)
                    w.voice_player.sync(scene.drag_reactions.voice)
                    self.assertEqual(sound.paths, [path])
                finally:
                    w.close()

    def test_selector_refresh_missing_choice_note_and_saved_selection(self):
        path = self.wav()
        isolate_characters(self, self.root)
        store = SettingsStore(self.root/'ui/settings.json')
        d = OracleSettingsDialog(self.config, store, assets=geometry_assets())
        self.dialogs.append(d)
        self.enterContext(patch.object(d, 'space_assessment', return_value=None))
        voice = d.controls['oracle.voice']
        self.assertEqual(voice.currentData(), 'custom:moon')
        self.assertEqual(voice.currentText(), '[自定义] moon')
        self.assertNotEqual(voice.findData('moon'), voice.findData('custom:moon'))
        self.assertTrue(d.controls['oracle.drag_reactions.voice_probability'].isEnabled())
        note = next(w for w in d.findChildren(QLabel) if w.text().startswith('*您也可以在presets/voices'))
        self.assertEqual(note.styleSheet(), NOTE_STYLE)
        self.wav('中文目录')
        voice.refresh()
        self.assertGreaterEqual(voice.findData('custom:中文目录'), 0)
        self.assertEqual(voice.currentData(), 'custom:moon')
        path.unlink()
        d.resource_commit = Mock()
        voice.refresh()
        self.assertIn('不可用', voice.currentText())
        self.assertEqual(voice.currentData(), 'custom:moon')
        self.assertFalse(d.controls['oracle.drag_reactions.voice_probability'].isEnabled())
        self.assertNotIn('custom:moon/hello.wav', d.assets.voice_paths)
        d.resource_commit.assert_called_once()
        self.wav()
        voice.refresh()
        self.assertEqual(voice.currentText(), '[自定义] moon')
        voice.setCurrentIndex(voice.findData('custom:中文目录'))
        self.assertTrue(d.preset_workflow.flush())
        self.assertEqual(store.load().oracle.voice, 'custom:中文目录')
        language_manager().set_language('en')
        self.assertEqual(voice.currentText(), '[Custom] 中文目录')
        d.fill_control('oracle.voice', voice, 'custom:missing')
        self.assertEqual(d.candidate().oracle.voice, 'custom:missing')


if __name__ == '__main__':
    unittest.main()
