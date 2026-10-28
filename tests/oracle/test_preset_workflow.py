"""个人调整的自动保存、只读默认值、角色归属及外观历史"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QTimer
from PySide6.QtGui import QImage, QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMenu

from rw_creature_pet.config import AppConfig
from rw_creature_pet.i18n import language_manager
from rw_creature_pet.oracle.ui.preset_dialogs import AppearanceImportDialog, PresetSaveDialog
from rw_creature_pet.oracle.ui.settings import OracleSettingsDialog
from rw_creature_pet.presets.startup import BELL_PROFILE_ID
from rw_creature_pet.presets.library import AppearanceLibrary
from rw_creature_pet.presets.profile_library import ProfileLibrary
from rw_creature_pet.settings_store import SettingsStore
from rw_creature_pet.ui_config import UiConfig


class PresetWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        game = self.root/'game'
        (game/'RainWorld_Data').mkdir(parents=True)
        (game/'RainWorld_Data/resources.assets').touch()
        self.config = AppConfig(game_dir=game, ui=UiConfig('zh'))
        self.other = replace(self.config, oracle=replace(self.config.oracle,
            colors=replace(self.config.oracle.colors, skin='#123456'), float_speed=1.2))
        self.library = AppearanceLibrary(self.root/'appearances')
        self.profiles = ProfileLibrary(self.root/'profiles')
        self.store = SettingsStore(self.root/'user/settings.json')
        self.enterContext(patch('rw_creature_pet.presets.library.default_appearance_directory', return_value=self.library.directory))
        self.enterContext(patch('rw_creature_pet.presets.profile_library.default_profile_directory', return_value=self.profiles.directory))
        self.dialogs = []

    def tearDown(self):
        for dialog in self.dialogs:
            if hasattr(dialog, 'preset_workflow'):
                dialog.preset_workflow.timer.stop()
                dialog.preset_workflow.state.autosave = False
            dialog.close()
            dialog.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()
        language_manager().set_language('zh')

    def dialog(self, config=None, **kwargs):
        dialog = OracleSettingsDialog(config or self.config, self.store, assets=kwargs.pop('assets', object()), **kwargs)
        self.dialogs.append(dialog)
        self.enterContext(patch.object(dialog, 'space_assessment', return_value=None))
        return dialog

    def select(self, panel, preset):
        panel.refresh(preset.id)
        return panel.choose(panel.selector.currentIndex())

    def test_autosave_updates_current_and_keeps_original_defaults_and_name(self):
        preset = self.profiles.export(self.config, '角色 A')
        d = self.dialog()
        self.assertTrue(d.personal_controls.autosave.isChecked())
        self.assertTrue(self.select(d.profile_presets, preset))
        from rw_creature_pet.presets.profile import load_profile
        baseline = load_profile(preset.path.parent/'original/profile.json')
        original = baseline.path.read_bytes(), baseline.appearance.path.read_bytes()
        d.controls['oracle.colors.skin'].setValue('#654321')
        self.assertIn('角色 A', d.profile_presets.selector.currentText())
        QTest.qWait(750)
        self.assertEqual(self.store.load().oracle.colors.skin, '#654321')
        self.assertEqual(original, (baseline.path.read_bytes(), baseline.appearance.path.read_bytes()))
        self.assertEqual(load_profile(preset.path).appearance.oracle.colors.skin, '#654321')
        self.assertFalse(d.preset_workflow.dirty)
        self.assertEqual(d.appearance_owner.text(), '正在调整：角色 A')
        self.assertTrue(d.appearance_presets.selection_panel.isHidden())

    def test_edit_burst_applies_once_without_resource_preparation(self):
        def commit(config, assets):
            self.store.save(config)
        with patch('rw_creature_pet.oracle.ui.settings.prepare_oracle_assets') as prepare:
            d = self.dialog(commit=commit)
            with patch.object(d, 'commit', wraps=commit) as apply:
                for color in ('#123456', '#234567', '#345678'):
                    d.controls['oracle.colors.skin'].setValue(color)
                QTest.qWait(750)
                self.assertEqual(apply.call_count, 1)
            prepare.assert_not_called()

    def test_repeated_png_autosaves_survive_generation_cleanup_after_reopen(self):
        png = self.root/'face.png'
        image = QImage(5, 5, QImage.Format.Format_ARGB32)
        image.fill(QColor('red'))
        image.save(str(png))
        shape = replace(self.config.oracle.custom_appearance, forehead=replace(
            self.config.oracle.custom_appearance.forehead, enabled=True, image_path=str(png)))
        role = self.profiles.export(replace(self.config, oracle=replace(self.config.oracle,
            body_appearance='custom', custom_appearance=shape)), 'PNG')
        first = self.dialog()
        self.select(first.profile_presets, role)
        self.assertTrue(first.preset_workflow.flush())
        first.preset_workflow.timer.stop()
        reopened = self.dialog(self.store.load())
        for color in ('#123456', '#234567', '#345678', '#456789'):
            reopened.controls['oracle.custom_colors.skin'].setValue(color)
            self.assertTrue(reopened.preset_workflow.flush())
            self.assertTrue(Path(reopened.candidate().oracle.custom_appearance.forehead.image_path).is_file())
        self.assertEqual(self.store.load().oracle.custom_colors.skin, '#456789')

    def test_autosave_does_not_commit_local_draft(self):
        d = self.dialog()
        d.controls['audio.volume'].setValue(13)
        d.controls['oracle.colors.skin'].setValue('#654321')
        self.assertTrue(d.preset_workflow.flush())
        self.assertEqual(self.store.load().audio, self.config.audio)
        self.assertEqual(d.candidate().audio.volume, .13)
        d.save(close=False)
        self.assertEqual(self.store.load().audio.volume, .13)

    def test_off_discards_draft_on_close_and_on_profile_switch(self):
        first = self.profiles.export(self.config, 'A')
        second = self.profiles.export(self.other, 'B')
        d = self.dialog()
        self.select(d.profile_presets, first)
        d.personal_controls.autosave.setChecked(False)
        saved = self.store.path.read_bytes()
        d.controls['oracle.colors.skin'].setValue('#654321')
        self.select(d.profile_presets, second)
        self.select(d.profile_presets, first)
        self.assertEqual(d.candidate().oracle.colors.skin, self.config.oracle.colors.skin)
        d.controls['oracle.colors.skin'].setValue('#abcdef')
        d.reject()
        self.assertEqual(self.store.path.read_bytes(), saved)
        reopened = self.dialog(self.store.load())
        self.assertFalse(reopened.personal_controls.autosave.isChecked())
        self.assertEqual(reopened.candidate().oracle.colors.skin, self.config.oracle.colors.skin)

    def test_manual_save_off_then_discard_returns_to_personal_values_not_defaults(self):
        d = self.dialog()
        d.personal_controls.autosave.setChecked(False)
        d.controls['oracle.colors.skin'].setValue('#654321')
        d.personal_controls.save.click()
        d.controls['oracle.colors.skin'].setValue('#abcdef')
        d.reject()
        self.assertEqual(self.dialog(self.store.load()).candidate().oracle.colors.skin, '#654321')

    def test_enable_autosave_commits_current_draft_and_close_flushes_pending(self):
        d = self.dialog()
        d.personal_controls.autosave.setChecked(False)
        d.controls['oracle.colors.skin'].setValue('#654321')
        d.personal_controls.autosave.setChecked(True)
        self.assertEqual(self.store.load().oracle.colors.skin, '#654321')
        d.controls['oracle.colors.skin'].setValue('#abcdef')
        d.reject()
        self.assertEqual(self.store.load().oracle.colors.skin, '#abcdef')

    def test_role_owns_imported_appearance_and_retains_history_after_reopen(self):
        role = self.profiles.export(self.config, 'A')
        look = self.library.export(self.other, 'Y')
        unchanged = look.path.read_bytes()
        d = self.dialog()
        self.select(d.profile_presets, role)
        d.controls['oracle.colors.skin'].setValue('#654321')
        self.select(d.appearance_presets, look)
        self.assertEqual(d.profile_presets.loaded.id, role.id)
        self.assertIsNone(d.appearance_presets.loaded)
        d.controls['oracle.colors.skin'].setValue('#aabbcc')
        d.preset_workflow.flush()
        self.assertEqual(look.path.read_bytes(), unchanged)
        reopened = self.dialog(self.store.load())
        reopened.preset_workflow.restore_history(0)
        self.assertEqual(reopened.candidate().oracle.colors.skin, '#654321')
        self.assertEqual(reopened.candidate().oracle.float_speed, self.config.oracle.float_speed)
        reopened.preset_workflow.restore_history(0)
        self.assertEqual(reopened.candidate().oracle.colors.skin, '#aabbcc')

    def test_off_appearance_trials_keep_in_session_undo_but_do_not_persist(self):
        role = self.profiles.export(self.config, 'A')
        look = self.library.export(self.other, 'Y')
        d = self.dialog(); self.select(d.profile_presets, role)
        d.personal_controls.autosave.setChecked(False)
        d.controls['oracle.colors.skin'].setValue('#654321')
        self.select(d.appearance_presets, look)
        d.preset_workflow.restore_history(0)
        self.assertEqual(d.candidate().oracle.colors.skin, '#654321')
        d.reject()
        self.assertEqual(self.store.load().oracle.colors.skin, self.config.oracle.colors.skin)
        self.assertEqual(self.dialog(self.store.load()).preset_workflow.entry.history, [])

    def test_distinct_roles_keep_adjustments_and_appearance_imports_always_read_source(self):
        roles = [self.profiles.export(self.config, name) for name in ('A', 'B')]
        d = self.dialog()
        self.select(d.profile_presets, roles[0]); d.controls['oracle.colors.skin'].setValue('#654321')
        self.select(d.profile_presets, roles[1]); d.controls['oracle.colors.skin'].setValue('#abcdef')
        self.select(d.profile_presets, roles[0])
        self.assertEqual(d.candidate().oracle.colors.skin, '#654321')
        d.profile_presets.clear_selection()
        looks = [self.library.export(self.config, name) for name in ('X', 'Y')]
        self.select(d.appearance_presets, looks[0]); d.controls['oracle.colors.skin'].setValue('#112233')
        self.select(d.appearance_presets, looks[1]); self.select(d.appearance_presets, looks[0])
        self.assertEqual(d.candidate().oracle.colors.skin, self.config.oracle.colors.skin)
        self.assertEqual(d.profile_presets.loaded.id, roles[0].id)
        d.preset_workflow.restore_history(0)
        self.assertEqual(d.candidate().oracle.colors.skin, '#112233')

    def test_failed_save_prevents_switch_and_close_and_retains_draft(self):
        first = self.profiles.export(self.config, 'A'); target = self.profiles.export(self.other, 'B')
        d = self.dialog(); self.select(d.profile_presets, first)
        saved = self.store.path.read_bytes()
        d.controls['oracle.colors.skin'].setValue('#654321')
        with patch.object(self.store, '_write', side_effect=OSError('locked')):
            self.assertFalse(self.select(d.profile_presets, target))
            self.assertFalse(d.preset_workflow.before_close())
        self.assertEqual(d.profile_presets.loaded.id, first.id)
        self.assertEqual(d.candidate().oracle.colors.skin, '#654321')
        self.assertEqual(self.store.path.read_bytes(), saved)
        self.assertTrue(d.preset_workflow.flush())

    def test_failed_target_save_keeps_previous_context_and_history(self):
        first = self.profiles.export(self.config, 'A'); target = self.library.export(self.other, 'Y')
        d = self.dialog(); self.select(d.profile_presets, first)
        with patch.object(self.store, '_write', side_effect=OSError('locked')):
            self.assertFalse(self.select(d.appearance_presets, target))
        self.assertEqual(d.candidate().oracle.colors.skin, self.config.oracle.colors.skin)
        self.assertEqual(d.preset_workflow.entry.history, [])

    def test_parameter_defaults_use_file_values_and_restore_appearance_keeps_behavior(self):
        role = self.profiles.export(self.other, 'A')
        d = self.dialog(); self.select(d.profile_presets, role)
        d.controls['oracle.colors.skin'].setValue('#654321')
        d.controls['oracle.float_speed'].setValue(.8)
        d.preset_workflow.reset_parameter('oracle.colors.skin')
        self.assertEqual(d.candidate().oracle.colors.skin, '#123456')
        self.assertEqual(d.candidate().oracle.float_speed, .8)
        d.controls['oracle.colors.skin'].setValue('#abcdef')
        d.preset_workflow.restore_defaults('appearance')
        self.assertEqual(d.candidate().oracle.colors.skin, '#123456')
        self.assertEqual(d.candidate().oracle.float_speed, .8)
        d.preset_workflow.restore_defaults('profile')
        self.assertEqual(d.candidate().oracle.float_speed, 1.2)

    def test_history_is_bounded_deduplicated_and_does_not_track_each_edit(self):
        role = self.profiles.export(self.config, 'A')
        d = self.dialog(); self.select(d.profile_presets, role)
        for i in range(12):
            c=replace(self.config,oracle=replace(self.config.oracle,colors=replace(self.config.oracle.colors,skin=f'#{i+1:06x}')))
            look=self.library.export(c,str(i)); self.select(d.appearance_presets,look)
        self.assertEqual(len(d.preset_workflow.entry.history),10)
        self.select(d.appearance_presets,look)
        self.assertEqual(len(d.preset_workflow.entry.history),10)
        for color in ('#aabbcc','#bbccdd','#ccddee'):
            d.controls['oracle.colors.skin'].setValue(color)
        d.preset_workflow.flush()
        self.assertEqual(len(d.preset_workflow.entry.history),10)

    def test_snapshots_and_defaults_survive_external_png_and_package_removal(self):
        png=self.root/'face.png'; image=QImage(5,5,QImage.Format.Format_ARGB32); image.fill(QColor('red')); image.save(str(png))
        shape=replace(self.config.oracle.custom_appearance,forehead=replace(self.config.oracle.custom_appearance.forehead,enabled=True,image_path=str(png)))
        custom=replace(self.config,oracle=replace(self.config.oracle,body_appearance='custom',custom_appearance=shape))
        role=self.profiles.export(custom,'A'); look=self.library.export(self.other,'Y')
        d=self.dialog(); self.select(d.profile_presets,role)
        self.select(d.appearance_presets,look)
        png.unlink()
        for path in role.appearance.path.parent.glob('images/*.png'): path.unlink()
        reopened=self.dialog(self.store.load()); reopened.preset_workflow.restore_history(0)
        self.assertTrue(Path(reopened.candidate().oracle.custom_appearance.forehead.image_path).is_file())
        self.assertEqual(reopened.candidate().oracle.body_appearance,'custom')
        prior = next(entry for entry in reopened.preset_workflow.state.entries.values()
                     if entry.source and entry.source.id == role.id)
        self.assertTrue(any(item['values']['oracle.body_appearance'] == 'bell' for item in prior.history))

    def test_export_current_values_become_new_defaults_without_changing_active_role(self):
        role=self.profiles.export(self.config,'A'); d=self.dialog(); self.select(d.profile_presets,role)
        d.controls['oracle.colors.skin'].setValue('#654321')
        look=d.appearance_presets.export_current('分享')
        self.assertEqual(look.oracle.colors.skin,'#654321')
        self.assertEqual(d.profile_presets.loaded.id,role.id)
        self.assertEqual(d.preset_workflow.entry.defaults['oracle.colors.skin'],self.config.oracle.colors.skin)
        before = len(self.profiles.scan().presets)
        archive=d.profile_presets.export_current('分享角色', destination=self.root/'shared.zip')
        from rw_creature_pet.presets.sharing import open_profile
        with open_profile(archive) as shared:
            self.assertEqual(shared.id, role.id)
            self.assertEqual(shared.appearance.oracle.colors.skin, '#654321')
        self.assertEqual(d.profile_presets.loaded.id, role.id)
        self.assertEqual(d.preset_workflow.entry.defaults['oracle.colors.skin'],self.config.oracle.colors.skin)
        self.assertEqual(len(self.profiles.scan().presets), before)

    def test_new_version_has_separate_defaults_and_old_adjustments_survive(self):
        old=self.profiles.export(self.config,'旧'); d=self.dialog(); self.select(d.profile_presets,old)
        d.controls['oracle.colors.skin'].setValue('#654321'); d.preset_workflow.flush()
        new=self.profiles.export(self.other,'新',preset_id=old.id)
        self.select(d.profile_presets,new)
        self.assertEqual(d.candidate().oracle.colors.skin,'#123456')
        d.preset_workflow.activate('profile',old)
        self.assertEqual(d.candidate().oracle.colors.skin,'#654321')

    def test_invalid_import_does_not_alter_selection_or_draft(self):
        d=self.dialog(); d.controls['oracle.colors.skin'].setValue('#654321')
        bad=self.root/'bad.json'; bad.write_text('{}',encoding='utf-8')
        self.assertFalse(d.appearance_presets.import_file(bad))
        self.assertEqual(d.candidate().oracle.colors.skin,'#654321')

    def test_old_settings_migrate_appearance_and_behavior_and_keep_original_defaults(self):
        role = self.profiles.export(self.config, 'Bell', preset_id=BELL_PROFILE_ID)
        self.store.save(self.other)
        d = self.dialog(self.store.load())
        self.assertEqual(d.profile_presets.loaded.id, role.id)
        self.assertEqual(d.candidate().oracle.colors.skin, self.other.oracle.colors.skin)
        self.assertEqual(d.candidate().oracle.float_speed, 1.2)
        self.assertTrue(d._migration_notice)
        d.preset_workflow.reset_parameter('oracle.float_speed')
        self.assertEqual(d.candidate().oracle.float_speed, self.config.oracle.float_speed)
        d.preset_workflow.flush()
        self.assertTrue(self.store.load_preset_state()['character_setup']['complete'])

    def test_initial_setup_does_not_write_before_game_resources_are_ready(self):
        d=self.dialog(assets=None)
        d.controls['oracle.colors.skin'].setValue('#654321')
        d.preset_workflow.flush(); d.reject()
        self.assertFalse(self.store.path.exists())

    def test_preview_parameter_context_menu_resets_only_that_parameter(self):
        shape = self.config.oracle.custom_appearance
        custom = replace(self.config, oracle=replace(self.config.oracle, body_appearance='custom',
            custom_appearance=replace(shape, ear_body=replace(shape.ear_body, width=7., height=9.))))
        role = self.profiles.export(custom, '自定义')
        d = self.dialog(); self.select(d.profile_presets, role)
        d.open_face_preview()
        editor = d.face_preview.ear_editors['ear_body']
        editor.width_input.setValue(12.)
        editor.height_input.setValue(13.)
        def choose_reset():
            menu = QApplication.activePopupWidget()
            if isinstance(menu, QMenu):
                next(action for action in menu.actions() if action.text() == '恢复此项默认值').trigger()
                menu.close()
        QTimer.singleShot(50, choose_reset)
        editor.width_input.customContextMenuRequested.emit(QPoint(1, 1))
        self.assertEqual(editor.width_input.value(), 7.)
        self.assertEqual(editor.height_input.value(), 13.)
        self.assertEqual(d.candidate().oracle.custom_appearance.ear_body.width, 7.)

    def test_restore_default_appearance_keeps_trial_history_and_local_preferences(self):
        role = self.profiles.export(self.config, 'A')
        d = self.dialog(); self.select(d.profile_presets, role)
        d.controls['oracle.colors.skin'].setValue('#654321')
        d.controls['audio.volume'].setValue(17)
        d.preset_workflow.restore_defaults('appearance')
        self.assertEqual(d.candidate().audio.volume, .17)
        d.preset_workflow.restore_history(0)
        self.assertEqual(d.candidate().oracle.colors.skin, '#654321')

    def test_language_change_survives_later_autosave(self):
        d = self.dialog()
        language_manager().set_language('en')
        self.app.processEvents()
        d.controls['oracle.colors.skin'].setValue('#654321')
        self.assertTrue(d.preset_workflow.flush())
        self.assertEqual(self.store.load().ui.language, 'en')

    def test_missing_image_edit_can_be_fixed_without_crashing_settings(self):
        role = self.profiles.export(replace(self.config, oracle=replace(self.config.oracle,
            body_appearance='custom')), 'Custom')
        d = self.dialog()
        self.select(d.profile_presets, role)
        editor = d.face_editors['forehead']
        editor.setValue(replace(editor.value(), enabled=True, image_path=str(self.root/'missing.png')))
        self.assertFalse(d.preset_workflow.flush())
        editor.setValue(replace(editor.value(), enabled=False, image_path='', image_name=''))
        self.assertTrue(d.preset_workflow.flush())

    def test_import_dialog_browsing_cancel_and_confirm_preserve_character(self):
        role = self.profiles.export(self.config, 'Role')
        look = self.library.export(self.other, 'Look')
        d = self.dialog()
        self.select(d.profile_presets, role)
        before = d.candidate()
        dialog = AppearanceImportDialog(d.appearance_presets)
        self.dialogs.append(dialog)
        dialog.selector.setCurrentIndex(0)
        self.assertEqual(d.candidate(), before)
        self.assertEqual(d.preset_workflow.entry.history, [])
        dialog.reject()
        self.assertEqual(d.candidate(), before)
        dialog = AppearanceImportDialog(d.appearance_presets)
        self.dialogs.append(dialog)
        dialog.submit()
        self.assertEqual(dialog.result(), dialog.DialogCode.Accepted)
        self.assertEqual(d.profile_presets.loaded.id, role.id)
        self.assertEqual(d.candidate().oracle.colors.skin, '#123456')
        self.assertEqual(d.candidate().oracle.float_speed, before.oracle.float_speed)
        self.assertEqual(len(d.preset_workflow.entry.history), 1)
        self.assertEqual(look.path.read_bytes(), self.library.scan().presets[0].path.read_bytes())

    def test_create_character_always_uses_custom_template_and_selects_new_file(self):
        d = self.dialog()
        d.controls['oracle.colors.skin'].setValue('#abcdef')
        before = d.profile_presets.loaded.id
        created = d.preset_workflow.create_character('My character')
        self.assertNotEqual(created.id, before)
        self.assertEqual(created.appearance.oracle.body_appearance, 'custom')
        self.assertEqual(d.profile_presets.loaded.id, created.id)
        self.assertTrue(d.controls['oracle.body_appearance'].isHidden())
        self.assertEqual(d.candidate().oracle.outfit, 'normal')
        self.assertEqual(d.candidate().oracle.custom_colors.skin, '#c5c9cf')
        self.assertEqual(created.appearance.oracle.custom_colors.robe_top, '#f5f5f5')
        self.assertEqual(created.appearance.oracle.custom_colors.robe_bottom, '#c6cfdc')
        self.assertEqual(created.appearance.oracle.pearl_bubble_color, '#00ff00')
        shape = created.appearance.oracle.custom_appearance
        self.assertEqual(shape.head_length, 0.9414414414414414)
        self.assertEqual(shape.neckline_depth, 3.)
        self.assertFalse(shape.inner_robe_enabled)
        self.assertFalse(shape.inner_collar_enabled)
        d.controls['oracle.custom_colors.skin'].setValue('#123456')
        d.preset_workflow.restore_defaults('appearance')
        self.assertEqual(d.candidate().oracle.custom_colors.skin, created.appearance.oracle.custom_colors.skin)

    def test_empty_library_refresh_creates_and_selects_fallback_bell(self):
        d = self.dialog()
        for preset in self.profiles.scan().presets:
            preset.path.unlink()
        self.assertTrue(d.profile_presets.refresh())
        self.assertEqual(d.profile_presets.loaded.id, BELL_PROFILE_ID)
        self.assertIsNotNone(d.profile_presets.selector.currentData())

    def test_save_dialog_failure_keeps_inputs_and_allows_retry(self):
        d=self.dialog(); dialog=PresetSaveDialog(d,(),None,'导出外观','我的外观'); self.dialogs.append(dialog)
        dialog.name.setText('保留这个名称'); dialog.on_save=lambda name,target:(False,'locked'); dialog.submit()
        self.assertEqual(dialog.selection,('保留这个名称',None)); self.assertEqual(dialog.error.text(),'locked')
        dialog.on_save=lambda name,target:(True,''); dialog.submit(); self.assertEqual(dialog.result(),dialog.DialogCode.Accepted)


if __name__ == '__main__':
    unittest.main()
