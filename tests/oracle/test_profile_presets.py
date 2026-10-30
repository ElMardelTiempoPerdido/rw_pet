"""角色设置在设置面板中的草稿、外观引用和统一保存"""
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication

from tests.oracle.character_fixture import geometry_assets
from rw_creature_pet.config import AppConfig
from rw_creature_pet.i18n import language_manager
from rw_creature_pet.oracle.config import DragReactionConfig, OracleColors
from rw_creature_pet.oracle.ui.settings import OracleSettingsDialog
from rw_creature_pet.presets.library import AppearanceLibrary
from rw_creature_pet.presets.profile import profile_mapping
from rw_creature_pet.presets.profile_library import ProfileLibrary
from rw_creature_pet.presets.sharing import open_profile
from rw_creature_pet.settings_store import SettingsStore
from rw_creature_pet.ui_config import UiConfig


class ProfilePresetUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.game = self.root/'game'
        (self.game/'RainWorld_Data').mkdir(parents=True)
        (self.game/'RainWorld_Data/resources.assets').touch()
        self.library = ProfileLibrary(self.root/'profiles')
        self.appearances = AppearanceLibrary(self.root/'appearances')
        self.enterContext(patch('rw_creature_pet.presets.profile_library.default_profile_directory',
                                return_value=self.library.directory))
        self.enterContext(patch('rw_creature_pet.presets.library.default_appearance_directory',
                                return_value=self.appearances.directory))
        self.store = SettingsStore(self.root/'user/settings.json')
        self.config = AppConfig(game_dir=self.game, ui=UiConfig('zh'))
        self.profile = replace(self.config, oracle=replace(self.config.oracle,
            body_appearance='custom', outfit='maid', custom_colors=OracleColors(skin='#abc123'),
            float_speed=1.234567, base_speed=3.123456, pearl_follow_width=412.3456,
            pearl_matrix_count=0, projection_opacity=.123456,
            drag_reactions=DragReactionConfig(voice_probability=0., gesture_probability=.876543)))
        self.dialogs = []

    def tearDown(self):
        for dialog in self.dialogs:
            dialog.close()
            dialog.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()
        language_manager().set_language('zh')

    def dialog(self, config=None):
        dialog = OracleSettingsDialog(config or self.config, self.store, assets=geometry_assets())
        # 此组验证手动保存边界；默认开启的自动保存由 test_preset_workflow 覆盖
        dialog.preset_workflow.state.autosave = False
        dialog.personal_controls.autosave.blockSignals(True)
        dialog.personal_controls.autosave.setChecked(False)
        dialog.personal_controls.autosave.blockSignals(False)
        self.dialogs.append(dialog)
        self.enterContext(patch.object(dialog, 'space_assessment', return_value=None))
        return dialog

    def select(self, dialog, preset):
        panel = dialog.profile_presets
        panel.refresh(preset.id)
        panel.choose(panel.selector.currentIndex())

    def test_profile_load_preserves_unsaved_local_preferences_and_waits_for_save(self):
        preset = self.library.export(self.profile, '新角色')
        d = self.dialog()
        d.controls['audio.volume'].setValue(19)
        d.controls['oracle.arm_scale'].setValue(55)
        d.controls['oracle.halo_enabled'].setChecked(False)
        d.controls['oracle.colors.skin'].setValue('#abcdef')
        d.controls['oracle.float_speed'].setValue(.9)
        self.select(d, preset)
        value = d.candidate()
        self.assertEqual(value.audio.volume, .19)
        self.assertEqual(value.oracle.arm_scale, .55)
        self.assertFalse(value.oracle.halo_enabled)
        self.assertEqual(value.oracle.colors.skin, self.config.oracle.colors.skin)
        self.assertEqual(profile_mapping(value), profile_mapping(self.profile))
        self.assertEqual(value.oracle.custom_colors.skin, '#abc123')
        self.assertIsNone(d.appearance_presets.loaded)
        self.assertEqual(d._appearance_source.path, preset.appearance.path)
        self.assertFalse(self.store.path.exists())
        d.reject()
        self.assertFalse(self.store.path.exists())

    def test_hidden_behavior_and_precision_survive_apply_save_and_reopen(self):
        preset = self.library.export(self.profile, '精确参数')
        d = self.dialog()
        self.select(d, preset)
        d.save(close=False)
        saved = self.store.load()
        self.assertEqual(profile_mapping(saved), profile_mapping(self.profile))
        self.assertEqual(saved.oracle.drag_reactions.voice_probability, 0.)
        self.assertEqual(profile_mapping(self.dialog(saved).profile_draft()), profile_mapping(self.profile))

    def test_export_uses_behavior_and_appearance_drafts_without_validating_local_pages(self):
        d = self.dialog()
        d.game_dir.setText('')
        d.controls['oracle.float_speed'].setValue(1.1)
        d.controls['oracle.colors.skin'].setValue('#123456')
        previous = d.profile_presets.loaded
        archive = d.profile_presets.export_current('当前草稿', destination=self.root/'draft.zip')
        self.assertIsNotNone(archive)
        with open_profile(archive) as preset:
            self.assertEqual(preset.config.oracle.float_speed, 1.1)
            self.assertEqual(preset.appearance.oracle.colors.skin, '#123456')
            self.assertEqual(preset.id, previous.id)
        self.assertEqual(d.profile_presets.loaded, previous)
        self.assertFalse(self.store.path.exists())

    def test_broken_reference_keeps_all_current_draft_values(self):
        preset = self.library.export(self.profile, '缺失外观')
        d = self.dialog()
        panel = d.profile_presets
        panel.refresh(preset.id)
        before = d.candidate()
        preset.appearance.path.unlink()
        panel.choose(panel.selector.currentIndex())
        self.assertEqual(d.candidate(), before)
        self.assertIsNotNone(panel.loaded)
        self.assertIn('无法载入角色设置', panel.status.text())

    def test_changing_appearance_after_profile_preserves_behavior_and_updates_export_reference(self):
        preset = self.library.export(self.profile, '角色')
        d = self.dialog()
        self.select(d, preset)
        bell = self.appearances.export(self.config, 'Bell 配色')
        panel = d.appearance_presets
        panel.refresh(bell.id)
        panel.choose(panel.selector.currentIndex())
        self.assertEqual(profile_mapping(d.candidate()), profile_mapping(self.profile))
        self.assertEqual(d.candidate().oracle.body_appearance, 'bell')
        result = d.profile_presets.export_current('角色新版', destination=self.root/'new.zip')
        with open_profile(result) as shared:
            self.assertEqual(shared.appearance.id, bell.id)
            self.assertEqual(shared.appearance.oracle.body_appearance, 'bell')

    def test_native_share_dialog_does_not_offer_local_file_update(self):
        d = self.dialog()
        destination = self.root/'shared.zip'
        with patch('rw_creature_pet.oracle.ui.profile_presets.QFileDialog.getSaveFileName',
                   return_value=(str(destination), '')), patch(
                       'rw_creature_pet.oracle.ui.preset_panel.PresetSaveDialog') as legacy:
            self.assertTrue(d.profile_presets.choose_export())
        legacy.assert_not_called()
        self.assertEqual(d.profile_presets.export_button.text(), '导出分享此角色')
        self.assertIn('强烈建议', d.profile_presets.share_hint.text())
        self.assertTrue(destination.is_file())
        language_manager().set_language('en')
        self.assertEqual(d.profile_presets.export_button.text(), 'Export character for sharing')
        self.assertEqual(d.profile_presets.import_actions[0][0].text(), 'Import from ZIP or JSON…')
        language_manager().set_language('zh')

    def test_import_conflict_cancel_keeps_draft_and_local_files(self):
        role = self.library.export(self.config, 'Local')
        incoming = ProfileLibrary(self.root/'external').export(self.profile, 'Incoming', preset_id=role.id)
        d = self.dialog()
        self.select(d, role)
        d.controls['oracle.colors.skin'].setValue('#654321')
        before = role.path.read_bytes()
        with patch.object(d.profile_presets, 'resolve_conflict', return_value=None) as prompt:
            self.assertFalse(d.profile_presets.import_file(incoming.path))
        prompt.assert_called_once()
        self.assertEqual(role.path.read_bytes(), before)
        self.assertEqual(d.candidate().oracle.colors.skin, '#654321')

    def test_import_older_same_id_uses_explicit_incoming_choice(self):
        role = self.library.export(self.config, 'Local')
        incoming = ProfileLibrary(self.root/'external').export(self.profile, 'Incoming', preset_id=role.id)
        import json
        data = json.loads(incoming.path.read_text(encoding='utf-8'))
        data['updated_at'] = '2000-01-01T00:00:00+00:00'
        incoming.path.write_text(json.dumps(data), encoding='utf-8')
        d = self.dialog()
        self.select(d, role)
        with patch.object(d.profile_presets, 'resolve_conflict', return_value='replace'):
            self.assertTrue(d.profile_presets.import_file(incoming.path))
        self.assertEqual(d.candidate().oracle.float_speed, self.profile.oracle.float_speed)
        self.assertEqual(d.profile_presets.loaded.id, role.id)
        self.assertTrue(list((role.path.parent/'history/imports').glob('*/profile.json')))

    def test_newer_external_appearance_is_not_selected_when_loading_profile(self):
        old = self.appearances.export(self.config, '外观旧版')
        preset = self.library.export(self.config, '角色旧版', appearance_source=old)
        changed = replace(self.config, oracle=replace(self.config.oracle, colors=OracleColors(skin='#ff0000')))
        self.appearances.export(changed, '外观新版', preset_id=old.id)
        d = self.dialog()
        self.select(d, preset)
        self.assertEqual(d.candidate().oracle.colors.skin, self.config.oracle.colors.skin)
        self.assertEqual(d._appearance_source.path, preset.appearance.path)
        self.assertTrue(d.appearance_presets.selection_panel.isHidden())

    def test_import_copies_bundle_and_updates_reference_without_committing(self):
        external = ProfileLibrary(self.root/'external')
        preset = external.export(self.profile, '朋友的角色')
        d = self.dialog()
        d.profile_presets.import_file(preset.path)
        self.assertTrue(d.profile_presets.loaded.path.is_relative_to(self.library.directory))
        self.assertEqual(d._appearance_source.id, preset.appearance.id)
        self.assertEqual(profile_mapping(d.candidate()), profile_mapping(self.profile))
        self.assertFalse(self.store.path.exists())

    def test_language_and_navigation_keep_loaded_values_and_reference(self):
        preset = self.library.export(self.profile, '用户命名')
        d = self.dialog()
        self.select(d, preset)
        d.tabs.setCurrentWidget(d.pages['profile'])
        language_manager().set_language('en')
        self.app.processEvents()
        self.assertEqual(d.tabs.tabText(d.tabs.currentIndex()), 'Character settings')
        self.assertEqual(d.profile_presets.import_button.text(), 'Import character settings…')
        self.assertEqual(d.profile_presets.selector.currentText(), '用户命名 *')
        self.assertEqual(d._appearance_source.id, preset.appearance.id)
        self.assertEqual(profile_mapping(d.candidate()), profile_mapping(self.profile))
        d.tabs.setCurrentWidget(d.pages['appearance'])
        self.assertIs(d.tabs.currentWidget(), d.pages['appearance'])
        self.assertEqual(profile_mapping(d.candidate()), profile_mapping(self.profile))


if __name__ == '__main__':
    unittest.main()
