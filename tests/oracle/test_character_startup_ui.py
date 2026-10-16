"""桌面入口实际执行角色初始化、迁移提示和存储边界"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtCore import QTimer

from rw_creature_pet.app import main
from rw_creature_pet.config import AppConfig
from rw_creature_pet.presets.profile_library import ProfileLibrary
from rw_creature_pet.presets.startup import BELL_PROFILE_ID
from rw_creature_pet.settings_store import SettingsStore
from rw_creature_pet.oracle.ui.preset_dialogs import acknowledge_character_upgrade


class CharacterStartupUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        (root/'RainWorld_Data').mkdir()
        (root/'RainWorld_Data/resources.assets').touch()
        self.defaults = AppConfig(game_dir=root)
        self.store = SettingsStore(root/'settings.json')
        self.library = ProfileLibrary(root/'profiles')
        bell = replace(self.defaults, oracle=replace(self.defaults.oracle, pearl_matrix_count=7))
        self.library.export(bell, 'Bell', preset_id=BELL_PROFILE_ID)
        self.enterContext(patch('rw_creature_pet.presets.profile_library.default_profile_directory',
                               return_value=self.library.directory))
        self.enterContext(patch('rw_creature_pet.settings_store.load_defaults', return_value=self.defaults))
        self.enterContext(patch('rw_creature_pet.settings_store.SettingsStore', return_value=self.store))
        self.enterContext(patch('rw_creature_pet.app.QApplication', return_value=self.app))
        self.enterContext(patch.object(self.app, 'exec', return_value=0))
        self.window = self.enterContext(patch('rw_creature_pet.oracle.ui.desktop.OracleDesktopWindow'))
        self.notice = self.enterContext(patch('rw_creature_pet.oracle.ui.preset_dialogs.acknowledge_character_upgrade'))

    def launch(self, *args):
        with self.assertRaises(SystemExit) as result:
            main(['--creature', 'oracle', '--desktop', *args])
        self.assertEqual(result.exception.code, 0)
        return self.window.call_args.args[0]

    def test_legacy_startup_acknowledges_once_and_applies_before_scene_creation(self):
        old = replace(self.defaults, oracle=replace(self.defaults.oracle, pearl_matrix_count=0))
        self.store.save(old)
        running = self.launch()
        self.notice.assert_called_once()
        self.assertEqual(running.oracle.pearl_matrix_count, 0)
        state = self.store.load_preset_state()
        self.assertTrue(state['character_setup']['complete'])
        self.assertEqual(state['entries'][state['active']]['defaults']['oracle.pearl_matrix_count'], 7)
        self.launch()
        self.notice.assert_called_once()

    def test_command_line_scale_is_not_saved_by_character_initialization(self):
        self.store.save(self.defaults)
        self.assertEqual(self.launch('--scale', '2').desktop.scale, 2.)
        self.assertEqual(self.store.load().desktop.scale, 1.)

    def test_fresh_setup_receives_selected_bell_and_cancel_does_not_write_settings(self):
        dialog = MagicMock()
        dialog.DialogCode.Accepted = 1
        dialog.exec.return_value = 0
        with patch('rw_creature_pet.oracle.ui.settings.OracleSettingsDialog', return_value=dialog) as factory:
            self.assertEqual(main(['--creature', 'oracle', '--desktop']), 0)
        prepared = factory.call_args.kwargs['initialization']
        self.assertEqual(prepared.state.entries[prepared.state.active].source.id, BELL_PROFILE_ID)
        self.assertEqual(prepared.config.oracle.pearl_matrix_count, 7)
        self.notice.assert_not_called()
        self.assertFalse(self.store.path.exists())

    def test_notice_has_only_one_confirmation_button(self):
        found = []
        def confirm():
            box = self.app.activeModalWidget()
            if isinstance(box, QMessageBox):
                found.append(box.standardButtons())
                box.button(QMessageBox.StandardButton.Ok).click()
        QTimer.singleShot(30, confirm)
        acknowledge_character_upgrade()
        self.assertEqual(found, [QMessageBox.StandardButton.Ok])
