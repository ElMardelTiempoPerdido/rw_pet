"""缺少可选素材时正常启动、参数保留、局部禁用及修复后的状态恢复"""
import os
import sys
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from contextlib import ExitStack
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from threading import Event
from unittest.mock import Mock, patch

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from rw_creature_pet.config import AppConfig
from rw_creature_pet.i18n import language_manager
from rw_creature_pet.oracle.assets import OracleAssets, prepare_oracle_assets, resource_key
from rw_creature_pet.oracle.audio.assets import prepare_bell_voice
from rw_creature_pet.oracle.graphics.render import OracleRenderer
from rw_creature_pet.oracle.ui.settings import OracleSettingsDialog
from rw_creature_pet.resources import Availability as A
from rw_creature_pet.resources.status import ResourceReport
from rw_creature_pet.settings_store import SettingsStore
from tests.oracle.character_fixture import isolate_characters


class AssetAvailabilityTests(unittest.TestCase):
    def prepare_with(self, config, *, voice_error='', glyph_error=None, curve_error='', scan_error=''):
        with ExitStack() as stack:
            atlas = Mock()
            stack.enter_context(patch('rw_creature_pet.oracle.assets.extract_atlas', return_value=Path('fixture')))
            stack.enter_context(patch('rw_creature_pet.oracle.assets.Atlas', return_value=atlas))
            stack.enter_context(patch('rw_creature_pet.oracle.assets.load_pearl_glyphs',
                                     side_effect=glyph_error, return_value=object()))
            voice = stack.enter_context(patch('rw_creature_pet.oracle.assets.prepare_bell_voice',
                                        return_value=({}, voice_error) if voice_error else ({'bell': Path('a.wav')}, '')))
            def curve(renderer):
                renderer.playback_curve = None if curve_error else object()
                return curve_error
            def scan(game, renderer):
                renderer.projection_images = () if scan_error else (object(), object())
                return scan_error
            stack.enter_context(patch('rw_creature_pet.oracle.assets.prepare_pearl_playback', side_effect=curve))
            stack.enter_context(patch('rw_creature_pet.oracle.assets.prepare_projection', side_effect=scan))
            assets = prepare_oracle_assets(config)
            return assets, voice.call_count

    def test_missing_watcher_voice_keeps_required_and_other_features(self):
        config = AppConfig()
        assets, calls = self.prepare_with(config, voice_error='missing interview')
        self.assertEqual(calls, 1)
        self.assertEqual(assets.resources.states['main_atlas'], A.AVAILABLE)
        self.assertEqual(assets.resources.states['bell_voice'], A.UNAVAILABLE)
        self.assertEqual(assets.voice_paths, {})
        self.assertIsNotNone(assets.renderer.playback_curve)
        self.assertTrue(assets.renderer.projection_images)
        self.assertTrue(assets.reusable(config))

    def test_none_skips_voice_extraction_but_bell_selection_requires_preparation(self):
        base = AppConfig()
        config = replace(base, oracle=replace(base.oracle, voice='none'))
        assets, calls = self.prepare_with(config)
        self.assertEqual(calls, 0)
        self.assertNotIn('bell_voice', assets.resources.items)
        self.assertTrue(assets.reusable(config))
        self.assertFalse(assets.reusable(base))
        with patch('rw_creature_pet.oracle.audio.assets.ensure_bell_voice') as extract:
            self.assertEqual(prepare_bell_voice(config), ({}, ''))
            extract.assert_not_called()

    def test_all_optional_game_resources_can_fail_together(self):
        assets, _ = self.prepare_with(AppConfig(), voice_error='missing voice',
            glyph_error=OSError('missing glyphs'), curve_error='missing curve', scan_error='missing images')
        for key in ('bell_voice', 'pearl_glyphs', 'pearl_playback_curve', 'scan_images'):
            self.assertEqual(assets.resources.states[key], A.UNAVAILABLE)
        self.assertFalse(assets.renderer.projection_images)
        self.assertIsNone(assets.renderer.playback_curve)

    def test_missing_base_atlas_is_still_fatal(self):
        with patch('rw_creature_pet.oracle.assets.extract_atlas', side_effect=FileNotFoundError('base game')):
            with self.assertRaises(FileNotFoundError):
                prepare_oracle_assets(AppConfig())

    def test_changing_voice_override_invalidates_cached_preparation(self):
        config = AppConfig()
        assets, _ = self.prepare_with(config)
        self.assertFalse(assets.reusable(replace(config, oracle=replace(config.oracle, voice_directory='another'))))


class ResourceSettingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        isolate_characters(self, self.root)
        game = self.root/'game'
        (game/'RainWorld_Data').mkdir(parents=True)
        (game/'RainWorld_Data/resources.assets').write_bytes(b'fixture')
        self.config = AppConfig(game_dir=game)
        self.store = SettingsStore(self.root/'settings.json')
        language_manager().set_language('zh')
        self.dialogs = []

    def tearDown(self):
        for dialog in self.dialogs:
            dialog.shutdown()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()

    def assets(self, missing=()):
        report = ResourceReport()
        for key in ('main_atlas', 'bell_voice', 'pearl_glyphs', 'scan_images', 'pearl_playback_curve'):
            report.record(key, error='fixture missing' if key in missing else '')
        return OracleAssets(OracleRenderer(), '', {}, '', report, resource_key(self.config))

    def dialog(self, missing=()):
        dialog = OracleSettingsDialog(self.config, self.store, assets=self.assets(missing))
        self.dialogs.append(dialog)
        return dialog

    def test_missing_options_are_marked_without_changing_saved_values(self):
        d = self.dialog(('bell_voice', 'scan_images', 'pearl_glyphs', 'pearl_playback_curve'))
        voice = d.controls['oracle.voice']
        self.assertEqual(voice.currentData(), 'bell')
        self.assertIn('不可用', voice.itemText(voice.findData('bell')))
        self.assertFalse(voice.model().item(voice.findData('bell')).isEnabled())
        self.assertTrue(voice.model().item(voice.findData('none')).isEnabled())
        self.assertFalse(d.controls['oracle.drag_projection_probability'].isEnabled())
        self.assertFalse(d.controls['oracle.pearl_playback_probability'].isEnabled())
        self.assertTrue(d.controls['oracle.projection_opacity'].isEnabled())
        self.assertTrue(d.controls['oracle.drag_reactions.enabled'].isEnabled())
        self.assertEqual(d.candidate().oracle, d.original.oracle)

    def test_availability_restores_and_respects_normal_dependencies(self):
        d = self.dialog(('bell_voice', 'scan_images'))
        d.controls['oracle.drag_reactions.enabled'].setChecked(False)
        d.assets = self.assets()
        d.resource_settings.install(d.assets)
        self.assertNotIn('不可用', d.controls['oracle.voice'].currentText())
        self.assertFalse(d.controls['oracle.drag_projection_probability'].isEnabled())
        d.controls['oracle.drag_reactions.enabled'].setChecked(True)
        self.assertTrue(d.controls['oracle.drag_projection_probability'].isEnabled())
        self.assertTrue(d.controls['oracle.voice'].model().item(0).isEnabled())

    def test_refresh_is_read_only_and_updates_runtime_callback(self):
        d = self.dialog(('bell_voice',))
        d.resource_commit = Mock()
        before = self.store.path.read_bytes() if self.store.path.exists() else None
        repaired = self.assets()
        with patch('rw_creature_pet.oracle.ui.settings.prepare_oracle_assets', return_value=repaired) as prepare:
            d.resource_settings.schedule(force=True)
            for _ in range(100):
                QTest.qWait(20)
                if not d.resource_settings._queued and d.resource_settings.worker is None:
                    break
            self.assertEqual(prepare.call_count, 1)
        self.assertIsNone(d.resource_settings.worker)
        d.resource_commit.assert_called_once_with(repaired)
        self.assertNotIn('不可用', d.controls['oracle.voice'].currentText())
        self.assertEqual(self.store.path.read_bytes() if self.store.path.exists() else None, before)

    def test_retranslation_does_not_drop_unavailability(self):
        d = self.dialog(('scan_images',))
        for _ in range(3):
            d.retranslate()
            d.sync_dependencies()
        control = d.controls['oracle.drag_projection_probability']
        label = d.resource_settings._label(control)
        self.assertEqual(label.text().count('不可用'), 1)
        self.assertFalse(control.isEnabled())

    def test_all_color_editors_share_resource_availability(self):
        d = self.dialog(('pearl_glyphs', 'pearl_playback_curve'))
        for key, editors in d.color_editors.items():
            if key.endswith('.pearl_glyph') or key == 'oracle.pearl_bubble_color':
                self.assertTrue(all(not editor.isEnabled() for editor in editors), key)
        label = d.resource_settings._label(d.projection_colors['oracle.colors.pearl_glyph'])
        self.assertEqual(label.text().count('不可用'), 1)
        d.resource_settings.install(self.assets())
        self.assertTrue(all(editor.isEnabled() for editor in d.color_editors['oracle.colors.pearl_glyph']))

    def test_directory_picker_requests_fresh_availability(self):
        d = self.dialog()
        with patch('rw_creature_pet.oracle.ui.settings.QFileDialog.getExistingDirectory', return_value=str(self.root/'new-game')):
            with patch.object(d.resource_settings, 'schedule') as schedule:
                d.browse()
                schedule.assert_called_once()

    def test_failed_refresh_resumes_pending_autosave(self):
        d = self.dialog()
        finish = Event()
        def fail(config):
            finish.wait(5)
            raise OSError('failed probe')
        with patch('rw_creature_pet.oracle.ui.settings.prepare_oracle_assets', side_effect=fail):
            try:
                d.resource_settings.schedule(force=True)
                QTest.qWait(30)
                d.controls['oracle.float_speed'].setValue(1.1)
                QTest.qWait(750)
                self.assertTrue(d.preset_workflow.dirty)
                finish.set()
                for _ in range(100):
                    QTest.qWait(20)
                    if d.resource_settings.worker is None and not d.preset_workflow.dirty:
                        break
                self.assertFalse(d.preset_workflow.dirty)
                self.assertEqual(d.saved_config.oracle.float_speed, 1.1)
            finally:
                finish.set()

    def test_first_run_check_does_not_cross_save_and_start_boundary(self):
        d = OracleSettingsDialog(self.config, self.store, first_run=True)
        self.dialogs.append(d)
        d.controls['oracle.float_speed'].setValue(1.1)
        with patch('rw_creature_pet.oracle.ui.settings.prepare_oracle_assets', return_value=self.assets()):
            d.resource_settings.schedule(force=True)
            QTest.qWait(1000)
        self.assertIsNone(d.assets)
        self.assertIsNotNone(d.resource_settings.checked_assets)
        self.assertTrue(d.preset_workflow.dirty)
        self.assertFalse(self.store.path.exists())
        self.assertIsNone(d.saved_config)

    def test_queued_completion_after_shutdown_is_safe(self):
        d = self.dialog()
        with patch('rw_creature_pet.oracle.ui.settings.prepare_oracle_assets', return_value=self.assets()):
            with patch.object(sys, 'excepthook') as exception:
                d.resource_settings._force = True
                d.resource_settings.refresh()
                d.resource_settings.worker.wait()
                d.shutdown()
                self.app.processEvents()
                exception.assert_not_called()

    def test_stale_directory_result_is_not_applied(self):
        d = self.dialog()
        d.resource_commit = Mock()
        finish = Event()
        new_game = self.root/'another-game'
        def prepare(config):
            if config.game_dir == self.config.game_dir:
                finish.wait(5)
            return replace(self.assets(), source_key=resource_key(config))
        with patch('rw_creature_pet.oracle.ui.settings.prepare_oracle_assets', side_effect=prepare) as load:
            try:
                d.resource_settings._force = True
                d.resource_settings.refresh()
                d.game_dir.setText(str(new_game))
                d.game_dir.editingFinished.emit()
                finish.set()
                for _ in range(100):
                    QTest.qWait(20)
                    if d.resource_settings.worker is None and not d.resource_settings._queued:
                        break
                self.assertEqual(load.call_count, 2)
                self.assertEqual(d.resource_settings.checked_key[0], str(new_game.resolve()))
                self.assertEqual(d.assets.source_key, resource_key(self.config))
                d.resource_commit.assert_not_called()
            finally:
                finish.set()

    def test_character_voice_uses_committed_directory_while_another_directory_is_a_draft(self):
        self.check_character_voice_directory(draft_fails=False)

    def test_failed_draft_check_still_prepares_pending_runtime_voice(self):
        self.check_character_voice_directory(draft_fails=True)

    def test_close_waits_for_runtime_voice_queued_by_final_autosave(self):
        self.config = replace(self.config, oracle=replace(self.config.oracle, voice='none'))
        initial = self.assets()
        initial.resources.items.pop('bell_voice')
        d = OracleSettingsDialog(self.config, self.store, assets=initial, resource_commit=Mock())
        self.dialogs.append(d)
        draft_game = self.root/'draft-game'
        checked = self.assets()
        checked.source_key = resource_key(replace(self.config, game_dir=draft_game))
        d.game_dir.setText(str(draft_game))
        d.resource_settings.checked_assets = checked
        d.resource_settings.checked_key = checked.source_key
        d.resource_settings.report = checked.resources
        runtime = self.assets()
        runtime.voice_paths = {'bell': self.config.game_dir/'bell.wav'}
        finished = Mock()
        d.finished.connect(finished)
        with patch('rw_creature_pet.oracle.ui.settings.prepare_oracle_assets', return_value=runtime) as prepare:
            d.controls['oracle.voice'].setCurrentIndex(d.controls['oracle.voice'].findData('bell'))
            d.reject()
            finished.assert_not_called()
            for _ in range(100):
                QTest.qWait(20)
                if finished.called:
                    break
            finished.assert_called_once()
            prepare.assert_called_once()
            self.assertEqual(prepare.call_args.args[0].game_dir, self.config.game_dir)
            d.resource_commit.assert_called_once_with(runtime)
            self.assertEqual(d.assets.voice_paths, runtime.voice_paths)

    def check_character_voice_directory(self, *, draft_fails):
        from rw_creature_pet.presets.profile_library import ProfileLibrary
        self.config = replace(self.config, oracle=replace(self.config.oracle, voice='none'))
        initial = self.assets()
        initial.resources.items.pop('bell_voice')
        d = OracleSettingsDialog(self.config, self.store, assets=initial, resource_commit=Mock())
        self.dialogs.append(d)
        bell = ProfileLibrary().export(replace(self.config, oracle=replace(self.config.oracle, voice='bell')), 'Bell voice')
        draft_game = self.root/'draft-game'
        finish = Event()
        calls = []
        def prepare(config):
            calls.append((config.game_dir, config.oracle.voice))
            if config.game_dir == draft_game and config.oracle.voice == 'none':
                finish.wait(5)
            if config.game_dir == draft_game and draft_fails:
                raise OSError('invalid draft game directory')
            assets = replace(self.assets(), source_key=resource_key(config))
            if config.oracle.voice == 'none':
                assets.resources.items.pop('bell_voice')
            else:
                assets.voice_paths = {'bell': config.game_dir/'bell.wav'}
            return assets
        with patch('rw_creature_pet.oracle.ui.settings.prepare_oracle_assets', side_effect=prepare):
            try:
                d.game_dir.setText(str(draft_game))
                d.resource_settings.schedule()
                QTest.qWait(30)
                d.preset_workflow.activate('profile', bell)
                finish.set()
                for _ in range(150):
                    QTest.qWait(20)
                    if d.resource_settings.worker is None and not d.resource_settings._queued:
                        break
                self.assertIn((self.config.game_dir, 'bell'), calls)
                self.assertEqual(d.assets.source_key, resource_key(self.config))
                self.assertEqual(d.assets.voice_paths['bell'], self.config.game_dir/'bell.wav')
                self.assertEqual(self.store.load().game_dir, self.config.game_dir)
                if not draft_fails:
                    self.assertEqual(d.resource_settings.checked_key[0], str(draft_game.resolve()))
                d.resource_commit.assert_called_once_with(d.assets)
            finally:
                finish.set()


if __name__ == '__main__':
    unittest.main()
