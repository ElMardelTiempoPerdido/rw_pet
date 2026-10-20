"""托盘复用角色列表与应用流程，不写入真实角色库"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication

from rw_creature_pet.config import AppConfig
from rw_creature_pet.i18n import language_manager
from rw_creature_pet.oracle.assets import OracleAssets
from rw_creature_pet.oracle.graphics.render import OracleRenderer
from rw_creature_pet.oracle.ui.desktop import OracleDesktopWindow
from rw_creature_pet.presets.profile_library import ProfileLibrary
from rw_creature_pet.presets.startup import prepare_character, BELL_PROFILE_ID
from rw_creature_pet.settings_store import SettingsStore


class CharacterMenuTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch('rw_creature_pet.presets.profile_library.default_profile_directory',
                                return_value=self.root/'profiles'))
        self.enterContext(patch('rw_creature_pet.presets.library.default_appearance_directory',
                                return_value=self.root/'appearances'))
        self.enterContext(patch('rw_creature_pet.oracle.ui.desktop.QSystemTrayIcon.isSystemTrayAvailable',
                                return_value=True))
        self.store = SettingsStore(self.root/'settings.json')
        config = AppConfig(game_dir=self.root)
        self.library = ProfileLibrary()
        self.bell = self.library.export(config, 'Bell', preset_id=BELL_PROFILE_ID)
        self.custom = self.library.export(replace(config, oracle=replace(config.oracle,
            body_appearance='custom', float_speed=.7)), 'Custom')
        initialized = prepare_character(config, self.store)
        with self.store.preset_state(initialized.state.serialize()):
            self.store.save(initialized.config)
        assets = OracleAssets(OracleRenderer(), '', {}, '')
        self.window = OracleDesktopWindow(initialized.config, config_store=self.store, assets=assets)
        self.window.timer.stop()
        self.menu = self.window.character_menu

    def tearDown(self):
        self.window.close()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()
        language_manager().set_language('zh')

    def test_first_menu_matches_settings_and_switches_without_showing_dialog(self):
        self.assertIs(self.window.menu.actions()[0].menu(), self.menu)
        self.menu.refresh()
        self.assertIsNone(self.window.settings_dialog)
        names = [a.text() for a in self.menu.actions()]
        d = self.window.ensure_settings_dialog()
        selector = d.profile_presets.selector
        self.assertEqual(names, [selector.itemText(i) for i in range(selector.count())])
        self.assertFalse(d.isVisible())
        d.shutdown()
        if self.window.settings_dialog is d:
            self.window.settings_closed()
        self.menu.choose(self.custom)
        self.assertIsNone(self.window.settings_dialog)
        self.assertEqual(self.window.config.oracle.body_appearance, 'custom')
        self.assertEqual(self.store.load().oracle.float_speed, .7)
        self.menu.refresh()
        self.assertEqual([a.text() for a in self.menu.actions() if a.isChecked()], ['Custom'])
        language_manager().set_language('en')
        self.assertEqual(self.menu.title(), 'Switch character')

    def test_manual_save_mode_discards_old_character_draft_and_preserves_local_draft(self):
        d = self.window.ensure_settings_dialog()
        workflow = d.preset_workflow
        workflow.set_autosave(False)
        d.controls['oracle.float_speed'].setValue(1.3)
        d.controls['audio.volume'].setValue(12)
        self.menu.choose(self.custom)
        self.assertEqual(self.window.config.oracle.float_speed, .7)
        self.assertEqual(self.store.load().oracle.body_appearance, 'custom')
        self.assertFalse(self.store.load_preset_state()['autosave'])
        self.assertEqual(d.controls['audio.volume'].value(), 12)
        self.assertNotEqual(self.store.load().audio.volume, .12)

    def test_deleted_target_preserves_running_character(self):
        self.menu.refresh()
        self.custom.path.unlink()
        with patch.object(self.window.tray, 'showMessage') as warning:
            self.menu.choose(self.custom)
        warning.assert_called_once()
        self.assertEqual(self.window.config.oracle.body_appearance, 'bell')
        self.assertEqual(self.store.load().oracle.body_appearance, 'bell')
        self.assertIsNotNone(self.window.settings_dialog)

    def test_pending_manual_selection_is_applied_and_failed_save_can_retry(self):
        d = self.window.ensure_settings_dialog()
        d.preset_workflow.set_autosave(False)
        panel = d.profile_presets
        index = next(i for i in range(panel.selector.count())
                     if panel.selector.itemData(i).id == self.custom.id)
        self.assertTrue(panel.choose(index))
        self.assertEqual(self.window.config.oracle.body_appearance, 'bell')
        self.menu.refresh()
        self.assertEqual([a.text() for a in self.menu.actions() if a.isChecked()], ['Bell'])
        with patch.object(self.store, 'save', side_effect=PermissionError('locked')), \
                patch.object(self.window.tray, 'showMessage') as warning:
            self.menu.choose(self.custom)
        warning.assert_called_once()
        self.assertEqual(self.window.config.oracle.body_appearance, 'bell')
        self.menu.choose(self.custom)
        self.assertEqual(self.window.config.oracle.body_appearance, 'custom')
        self.assertEqual(self.store.load().oracle.body_appearance, 'custom')

    def test_deleted_current_file_keeps_runtime_identity_and_can_switch_to_remaining_role(self):
        self.bell.path.unlink()
        self.menu.refresh()
        self.assertEqual([a.text() for a in self.menu.actions() if a.isChecked()], ['Bell（已载入版本）'])
        self.menu.choose(self.custom)
        self.assertEqual(self.window.config.oracle.body_appearance, 'custom')
        self.assertEqual(self.window.config.oracle.float_speed, .7)
        self.assertEqual(self.store.load().oracle.body_appearance, 'custom')

    def test_reopening_menu_does_not_revalidate_profiles_or_construct_settings_widgets(self):
        self.menu.refresh()
        names = [action.text() for action in self.menu.actions()]
        with patch('rw_creature_pet.presets.catalog.scan_library', side_effect=AssertionError('full scan')), \
             patch('rw_creature_pet.oracle.ui.character_menu.PersonalState', side_effect=AssertionError('full state')), \
             patch('rw_creature_pet.oracle.ui.profile_presets.ProfilePresetPanel', side_effect=AssertionError('widget')), \
             patch.object(self.store, 'load_preset_state', side_effect=AssertionError('unchanged state')):
            for _ in range(3):
                self.menu.refresh()
                self.assertEqual([action.text() for action in self.menu.actions()], names)
        self.assertIsNone(self.window.settings_dialog)

    def test_menu_refresh_detects_new_removed_and_updated_profiles(self):
        self.menu.refresh()
        newer = self.library.update(self.custom.config, self.custom, name='Renamed')
        self.menu.refresh()
        self.assertEqual([action.text() for action in self.menu.actions()], ['Bell', 'Renamed'])
        added = self.library.export(self.custom.config, 'Added')
        self.menu.refresh()
        self.assertEqual([action.text() for action in self.menu.actions()], ['Added', 'Bell', 'Renamed'])
        newer.path.unlink()
        added.path.unlink()
        self.menu.refresh()
        self.assertEqual([action.text() for action in self.menu.actions()], ['Bell'])
