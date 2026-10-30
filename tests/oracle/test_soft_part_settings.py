"""柔性部件的设置、角色归属、图片副本、分享与默认值恢复"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QEvent, QPoint, Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication

from rw_creature_pet.config import AppConfig
from rw_creature_pet.i18n import language_manager
from rw_creature_pet.oracle.config import CustomAppearance, OracleConfig
from rw_creature_pet.oracle.assets import OracleAssets
from rw_creature_pet.oracle.graphics.face_assets import read_face_png
from rw_creature_pet.oracle.graphics.render import OracleRenderer
from rw_creature_pet.oracle.soft_part_config import SoftPart
from rw_creature_pet.oracle.ui.desktop import OracleDesktopWindow
from rw_creature_pet.oracle.ui.settings import OracleSettingsDialog
from rw_creature_pet.presets.library import AppearanceLibrary
from rw_creature_pet.presets.profile_library import ProfileLibrary
from rw_creature_pet.settings_store import SettingsStore
from tests.oracle.character_fixture import geometry_assets, isolate_characters


PREFIX = 'oracle.custom_appearance.soft_part_1'


class SoftPartSettingsTests(unittest.TestCase):
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
        shape = CustomAppearance(soft_part_1=SoftPart(enabled=True, offset_x=-3., width=6.12345,
                                                     softness=.712345, damping=.523456))
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

    def dialog(self, config=None):
        d = OracleSettingsDialog(config or self.config, self.store, assets=geometry_assets())
        self.dialogs.append(d)
        self.enterContext(patch.object(d, 'space_assessment', return_value=None))
        return d

    def png(self, name='围巾.png', color='#876543', width=24, height=128):
        source = self.root/name
        image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(QColor(color))
        image.save(str(source))
        return source

    def test_controls_dependencies_precision_resets_and_language(self):
        d = self.dialog()
        editor = d.soft_part_editors['soft_part_1']
        controls = editor.parameter_controls
        self.assertEqual(editor.value(), self.config.oracle.custom_appearance.soft_part_1)
        self.assertTrue(all(c.property('default_reset_bound') for c in controls.values()))
        controls['length'].setValue(40.)
        self.assertEqual(d.candidate().oracle.custom_appearance.soft_part_1.width, 6.12345)
        self.assertEqual(editor.value().softness, .712345)
        controls['kind'].setCurrentIndex(controls['kind'].findData('trapezoid'))
        self.assertTrue(controls['tip_width_ratio'].isEnabled())
        controls['tip_width_ratio'].setValue(65)
        self.assertEqual(editor.value().tip_width_ratio, .65)
        controls['layer'].setCurrentIndex(controls['layer'].findData('back'))
        d.preset_workflow.reset_parameter(PREFIX+'.length')
        self.assertEqual(editor.value().length, self.config.oracle.custom_appearance.soft_part_1.length)
        self.assertEqual(editor.value().layer, 'back')
        d.preset_workflow.reset_parameter(PREFIX)
        self.assertEqual(editor.value(), self.config.oracle.custom_appearance.soft_part_1)
        self.assertFalse(controls['tip_width_ratio'].isEnabled())
        editor.enabled.setChecked(False)
        self.assertFalse(controls['width'].isEnabled())
        language_manager().set_language('en')
        self.assertEqual(editor.enabled.text(), 'Enable soft part 1')
        self.assertEqual(controls['kind'].currentText(), 'Rectangle')
        self.assertEqual(controls['layer'].itemText(0), 'Behind puppet')
        language_manager().set_language('zh')
        self.assertEqual(editor.enabled.text(), '启用柔性部件 1')

    def test_switch_to_png_keeps_upload_controls_visible_and_rows_uncompressed(self):
        d = self.dialog()
        page = d.pages['appearance']
        d.tabs.setCurrentWidget(page)
        d.resize(960, 1040)
        d.show()
        first, second = d.soft_part_editors.values()

        def settle():
            QTest.qWait(120)
            page.verticalScrollBar().setValue(first.mapTo(page.widget(), QPoint()).y()-12)
            self.app.processEvents()

        def check_upload(editor):
            self.assertTrue(editor.png_panel.isVisible())
            self.assertFalse(editor.layout().isRowVisible(editor.dimensions_row))
            for field in ('width', 'length'):
                self.assertFalse(editor.parameter_controls[field].isVisible())
            self.assertGreaterEqual(editor.height(), editor.heightForWidth(editor.width()))
            self.assertTrue(editor.rect().contains(editor.png_panel.geometry()))
            self.assertGreaterEqual(editor.png_panel.height(), editor.png_panel.minimumSizeHint().height())
            self.assertGreaterEqual(editor.import_button.height(), editor.import_button.minimumSizeHint().height())
            self.assertLess(first.geometry().bottom(), second.geometry().top())
            self.assertEqual(page.horizontalScrollBar().maximum(), 0)

        settle()
        kind = first.parameter_controls['kind']
        for language, width in (('zh', 960), ('en', 720), ('zh', 960)):
            language_manager().set_language(language)
            d.resize(width, 1040)
            settle()
            for _ in range(2):
                kind.setCurrentIndex(kind.findData('png'))
                settle()
                check_upload(first)
                kind.setCurrentIndex(kind.findData('rectangle'))
                settle()
                self.assertTrue(first.png_panel.isHidden())
                self.assertTrue(first.layout().isRowVisible(first.dimensions_row))
        kind.setCurrentIndex(kind.findData('png'))
        settle()
        check_upload(first)
        # 点击实际显示的按钮，导入后错误说明消失时也要重新计算所需高度
        with patch('rw_creature_pet.oracle.ui.soft_part_editor.QFileDialog.getOpenFileName',
                   return_value=(str(self.png()), 'PNG (*.png)')) as browse:
            QTest.mouseClick(first.import_button, Qt.MouseButton.LeftButton)
            browse.assert_called_once()
        settle()
        check_upload(first)
        self.assertTrue(first.message.isHidden())
        self.assertTrue(first.value().image_path)
        self.assertEqual(first.value().width, self.config.oracle.custom_appearance.soft_part_1.width)
        self.assertEqual(first.value().length, self.config.oracle.custom_appearance.soft_part_1.length)
        second.enabled.setChecked(True)
        second.parameter_controls['kind'].setCurrentIndex(second.parameter_controls['kind'].findData('png'))
        settle()
        check_upload(second)
        # 布局收敛后不应继续调度刷新，避免设置窗口空闲时反复计算
        root = page.widget().layout()
        settle()
        refresh = QSignalSpy(root._reflow_timer.timeout)
        QTest.qWait(200)
        self.assertEqual(refresh.count(), 0)
        self.assertFalse(root._reflow_timer.isActive())

    def test_autosave_role_isolation_and_reopen_keep_share_defaults_read_only(self):
        d = self.dialog()
        initial = d.profile_presets.loaded
        original = initial.path.read_bytes()
        other_config = replace(self.config, oracle=replace(self.config.oracle, custom_appearance=CustomAppearance()))
        other = ProfileLibrary().export(other_config, '角色 B')
        editor = d.soft_part_editors['soft_part_1']
        with patch.object(self.store, 'save', wraps=self.store.save) as save:
            editor.parameter_controls['length'].setValue(48.)
            editor.parameter_controls['damping'].setValue(80.)
            QTest.qWait(800)
            self.assertEqual(save.call_count, 1)
        self.assertEqual(self.store.load().oracle.custom_appearance.soft_part_1.length, 48.)
        self.assertEqual(initial.path.read_bytes(), original)
        d.preset_workflow.activate('profile', other)
        self.assertEqual(editor.value(), CustomAppearance().soft_part_1)
        editor.enabled.setChecked(True)
        editor.parameter_controls['length'].setValue(22.)
        self.assertTrue(d.preset_workflow.flush())
        d.preset_workflow.activate('profile', initial)
        self.assertEqual(editor.value().length, 48.)
        self.assertEqual(editor.value().damping, .8)
        d.reject()
        reopened = self.dialog(self.store.load())
        self.assertEqual(reopened.soft_part_editors['soft_part_1'].value().length, 48.)
        reopened.preset_workflow.reset_parameter(PREFIX+'.length')
        self.assertEqual(reopened.soft_part_editors['soft_part_1'].value().length, 28.)
        self.assertEqual(reopened.soft_part_editors['soft_part_1'].value().damping, .8)
        reopened.preset_workflow.activate('profile', other)
        self.assertEqual(reopened.soft_part_editors['soft_part_1'].value().length, 22.)
        bell = ProfileLibrary().export(replace(self.config, oracle=replace(self.config.oracle, body_appearance='bell')), 'Bell')
        reopened.preset_workflow.activate('profile', bell)
        self.assertTrue(reopened.custom_parameters.isHidden())

    def test_manual_save_and_discard_do_not_overwrite_last_saved_parts(self):
        d = self.dialog()
        d.personal_controls.autosave.setChecked(False)
        editor = d.soft_part_editors['soft_part_1']
        editor.parameter_controls['length'].setValue(51.)
        d.personal_controls.save.click()
        self.assertEqual(self.store.load().oracle.custom_appearance.soft_part_1.length, 51.)
        editor.parameter_controls['length'].setValue(63.)
        d.reject()
        again = self.dialog(self.store.load())
        self.assertEqual(again.soft_part_editors['soft_part_1'].value().length, 51.)
        self.assertFalse(again.personal_controls.autosave.isChecked())

    def test_png_export_import_and_appearance_history_carry_both_slots(self):
        d = self.dialog()
        first, second = d.soft_part_editors.values()
        sources = [self.png(), self.png('另一条.png', '#123456')]
        self.assertTrue(first.import_file(sources[0]))
        self.assertTrue(second.import_file(sources[1]))
        first.parameter_controls['width'].setValue(9.5)
        second.parameter_controls['layer'].setCurrentIndex(0)
        second.enabled.setChecked(False)  # 已关闭部件的参数及图片也应保留
        self.assertTrue(d.preset_workflow.flush())
        expected = first.value(), second.value()
        for source in sources:
            source.unlink()
        look = d.appearance_presets.export_current('柔性外观')
        role = d.profile_presets.export_current('柔性角色', destination=self.root/'soft-role.zip')
        self.assertIsNotNone(look)
        self.assertIsNotNone(role)
        self.assertTrue(look.oracle.custom_appearance.soft_part_1.image_path.startswith('images/'))
        self.assertFalse(look.oracle.custom_appearance.soft_part_2.enabled)
        # 经接收方角色库复制一份，实际面板导入入口再读入
        imported_role = ProfileLibrary(self.root/'received-roles').import_file(role)
        imported_look = AppearanceLibrary(self.root/'received-looks').import_file(look.path)
        empty = ProfileLibrary().export(replace(self.config, oracle=replace(self.config.oracle,
                         custom_appearance=CustomAppearance())), '无附件')
        d.preset_workflow.activate('profile', empty)
        self.assertTrue(d.appearance_presets.import_file(imported_look.path))
        self.assertEqual(d.profile_presets.loaded.id, empty.id)
        self.assertEqual(first.value().width, expected[0].width)
        self.assertEqual(second.value().layer, 'back')
        self.assertFalse(second.value().enabled)
        for editor, old in zip((first, second), expected):
            self.assertEqual(read_face_png(editor.value().image_path, 128).height(), 128)
            self.assertEqual(replace(editor.value(), image_path=old.image_path), old)
        d.preset_workflow.restore_history(0)
        self.assertFalse(first.value().enabled)
        d.preset_workflow.restore_history(0)
        self.assertEqual(first.value().width, 9.5)
        self.assertTrue(d.profile_presets.import_file(imported_role.path, conflict='replace'))
        first.parameter_controls['length'].setValue(55.)
        self.assertTrue(d.preset_workflow.flush())
        d.preset_workflow.restore_defaults('appearance')
        self.assertEqual(first.value().length, expected[0].length)
        original = (d.profile_presets.loaded.path.parent/'original/profile.json').read_bytes()
        updated = d.profile_presets.export_current('柔性角色', destination=self.root/'soft-role-new.zip')
        self.assertIsNotNone(updated)
        self.assertTrue(updated.is_file())
        self.assertEqual((d.profile_presets.loaded.path.parent/'original/profile.json').read_bytes(), original)

    def test_invalid_png_or_failed_save_preserves_selection_and_draft(self):
        d = self.dialog()
        editor = d.soft_part_editors['soft_part_1']
        self.assertTrue(editor.import_file(self.png()))
        self.assertTrue(d.preset_workflow.flush())
        good = editor.value()
        self.assertFalse(editor.import_file(self.png('oversize.png', width=129)))
        self.assertEqual(editor.value(), good)
        self.assertFalse(editor.message.isHidden())
        editor.clear_button.click()
        self.assertFalse(editor.value().enabled)
        self.assertTrue(d.preset_workflow.flush())
        saved = self.store.path.read_bytes()
        editor.enabled.setChecked(True)
        self.assertFalse(d.preset_workflow.flush())
        self.assertEqual(self.store.path.read_bytes(), saved)
        self.assertTrue(d.preset_workflow.dirty)
        with self.assertRaises(ValueError):
            d.candidate()
        self.assertIsNone(d.appearance_presets.export_current('无图片'))
        self.assertTrue(editor.import_file(self.png('valid.png')))
        source = editor.value()
        with patch.object(self.store, 'save', side_effect=OSError('test disk error')):
            self.assertFalse(d.preset_workflow.flush())
        self.assertEqual(editor.value(), source)
        self.assertEqual(self.store.path.read_bytes(), saved)
        self.assertTrue(d.preset_workflow.flush())

    def test_old_cached_characters_do_not_borrow_new_slot_fields(self):
        d = self.dialog()
        initial = d.profile_presets.loaded
        other = ProfileLibrary().export(replace(self.config, oracle=replace(self.config.oracle,
            custom_appearance=CustomAppearance())), '旧角色')
        d.preset_workflow.activate('profile', other)
        d.preset_workflow.activate('profile', initial)
        d.reject()
        data = self.store.read_document()
        for entry in data['preset_state']['entries'].values():
            for group in ('defaults', 'overrides'):
                entry[group] = {k: v for k, v in entry[group].items() if '.soft_part_' not in k}
        self.store._write(data)
        again = self.dialog(self.store.load())
        editor = again.soft_part_editors['soft_part_1']
        self.assertFalse(editor.value().enabled)
        editor.enabled.setChecked(True)
        editor.parameter_controls['length'].setValue(60.)
        self.assertTrue(again.preset_workflow.flush())
        again.preset_workflow.activate('profile', other)
        self.assertEqual(editor.value(), CustomAppearance().soft_part_1)
        again.preset_workflow.activate('profile', initial)
        self.assertEqual(editor.value().length, 60.)
        self.assertTrue(editor.value().enabled)

    def test_settings_commit_updates_running_parts_without_resetting_puppet(self):
        assets = OracleAssets(OracleRenderer(), '', {}, '')
        with patch('rw_creature_pet.oracle.ui.desktop.QSystemTrayIcon.isSystemTrayAvailable', return_value=True):
            window = OracleDesktopWindow(self.config, config_store=self.store, assets=assets)
        window.timer.stop()
        try:
            scene = window.motion.scene
            body = scene.body
            position = body.chunks[0].position
            d = OracleSettingsDialog(self.config, self.store, assets=assets, commit=window.apply_settings)
            self.dialogs.append(d)
            self.enterContext(patch.object(d, 'space_assessment', return_value=None))
            editor = d.soft_part_editors['soft_part_1']
            self.assertTrue(editor.import_file(self.png()))
            editor.parameter_controls['length'].setValue(52.)
            editor.parameter_controls['layer'].setCurrentIndex(0)
            window.set_paused(True)
            self.assertTrue(d.preset_workflow.flush())
            self.assertIs(window.motion.scene, scene)
            self.assertIs(scene.body, body)
            self.assertEqual(body.chunks[0].position, position)
            self.assertEqual(scene.soft_parts.parts[0].config, editor.value())
            self.assertEqual((scene.soft_parts.parts[0].width, scene.soft_parts.parts[0].length), (24., 128.))
            self.assertEqual(self.store.load().oracle.custom_appearance.soft_part_1, editor.value())
            editor.enabled.setChecked(False)
            self.assertTrue(d.preset_workflow.flush())
            self.assertIsNone(scene.soft_parts.parts[0])
            self.assertTrue(window.clock.paused)
            d.preset_workflow.timer.stop()
        finally:
            window.close()
            window.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


if __name__ == '__main__':
    unittest.main()
