"""设置面板的外观预设草稿、精度、双入口和提交边界"""
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import QEvent, QCoreApplication
from PySide6.QtWidgets import QApplication

from tests.oracle.character_fixture import geometry_assets
from rw_creature_pet.config import AppConfig
from rw_creature_pet.i18n import language_manager
from rw_creature_pet.oracle.config import CustomAppearance, OracleColors
from rw_creature_pet.oracle.ui.settings import OracleSettingsDialog
from rw_creature_pet.presets.library import AppearanceLibrary
from rw_creature_pet.settings_store import SettingsStore
from rw_creature_pet.ui_config import UiConfig


class AppearancePresetUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.game = self.root/'game'
        (self.game/'RainWorld_Data').mkdir(parents=True)
        (self.game/'RainWorld_Data/resources.assets').touch()
        self.library = AppearanceLibrary(self.root/'presets')
        self.enterContext(patch('rw_creature_pet.presets.library.default_appearance_directory',
                                return_value=self.library.directory))
        self.enterContext(patch('rw_creature_pet.presets.profile_library.default_profile_directory',
                                return_value=self.root/'characters'))
        self.store = SettingsStore(self.root/'user/settings.json')
        self.config = AppConfig(game_dir=self.game, ui=UiConfig('zh'))
        self.custom = replace(self.config, oracle=replace(self.config.oracle, body_appearance='custom',
            outfit='maid', custom_colors=OracleColors(skin='#abc123', pearl_glyph='#123abc'),
            custom_appearance=CustomAppearance(head_length=1.234567, neckline_depth=5.4321),
            pearl_bubble_color='#6789ab'))
        self.dialogs = []

    def tearDown(self):
        for dialog in self.dialogs:
            dialog.close()
            dialog.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()
        language_manager().set_language('zh')

    def dialog(self):
        dialog = OracleSettingsDialog(self.config, self.store, assets=geometry_assets())
        # 此组验证手动保存边界；默认开启的自动保存由 test_preset_workflow 覆盖
        dialog.preset_workflow.state.autosave = False
        dialog.personal_controls.autosave.blockSignals(True)
        dialog.personal_controls.autosave.setChecked(False)
        dialog.personal_controls.autosave.blockSignals(False)
        self.dialogs.append(dialog)
        self.enterContext(patch.object(dialog, 'space_assessment', return_value=None))
        return dialog

    def select(self, dialog, preset):
        panel = dialog.appearance_presets
        panel.refresh(preset.id)
        panel.choose(panel.selector.currentIndex())

    def test_selection_is_draft_and_preserves_other_unsaved_preferences(self):
        preset = self.library.export(self.custom, '新外观')
        dialog = self.dialog()
        dialog.controls['oracle.float_speed'].setValue(1.1)
        dialog.controls['oracle.colors.skin'].setValue('#abcdef')
        self.select(dialog, preset)
        candidate = dialog.candidate()
        self.assertEqual(candidate.oracle.float_speed, 1.1)
        self.assertEqual(candidate.oracle.colors.skin, '#abcdef')
        self.assertEqual(candidate.oracle.custom_colors, self.custom.oracle.custom_colors)
        self.assertEqual(candidate.oracle.custom_appearance.head_length, 1.234567)
        self.assertEqual(candidate.oracle.custom_appearance.neckline_depth, 5.4321)
        self.assertEqual(candidate.oracle.outfit, 'maid')
        self.assertFalse(self.store.path.exists())
        dialog.reject()
        self.assertFalse(self.store.path.exists())

    def test_save_applies_imported_values_and_reopen_keeps_them(self):
        preset = self.library.export(self.custom, '新外观')
        dialog = self.dialog()
        self.select(dialog, preset)
        dialog.save(close=False)
        self.assertEqual(self.store.load().oracle.custom_appearance.head_length, 1.234567)
        self.assertEqual(dialog.saved_config.oracle.custom_colors.skin, '#abc123')
        self.assertEqual(dialog.candidate().oracle.custom_appearance.neckline_depth, 5.4321)
        reopened = OracleSettingsDialog(self.store.load(), self.store, assets=geometry_assets())
        self.dialogs.append(reopened)
        self.assertEqual(reopened.draft_value('oracle.custom_appearance.head_length'), 1.234567)

    def test_export_uses_draft_without_requiring_game_or_valid_screen_settings(self):
        dialog = self.dialog()
        dialog.game_dir.setText('')
        dialog.controls['oracle.colors.skin'].setValue('#123456')
        exported = dialog.appearance_presets.export_current('当前编辑')
        self.assertIsNotNone(exported)
        self.assertEqual(exported.oracle.colors.skin, '#123456')
        self.assertFalse(self.store.path.exists())

    def test_projection_color_controls_follow_the_loaded_branch(self):
        preset = self.library.export(self.custom, '投影配色')
        dialog = self.dialog()
        self.select(dialog, preset)
        for editor in dialog.color_editors['oracle.custom_colors.pearl_glyph']:
            self.assertEqual(editor.value(), '#123abc')
        self.assertEqual(dialog.controls['oracle.pearl_bubble_color'].value(), '#6789ab')
        self.assertTrue(dialog.bell_parameters.isHidden())
        self.assertFalse(dialog.custom_parameters.isHidden())

    def test_bad_selection_preserves_current_draft_and_reports_error(self):
        preset = self.library.export(self.custom, '已删除')
        dialog = self.dialog()
        dialog.appearance_presets.refresh(preset.id)
        before = dialog.appearance_draft()
        preset.path.unlink()
        dialog.appearance_presets.choose(dialog.appearance_presets.selector.currentIndex())
        self.assertEqual(dialog.appearance_draft(), before)
        self.assertEqual(dialog.appearance_presets.selector.currentIndex(), -1)
        self.assertIn('无法载入', dialog.appearance_presets.status.text())

    def test_update_keeps_id_and_path_without_creating_duplicates(self):
        dialog = self.dialog()
        panel = dialog.appearance_presets
        first = panel.export_current('版本')
        dialog.controls['oracle.colors.skin'].setValue('#123456')
        second = panel.export_current('版本', target=first)
        self.assertEqual(first.id, second.id)
        self.assertEqual(first.path, second.path)
        self.assertTrue(panel.warning.isHidden())
        self.assertIsNone(panel.loaded)
        self.assertIsNotNone(dialog.profile_presets.loaded)
        panel.selector.setCurrentIndex(0)
        panel.choose(0)
        fork = panel.export_current('独立外观')
        self.assertNotEqual(fork.id, first.id)

    def test_import_button_copies_external_bundle_and_loads_it_as_draft(self):
        external = AppearanceLibrary(self.root/'external')
        preset = external.export(self.custom, '来自朋友')
        dialog = self.dialog()
        dialog.appearance_presets.import_file(preset.path)
        self.assertEqual(dialog._appearance_source.id, preset.id)
        self.assertTrue(dialog._appearance_source.path.is_relative_to(self.library.directory))
        self.assertEqual(dialog.appearance_draft().oracle.custom_colors.skin, '#abc123')
        self.assertFalse(self.store.path.exists())

    def test_refresh_keeps_deleted_source_identity_without_changing_draft(self):
        dialog = self.dialog()
        panel = dialog.appearance_presets
        preset = panel.export_current('旧关联')
        panel.import_file(preset.path)
        before = dialog.appearance_draft()
        preset.path.unlink()
        panel.refresh()
        self.assertTrue(panel.selection_panel.isHidden())
        self.assertEqual(dialog._appearance_source.id, preset.id)
        self.assertEqual(dialog.appearance_draft(), before)

    def test_language_change_keeps_selection_user_name_and_loaded_values(self):
        dialog = self.dialog()
        preset = self.library.export(self.custom, '不会翻译的名字')
        self.select(dialog, preset)
        before = dialog.appearance_draft()
        language_manager().set_language('en')
        self.app.processEvents()
        panel = dialog.appearance_presets
        self.assertEqual(dialog._appearance_source.name, '不会翻译的名字')
        self.assertIsNotNone(dialog.profile_presets.loaded)
        self.assertEqual(panel.import_button.text(), 'Import appearance into current character…')
        self.assertEqual(panel.status.text(), 'Appearance loaded')
        self.assertEqual(dialog.appearance_draft().oracle, before.oracle)


if __name__ == '__main__':
    unittest.main()
