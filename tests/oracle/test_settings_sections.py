"""小节边界、默认折叠、动态子项和设置窗口的保存边界"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QEvent, QPoint, Qt
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication, QLabel, QSpinBox, QWidget

from rw_creature_pet.config import AppConfig
from rw_creature_pet.i18n import language_manager
from rw_creature_pet.oracle.config import OracleConfig
from rw_creature_pet.oracle.ui.sections import CollapsibleSection
from rw_creature_pet.oracle.ui.settings import OracleSettingsDialog, _ParameterForm, _ParameterRow
from rw_creature_pet.oracle.ui.form_layout import ContentForm
from rw_creature_pet.oracle.ui.settings_style import PixelRuleThin, apply_settings_style
from rw_creature_pet.settings_store import SettingsStore
from tests.oracle.character_fixture import isolate_characters


class SettingsSectionTests(unittest.TestCase):
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
        self.config = AppConfig(game_dir=game, oracle=OracleConfig(body_appearance='custom'))
        self.store = SettingsStore(self.root/'settings.json')
        self.widgets = []

    def tearDown(self):
        for widget in self.widgets:
            if isinstance(widget, OracleSettingsDialog):
                widget.shutdown()
            widget.close()
            widget.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()
        language_manager().set_language('zh')

    def dialog(self):
        d = OracleSettingsDialog(self.config, self.store, assets=object())
        self.widgets.append(d)
        self.enterContext(patch.object(d, 'space_assessment', return_value=None))
        d.resize(960, 1000)
        d.show()
        self.app.processEvents()
        return d

    @staticmethod
    def section(root, title):
        return next(s for s in root.findChildren(CollapsibleSection) if s.heading.text() == title)

    def settle_layout(self, root):
        spies = [QSignalSpy(form._reflow_timer.timeout) for form in root.findChildren(ContentForm)]
        previous, quiet = -1, 0
        for _ in range(50):
            QTest.qWait(10)
            count = sum(spy.count() for spy in spies)
            quiet = quiet + 1 if count == previous else 0
            previous = count
            if quiet >= 3 and not any(form._reflow_timer.isActive() for form in root.findChildren(ContentForm)):
                break
        # 刷新必须收敛，窗口静置不能不断触发布局定时器
        self.assertFalse(any(form._reflow_timer.isActive() for form in root.findChildren(ContentForm)))
        self.assertGreaterEqual(quiet, 3)

    def assert_readable_rows(self, root):
        for row in root.findChildren(_ParameterRow):
            if not row.isVisible():
                continue
            expected = row.heightForWidth(row.width())
            if expected < 0:
                expected = row.sizeHint().height()
            self.assertGreaterEqual(row.height(), expected)
            self.assertLessEqual(row.height(), expected + 1)
            for label in row.findChildren(QLabel):
                if not label.isVisible():
                    continue
                self.assertGreaterEqual(label.height() + 1, label.heightForWidth(label.width()), label.text())
                control = label.buddy()
                if control is not None:
                    self.assertLess(label.geometry().right(), control.geometry().left())
                    self.assertGreaterEqual(control.height(), control.minimumSizeHint().height())

    def test_repeated_folding_preserves_content_heights_and_row_spacing(self):
        d = self.dialog()
        page = d.pages['behavior']
        d.tabs.setCurrentWidget(page)
        sections = page.findChildren(CollapsibleSection)
        for language in ('zh', 'en'):
            language_manager().set_language(language)
            for width in (800, 960):
                with self.subTest(language=language, width=width):
                    d.resize(width, 760)
                    self.settle_layout(d)
                    for index in (0, 0, 1, 0, 1, 2, 3, 2, 3, 0):
                        sections[index].heading.click()
                        self.settle_layout(d)
                        for section in sections:
                            expected = (section.heightForWidth(section.width()) if section.heading.isChecked()
                                        else section.heading.height())
                            self.assertEqual(section.height(), expected, section.heading.text())
                        for first, second in zip(sections, sections[1:]):
                            self.assertLess(first.geometry().bottom(), second.y())
                        self.assert_readable_rows(page)
                        self.assertFalse(page.horizontalScrollBar().maximum())

    def test_extra_height_stays_below_content_and_dynamic_rows_reflow(self):
        panel = QWidget()
        self.widgets.append(panel)
        form = _ParameterForm(panel)
        form.setVerticalSpacing(20)
        first = form.add_section('First')
        form.addRow('Value', QSpinBox())
        second = form.add_section('Second')
        form.addRow('Value', QSpinBox())
        apply_settings_style(panel)
        panel.resize(800, 450)
        panel.show()
        self.settle_layout(panel)
        baseline = [s.geometry().getRect() for s in (first, second)]
        panel.resize(800, 900)
        self.settle_layout(panel)
        self.assertEqual([s.geometry().getRect() for s in (first, second)], baseline)
        self.assertLess(second.geometry().bottom(), panel.height() // 2)
        # 运行中增加、移除行和更改文本都由公共布局捕获，无需调用刷新方法
        form.addRow('Added value', QSpinBox())
        self.settle_layout(panel)
        self.assertGreater(second.height(), baseline[1][3])
        second.body.removeRow(second.body.rowCount() - 1)
        self.settle_layout(panel)
        self.assertEqual(second.geometry().getRect(), baseline[1])
        note = QLabel('Short note')
        note.setWordWrap(True)
        second.body.addRow(note)
        self.settle_layout(panel)
        short_height = second.height()
        note.setText('A longer explanation that needs wrapping ' * 15)
        self.settle_layout(panel)
        self.assertGreater(second.height(), short_height)
        first.set_expanded(False)
        self.settle_layout(panel)
        self.assertLess(second.y(), baseline[1][1])
        self.assert_readable_rows(panel)

    def test_refreshes_are_coalesced_and_stop_when_idle(self):
        class CountingForm(_ParameterForm):
            reflows = 0

            def _reflow(self):
                self.reflows += 1
                super()._reflow()

        panel = QWidget()
        self.widgets.append(panel)
        form = CountingForm(panel)
        section = form.add_section('Section')
        form.addRow('Value', QSpinBox())
        panel.resize(800, 450)
        panel.show()
        self.settle_layout(panel)
        before = form.reflows
        timer_ids = set()
        for _ in range(20):
            section.body.invalidate()
            timer_ids.add(form._reflow_timer.timerId())
        self.assertEqual(form.reflows, before)
        self.assertEqual(len(timer_ids), 1)
        self.settle_layout(panel)
        # Qt 的激活通知可追加一次无变化检查，但不能逐次重排或在静置时循环
        self.assertGreater(form.reflows, before)
        self.assertLessEqual(form.reflows - before, 2)
        settled = form.reflows
        QTest.qWait(80)
        self.assertEqual(form.reflows, settled)

    def test_shared_rows_remain_readable_across_tabs_languages_and_widths(self):
        d = self.dialog()
        for language, width in (('zh', 960), ('en', 800), ('zh', 800)):
            language_manager().set_language(language)
            d.resize(width, 760)
            for name, page in d.pages.items():
                with self.subTest(language=language, width=width, page=name):
                    d.tabs.setCurrentWidget(page)
                    self.settle_layout(d)
                    self.assertFalse(page.horizontalScrollBar().maximum())
                    self.assert_readable_rows(page)
                    for button in (d.apply_button, d.save_button):
                        self.assertTrue(d.rect().contains(button.mapTo(d, button.rect().bottomRight())))

    def test_boundaries_default_state_and_click_hide_only_own_content(self):
        panel = QWidget()
        self.widgets.append(panel)
        form = _ParameterForm(panel)
        form.setVerticalSpacing(20)
        before, outside = QLabel('Before'), QLabel('Outside')
        form.addRow(before)
        first = OracleSettingsDialog.section_heading(form, 'First', default_collapsed=True)
        value = QSpinBox()
        form.addRow('Value', value)
        second = OracleSettingsDialog.section_heading(form, 'Second')
        second_value = QLabel('Second value')
        form.addRow(second_value)
        rule = PixelRuleThin()
        form.addRow(rule)
        form.addRow(outside)
        last = OracleSettingsDialog.section_heading(form, 'Last')
        last_value = QLabel('Last value')
        form.addRow(last_value)
        apply_settings_style(panel)
        panel.resize(600, 600)
        panel.show()
        self.app.processEvents()
        self.assertTrue(first.isAncestorOf(value))
        self.assertFalse(first.isAncestorOf(second_value))
        self.assertFalse(second.isAncestorOf(outside))
        self.assertFalse(second.isAncestorOf(rule))
        self.assertTrue(last.isAncestorOf(last_value))
        self.assertFalse(value.isVisible())
        self.assertEqual(first.height(), first.heading.height())
        QTest.mouseClick(first.heading, Qt.MouseButton.LeftButton)
        self.app.processEvents()
        self.assertTrue(value.isVisible())
        QTest.mouseClick(first.heading, Qt.MouseButton.LeftButton)
        self.app.processEvents()
        self.assertTrue(before.isVisible() and outside.isVisible() and second_value.isVisible())
        self.assertEqual(first.height(), first.heading.height())
        self.assertFalse(value.isVisible())
        self.assertGreater(second.height(), second.heading.height())

    def test_folding_does_not_write_or_change_drafts_and_reopen_resets(self):
        d = self.dialog()
        page = d.pages['behavior']
        d.tabs.setCurrentWidget(page)
        first = self.section(page, '移动与漫游')
        second = self.section(page, '鼠标观察与避让')
        expected = d.profile_draft()
        with patch.object(self.store, 'save', wraps=self.store.save) as save:
            first.heading.click()
            second.heading.click()
            QTest.qWait(800)
            save.assert_not_called()
        self.assertEqual(d.profile_draft(), expected)
        self.assertFalse(first.heading.isChecked())
        self.assertFalse(second.heading.isChecked())
        # 模拟同一个窗口实例再次打开，也使用各小节声明的默认状态
        second.default_collapsed = True
        d.reject()
        d.show()
        self.app.processEvents()
        self.assertTrue(first.heading.isChecked())
        self.assertFalse(second.heading.isChecked())
        again = self.dialog()
        self.assertTrue(all(s.heading.isChecked() for s in again.pages['behavior'].findChildren(CollapsibleSection)))

    def test_dynamic_children_remain_hidden_inside_collapsed_sections(self):
        d = self.dialog()
        page = d.pages['appearance']
        d.tabs.setCurrentWidget(page)
        d.personal_controls.autosave.setChecked(False)
        outfit = self.section(page, '附加外观')
        colors = self.section(d.custom_parameters, '配色')
        outfit.heading.click()
        d.controls['oracle.outfit'].setValue('maid')
        self.app.processEvents()
        self.assertFalse(d.outfit_parameter_panels['maid'].isVisible())
        self.assertTrue(colors.heading.isVisible())
        outfit.heading.click()
        self.app.processEvents()
        self.assertTrue(d.outfit_parameter_panels['maid'].isVisible())
        d.controls['oracle.outfit'].setValue('normal')
        outfit.heading.click()
        outfit.heading.click()
        self.assertTrue(d.outfit_parameter_panels['maid'].isHidden())
        soft = self.section(page, '柔性部件')
        soft.set_expanded(False)
        editor = d.soft_part_editors['soft_part_1']
        kind = editor.parameter_controls['kind']
        kind.setCurrentIndex(kind.findData('png'))
        self.assertFalse(editor.png_panel.isVisible())
        soft.set_expanded(True)
        self.app.processEvents()
        self.assertTrue(editor.png_panel.isVisible())
        self.assertFalse(editor.parameter_controls['width'].isVisible())
        self.assertFalse(editor.parameter_controls['length'].isVisible())
        # 切 Bell/自定义分支不改变折叠状态，也不把预览按钮收入眼睛组
        colors.set_expanded(False)
        d.controls['oracle.body_appearance'].setValue('bell')
        self.assertTrue(d.custom_parameters.isHidden())
        d.controls['oracle.body_appearance'].setValue('custom')
        self.assertFalse(colors.heading.isChecked())
        self.assertTrue(colors.content.isHidden())

    def test_translation_layout_and_editing_while_sections_are_collapsed(self):
        d = self.dialog()
        d.personal_controls.autosave.setChecked(False)
        page = d.pages['appearance']
        d.tabs.setCurrentWidget(page)
        sections = page.findChildren(CollapsibleSection)
        before = page.verticalScrollBar().maximum()
        for section in sections:
            section.set_expanded(False)
        for _ in range(4):
            self.app.processEvents()
        self.assertLess(page.verticalScrollBar().maximum(), before)
        self.assertFalse(page.horizontalScrollBar().maximum())
        shape = self.section(page, '基础体型')
        control = d.controls['oracle.custom_appearance.neck_width']
        control.setValue(5.)
        self.assertEqual(d.candidate().oracle.custom_appearance.neck_width, 5.)
        for language, width in (('en', 800), ('zh', 960)):
            language_manager().set_language(language)
            d.resize(width, 1000)
            for _ in range(4):
                self.app.processEvents()
            self.assertFalse(page.horizontalScrollBar().maximum())
            self.assertFalse(shape.heading.isChecked())
            self.assertFalse(control.isVisible())
            for section in sections:
                if section.isVisible():
                    self.assertEqual(section.height(), section.heading.height())
        shape.set_expanded(True)
        self.app.processEvents()
        self.assertTrue(control.isVisible())
        self.assertEqual(control.value(), 5.)
        head = d.controls['oracle.custom_appearance.head_length']
        self.assertEqual(control.mapTo(page.widget(), QPoint()).y(), head.mapTo(page.widget(), QPoint()).y())


if __name__ == '__main__':
    unittest.main()
