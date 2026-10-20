"""斗篷的设置入口、角色隔离、分享与默认值恢复"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from dataclasses import asdict, replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from rw_creature_pet.config import AppConfig
from rw_creature_pet.i18n import language_manager
from rw_creature_pet.oracle.cape_config import Cape
from rw_creature_pet.oracle.config import CustomAppearance, OracleConfig
from rw_creature_pet.oracle.ui.settings import OracleSettingsDialog
from rw_creature_pet.presets.appearance import apply_appearance
from rw_creature_pet.presets.fields import scope_for
from rw_creature_pet.presets.library import AppearanceLibrary
from rw_creature_pet.presets.profile import apply_profile
from rw_creature_pet.presets.profile_library import ProfileLibrary
from rw_creature_pet.settings_store import SettingsStore
from tests.oracle.character_fixture import isolate_characters


PREFIX = 'oracle.custom_appearance.cape.'


class CapeSettingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        isolate_characters(self, self.root)
        self.enterContext(patch('rw_creature_pet.presets.library.default_appearance_directory',
                                return_value=self.root/'appearances'))
        game = self.root/'game'
        (game/'RainWorld_Data').mkdir(parents=True)
        (game/'RainWorld_Data/resources.assets').touch()
        shape = CustomAppearance(cape=Cape(enabled=True, length=21.12345, hem_trim_width=.712345))
        self.config = AppConfig(game_dir=game, oracle=OracleConfig(body_appearance='custom', custom_appearance=shape))
        self.store = SettingsStore(self.root/'user/settings.json')
        self.dialogs = []

    def tearDown(self):
        for d in self.dialogs:
            d.preset_workflow.timer.stop()
            d.preset_workflow.state.autosave = False
            d.close()
            d.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()
        language_manager().set_language('zh')

    def dialog(self):
        d = OracleSettingsDialog(self.config, self.store, assets=object())
        self.dialogs.append(d)
        self.enterContext(patch.object(d, 'space_assessment', return_value=None))
        return d

    def test_dependencies_autosave_precision_resets_and_role_isolation(self):
        d = self.dialog()
        c = d.controls
        self.assertEqual(d.candidate().oracle.custom_appearance.cape, self.config.oracle.custom_appearance.cape)
        c[PREFIX+'enabled'].setChecked(False)
        self.assertFalse(c[PREFIX+'length'].isEnabled())
        c[PREFIX+'enabled'].setChecked(True)
        shape = c[PREFIX+'neckline_shape']
        shape.setCurrentIndex(shape.findData('v'))
        self.assertFalse(c[PREFIX+'neckline_roundness'].isEnabled())
        self.assertTrue(c[PREFIX+'neckline_tip_radius'].isEnabled())
        c[PREFIX+'hem_trim_enabled'].setChecked(False)
        self.assertFalse(c[PREFIX+'hem_trim_color'].isEnabled())
        c[PREFIX+'color'].setValue('#123456')
        QTest.qWait(800)
        saved = self.store.load().oracle.custom_appearance.cape
        self.assertEqual(saved.length, 21.12345)
        self.assertEqual(saved.hem_trim_width, .712345)
        self.assertEqual(saved.color, '#123456')
        d.preset_workflow.reset_parameter(PREFIX+'color')
        self.assertEqual(c[PREFIX+'color'].value(), Cape().color)
        self.assertTrue(d.preset_workflow.flush())
        first = d.profile_presets.loaded
        other_config = replace(self.config, oracle=replace(self.config.oracle,
            custom_appearance=replace(self.config.oracle.custom_appearance, cape=Cape())))
        other = ProfileLibrary().export(other_config, 'Other')
        d.preset_workflow.activate('profile', other)
        self.assertFalse(c[PREFIX+'enabled'].isChecked())
        d.preset_workflow.activate('profile', first)
        self.assertTrue(c[PREFIX+'enabled'].isChecked())
        self.assertEqual(c[PREFIX+'neckline_shape'].currentData(), 'v')
        language_manager().set_language('en')
        self.assertEqual(c[PREFIX+'enabled'].text(), 'Enable cape')

    def test_appearance_and_character_exports_keep_cape_values(self):
        for name in asdict(Cape()):
            self.assertEqual(scope_for(PREFIX+name).value, 'appearance')
        appearance = AppearanceLibrary(self.root/'export').export(self.config, 'Cape appearance')
        applied = apply_appearance(AppConfig(), appearance, self.root/'images')
        self.assertEqual(applied.oracle.custom_appearance.cape, self.config.oracle.custom_appearance.cape)
        profile = ProfileLibrary().export(self.config, 'Cape character')
        applied = apply_profile(AppConfig(), profile, self.root/'images')
        self.assertEqual(applied.oracle.custom_appearance.cape, self.config.oracle.custom_appearance.cape)
        self.assertFalse(OracleConfig.from_mapping({'body_appearance': 'custom'}).custom_appearance.cape.enabled)


if __name__ == '__main__':
    unittest.main()
