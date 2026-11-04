"""范围编辑的真实字段、角色保存、资源提示及单框布局"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from math import ceil
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPalette, QWheelEvent
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication, QLabel

from rw_creature_pet.config import AppConfig
from rw_creature_pet.i18n import language_manager
from rw_creature_pet.oracle.ui.form_layout import ContentForm
from rw_creature_pet.oracle.ui.number_range import NumberRange
from rw_creature_pet.oracle.ui.sections import CollapsibleSection
from rw_creature_pet.oracle.ui.settings import OracleSettingsDialog, _ParameterRow
from rw_creature_pet.oracle.ui.settings_style import INK, OUTLINE_WIDTH_PX, PAPER
from rw_creature_pet.presets.common import get_value
from rw_creature_pet.presets.profile import profile_mapping
from rw_creature_pet.settings_store import SettingsStore
from tests.oracle.character_fixture import geometry_assets, isolate_characters


class BehaviorRangeTests(unittest.TestCase):
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
        self.store = SettingsStore(self.root/'settings.json')
        self.d = OracleSettingsDialog(AppConfig(game_dir=game), self.store, assets=geometry_assets())
        self.d.preset_workflow.set_autosave(False)
        self.enterContext(patch.object(self.d, 'space_assessment', return_value=None))

    def tearDown(self):
        self.d.shutdown()
        self.d.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()
        language_manager().set_language('zh')

    def settle(self):
        forms = self.d.findChildren(ContentForm)
        spies = [QSignalSpy(form._reflow_timer.timeout) for form in forms]
        previous, quiet = -1, 0
        for _ in range(40):
            QTest.qWait(10)
            count = sum(spy.count() for spy in spies)
            quiet = quiet + 1 if count == previous else 0
            previous = count
            # 字体变化会延后投递布局请求，需确认连续安静而非只看当前计时器
            if quiet >= 3 and not any(f._reflow_timer.isActive() for f in forms):
                return
        self.fail('范围输入框重排未收敛')

    def pair(self, path):
        low = self.d.controls[path]
        field = low.parentWidget()
        self.assertIsInstance(field, NumberRange)
        return field, field.minimum_input, field.maximum_input

    def choose(self, dimension, identifier):
        selector = self.d.behavior_styles.groups[dimension].selector
        selector.setCurrentIndex(selector.findData(identifier))
        selector.activated.emit(selector.currentIndex())

    def test_all_behavior_ranges_use_one_frame_and_keep_existing_leaf_values(self):
        d = self.d
        page = d.pages['behavior']
        fields = page.findChildren(NumberRange)
        self.assertEqual(len(fields), 39)
        for group in d.behavior_styles.groups.values():
            self.assertTrue(group.content.autoFillBackground())
            self.assertEqual(group.content.palette().color(QPalette.ColorRole.Window), QColor('#d5d5d5'))
            self.assertEqual(group.body.contentsMargins().left(), 12)
        paths = {widget: path for path, widget in d.controls.items()}
        for field in fields:
            low, high = field.minimum_input, field.maximum_input
            low_path, high_path = paths[low], paths[high]
            expected_high = low_path.replace('_min_', '_max_') if '_min_' in low_path else low_path[:-4]+'_max'
            self.assertEqual(high_path, expected_high)
            self.assertFalse(low.hasFrame())
            self.assertFalse(high.hasFrame())
            self.assertAlmostEqual(get_value(d.candidate(), low_path), get_value(d.original, low_path))
            self.assertAlmostEqual(get_value(d.candidate(), high_path), get_value(d.original, high_path))
            self.assertEqual(low.decimals(), high.decimals())
            self.assertEqual(low.suffix(), high.suffix())
            self.assertTrue(low.property('default_reset_bound'))
            self.assertTrue(high.property('default_reset_bound'))
        for path in ('oracle.mouse_avoidance.enter_distance', 'oracle.mouse_avoidance.exit_distance',
                     'oracle.reading.observe_distance', 'oracle.reading.recall_distance'):
            self.assertNotIsInstance(d.controls[path].parentWidget(), NumberRange)
        self.assertEqual(profile_mapping(d.candidate()), profile_mapping(d.original))

    def test_edit_validation_style_and_save_still_use_each_original_parameter(self):
        d = self.d
        style = d.behavior_styles.library.for_dimension('daily_activity')[0]
        self.choose('daily_activity', style.id)
        field, low, high = self.pair('oracle.daily_activity.meditate_min_seconds')
        high.setValue(90.)
        low.setValue(45.)
        self.assertFalse(d.candidate().oracle.behavior_styles.daily_activity.id)
        self.assertEqual((d.candidate().oracle.daily_activity.meditate_min_seconds,
                          d.candidate().oracle.daily_activity.meditate_max_seconds), (45., 90.))
        self.assertTrue(d.preset_workflow.flush())
        self.assertEqual(self.store.load().oracle.daily_activity, d.candidate().oracle.daily_activity)
        before_high = high.value()
        d.preset_workflow.reset_parameter('oracle.daily_activity.meditate_min_seconds')
        self.assertEqual(low.value(), 30.)
        self.assertEqual(high.value(), before_high)
        low.setValue(120.)  # 保留原校验：无效草稿不静默挪动另一端
        self.assertEqual(high.value(), before_high)
        with self.assertRaises(ValueError):
            d.candidate()
        self.choose('daily_activity', style.id)
        self.assertEqual(profile_mapping(d.candidate())['oracle']['daily_activity'],
                         profile_mapping(style.apply(d.original))['oracle']['daily_activity'])
        _, low, high = self.pair('oracle.drag_reactions.gesture_min_amplitude')
        low.setValue(12.5)
        high.setValue(87.5)
        self.assertEqual(d.candidate().oracle.drag_reactions.gesture_min_amplitude, .125)
        self.assertEqual(d.candidate().oracle.drag_reactions.gesture_max_amplitude, .875)
        _, low, high = self.pair('oracle.drag_reactions.gesture_interval_min_seconds')
        low.setValue(.025)
        self.assertEqual(d.candidate().oracle.drag_reactions.gesture_interval_min_seconds, .025)

    def test_resource_disable_marks_shared_label_once_and_restores_values(self):
        d = self.d
        field, low, high = self.pair('oracle.drag_reactions.voice_delay_min_seconds')
        labels = [w for w in d.form.findChildren(QLabel) if w.buddy() is field]
        self.assertEqual(len(labels), 1)
        label = labels[0]
        before = d.candidate().oracle
        d.assets.resources.record('bell_voice', error='missing')
        d.resource_settings.install(d.assets)
        self.assertFalse(low.isEnabled())
        self.assertFalse(high.isEnabled())
        self.assertFalse(field.separator.isEnabled())
        self.assertEqual(label.text().count('不可用'), 1)
        self.assertEqual(d.candidate().oracle, before)
        d.resource_settings.install(geometry_assets())
        self.assertTrue(low.isEnabled())
        self.assertTrue(high.isEnabled())
        self.assertTrue(field.separator.isEnabled())
        self.assertEqual(label.text(), '首次语音延迟')
        self.assertEqual(d.candidate().oracle, before)

    def test_language_width_and_folding_preserve_ranges_and_content_geometry(self):
        d = self.d
        page = d.pages['behavior']
        d.tabs.setCurrentWidget(page)
        for group in d.behavior_styles.groups.values():
            group.advanced.setChecked(True)
        before = profile_mapping(d.candidate())
        d.show()
        for language, width in (('zh', 800), ('en', 800), ('zh', 960)):
            language_manager().set_language(language)
            d.resize(width, 900)
            self.settle()
            self.assertEqual(page.horizontalScrollBar().maximum(), 0)
            for row in page.findChildren(_ParameterRow):
                if not row.isVisible():
                    continue
                left, right = (row.layout().itemAt(i).widget() for i in range(2))
                self.assertLessEqual(abs(left.width()-right.width()), 1)
                for label in row.findChildren(QLabel):
                    self.assertGreaterEqual(label.height()+1, label.heightForWidth(label.width()), label.text())
                    if control := label.buddy():
                        self.assertLess(label.geometry().right(), control.x(), label.text())
            for field in page.findChildren(NumberRange):
                row = field.parentWidget().parentWidget()
                self.assertIsInstance(row, _ParameterRow)
                self.assertLessEqual(field.width(), row.width()//2)
                low, high = field.minimum_input, field.maximum_input
                self.assertEqual(field.separator.text(), 'to' if language == 'en' else '至')
                self.assertLess(low.geometry().right(), field.separator.x())
                self.assertLess(field.separator.geometry().right(), high.x())
                self.assertLessEqual(high.geometry().right(), field.width()-2)
                self.assertGreaterEqual(low.lineEdit().width(), low.fontMetrics().horizontalAdvance(low.text())-1)
                self.assertGreaterEqual(high.lineEdit().width(), high.fontMetrics().horizontalAdvance(high.text())-1)
            sections = page.findChildren(CollapsibleSection)
            baseline = [field.geometry().getRect() for field in page.findChildren(NumberRange)]
            sections[0].set_expanded(False)
            self.settle()
            sections[0].set_expanded(True)
            self.settle()
            self.assertEqual([field.geometry().getRect() for field in page.findChildren(NumberRange)], baseline)
            self.assertEqual(profile_mapping(d.candidate()), before)
            # 缺失资源会加长标签，嵌套双列仍须重新计算行高
            d.assets.resources.record('bell_voice', error='missing')
            d.resource_settings.install(d.assets)
            self.settle()
            for label in d.behavior_styles.groups['drag_reactions'].content.findChildren(QLabel):
                self.assertGreaterEqual(label.height()+1, label.heightForWidth(label.width()), label.text())
            d.assets.resources.record('bell_voice', available=True)
            d.resource_settings.install(d.assets)
            self.settle()

    def test_one_continuous_border_at_fractional_dpi_and_endpoint_editing(self):
        d = self.d
        page = d.pages['behavior']
        d.tabs.setCurrentWidget(page)
        d.behavior_styles.groups['daily_activity'].advanced.setChecked(True)
        d.show()
        self.settle()
        field, low, high = self.pair('oracle.daily_activity.meditate_min_seconds')
        for density in (1., 1.25, 1.5, 2.):
            image = QImage(ceil(field.width()*density), ceil(field.height()*density),
                           QImage.Format.Format_ARGB32_Premultiplied)
            image.setDevicePixelRatio(density)
            image.fill(PAPER)
            painter = QPainter(image)
            try:
                field.render(painter, field.rect().topLeft())
            finally:
                painter.end()
            # 两个数字框接缝处也只有上下两条共同外边框，无各自的内框竖边
            x = round((low.geometry().right()+1)*density)
            self.assertEqual(sum(image.pixelColor(x, y) == INK for y in range(image.height())),
                             2*OUTLINE_WIDTH_PX)
        d.activateWindow()
        low.setFocus()
        self.app.processEvents()
        low.lineEdit().selectAll()
        QTest.keyClicks(low.lineEdit(), '42.5')
        QTest.keyClick(low.lineEdit(), Qt.Key.Key_Tab)
        self.assertEqual(low.value(), 42.5)
        self.assertEqual(high.value(), 60.)
        for control in (low, high):
            before = control.value()
            spy = QSignalSpy(control.valueChanged)
            event = QWheelEvent(QPointF(control.rect().center()), QPointF(control.mapToGlobal(control.rect().center())),
                QPoint(), QPoint(0, -120), Qt.MouseButton.NoButton,
                Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
            QCoreApplication.sendEvent(control, event)
            self.assertEqual(spy.count(), 0)
            self.assertEqual(control.value(), before)


if __name__ == '__main__':
    unittest.main()
