"""三个通用槽位的编辑、角色隔离、默认值和分享资源闭环"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from dataclasses import asdict, replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from rw_creature_pet.config import AppConfig
from rw_creature_pet.i18n import language_manager
from rw_creature_pet.oracle.clothing_config import CLOTHING_DECAL_FIELDS, ClothingDecal
from rw_creature_pet.oracle.config import CustomAppearance, OracleConfig
from rw_creature_pet.oracle.ui.settings import OracleSettingsDialog
from rw_creature_pet.presets.appearance import apply_appearance
from rw_creature_pet.presets.fields import scope_for
from rw_creature_pet.presets.library import AppearanceLibrary
from rw_creature_pet.presets.profile import apply_profile
from rw_creature_pet.presets.profile_library import ProfileLibrary
from rw_creature_pet.settings_store import SettingsStore
from tests.oracle.character_fixture import isolate_characters


PREFIX = 'oracle.custom_appearance.'


class ClothingSettingsTests(unittest.TestCase):
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
        shape = CustomAppearance(clothing_decal_1=ClothingDecal(offset_x=1.12345))
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

    def png(self, name='衣料.png', size=128):
        source = self.root/name
        image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(QColor('#246a9e'))
        image.save(str(source))
        return source

    def test_validation_defaults_paths_and_explicit_ownership(self):
        for bad in ({'part': 'cape'}, {'enabled': 1}, {'offset_x': 129}, {'offset_y': float('nan')}):
            with self.assertRaises(ValueError):
                ClothingDecal(**bad)
        shape = CustomAppearance.from_mapping({'clothing_decal_2': {'image_path': 'pattern.png'}})
        self.assertEqual(shape.clothing_decal_2.part, 'left_sleeve')
        self.assertEqual(shape.resolve_image_paths(self.root).clothing_decal_2.image_path,
                         str((self.root/'pattern.png').resolve()))
        for name in CLOTHING_DECAL_FIELDS:
            self.assertFalse(getattr(shape, name).enabled)
            for field in asdict(getattr(shape, name)):
                self.assertEqual(scope_for(PREFIX+name+'.'+field).value, 'appearance')

    def test_import_autosave_reset_role_isolation_and_language(self):
        d = self.dialog()
        first = d.profile_presets.loaded
        original = first.path.read_bytes()
        editor = d.clothing_editors['clothing_decal_1']
        self.assertTrue(all(c.property('default_reset_bound') for c in editor.parameter_controls.values()))
        source = self.png()
        self.assertTrue(editor.import_file(source))
        source.unlink()
        self.assertTrue(Path(editor.value().image_path).is_file())
        self.assertFalse(editor.import_file(self.png('too-large.png', 129)))
        editor.part.setCurrentIndex(editor.part.findData('left_sleeve'))
        editor.y_input.setValue(4.5)
        QTest.qWait(800)
        saved = self.store.load().oracle.custom_appearance.clothing_decal_1
        self.assertEqual(saved.offset_x, 1.12345)
        self.assertEqual(saved.offset_y, 4.5)
        self.assertEqual(saved.part, 'left_sleeve')
        self.assertEqual(original, first.path.read_bytes())
        d.preset_workflow.reset_parameter(PREFIX+'clothing_decal_1.part')
        self.assertEqual(editor.value().part, 'robe')
        self.assertTrue(d.preset_workflow.flush())
        other = ProfileLibrary().export(replace(self.config, oracle=replace(self.config.oracle,
            custom_appearance=CustomAppearance())), 'Other')
        d.preset_workflow.activate('profile', other)
        self.assertEqual(editor.value(), ClothingDecal())
        d.preset_workflow.activate('profile', first)
        self.assertTrue(editor.value().enabled)
        self.assertEqual(editor.value().offset_y, 4.5)
        language_manager().set_language('en')
        self.assertEqual(editor.enabled.text(), 'Clothing texture 1')
        self.assertEqual(editor.part.currentText(), 'Robe')
        d.controls['oracle.outfit'].setValue('maid')
        self.assertEqual(d.candidate().oracle.custom_appearance.clothing_decal_1, editor.value())

    def test_three_slots_export_and_reimport_include_disabled_images(self):
        d = self.dialog()
        for i, editor in enumerate(d.clothing_editors.values()):
            self.assertTrue(editor.import_file(self.png(f'{i}.png', 64+i)))
            editor.part.setCurrentIndex(0)  # 三个槽位允许同一部位
            editor.x_input.setValue(i*2.)
        d.clothing_editors['clothing_decal_2'].enabled.setChecked(False)
        expected = d.candidate()
        look = AppearanceLibrary(self.root/'export').export(expected, 'Clothing')
        role = ProfileLibrary().export(expected, 'Clothing character')
        received_look = AppearanceLibrary(self.root/'received-look').import_file(look.path)
        received_role = ProfileLibrary(self.root/'received-role').import_file(role.path)
        for applied in (apply_appearance(AppConfig(), received_look, self.root/'look-images'),
                        apply_profile(AppConfig(), received_role, self.root/'role-images')):
            for name in CLOTHING_DECAL_FIELDS:
                actual = getattr(applied.oracle.custom_appearance, name)
                original = getattr(expected.oracle.custom_appearance, name)
                self.assertEqual(replace(actual, image_path=original.image_path), original)
                self.assertEqual(Path(actual.image_path).read_bytes(), Path(original.image_path).read_bytes())


if __name__ == '__main__':
    unittest.main()
