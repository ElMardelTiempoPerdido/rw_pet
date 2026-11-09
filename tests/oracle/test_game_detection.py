"""首次设置后台检测、整体锁定、手动回退与迟到结果隔离"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'

from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
import unittest
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog

from rw_creature_pet.config import AppConfig
from rw_creature_pet.i18n import language_manager
from rw_creature_pet.oracle.ui.game_detection import GameDirectoryDetection
from rw_creature_pet.oracle.ui.settings import OracleSettingsDialog
from rw_creature_pet.settings_store import SettingsStore
from tests.oracle.character_fixture import geometry_assets, isolate_characters


class GameDetectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.root = Path(self.enterContext(TemporaryDirectory()))
        isolate_characters(self, self.root)
        self.game = self.root/'检测到的游戏'
        (self.game/'RainWorld_Data').mkdir(parents=True)
        (self.game/'RainWorld_Data/resources.assets').touch()
        self.config = AppConfig(game_dir=self.root/'invalid')
        self.store = SettingsStore(self.root/'settings.json')
        self.dialogs, self.gates = [], []
        self.enterContext(patch('rw_creature_pet.shared.game_mods._system_steam_roots', return_value=[]))
        language_manager().set_language('zh')

    def tearDown(self):
        for dialog in self.dialogs:
            dialog.shutdown()
        for gate in self.gates:
            gate.set()
        QTest.qWait(20)
        for dialog in self.dialogs:
            dialog.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()

    def dialog(self, *, config=None, first_run=True):
        dialog = OracleSettingsDialog(config or self.config, self.store, first_run=first_run)
        self.dialogs.append(dialog)
        dialog.show()
        self.app.processEvents()
        return dialog

    def wait(self, predicate):
        for _ in range(200):
            if predicate():
                return
            QTest.qWait(10)
        self.fail('后台检测或资源准备未按时完成')

    def blocked_finder(self):
        gate, entered, returned = Event(), Event(), Event()
        self.gates.append(gate)
        def find(preferred):
            entered.set()
            gate.wait(3.)
            returned.set()
            return self.game
        self.enterContext(patch('rw_creature_pet.oracle.ui.game_detection.find_game_directory', side_effect=find))
        return gate, entered, returned

    def test_detection_locks_all_controls_and_prefills_without_saving(self):
        gate, entered, _ = self.blocked_finder()
        with patch('rw_creature_pet.oracle.ui.settings.prepare_oracle_assets') as prepare:
            d = self.dialog()
            self.wait(entered.is_set)
            overlay = d.game_detection.overlay
            self.assertTrue(d.initializing and overlay.isVisible())
            for widget in (d.form, d.game_dir, d.tabs, d.personal_controls, d.buttons,
                           d.save_button, d.reset_all_button, d.apply_button, d.close_button):
                self.assertFalse(widget.isEnabled())
            scale = d.controls['desktop.scale']
            before = scale.currentIndex()
            QTest.keyClick(scale, Qt.Key.Key_Down)
            QTest.keyClick(overlay, Qt.Key.Key_Return)
            QTest.keyClick(overlay, Qt.Key.Key_Escape)
            d.save()
            d.reject()
            self.assertEqual(scale.currentIndex(), before)
            self.assertTrue(d.isVisible())
            prepare.assert_not_called()
            d.resize(760, 600)
            self.app.processEvents()
            self.assertEqual(overlay.geometry(), d.rect())
            gate.set()
            self.wait(lambda: not d.initializing)
            self.assertEqual(Path(d.game_dir.text()), self.game)
            self.assertTrue(d.form.isEnabled() and d.save_button.isEnabled())
            self.assertTrue(overlay.isHidden())
            self.assertEqual(d.original.game_dir, self.config.game_dir)
            self.assertFalse(self.store.path.exists())
            prepare.assert_not_called()
        with patch('rw_creature_pet.oracle.ui.settings.prepare_oracle_assets', return_value=geometry_assets()):
            d.save()
            self.wait(lambda: d.worker is None)
        self.assertEqual(d.result(), QDialog.DialogCode.Accepted)
        self.assertEqual(self.store.load().game_dir, self.game)

    def test_no_match_and_failure_allow_manual_browse_and_save(self):
        for error in (False, True):
            with self.subTest(error=error):
                options = dict(side_effect=OSError('fixture')) if error else dict(return_value=None)
                with patch('rw_creature_pet.oracle.ui.game_detection.find_game_directory', **options), \
                     patch('rw_creature_pet.oracle.ui.game_detection.logging.getLogger'):
                    d = self.dialog()
                    self.wait(lambda: not d.initializing)
                self.assertIn('手动选择', d.status.text())
                self.assertEqual(d.game_dir.text(), str(self.config.game_dir))
                self.assertTrue(d.browse_button.isEnabled())
                with patch('rw_creature_pet.oracle.ui.settings.QFileDialog.getExistingDirectory', return_value=str(self.game)):
                    d.browse_button.click()
                self.assertEqual(d.candidate().game_dir, self.game)
                d.reject()
                self.assertFalse(self.store.path.exists())

    def test_valid_path_is_preserved_and_regular_settings_do_not_detect(self):
        config = replace(self.config, game_dir=self.game)
        with patch('rw_creature_pet.shared.game_installation.steam_libraries') as libraries:
            d = self.dialog(config=config)
            self.wait(lambda: not d.initializing)
            self.assertEqual(Path(d.game_dir.text()), self.game)
            libraries.assert_not_called()
        d.reject()
        with patch('rw_creature_pet.oracle.ui.game_detection.find_game_directory') as find:
            d = self.dialog(config=config, first_run=False)
            QTest.qWait(20)
            self.assertIsNone(d.game_detection)
            self.assertTrue(d.form.isEnabled())
            find.assert_not_called()

    def test_timeout_unlocks_and_late_result_cannot_overwrite_manual_input(self):
        gate, entered, returned = self.blocked_finder()
        with patch.object(GameDirectoryDetection, 'TIMEOUT_MS', 50):
            d = self.dialog()
            self.wait(entered.is_set)
            self.wait(lambda: not d.initializing)
        self.assertIn('超时', d.status.text())
        manual = str(self.root/'manually selected')
        d.game_dir.setText(manual)
        gate.set()
        self.wait(returned.is_set)
        QTest.qWait(30)
        self.assertEqual(d.game_dir.text(), manual)
        self.assertFalse(self.store.path.exists())

    def test_shutdown_during_detection_discards_results_without_waiting_for_disk(self):
        gate, entered, returned = self.blocked_finder()
        d = self.dialog()
        self.wait(entered.is_set)
        d.shutdown()
        self.assertFalse(d.initializing)
        self.assertFalse(d.isVisible())
        gate.set()
        self.wait(returned.is_set)
        QTest.qWait(30)
        self.assertEqual(d.game_dir.text(), str(self.config.game_dir))
        self.assertFalse(self.store.path.exists())


if __name__ == '__main__':
    unittest.main()
