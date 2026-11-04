"""比例联动、旧数据无损读取、原子提交及真实鼠标编辑"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from dataclasses import replace
from pathlib import Path
import random
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QEvent, QPoint, Qt
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication

from rw_creature_pet.config import AppConfig
from rw_creature_pet.i18n import language_manager
from rw_creature_pet.oracle.ui.proportion_slider import shares, redistribute
from rw_creature_pet.oracle.ui.form_layout import ContentForm
from rw_creature_pet.oracle.ui.settings import OracleSettingsDialog
from rw_creature_pet.presets.profile import profile_mapping
from rw_creature_pet.settings_store import SettingsStore
from tests.oracle.character_fixture import geometry_assets, isolate_characters

DAILY = 'oracle.daily_activity.idle_weight'
BOUT = 'oracle.drift.long_bout_probability'
HANDS = 'oracle.drag_reactions.flutter_probability'
PEARLS = 'oracle.reading.matrix_probability'
METHODS = 'oracle.reading.approach_weight'


class ShareCalculationTests(unittest.TestCase):
    def test_rounding_extremes_and_proportional_redistribution(self):
        self.assertEqual(shares((28, 12, 35)), [373, 160, 467])
        self.assertEqual(redistribute([200, 300, 500], 0, 400), [400, 225, 375])
        self.assertEqual(redistribute([1000, 0, 0], 0, 500), [500, 250, 250])
        self.assertEqual(redistribute([200, 300, 500], 1, 1000), [0, 1000, 0])
        self.assertEqual(shares([1, 1, 1]), [334, 333, 333])
        rng = random.Random(12)
        values = [334, 333, 333]
        for _ in range(500):
            values = redistribute(values, rng.randrange(3), rng.randrange(1001))
            self.assertEqual(sum(values), 1000)
            self.assertTrue(all(0 <= value <= 1000 for value in values))


class BehaviorProportionTests(unittest.TestCase):
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
        self.config = AppConfig(game_dir=game)
        self.store = SettingsStore(self.root/'settings.json')
        self.d = None

    def open(self, config=None):
        self.d = OracleSettingsDialog(config or self.config, self.store, assets=geometry_assets())
        self.d.preset_workflow.set_autosave(False)
        self.enterContext(patch.object(self.d, 'space_assessment', return_value=None))
        return self.d

    def tearDown(self):
        if self.d:
            self.d.shutdown()
            self.d.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()
        language_manager().set_language('zh')

    def show_group(self, dimension):
        self.d.tabs.setCurrentWidget(self.d.pages['behavior'])
        self.d.behavior_styles.groups[dimension].advanced.setChecked(True)
        self.d.show()
        self.d.activateWindow()
        QTest.qWait(100)

    def settle(self):
        forms = self.d.findChildren(ContentForm)
        spies = [QSignalSpy(form._reflow_timer.timeout) for form in forms]
        previous, quiet = -1, 0
        for _ in range(50):
            QTest.qWait(10)
            count = sum(spy.count() for spy in spies)
            quiet = quiet + 1 if count == previous else 0
            previous = count
            if quiet >= 3 and not any(form._reflow_timer.isActive() for form in forms):
                return
        self.fail('比例控件布局未收敛')

    def test_opening_preserves_exact_legacy_weights_and_style_values(self):
        o = self.config.oracle
        config = replace(self.config, oracle=replace(o,
            daily_activity=replace(o.daily_activity, idle_weight=2.123456, move_weight=3.234567, meditate_weight=4.345678),
            drift=replace(o.drift, long_bout_probability=.234567)))
        d = self.open(config)
        self.assertEqual(len(d.proportion_groups), 6)
        before = profile_mapping(config)
        self.assertEqual(d.proportion_groups[DAILY].slider.values, shares([2.123456, 4.345678, 3.234567]))
        for language in ('en', 'zh'):
            language_manager().set_language(language)
            for group in d.behavior_styles.groups.values():
                group.advanced.setChecked(True)
                group.advanced.setChecked(False)
            self.assertEqual(profile_mapping(d.candidate()), before)
        self.assertFalse(d.preset_workflow.dirty)

    def test_manual_typing_commits_one_complete_group_and_saves(self):
        d = self.open()
        editor = d.proportion_groups[DAILY]
        self.show_group('daily_activity')
        original = d.candidate()
        source_signals = [QSignalSpy(source.valueChanged) for source in editor.sources]
        with patch.object(d.preset_workflow, 'changed', wraps=d.preset_workflow.changed) as changed:
            control = editor.inputs[0]
            control.setFocus()
            control.lineEdit().selectAll()
            QTest.keyClicks(control.lineEdit(), '50')
            QTest.keyClick(control.lineEdit(), Qt.Key.Key_Tab)
            self.assertEqual(changed.call_count, 1)
        self.assertEqual([spy.count() for spy in source_signals], [0, 0, 0])
        self.assertEqual(sum(editor.slider.values), 1000)
        self.assertEqual(editor.slider.values[0], 500)
        value = d.candidate()
        daily = value.oracle.daily_activity
        self.assertAlmostEqual(daily.idle_weight+daily.move_weight+daily.meditate_weight, 100)
        self.assertEqual(value.oracle.drift, original.oracle.drift)
        self.assertEqual(value.oracle.drag_reactions, original.oracle.drag_reactions)
        self.assertFalse(value.oracle.behavior_styles.daily_activity.id)
        self.assertTrue(d.preset_workflow.flush())
        self.assertEqual(self.store.load().oracle.daily_activity, daily)
        editor.reset()
        self.assertEqual(d.candidate().oracle.daily_activity, original.oracle.daily_activity)

    def test_slider_drag_only_changes_neighbors_and_accepts_zero_shares(self):
        d = self.open()
        editor = d.proportion_groups[DAILY]
        self.show_group('daily_activity')
        slider = editor.slider
        previous = slider.values[:]
        track = slider.track()
        start = QPoint(round(track.left()+track.width()*previous[0]/1000), round(track.center().y()))
        end = QPoint(round(track.left()+track.width()*.2), start.y())
        QTest.mousePress(slider, Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(slider, end)
        QTest.mouseRelease(slider, Qt.MouseButton.LeftButton, pos=end)
        self.assertLessEqual(abs(slider.values[0]-200), 2)
        self.assertEqual(slider.values[2], previous[2])
        self.assertEqual(sum(slider.values), 1000)
        QTest.keyClick(slider, Qt.Key.Key_Home)
        self.assertEqual(slider.values[0], 0)
        QTest.keyClick(slider, Qt.Key.Key_Right)
        self.assertEqual(slider.values[0], 10)
        self.assertEqual([round(control.value()*10) for control in editor.inputs], slider.values)

    def test_complement_and_nested_hand_probabilities_roundtrip_without_precision_loss(self):
        d = self.open()
        bout = d.proportion_groups[BOUT]
        bout.inputs[0].setValue(70)
        self.assertAlmostEqual(d.candidate().oracle.drift.long_bout_probability, .3)
        hands = d.proportion_groups[HANDS]
        hands.edit_values([1, 499, 500])
        reactions = d.candidate().oracle.drag_reactions
        self.assertEqual(reactions.flutter_probability, .999)
        self.assertEqual(reactions.alternating_probability, 500/999)
        self.assertEqual(hands.slider.values, [1, 499, 500])
        self.assertTrue(d.preset_workflow.flush())
        self.assertEqual(self.store.load().oracle.drag_reactions.alternating_probability, 500/999)
        hands.inputs[0].setValue(100)
        self.assertEqual(hands.slider.values, [1000, 0, 0])
        self.assertTrue(hands.slider.isEnabled())  # 仍可从单手 100% 拖回双手
        self.assertEqual(d.candidate().oracle.drag_reactions.alternating_probability, reactions.alternating_probability)
        hands.inputs[0].setValue(50)
        self.assertEqual(hands.slider.values, [500, 250, 250])
        pearl = d.proportion_groups[PEARLS]
        pearl.inputs[0].setValue(80)
        self.assertAlmostEqual(d.candidate().oracle.reading.matrix_probability, .2)

    def test_styles_resets_and_dependencies_refresh_the_shared_editor(self):
        d = self.open()
        d.controls['oracle.pearl_matrix_enabled'].setChecked(True)
        selector = d.behavior_styles.groups['daily_activity'].selector
        selector.setCurrentIndex(selector.findData('daily_activity.active'))
        selector.activated.emit(selector.currentIndex())
        editor = d.proportion_groups[DAILY]
        self.assertEqual(editor.slider.values, shares(editor.source_values()))
        self.assertTrue(d.candidate().oracle.behavior_styles.daily_activity.id)
        editor.inputs[1].setValue(50)
        self.assertFalse(d.candidate().oracle.behavior_styles.daily_activity.id)
        d.preset_workflow.reset_parameter(DAILY)
        self.assertEqual(editor.slider.values, shares(editor.source_values()))
        hands = d.proportion_groups[HANDS]
        d.controls['oracle.drag_reactions.gesture_probability'].setValue(0)
        self.assertFalse(hands.slider.isEnabled())
        d.controls['oracle.drag_reactions.gesture_probability'].setValue(80)
        self.assertTrue(hands.slider.isEnabled())
        before = d.candidate().oracle.reading
        d.controls['oracle.pearl_fixed_count'].setValue(0)
        self.assertFalse(d.proportion_groups[METHODS].slider.isEnabled())
        self.assertFalse(d.proportion_groups[PEARLS].slider.isEnabled())
        self.assertEqual(d.candidate().oracle.reading, before)
        d.controls['oracle.pearl_fixed_count'].setValue(2)
        self.assertTrue(d.proportion_groups[METHODS].slider.isEnabled())
        self.assertTrue(d.proportion_groups[PEARLS].slider.isEnabled())

    def test_optional_resources_do_not_disable_unrelated_choices(self):
        d = self.open()
        d.controls['oracle.pearl_matrix_enabled'].setChecked(True)
        before = d.candidate()
        for resource in ('bell_voice', 'scan_images', 'pearl_glyphs'):
            d.assets.resources.record(resource, error='missing')
        d.resource_settings.install(d.assets)
        for group in d.proportion_groups.values():
            self.assertTrue(group.slider.isEnabled())
        self.assertEqual(d.candidate(), before)

    def test_layout_localization_and_folding_keep_choices_readable(self):
        d = self.open()
        page = d.pages['behavior']
        d.tabs.setCurrentWidget(page)
        for group in d.behavior_styles.groups.values():
            group.advanced.setChecked(True)
        d.show()
        before = profile_mapping(d.candidate())
        for language, width in (('zh', 800), ('en', 800), ('zh', 960)):
            language_manager().set_language(language)
            d.resize(width, 900)
            self.settle()
            self.assertEqual(page.horizontalScrollBar().maximum(), 0)
            for editor in d.proportion_groups.values():
                self.assertEqual(sum(editor.slider.values), 1000)
                cells = [label.parentWidget() for label in editor.labels]
                self.assertLessEqual(max(cell.width() for cell in cells)-min(cell.width() for cell in cells), 1)
                for label, control in zip(editor.labels, editor.inputs):
                    self.assertGreaterEqual(label.height()+1, label.heightForWidth(label.width()), label.text())
                    self.assertLess(label.geometry().right(), control.x())
                    self.assertGreaterEqual(control.lineEdit().width(), control.fontMetrics().horizontalAdvance(control.text()))
            normal = d.proportion_groups[DAILY].geometry().getRect()
            group = d.behavior_styles.groups['daily_activity']
            group.advanced.setChecked(False)
            self.settle()
            group.advanced.setChecked(True)
            self.settle()
            self.assertEqual(d.proportion_groups[DAILY].geometry().getRect(), normal)
            self.assertEqual(profile_mapping(d.candidate()), before)


if __name__ == '__main__':
    unittest.main()
