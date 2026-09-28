"""CLI 正确选择桌宠窗口，Oracle 入口不再被阶段限制拦截。"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import unittest
from dataclasses import replace
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QDialog
from rw_creature_pet.app import bell_main, main
from rw_creature_pet.config import AppConfig


class DesktopEntryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def test_bell_entry_defaults_to_desktop_and_can_launch_debug_with_saved_or_explicit_config(self):
        config = AppConfig()
        for flags in ([], ['--debug'], ['--debug', '--config', 'debug.toml']):
            with self.subTest(flags=flags), \
                 patch('sys.argv', ['BellPet.exe', *flags]), \
                 patch('rw_creature_pet.app.QApplication', return_value=self.app), \
                 patch('rw_creature_pet.settings_store.SettingsStore.startup', return_value=(config, False, '')) as startup, \
                 patch('rw_creature_pet.settings_store.validate_game_directory'), \
                 patch('rw_creature_pet.oracle.settings.OracleSettingsDialog') as dialog, \
                 patch('rw_creature_pet.oracle.desktop.OracleDesktopWindow') as desktop, \
                 patch('rw_creature_pet.oracle.debug_window.OracleDebugWindow') as debug, \
                 patch.object(self.app, 'exec', return_value=0):
                with self.assertRaises(SystemExit) as result:
                    bell_main()
                self.assertEqual(result.exception.code, 0)
                explicit = Path('debug.toml') if '--config' in flags else None
                startup.assert_called_once_with(explicit)
                dialog.assert_not_called()
                if '--debug' in flags:
                    debug.assert_called_once_with(config, explicit)
                    desktop.assert_not_called()
                    debug.return_value.show.assert_called_once()
                else:
                    desktop.assert_called_once()
                    debug.assert_not_called()

    def test_explicit_desktop_and_debug_modes_conflict(self):
        with patch('sys.stderr', new_callable=StringIO), patch('rw_creature_pet.app.QApplication') as app:
            with self.assertRaises(SystemExit) as result:
                main(['--desktop', '--debug'])
            self.assertEqual(result.exception.code, 2)
            app.assert_not_called()

    def test_oracle_invalid_scale_is_rejected_before_starting_qt_or_loading_assets(self):
        for scale in ('.5', '1.25', '3', '4', 'nan', 'inf'):
            with self.subTest(scale=scale), \
                    patch('sys.argv', ['run_pet.py', '--creature', 'oracle', '--desktop', '--scale', scale]), \
                    patch('sys.stderr', new_callable=StringIO) as errors, \
                    patch('rw_creature_pet.app.QApplication') as application, \
                    patch('rw_creature_pet.app.AppConfig.load') as load:
                with self.assertRaises(SystemExit) as result:
                    main()
                self.assertEqual(result.exception.code, 2)
                self.assertIn('1、1.5、2', errors.getvalue())
                application.assert_not_called()
                load.assert_not_called()

    def test_cli_selects_oracle_and_preserves_lizard_activity(self):
        for creature in ('oracle', 'lizard'):
            with self.subTest(creature=creature), \
                 patch('sys.argv', ['run_pet.py', '--creature', creature, '--desktop', '--scale', '1.5', '--activity', 'wall']), \
                 patch('rw_creature_pet.app.QApplication', return_value=self.app), \
                 patch('rw_creature_pet.app.AppConfig.load', return_value=AppConfig()), \
                 patch('rw_creature_pet.settings_store.SettingsStore.startup', return_value=(AppConfig(), False, '')), \
                 patch('rw_creature_pet.settings_store.validate_game_directory'), \
                 patch.object(self.app, 'exec', return_value=0), \
                 patch('rw_creature_pet.oracle.desktop.OracleDesktopWindow') as oracle, \
                 patch('rw_creature_pet.lizard.desktop.DesktopWindow') as lizard:
                with self.assertRaises(SystemExit) as exit_result:
                    main()
                self.assertEqual(exit_result.exception.code, 0)
                selected, other = (oracle, lizard) if creature == 'oracle' else (lizard, oracle)
                selected.assert_called_once()
                other.assert_not_called()
                selected.return_value.show.assert_called_once()
                self.assertEqual(selected.call_args.args[1], 1.5)
                if creature == 'lizard':
                    self.assertEqual(selected.call_args.args[2], 'wall')

    def test_first_run_and_missing_game_directory_open_settings_before_creating_pet(self):
        config = AppConfig()
        saved = replace(config, desktop=replace(config.desktop, scale=2.))
        for first_run, invalid_path in ((True, False), (False, True)):
            with self.subTest(first_run=first_run), \
                 patch('rw_creature_pet.app.QApplication', return_value=self.app), \
                 patch('rw_creature_pet.settings_store.SettingsStore.startup', return_value=(config, first_run, '')), \
                 patch('rw_creature_pet.settings_store.validate_game_directory',
                       side_effect=ValueError('missing') if invalid_path else None), \
                 patch('rw_creature_pet.oracle.settings.OracleSettingsDialog') as dialog, \
                 patch('rw_creature_pet.oracle.desktop.OracleDesktopWindow') as window, \
                 patch.object(self.app, 'exec', return_value=0):
                dialog.return_value.exec.return_value = QDialog.DialogCode.Accepted
                dialog.return_value.DialogCode = QDialog.DialogCode
                dialog.return_value.saved_config = saved
                dialog.return_value.prepared_assets = None
                with self.assertRaises(SystemExit):
                    main(['--creature', 'oracle', '--desktop'])
                dialog.assert_called_once()
                self.assertEqual(window.call_args.args[0], saved)
                self.assertEqual(window.call_args.args[1], 2.)

    def test_first_run_cancel_exits_without_creating_pet_or_main_loop(self):
        with patch('rw_creature_pet.app.QApplication', return_value=self.app), \
             patch('rw_creature_pet.settings_store.SettingsStore.startup', return_value=(AppConfig(), True, '')), \
             patch('rw_creature_pet.settings_store.validate_game_directory'), \
             patch('rw_creature_pet.oracle.settings.OracleSettingsDialog') as dialog, \
             patch('rw_creature_pet.oracle.desktop.OracleDesktopWindow') as window, \
             patch.object(self.app, 'exec') as loop:
            dialog.return_value.exec.return_value = QDialog.DialogCode.Rejected
            dialog.return_value.DialogCode = QDialog.DialogCode
            self.assertEqual(main(['--creature', 'oracle', '--desktop']), 0)
            window.assert_not_called()
            loop.assert_not_called()

    def test_saved_configuration_skips_setup_and_uses_saved_scale(self):
        saved = AppConfig()
        saved = replace(saved, desktop=replace(saved.desktop, scale=1.5))
        with patch('rw_creature_pet.app.QApplication', return_value=self.app), \
             patch('rw_creature_pet.settings_store.SettingsStore.startup', return_value=(saved, False, '')), \
             patch('rw_creature_pet.settings_store.validate_game_directory'), \
             patch('rw_creature_pet.oracle.settings.OracleSettingsDialog') as dialog, \
             patch('rw_creature_pet.oracle.desktop.OracleDesktopWindow') as window, \
             patch.object(self.app, 'exec', return_value=0):
            with self.assertRaises(SystemExit):
                main(['--creature', 'oracle', '--desktop'])
            dialog.assert_not_called()
            self.assertEqual(window.call_args.args[1], 1.5)
