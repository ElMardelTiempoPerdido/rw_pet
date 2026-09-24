"""CLI 正确选择桌宠窗口，Oracle 入口不再被阶段限制拦截。"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import unittest
from unittest.mock import patch

from PySide6.QtWidgets import QApplication
from rw_creature_pet.app import main
from rw_creature_pet.config import AppConfig


class DesktopEntryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def test_cli_selects_oracle_and_preserves_lizard_activity(self):
        for creature in ('oracle', 'lizard'):
            with self.subTest(creature=creature), \
                 patch('sys.argv', ['run_pet.py', '--creature', creature, '--desktop', '--scale', '1.5', '--activity', 'wall']), \
                 patch('rw_creature_pet.app.QApplication', return_value=self.app), \
                 patch('rw_creature_pet.app.AppConfig.load', return_value=AppConfig()), \
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
