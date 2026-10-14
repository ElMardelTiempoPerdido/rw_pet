"""设置表单、资源准备和托盘保存后的真实场景更新。"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from dataclasses import fields, replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QEvent, QObject, QPoint, QPointF, QRect, Qt
from PySide6.QtGui import QColor, QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QAbstractSpinBox, QApplication, QComboBox, QDialog, QLabel, QPushButton, QWidget
from rw_creature_pet.config import AppConfig
from rw_creature_pet.oracle.assets import OracleAssets
from rw_creature_pet.oracle.config import CUSTOM_COLOR_NAMES, CustomAppearance, OracleColors, OracleConfig
from rw_creature_pet.i18n import language_manager, tr
from rw_creature_pet.oracle.ui.desktop import OracleDesktopMotion, OracleDesktopWindow, current_anchor
from rw_creature_pet.oracle.graphics.render import OracleRenderer
from rw_creature_pet.oracle.ui.settings import OracleSettingsDialog
from rw_creature_pet.settings_store import SettingsStore
from tests.oracle.test_desktop import FakeScreen


class OracleSettingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        (root/'游戏/RainWorld_Data').mkdir(parents=True)
        (root/'游戏/RainWorld_Data/resources.assets').write_bytes(b'fixture')
        self.config = AppConfig(game_dir=root/'游戏')
        self.store = SettingsStore(root/'settings.json')
        self.assets = OracleAssets(OracleRenderer(), '', {}, '')
        self.windows = []

    def tearDown(self):
        for window in self.windows:
            if isinstance(window, OracleSettingsDialog):
                window.shutdown()
            else:
                window.close()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()

    def dialog(self, **kwargs):
        d = OracleSettingsDialog(self.config, self.store, **kwargs)
        self.windows.append(d)
        d.show()
        self.app.processEvents()
        return d

    def wait_worker(self, dialog):
        for _ in range(150):
            if dialog.worker is None:
                break
            QTest.qWait(20)
        self.assertIsNone(dialog.worker)

    def test_cancel_does_not_save_or_change_original(self):
        d = self.dialog(assets=self.assets)
        d.controls['desktop.scale'].setCurrentIndex(2)
        d.reject()
        self.assertFalse(self.store.path.exists())
        self.assertEqual(self.config.desktop.scale, 1.)

    def test_neckline_controls_save_apply_and_preserve_bell_and_inactive_values(self):
        w = self.desktop()
        w.open_settings()
        d = w.settings_dialog
        c = d.controls
        prefix = 'oracle.custom_appearance.'
        c['oracle.body_appearance'].setValue('custom')
        c[prefix+'neckline_shape'].setValue('arc')
        self.assertTrue(c[prefix+'neckline_roundness'].isEnabled())
        self.assertFalse(c[prefix+'neckline_tip_radius'].isEnabled())
        for name, value in (('neckline_width', 12.), ('neckline_depth', 9.), ('neckline_height', -1.),
                            ('neckline_roundness', .8), ('neckline_tip_radius', 1.5),
                            ('neckline_trim_width', 1.5), ('neckline_trim_gap', 2.)):
            c[prefix+name].setValue(value)
        d.neckline_color.setValue('#123456')
        self.assertEqual(c['oracle.custom_colors.collar_trim'].value(), '#123456')
        c[prefix+'neckline_trim_enabled'].setChecked(False)
        self.assertFalse(c[prefix+'neckline_trim_gap'].isEnabled())
        c[prefix+'neckline_trim_enabled'].setChecked(True)
        shape = d.candidate().oracle.custom_appearance
        scene = w.motion.scene
        d.save(close=False)
        self.assertIs(w.motion.scene, scene)
        self.assertEqual(scene.config.active_custom_appearance, shape)
        self.assertEqual(self.store.load().oracle.custom_appearance, shape)
        self.assertEqual(w.renderer.colors.collar_trim, '#123456')
        c['oracle.body_appearance'].setValue('bell')
        d.save()
        self.assertIsNone(scene.config.active_custom_appearance)
        self.assertEqual(w.renderer.colors.collar_trim, self.config.oracle.colors.collar_trim)
        w.open_settings()
        d = w.settings_dialog
        self.assertEqual(d.controls[prefix+'neckline_height'].value(), -1.)
        d.controls[prefix+'neckline_shape'].setValue('v')
        self.assertEqual(d.controls[prefix+'neckline_tip_radius'].value(), 1.5)
        self.assertTrue(d.controls[prefix+'neckline_tip_radius'].isEnabled())

    def test_settings_construction_never_shows_a_standalone_control(self):
        shown = []

        class WindowShows(QObject):
            def eventFilter(self, watched, event):
                if event.type() == QEvent.Type.Show and isinstance(watched, QWidget) and watched.isWindow():
                    shown.append(watched)
                return False

        watcher = WindowShows()
        self.app.installEventFilter(watcher)
        try:
            for first_run in (True, False, False):
                with self.subTest(first_run=first_run):
                    shown.clear()
                    d = OracleSettingsDialog(self.config, self.store, assets=self.assets, first_run=first_run)
                    self.windows.append(d)
                    self.app.processEvents()
                    self.assertEqual(shown, [])
                    d.show()
                    self.app.processEvents()
                    self.assertEqual(shown, [d])
                    self.assertEqual(d.apply_button.isVisible(), not first_run)
                    d.hide()
        finally:
            self.app.removeEventFilter(watcher)

    def test_apply_keeps_dialog_and_updates_desktop_then_cancel_only_discards_new_edits(self):
        self.config = replace(self.config, oracle=replace(self.config.oracle, cross_edge_probability=.123456))
        w = self.desktop()
        w.open_settings()
        d = w.settings_dialog
        d.tabs.setCurrentIndex(2)
        bar = d.tabs.currentWidget().verticalScrollBar()
        bar.setValue(40)
        scroll = bar.value()
        volume = d.controls['audio.volume']
        for value in (35, 100):
            volume.setValue(value)
            d.apply_button.click()
            self.assertIs(w.settings_dialog, d)
            self.assertTrue(d.isVisible())
            self.assertTrue(d.apply_button.isEnabled())
            self.assertEqual(d.tabs.currentIndex(), 2)
            self.assertEqual(bar.value(), scroll)
            self.assertEqual(w.voice_player.volume, value / 100)
            self.assertEqual(self.store.load().audio.volume, value / 100)
            self.assertEqual(d.candidate(), d.saved_config)
            self.assertEqual(d.candidate().oracle.cross_edge_probability, .123456)
        volume.setValue(12)
        with patch.object(self.store, 'save', side_effect=PermissionError('locked')):
            d.apply_button.click()
        self.assertEqual(w.voice_player.volume, 1.)
        self.assertEqual(d.original.audio.volume, 1.)
        self.assertEqual(volume.value(), 12)
        self.assertIn('locked', d.status.text())
        self.assertTrue(d.apply_button.isEnabled())
        d.reject()
        self.assertIsNone(w.settings_dialog)
        self.assertEqual(self.store.load().audio.volume, 1.)

    def test_apply_rebases_reset_values_and_slot_precision_for_subsequent_edits(self):
        slot = replace(self.config.overseer.slots[0], size=.812345)
        defaults = replace(self.config, audio=replace(self.config.audio, volume=.701234),
                           overseer=replace(self.config.overseer, slots=(slot,)))
        d = self.dialog(assets=self.assets)
        with patch('rw_creature_pet.oracle.ui.settings.load_defaults', return_value=defaults):
            d.restore_defaults()
        d.apply_button.click()
        self.assertEqual(self.store.load(), defaults)
        self.assertEqual(d.candidate(), defaults)
        for volume, size in ((90, .9), (70, .81)):
            d.controls['audio.volume'].setValue(volume)
            d.controls['overseer.slots'].sizes[slot.id].setValue(size)
            d.apply_button.click()
            saved = self.store.load()
            self.assertEqual(saved.audio.volume, volume / 100)
            self.assertEqual(saved.overseer.slots[0].size, size)
        d.save_button.click()
        self.assertEqual(d.result(), QDialog.DialogCode.Accepted)
        self.assertEqual(self.store.load(), saved)

    def test_apply_prepares_new_assets_and_reuses_them_for_save_and_close(self):
        w = self.desktop()
        w.open_settings()
        d = w.settings_dialog
        new_game = self.config.game_dir.parent / '另一个游戏'
        (new_game / 'RainWorld_Data').mkdir(parents=True)
        (new_game / 'RainWorld_Data/resources.assets').touch()
        new_assets = OracleAssets(OracleRenderer(), '', {}, '')
        d.game_dir.setText(str(new_game))
        with patch('rw_creature_pet.oracle.ui.settings.prepare_oracle_assets', side_effect=RuntimeError('bad atlas')):
            d.apply_button.click()
            self.assertFalse(d.apply_button.isEnabled())
            self.assertFalse(d.save_button.isEnabled())
            self.assertFalse(d.reset_all_button.isEnabled())
            self.wait_worker(d)
        self.assertIn('bad atlas', d.status.text())
        self.assertTrue(d.apply_button.isEnabled())
        self.assertEqual(w.config.game_dir, self.config.game_dir)
        with patch('rw_creature_pet.oracle.ui.settings.prepare_oracle_assets', return_value=new_assets) as prepare:
            d.apply_button.click()
            d.save()  # 资源准备中不能重复提交，也不能改成保存后关闭
            self.wait_worker(d)
            self.assertIs(w.settings_dialog, d)
            self.assertTrue(d.isVisible())
            self.assertIs(w.renderer, new_assets.renderer)
            self.assertEqual(self.store.load().game_dir, new_game)
            d.apply_button.click()
            d.save_button.click()
            prepare.assert_called_once()
        self.assertIsNone(w.settings_dialog)
        self.assertEqual(d.result(), QDialog.DialogCode.Accepted)

    def test_large_scale_option_shares_row_enables_only_at_four_and_persists(self):
        # 离屏平台工作区很小，使用可容纳真实 4× 的活动带；此用例只检查像素选项
        self.config = replace(self.config, oracle=replace(self.config.oracle, arm_scale=.35, edge_fraction=.499))
        d = self.dialog(assets=self.assets)
        scale, coarse = d.controls['desktop.scale'], d.controls['oracle.coarse_pixels_4x']
        self.assertEqual([scale.itemData(i) for i in range(scale.count())], [1., 1.5, 2., 3., 4.])
        self.assertFalse(coarse.isChecked())
        self.assertFalse(coarse.isEnabled())
        scale.setCurrentIndex(scale.findData(4.))
        self.assertTrue(coarse.isEnabled())
        coarse.setChecked(True)
        for value in (1., 1.5, 2., 3.):
            scale.setCurrentIndex(scale.findData(value))
            self.assertFalse(coarse.isEnabled())
            self.assertTrue(coarse.isChecked())
        scale.setCurrentIndex(scale.findData(4.))
        self.app.processEvents()
        a = scale.mapTo(d, scale.rect().center())
        b = coarse.mapTo(d, coarse.rect().center())
        self.assertLess(abs(a.y()-b.y()), 4)
        self.assertLess(a.x(), b.x())
        d.save()
        self.config = self.store.load()
        self.assertEqual(self.config.desktop.scale, 4.)
        self.assertTrue(self.config.oracle.coarse_pixels_4x)
        reopened = self.dialog(assets=self.assets)
        self.assertTrue(reopened.controls['oracle.coarse_pixels_4x'].isChecked())
        self.assertTrue(reopened.controls['oracle.coarse_pixels_4x'].isEnabled())

    def test_changing_four_x_pixels_does_not_reset_desktop_pose(self):
        self.config = replace(self.config, desktop=replace(self.config.desktop, scale=4.),
                              oracle=replace(self.config.oracle, arm_scale=.35, edge_fraction=.499))
        w = self.desktop()
        w.change_scale(4.)
        scene = w.motion.scene
        d = self.dialog(assets=self.assets, commit=w.apply_settings)
        d.controls['oracle.coarse_pixels_4x'].setChecked(True)
        d.save()
        self.assertIs(w.motion.scene, scene)
        self.assertTrue(scene.config.coarse_pixels_4x)
        self.assertTrue(w.overseers.layers[1].coarse_pixels_4x)
        w.reset_position()
        self.assertTrue(w.motion.scene.config.coarse_pixels_4x)

    def test_drag_projection_controls_save_percent_seconds_and_keep_cooldown(self):
        w = self.desktop()
        w.motion.scene.projection.cooldown = 31.25
        d = self.dialog(assets=self.assets, commit=w.apply_settings)
        probability = d.controls['oracle.drag_projection_probability']
        cooldown = d.controls['oracle.drag_projection_cooldown_seconds']
        self.assertEqual((probability.value(), cooldown.value()), (20., 45.))
        probability.setValue(32.5)
        cooldown.setValue(90.)
        d.save()
        self.assertEqual(d.result(), QDialog.DialogCode.Accepted)
        saved = self.store.load().oracle
        self.assertEqual((saved.drag_projection_probability, saved.drag_projection_cooldown_seconds), (.325, 90.))
        self.assertEqual(w.motion.scene.config.drag_projection_probability, .325)
        self.assertEqual(w.motion.scene.projection.cooldown, 31.25)

    def test_arm_scale_percentage_preserves_precision_and_round_trips(self):
        d = self.dialog(assets=self.assets)
        scale = d.controls['oracle.arm_scale']
        self.assertEqual((scale.value(), scale.minimum(), scale.maximum()), (60., 35., 75.))
        self.config = replace(self.config, oracle=replace(self.config.oracle, arm_scale=.623456))
        d = self.dialog(assets=self.assets)
        self.assertEqual(d.controls['oracle.arm_scale'].value(), 62.3)
        self.assertEqual(d.candidate().oracle.arm_scale, .623456)
        d.controls['oracle.arm_scale'].setValue(70.5)
        d.save()
        self.config = self.store.load()
        self.assertEqual(self.config.oracle.arm_scale, .705)
        reopened = self.dialog(assets=self.assets)
        self.assertEqual(reopened.controls['oracle.arm_scale'].value(), 70.5)

    def test_arm_scale_applies_to_desktop_reach_only_after_successful_save(self):
        w = self.desktop()
        desktop_scale = w.requested_scale
        for percent in (75., 35.):
            old = w.motion.scene
            side, fraction = current_anchor(old)
            w.open_settings()
            d = w.settings_dialog
            d.controls['oracle.arm_scale'].setValue(percent)
            with patch.object(self.store, 'save', side_effect=PermissionError('locked')):
                d.save()
            self.assertIs(w.motion.scene, old)
            self.assertEqual(d.controls['oracle.arm_scale'].value(), percent)
            d.save()
            scene = w.motion.scene
            self.assertIsNot(scene, old)
            self.assertEqual(scene.config.arm_scale, percent / 100)
            for actual, original in zip(scene.arm.lengths, (300., 150., 90., 30.)):
                self.assertAlmostEqual(actual, original * percent / 100)
            self.assertAlmostEqual(scene.arm.maximum_reach, old.arm.maximum_reach * percent / 100 / old.config.arm_scale)
            self.assertEqual(current_anchor(scene)[0], side)
            self.assertAlmostEqual(current_anchor(scene)[1], fraction)
            self.assertEqual(w.requested_scale, desktop_scale)
            self.assertEqual(self.store.load().oracle.arm_scale, percent / 100)
            for _ in range(40):
                scene.step()
            self.assertTrue(scene.navigator.region.contains(scene.body.chunks[0].position))
            self.assertLess(scene.arm.constraint_error, .2)

    def test_overseer_fields_validate_persist_and_reload(self):
        d = self.dialog(assets=self.assets)
        self.assertFalse(d.controls['overseer.check_interval'].isEnabled())
        d.controls['overseer.enabled'].setChecked(True)
        self.assertTrue(d.controls['overseer.check_interval'].isEnabled())
        d.controls['overseer.slots'].colors[1].setValue('#fa5577')
        for key, value in dict(check_interval=8, appearance_probability=45, duration_min=4,
                               duration_max=7, cooldown_min=12, cooldown_max=18,
                               withdraw_distance=80, reemerge_distance=130,
                               puppet_withdraw_distance=110, puppet_reemerge_distance=170,
                               relocation_probability=70, observation_probability=80,
                               observation_interval=15).items():
            d.controls['overseer.'+key].setValue(value)
        d.controls['overseer.duration_max'].setValue(2)
        d.save()
        self.assertIn('duration_min', d.status.text())
        self.assertFalse(self.store.path.exists())
        d.controls['overseer.duration_max'].setValue(7)
        d.save()
        saved = self.store.load()
        self.assertTrue(saved.overseer.enabled)
        self.assertEqual(saved.overseer.slots[0].color, '#fa5577')
        self.assertEqual(saved.overseer.appearance_probability, .45)
        self.assertEqual(saved.overseer.reemerge_distance, 130)
        self.assertEqual(saved.overseer.observation_probability, .8)
        self.assertEqual(saved.overseer.observation_interval, 15)
        self.assertEqual(saved.overseer.puppet_withdraw_distance, 110)
        self.assertEqual(saved.overseer.puppet_reemerge_distance, 170)
        self.assertEqual(saved.overseer.relocation_probability, .7)
        self.config = saved
        reopened = self.dialog(assets=self.assets)
        self.assertEqual(reopened.controls['overseer.duration_min'].value(), 4)
        self.assertEqual(reopened.controls['overseer.cooldown_max'].value(), 18)
        self.assertEqual(reopened.controls['overseer.relocation_probability'].value(), 70)

    def test_overseer_only_apply_keeps_puppet_and_failed_save_keeps_event(self):
        from rw_creature_pet.overseer.events import EventPhase
        w = self.desktop()
        w.motion.scene.set_autonomous(False)
        for _ in range(800):
            w.motion.step()
        scene, hit = w.motion.scene, w.drag_hit
        w.settings_action.trigger()
        d = w.settings_dialog
        d.controls['overseer.enabled'].setChecked(True)
        d.controls['overseer.slots'].colors[1].setValue('#123456')
        with patch.object(self.store, 'save', side_effect=PermissionError('locked')):
            d.save()
        self.assertFalse(w.overseers.layers[1].model.config.enabled)
        with patch.object(w, 'update') as update:
            d.save()
            update.assert_not_called()
        self.assertIs(w.motion.scene, scene)
        self.assertIs(w.drag_hit, hit)
        self.assertTrue(scene.appearance.sleeping)
        self.assertEqual(w.overseers.layers[1].model.config.color, '#123456')
        w.overseers.layers[1].events.start(w.overseer_spawn_context())
        w.settings_action.trigger()
        d = w.settings_dialog
        d.controls['overseer.enabled'].setChecked(False)
        d.save()
        self.assertEqual(w.overseers.layers[1].events.phase, EventPhase.EXITING)
        self.assertIs(w.motion.scene, scene)

    def test_overseer_slots_mode_capacity_draft_and_persistence(self):
        d = self.dialog(assets=self.assets)
        editor = d.controls['overseer.slots']
        for _ in range(3):
            editor.add_button.click()
        self.assertEqual([s.id for s in editor.value()], [1, 2, 3, 4])
        self.assertEqual([s.color for s in editor.value()[1:]], ['#ffffff'] * 3)
        self.assertEqual(editor.value()[0].color, self.config.overseer.slots[0].color)
        self.assertFalse(editor.add_button.isEnabled())
        editor.colors[3].setValue('#aabbcc')
        editor.remove_slot(2)
        self.assertEqual([s.id for s in editor.value()], [1, 3, 4])
        editor.add_button.click()
        self.assertEqual(editor.colors[2].value(), '#ffffff')
        self.assertEqual(editor.colors[3].value(), '#aabbcc')
        self.assertFalse(self.store.path.exists())
        mode = d.controls['overseer.appearance_mode']
        d.controls['overseer.enabled'].setChecked(True)
        mode.setCurrentIndex(mode.findData('resident'))
        self.assertFalse(d.controls['overseer.check_interval'].isEnabled())
        self.assertFalse(d.controls['overseer.duration_min'].isEnabled())
        self.assertTrue(d.controls['overseer.withdraw_distance'].isEnabled())
        d.save()
        saved = self.store.load()
        self.assertEqual(saved.overseer.appearance_mode, 'resident')
        self.assertEqual(len(saved.overseer.slots), 4)
        self.assertEqual(saved.overseer.slots[2].color, '#aabbcc')
        self.config = saved
        reopened = self.dialog(assets=self.assets)
        for key in (1, 2, 3, 4):
            reopened.controls['overseer.slots'].remove_slot(key)
        reopened.save()
        self.assertEqual(self.store.load().overseer.slots, ())

    def test_overseer_friend_selection_defaults_and_saved_custom_color(self):
        d = self.dialog(assets=self.assets)
        editor = d.controls['overseer.slots']
        editor.add_slot()
        selector = editor.appearances[2]
        selector.setCurrentIndex(selector.findData('friend'))
        self.assertEqual(editor.colors[2].value(), '#000000')
        selector.setCurrentIndex(selector.findData('standard'))
        self.assertEqual(editor.colors[2].value(), '#ffffff')
        selector.setCurrentIndex(selector.findData('friend'))
        editor.colors[2].setValue('#243447')
        selector.setCurrentIndex(selector.findData('standard'))
        self.assertEqual(editor.colors[2].value(), '#243447')
        selector.setCurrentIndex(selector.findData('friend'))
        self.assertEqual(editor.colors[2].value(), '#000000')
        editor.colors[2].setValue('#243447')
        from rw_creature_pet.i18n import language_manager
        language_manager().set_language('en')
        self.assertEqual(selector.currentText(), 'Friend?')
        self.assertEqual(selector.currentData(), 'friend')
        self.assertEqual(editor.colors[2].value(), '#243447')
        language_manager().set_language('zh')
        self.assertEqual(selector.currentText(), '朋友？')
        d.save()
        self.config = self.store.load()
        slot = self.config.overseer.slots[1]
        self.assertEqual((slot.appearance, slot.color), ('friend', '#243447'))
        reopened = self.dialog(assets=self.assets).controls['overseer.slots']
        self.assertEqual(reopened.appearances[2].currentData(), 'friend')
        self.assertEqual(reopened.colors[2].value(), '#243447')

    def test_existing_colored_overseer_switch_to_friend_fills_black(self):
        from rw_creature_pet.overseer.config import OverseerSlot
        self.config = replace(self.config, overseer=replace(self.config.overseer,
            slots=(OverseerSlot(id=1, color='#123456'),)))
        d = self.dialog(assets=self.assets)
        editor = d.controls['overseer.slots']
        self.assertEqual(editor.colors[1].value(), '#123456')
        selector = editor.appearances[1]
        selector.setCurrentIndex(selector.findData('friend'))
        self.assertEqual(editor.colors[1].value(), '#000000')
        self.assertEqual(self.config.overseer.slots[0].color, '#123456')
        d.save()
        self.config = self.store.load()
        self.assertEqual(self.config.overseer.slots[0], OverseerSlot(id=1, appearance='friend'))
        reopened = self.dialog(assets=self.assets).controls['overseer.slots']
        self.assertEqual(reopened.colors[1].value(), '#000000')

    def test_overseer_individual_shape_controls_persist_and_limit_friend(self):
        from rw_creature_pet.overseer.config import OverseerSlot
        self.config = replace(self.config, overseer=replace(self.config.overseer, size=.85,
            slots=(OverseerSlot(1, size=.731, filament_count=3),)))
        d = self.dialog(assets=self.assets)
        editor = d.controls['overseer.slots']
        self.assertEqual(editor.sizes[1].value(), .73)
        self.assertEqual(editor.value()[0].size, .731)
        editor.sizes[1].setValue(.5)
        editor.filament_counts[1].setValue(3)
        editor.add_slot()
        self.assertEqual(editor.sizes[2].value(), .85)
        editor.sizes[2].setValue(1.)
        editor.filament_counts[2].setValue(5)
        selector = editor.appearances[2]
        selector.setCurrentIndex(selector.findData('friend'))
        self.assertFalse(editor.filament_counts[2].isEnabled())
        self.assertTrue(editor.filament_counts[2].isHidden())
        self.assertTrue(editor.sizes[2].isEnabled())
        editor.remove_slot(1)
        self.assertEqual(editor.value()[0].filament_count, 5)
        selector.setCurrentIndex(selector.findData('standard'))
        self.assertTrue(editor.filament_counts[2].isEnabled())
        self.assertEqual(editor.filament_counts[2].value(), 5)
        selector.setCurrentIndex(selector.findData('friend'))
        self.assertEqual(self.config.overseer.slots[0].size, .731)
        d.save()
        self.config = self.store.load()
        self.assertEqual(self.config.overseer.slots[0], OverseerSlot(2, appearance='friend', size=1., filament_count=5))
        reopened = self.dialog(assets=self.assets).controls['overseer.slots']
        self.assertEqual(reopened.sizes[2].value(), 1.)
        self.assertTrue(reopened.filament_counts[2].isHidden())

    def test_overseer_slot_rows_keep_control_height_after_add_remove(self):
        d = self.dialog(assets=self.assets)
        editor = d.controls['overseer.slots']
        d.tabs.setCurrentIndex(next(i for i in range(d.tabs.count())
                                   if d.tabs.widget(i).isAncestorOf(editor)))

        def check_geometry():
            for _ in range(4):
                self.app.processEvents()
            visible = [row for row in editor.rows.values() if not row.isHidden()]
            for row in visible:
                self.assertTrue(editor.rect().contains(row.geometry()))
                for button in row.findChildren(QPushButton):
                    self.assertGreaterEqual(button.height(), button.minimumSizeHint().height())
                for selector in row.findChildren(QComboBox):
                    self.assertGreaterEqual(selector.height(), selector.minimumSizeHint().height())
                    self.assertTrue(row.rect().contains(selector.geometry()))
                for control in row.findChildren(QAbstractSpinBox):
                    if not control.isHidden():
                        self.assertGreaterEqual(control.height(), control.minimumSizeHint().height())
                        self.assertTrue(row.rect().contains(control.geometry()))
            self.assertGreaterEqual(editor.add_button.height(), editor.add_button.minimumSizeHint().height())
            self.assertTrue(editor.rect().contains(editor.add_button.geometry()))
            content = d.tabs.currentWidget().widget()
            next_field = d.controls['overseer.check_interval']
            self.assertLess(editor.mapTo(content, QPoint(0, editor.height())).y(),
                            next_field.mapTo(content, QPoint()).y())

        for workarea in (QRect(0, 0, 1280, 900), QRect(0, 0, 800, 480)):
            d.fit_workarea(workarea)
            check_geometry()
            initial_height = editor.height()
            for removed in (2, 1):
                editor.add_button.click()
                check_geometry()
                editor.rows[removed].findChildren(QPushButton)[-1].click()
                check_geometry()
                self.assertEqual(editor.height(), initial_height)
            # 清空后只保留添加按钮，再加满、逐个移除，高度应随内容恢复
            editor.rows[2].findChildren(QPushButton)[-1].click()
            check_geometry()
            self.assertEqual(editor.height(), editor.add_button.height())
            for _ in range(4):
                editor.add_button.click()
                check_geometry()
            for key in (4, 3, 2):
                editor.rows[key].findChildren(QPushButton)[-1].click()
                check_geometry()
            self.assertEqual(editor.height(), initial_height)

    def test_matrix_avoidance_radius_round_trips_and_tracks_matrix_availability(self):
        d = self.dialog(assets=self.assets)
        radius = d.controls['oracle.pearl_matrix_avoid_radius']
        self.assertEqual(radius.value(), 80)
        self.assertFalse(radius.isEnabled())
        d.controls['oracle.pearl_matrix_enabled'].setChecked(True)
        self.assertTrue(radius.isEnabled())
        d.controls['oracle.pearl_matrix_count'].setValue(0)
        self.assertFalse(radius.isEnabled())
        d.controls['oracle.pearl_matrix_count'].setValue(7)
        radius.setValue(95)
        playback = d.controls['oracle.pearl_playback_probability']
        self.assertTrue(playback.isEnabled())
        playback.setValue(60)
        d.save()
        saved = self.store.load()
        self.assertEqual(saved.oracle.pearl_matrix_avoid_radius, 95)
        self.assertEqual(saved.oracle.pearl_playback_probability, .6)
        self.config = saved
        reopened = self.dialog(assets=self.assets)
        self.assertEqual(reopened.controls['oracle.pearl_matrix_avoid_radius'].value(), 95)
        self.assertEqual(reopened.controls['oracle.pearl_playback_probability'].value(), 60)

    def test_start_edge_auto_checks_allowed_edge_and_round_trips(self):
        d = self.dialog(assets=self.assets)
        for check in d.edge_checks.values():
            check.setChecked(False)
        d.start_edge_buttons['left'].setChecked(True)
        self.assertTrue(d.edge_checks['left'].isChecked())
        self.assertEqual(sum(b.isChecked() for b in d.start_edge_buttons.values()), 1)
        d.save()
        saved = self.store.load()
        self.assertEqual(saved.oracle.allowed_edges, ('left',))
        self.assertEqual(saved.oracle.base_side, 'left')
        self.config = saved
        reopened = self.dialog(assets=self.assets)
        self.assertTrue(reopened.start_edge_buttons['left'].isChecked())
        self.assertEqual([k for k, v in reopened.edge_checks.items() if v.isChecked()], ['left'])

    def test_invalid_edges_preserve_form_and_do_not_save(self):
        d = self.dialog(assets=self.assets)
        for edges, message in (((), '至少'), (('top', 'bottom'), '连续'),
                               (('right', 'bottom'), '启动时的位置')):
            with self.subTest(edges=edges):
                for edge, check in d.edge_checks.items():
                    check.setChecked(edge in edges)
                d.save()
                self.assertIn(message, d.status.text())
                self.assertFalse(self.store.path.exists())
                self.assertEqual(tuple(k for k, v in d.edge_checks.items() if v.isChecked()), edges)
                self.assertTrue(d.save_button.isEnabled())

    def test_removing_current_edge_rehomes_and_start_preference_survives_resize(self):
        w = self.desktop()
        w.open_settings()
        d = w.settings_dialog
        d.start_edge_buttons['bottom'].setChecked(True)
        for edge, check in d.edge_checks.items():
            check.setChecked(edge in ('bottom', 'left'))
        d.save()
        self.assertEqual(w.motion.scene.anchor.side.value, 'bottom')
        self.assertEqual(w.config.oracle.allowed_edges, ('bottom', 'left'))
        w.open_settings()
        w.settings_dialog.start_edge_buttons['left'].setChecked(True)
        w.settings_dialog.save()
        self.assertEqual(w.motion.scene.anchor.side.value, 'bottom')
        self.assertEqual(w.config.oracle.base_side, 'left')
        w.change_scale(2.)
        self.assertEqual(w.motion.scene.world.allowed_edges, ('bottom', 'left'))
        self.assertEqual(self.store.load().oracle.base_side, 'left')
        w.reset_position()
        self.assertEqual(w.motion.scene.anchor.side.value, 'left')

    def test_start_fraction_applies_each_save_without_lag_and_resize_preserves_current_location(self):
        w = self.desktop()
        for percentage in (25., 75., 37.5):
            w.open_settings()
            d = w.settings_dialog
            d.controls['oracle.base_fraction'].setValue(percentage)
            d.save()
            self.assertAlmostEqual(current_anchor(w.motion.scene)[1], percentage/100)
            self.assertEqual(self.store.load().oracle.base_fraction, percentage/100)
        w.open_settings()
        self.assertEqual(w.settings_dialog.controls['oracle.base_fraction'].value(), 37.5)
        w.settings_dialog.reject()
        # 模拟桌宠已经移动；改变缩放不应再跳回保存的启动百分比。
        w.motion = OracleDesktopMotion(replace(w.config.oracle, base_fraction=.61), w.motion.viewport)
        w.change_scale(1.5)
        self.assertAlmostEqual(current_anchor(w.motion.scene)[1], .61)
        self.assertEqual(self.store.load().oracle.base_fraction, .375)
        w.reset_position()
        self.assertAlmostEqual(current_anchor(w.motion.scene)[1], .375)

    def test_save_reload_disabled_options_and_unexposed_precision(self):
        self.config = replace(self.config, oracle=replace(self.config.oracle, cross_edge_probability=.123456,
            colors=replace(self.config.oracle.colors, skin='#123456')))
        d = self.dialog(assets=self.assets)
        d.controls['desktop.scale'].setCurrentIndex(1)
        d.controls['oracle.pearl_matrix_enabled'].setChecked(True)
        d.controls['oracle.pearl_matrix_count'].setValue(9)
        d.controls['oracle.halo_enabled'].setChecked(False)
        self.assertFalse(d.controls['oracle.halo_arc_max_count'].isEnabled())
        d.controls['audio.volume'].setValue(35)
        QTest.mouseClick(d.save_button, Qt.MouseButton.LeftButton)
        saved = self.store.load()
        self.assertEqual(d.result(), QDialog.DialogCode.Accepted)
        self.assertEqual(saved.desktop.scale, 1.5)
        self.assertEqual(saved.oracle.pearl_matrix_count, 9)
        self.assertFalse(saved.oracle.halo_enabled)
        self.assertTrue(saved.oracle.halo_arcs_enabled)
        self.assertEqual(saved.audio.volume, .35)
        self.assertEqual(saved.oracle.cross_edge_probability, .123456)
        self.assertEqual(saved.oracle.colors.skin, '#123456')

    def test_invalid_directory_and_write_failure_preserve_inputs(self):
        d = self.dialog(assets=self.assets)
        d.game_dir.setText(str(self.config.game_dir/'missing'))
        d.save()
        self.assertIn('RainWorld_Data', d.status.text())
        self.assertFalse(self.store.path.exists())
        d.game_dir.setText(str(self.config.game_dir))
        d.controls['oracle.pearl_fixed_count'].setValue(7)
        with patch.object(self.store, 'save', side_effect=PermissionError('只读')):
            d.save()
        self.assertIn('保存失败', d.status.text())
        self.assertTrue(d.save_button.isEnabled())
        self.assertEqual(d.controls['oracle.pearl_fixed_count'].value(), 7)

    def test_asset_preparation_failure_and_retry_use_background_worker(self):
        d = self.dialog(first_run=True)
        self.assertEqual(d.save_button.text(), tr('保存并启动'))
        self.assertTrue(d.apply_button.isHidden())
        with patch('rw_creature_pet.oracle.ui.settings.prepare_oracle_assets', side_effect=RuntimeError('bad atlas')):
            d.save()
            self.assertFalse(d.save_button.isEnabled())
            self.wait_worker(d)
        self.assertIn('bad atlas', d.status.text())
        self.assertFalse(self.store.path.exists())
        with patch('rw_creature_pet.oracle.ui.settings.prepare_oracle_assets', return_value=self.assets):
            d.save()
            self.wait_worker(d)
        self.assertEqual(self.store.load(), self.config)
        self.assertEqual(d.result(), QDialog.DialogCode.Accepted)

    def desktop(self):
        with patch('rw_creature_pet.oracle.ui.desktop.QSystemTrayIcon.isSystemTrayAvailable', return_value=True):
            window = OracleDesktopWindow(self.config, config_store=self.store, assets=self.assets)
        self.windows.append(window)
        window.timer.stop()
        window.bind_screen(FakeScreen(QRect(-1280, 40, 1280, 680), 1.5))
        return window

    def test_tray_saves_applies_and_reopens_with_new_values_without_changing_overlay_input(self):
        w = self.desktop()
        old = w.motion.scene
        w.settings_action.trigger()
        d = w.settings_dialog
        w.settings_action.trigger()
        self.assertIs(w.settings_dialog, d)
        self.assertTrue(w.windowFlags() & Qt.WindowType.WindowTransparentForInput)
        self.assertFalse(d.windowFlags() & Qt.WindowType.WindowTransparentForInput)
        d.controls['desktop.scale'].setCurrentIndex(1)
        d.controls['desktop.autonomous'].setChecked(False)
        d.controls['oracle.pearl_matrix_enabled'].setChecked(True)
        d.controls['oracle.pearl_matrix_count'].setValue(9)
        d.controls['oracle.pearl_inner_count'].setValue(6)
        d.controls['oracle.halo_enabled'].setChecked(False)
        d.save()
        self.assertIsNone(w.settings_dialog)
        self.assertIsNot(w.motion.scene, old)
        self.assertTrue(w.motion.scene.behavior.enabled)
        self.assertFalse(w.motion.scene.behavior.movement_enabled)
        self.assertEqual(w.requested_scale, 1.5)
        self.assertEqual(w.motion.scene.config.pearl_matrix_count, 9)
        self.assertEqual(w.motion.scene.config.pearl_inner_count, 6)
        self.assertFalse(w.motion.scene.config.halo_enabled)
        self.assertTrue(w.config.oracle.pearl_matrix_enabled)
        self.assertEqual(self.store.load(), w.config)
        w.bind_screen(FakeScreen(QRect(0, 0, 1600, 900)))
        self.assertEqual(w.motion.scene.config.pearl_matrix_count, 9)
        w.settings_action.trigger()
        self.assertEqual(w.settings_dialog.controls['oracle.pearl_matrix_count'].value(), 9)

    def test_settings_recovers_a_deleted_screen_reference_and_reopens_repeatedly(self):
        from shiboken6 import delete, isValid
        w = self.desktop()
        stale = w.screen
        # 模拟没有收到 screenRemoved 的旧 Qt 引用，直接覆盖用户报告的出错路径
        stale.destroyed.disconnect(w.screen_destroyed)
        delete(stale)
        self.assertFalse(isValid(stale))
        for _ in range(4):
            w.open_settings()
            self.assertTrue(w.settings_dialog.isVisible())
            self.assertTrue(isValid(w.screen))
            self.assertIn(w.screen, self.app.screens())
            w.settings_dialog.reject()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            self.app.processEvents()
            self.assertIsNone(w.settings_dialog)
            self.assertTrue(isValid(w.screen))

    def test_optional_inner_robe_controls_apply_and_preserve_hidden_collar_values(self):
        w = self.desktop()
        w.open_settings()
        d = w.settings_dialog
        c = d.controls
        prefix = 'oracle.custom_appearance.'
        c['oracle.body_appearance'].setValue('custom')
        c[prefix+'inner_collar_height'].setValue(6.5)
        c[prefix+'inner_collar_top_width'].setValue(5.)
        c[prefix+'inner_collar_bottom_width'].setValue(8.)
        c[prefix+'inner_collar_enabled'].setChecked(False)
        self.assertFalse(c[prefix+'inner_collar_height'].isEnabled())
        c[prefix+'inner_collar_enabled'].setChecked(True)
        c[prefix+'inner_robe_enabled'].setChecked(False)
        self.assertFalse(c[prefix+'inner_collar_enabled'].isEnabled())
        self.assertFalse(c[prefix+'inner_collar_top_width'].isEnabled())
        c[prefix+'inner_robe_enabled'].setChecked(True)
        self.assertTrue(c[prefix+'inner_collar_top_width'].isEnabled())
        scene = w.motion.scene
        d.save(close=False)
        self.assertIs(w.motion.scene, scene)
        shape = scene.config.active_custom_appearance
        self.assertEqual((shape.inner_collar_height, shape.inner_collar_top_width, shape.inner_collar_bottom_width),
                         (6.5, 5., 8.))
        self.assertEqual(self.store.load().oracle.custom_appearance, shape)
        c['oracle.body_appearance'].setValue('bell')
        d.save()
        self.assertIsNone(scene.config.active_custom_appearance)
        w.open_settings()
        self.assertEqual(w.settings_dialog.controls[prefix+'inner_collar_height'].value(), 6.5)

    def test_audio_only_does_not_rebuild_scene_and_failed_save_does_not_apply(self):
        w = self.desktop()
        scene = w.motion.scene
        scene.drift()
        self.assertTrue(scene.behavior.drift_active)
        w.settings_action.trigger()
        d = w.settings_dialog
        d.controls['audio.volume'].setValue(35)
        with patch.object(self.store, 'save', side_effect=PermissionError('locked')):
            d.save()
        self.assertEqual(w.voice_player.volume, .7)
        self.assertIs(w.motion.scene, scene)
        d.save()
        self.assertEqual(w.voice_player.volume, .35)
        self.assertIs(w.motion.scene, scene)
        self.assertTrue(scene.behavior.drift_active, '只改音量不能取消手动漫游')

    def test_hide_cords_persists_without_reset_and_failed_save_keeps_current_cords(self):
        w = self.desktop()
        scene = w.motion.scene
        scene.drift()
        appearance, cords = scene.appearance, scene.appearance.cords
        w.pause_action.setChecked(True)
        w.open_settings()
        d = w.settings_dialog
        d.controls['oracle.hide_cords'].setChecked(True)
        with patch.object(self.store, 'save', side_effect=PermissionError('locked')):
            d.save()
        self.assertIs(appearance.cords, cords)
        self.assertFalse(scene.config.hide_cords)
        d.save()
        self.assertIs(w.motion.scene, scene)
        self.assertIs(scene.appearance, appearance)
        self.assertTrue(scene.behavior.drift_active)
        self.assertIsNone(appearance.cords)
        self.assertTrue(self.store.load().oracle.hide_cords)
        w.open_settings()
        self.assertTrue(w.settings_dialog.controls['oracle.hide_cords'].isChecked())
        w.settings_dialog.controls['oracle.hide_cords'].setChecked(False)
        w.settings_dialog.save()
        self.assertIs(w.motion.scene, scene)
        self.assertIsNotNone(appearance.cords)
        self.assertIsNot(appearance.cords, cords)
        self.assertFalse(self.store.load().oracle.hide_cords)

    def test_glow_settings_and_color_picker_preserve_pose_and_persist(self):
        w = self.desktop()
        scene = w.motion.scene
        scene.drift()
        w.open_settings()
        d = w.settings_dialog
        color = d.controls['oracle.glow_color']
        self.assertFalse(color.isEnabled())
        opacity = d.controls['oracle.glow_opacity']
        self.assertFalse(opacity.isEnabled())
        self.assertEqual(opacity.value(), 40)
        d.controls['oracle.glow_enabled'].setChecked(True)
        self.assertTrue(color.isEnabled())
        self.assertTrue(opacity.isEnabled())
        with patch('rw_creature_pet.oracle.ui.inputs.QColorDialog.getColor', return_value=QColor('#73ddff')):
            color.choose_color()
        with patch('rw_creature_pet.oracle.ui.inputs.QColorDialog.getColor', return_value=QColor()):
            color.choose_color()
        self.assertEqual(color.value(), '#73ddff')
        d.controls['oracle.glow_radius'].setValue(9.)
        opacity.setValue(65)
        d.save()
        self.assertIs(w.motion.scene, scene)
        self.assertTrue(scene.behavior.drift_active)
        self.assertTrue(scene.config.glow_enabled)
        saved = self.store.load()
        self.assertEqual(saved.oracle.glow_color, '#73ddff')
        self.assertEqual(saved.oracle.glow_radius, 9.)
        self.assertEqual(saved.oracle.glow_opacity, .65)
        self.assertEqual(scene.config.glow_opacity, .65)
        w.open_settings()
        self.assertEqual(w.settings_dialog.controls['oracle.glow_color'].value(), '#73ddff')
        self.assertEqual(w.settings_dialog.controls['oracle.glow_opacity'].value(), 65)
        w.settings_dialog.controls['oracle.glow_opacity'].setValue(0)
        w.settings_dialog.save()
        self.assertIs(w.motion.scene, scene)
        self.assertEqual(self.store.startup()[0].oracle.glow_opacity, 0.)

    def test_palette_colors_save_apply_without_reset_and_survive_reload(self):
        w = self.desktop()
        scene = w.motion.scene
        scene.drift()
        w.open_settings()
        d = w.settings_dialog
        control = d.controls['oracle.colors.pearl_glyph']
        self.assertEqual(control.value(), '#7faabc')
        arm_colors = dict(arm='#234567', arm_highlight='#abcdef', joints='#102030')
        for name, value in arm_colors.items():
            d.controls['oracle.colors.' + name].setValue(value)
        with patch('rw_creature_pet.oracle.ui.inputs.QColorDialog.getColor', return_value=QColor('#ab36ef')):
            control.choose_color()
        with patch.object(self.store, 'save', side_effect=PermissionError('locked')):
            d.save()
        self.assertEqual(w.renderer.colors, self.config.oracle.colors)
        self.assertEqual(scene.config.colors, self.config.oracle.colors)
        self.assertEqual(control.value(), '#ab36ef')
        d.save()
        self.assertEqual(d.result(), QDialog.DialogCode.Accepted)
        self.assertIs(w.motion.scene, scene)
        self.assertTrue(scene.behavior.drift_active)
        colors = replace(self.config.oracle.colors, pearl_glyph='#ab36ef', **arm_colors)
        self.assertEqual(w.renderer.colors, colors)
        self.assertEqual(scene.config.colors, colors)
        self.assertEqual(self.store.load().oracle.colors, colors)
        self.assertEqual(scene.config.pearl_bubble_color, self.config.oracle.pearl_bubble_color)
        w.open_settings()
        self.assertEqual(w.settings_dialog.controls['oracle.colors.pearl_glyph'].value(), '#ab36ef')
        for name, value in arm_colors.items():
            self.assertEqual(w.settings_dialog.controls['oracle.colors.' + name].value(), value)

    def test_body_choice_only_hides_bell_drafts_and_preserves_outfit(self):
        d = self.dialog(assets=self.assets)
        d.tabs.setCurrentIndex(1)
        selector = d.controls['oracle.body_appearance']
        self.assertEqual(selector.value(), 'bell')
        d.controls['oracle.outfit'].setValue('maid')
        d.controls['oracle.colors.skin'].setValue('#abcdef')
        d.controls['oracle.arm_scale'].setValue(55)
        selector.buttons['custom'].click()
        self.assertTrue(d.bell_parameters.isHidden())
        self.assertFalse(d.custom_parameters.isHidden())
        self.assertTrue(d.controls['oracle.outfit'].isVisible())
        candidate = d.candidate()
        self.assertEqual(candidate.oracle.body_appearance, 'custom')
        self.assertEqual(candidate.oracle.outfit, 'maid')
        self.assertEqual(candidate.oracle.colors.skin, '#abcdef')
        self.assertEqual(candidate.oracle.arm_scale, .55)
        selector.buttons['bell'].click()
        self.assertFalse(d.bell_parameters.isHidden())
        self.assertTrue(d.custom_parameters.isHidden())
        self.assertEqual(d.candidate().oracle.colors, candidate.oracle.colors)
        d.reject()
        self.assertFalse(self.store.path.exists())

    def test_custom_palette_row_heights_survive_body_switches_and_window_resize(self):
        self.config = replace(self.config, oracle=replace(self.config.oracle, body_appearance='custom'))
        d = self.dialog(assets=self.assets)
        d.tabs.setCurrentIndex(1)
        selector = d.controls['oracle.body_appearance']
        colors = ('skin', 'head_highlight', 'arm', 'inner_robe')

        for width in (800, 620, 950):
            d.resize(width, 650)
            QTest.qWait(30)
            # 隐藏再显示后仍应按实际列宽换行，不能退回窄列 sizeHint 的大行高
            for _ in range(3):
                selector.buttons['bell'].click()
                QTest.qWait(30)
                selector.buttons['custom'].click()
                QTest.qWait(30)
                for name in colors:
                    row = d.controls['oracle.custom_colors.'+name].parentWidget().parentWidget()
                    self.assertLessEqual(abs(row.height()-row.heightForWidth(row.width())), 2,
                                         (name, width, row.size().toTuple(), row.heightForWidth(row.width())))

    def test_custom_dimensions_save_apply_in_place_and_survive_bell_switch(self):
        w = self.desktop()
        scene = w.motion.scene
        w.open_settings()
        d = w.settings_dialog
        shape = CustomAppearance(12.1/(100/11+1), 4.5, 13., (30.-8.41275)/19.13725,
                                 sleeve_cuff_radius=0., neck_width=5.5, chest_width=15.5, chest_height=6.,
                                 shoulder_width=12.5)
        d.controls['oracle.body_appearance'].setValue('custom')
        for name, value in (('head_length', 12.1), ('sleeve_root_width', 4.5),
                            ('sleeve_cuff_width', 13), ('robe_length', 30),
                            ('sleeve_cuff_radius', 0), ('neck_width', 5.5),
                            ('chest_width', 15.5), ('chest_height', 6.), ('shoulder_width', 12.5)):
            d.controls['oracle.custom_appearance.'+name].setValue(value)
        candidate_shape = d.candidate().oracle.custom_appearance
        for field in fields(CustomAppearance):
            actual, expected = getattr(candidate_shape, field.name), getattr(shape, field.name)
            if isinstance(expected, float):
                self.assertAlmostEqual(actual, expected)
            else:
                self.assertEqual(actual, expected)
        shape = candidate_shape
        self.assertIsNone(scene.config.active_custom_appearance)
        with patch.object(self.store, 'save', side_effect=PermissionError('locked')):
            d.save()
        self.assertIsNone(scene.config.active_custom_appearance)
        self.assertEqual(scene.appearance.robe_length, 1.)
        d.save()
        self.assertIs(w.motion.scene, scene)
        self.assertEqual(scene.config.active_custom_appearance, shape)
        self.assertAlmostEqual(scene.appearance.robe_length, shape.robe_length)
        self.assertEqual(self.store.load().oracle.custom_appearance, shape)
        w.open_settings()
        d = w.settings_dialog
        self.assertEqual(d.controls['oracle.custom_appearance.head_length'].value(), 12.1)
        self.assertEqual(d.controls['oracle.custom_appearance.sleeve_cuff_radius'].value(), 0.)
        self.assertEqual(d.controls['oracle.custom_appearance.neck_width'].value(), 5.5)
        self.assertEqual(d.controls['oracle.custom_appearance.chest_width'].value(), 15.5)
        self.assertEqual(d.controls['oracle.custom_appearance.chest_height'].value(), 6.)
        self.assertEqual(d.controls['oracle.custom_appearance.shoulder_width'].value(), 12.5)
        d.controls['oracle.body_appearance'].setValue('bell')
        d.save()
        self.assertIs(w.motion.scene, scene)
        self.assertIsNone(scene.config.active_custom_appearance)
        self.assertEqual(scene.appearance.robe_length, 1.)
        self.assertEqual(scene.config.custom_appearance, shape)

    def test_length_inputs_use_pixels_and_match_head_and_cloth_geometry(self):
        from rw_creature_pet.oracle.scene import OracleScene
        d = self.dialog(assets=self.assets)
        d.controls['oracle.body_appearance'].setValue('custom')
        head = d.controls['oracle.custom_appearance.head_length']
        robe = d.controls['oracle.custom_appearance.robe_length']
        self.assertEqual((head.value(), robe.value()), (10.1, 27.6))
        for control in (head, robe):
            self.assertEqual(control.suffix(), ' px')
            self.assertEqual(control.singleStep(), 1.)
            previous = control.value()
            control.stepUp()
            self.assertAlmostEqual(control.value()-previous, 1.)
        candidate = d.candidate()
        renderer = OracleRenderer()
        scene = OracleScene(replace(candidate.oracle, hide_cords=True))
        self.assertAlmostEqual(renderer.head_rect(candidate.oracle.custom_appearance.head_length).height(), head.value())
        app = scene.appearance
        goals = app.cloth_goals()
        self.assertAlmostEqual((goals[app.CLOTH_DIVS//2]-goals[-app.CLOTH_DIVS+app.CLOTH_DIVS//2]).length(), robe.value())
        for control in (head, robe):
            for end in (control.minimum(), control.maximum()):
                control.setValue(end)
                d.candidate()  # 显示精度不能让有效输入在反算后越界

    def test_all_debug_colors_save_without_rebuilding_scene_and_custom_reloads(self):
        w = self.desktop()
        scene = w.motion.scene
        scene.drift()
        w.open_settings()
        d = w.settings_dialog
        colors = OracleColors(**{field.name: f'#{index + 16:06x}'
                                 for index, field in enumerate(fields(OracleColors))})
        custom_colors = replace(self.config.oracle.custom_colors, **{
            name: f'#{index+256:06x}' for index, name in enumerate(CUSTOM_COLOR_NAMES)})
        for field in fields(OracleColors):
            d.controls['oracle.colors.' + field.name].setValue(getattr(colors, field.name))
        d.controls['oracle.body_appearance'].setValue('custom')
        for name in CUSTOM_COLOR_NAMES:
            d.controls['oracle.custom_colors.'+name].setValue(getattr(custom_colors, name))
        d.save()
        self.assertEqual(d.result(), QDialog.DialogCode.Accepted)
        self.assertIs(w.motion.scene, scene)
        self.assertTrue(scene.behavior.drift_active)
        self.assertEqual(scene.config.colors, colors)
        self.assertEqual(scene.config.custom_colors, custom_colors)
        self.assertEqual(w.renderer.colors, custom_colors)
        self.assertEqual(self.store.load().oracle.body_appearance, 'custom')
        self.assertEqual(self.store.load().oracle.colors, colors)
        self.assertEqual(self.store.load().oracle.custom_colors, custom_colors)
        w.open_settings()
        reopened = w.settings_dialog
        self.assertTrue(reopened.bell_parameters.isHidden())
        self.assertEqual(reopened.controls['oracle.body_appearance'].value(), 'custom')
        reopened.controls['oracle.body_appearance'].setValue('bell')
        reopened.save()
        self.assertIs(w.motion.scene, scene)
        self.assertEqual(w.renderer.colors, colors)
        self.assertEqual(scene.config.body_appearance, 'bell')
        self.assertEqual(scene.config.custom_colors, custom_colors)

    def test_projection_color_follows_selected_palette_and_preserves_both_drafts(self):
        d = self.dialog(assets=self.assets)
        bell, projection = d.color_editors['oracle.colors.pearl_glyph']
        bell.setValue('#abcdef')
        self.assertEqual(projection.value(), '#abcdef')
        d.controls['oracle.body_appearance'].setValue('custom')
        custom, custom_projection = d.color_editors['oracle.custom_colors.pearl_glyph']
        self.assertTrue(projection.isHidden())
        self.assertFalse(custom_projection.isHidden())
        custom_projection.setValue('#123456')
        self.assertEqual(custom.value(), '#123456')
        self.assertEqual(d.candidate().oracle.custom_colors.pearl_glyph, '#123456')
        self.assertEqual(d.candidate().oracle.colors.pearl_glyph, '#abcdef')
        d.controls['oracle.body_appearance'].setValue('bell')
        self.assertEqual(projection.value(), '#abcdef')
        self.assertTrue(custom_projection.isHidden())
        self.assertEqual(self.config.oracle.colors.pearl_glyph, '#7faabc')

    def test_appearance_colors_have_three_columns_and_localized_horizontal_choice(self):
        d = self.dialog(assets=self.assets)
        self.addCleanup(language_manager().set_language, self.config.ui.language)
        d.tabs.setCurrentIndex(1)
        d.resize(800, 900)
        selector = d.controls['oracle.body_appearance']
        palette = fields(OracleColors)
        self.assertEqual(set(d.color_editors), {'oracle.colors.' + f.name for f in palette}
                         | {'oracle.custom_colors.'+name for name in CUSTOM_COLOR_NAMES})
        for language in ('zh', 'en'):
            language_manager().set_language(language)
            for _ in range(3):
                self.app.processEvents()
            bell, custom = selector.buttons['bell'], selector.buttons['custom']
            self.assertEqual(bell.text(), tr('手势之铃'))
            self.assertEqual(custom.text(), tr('自定义迭代器'))
            self.assertEqual(bell.geometry().center().y(), custom.geometry().center().y())
            self.assertLess(bell.geometry().right(), custom.geometry().left())
            for start in range(0, len(palette), 3):
                controls = [d.controls['oracle.colors.' + f.name] for f in palette[start:start + 3]]
                positions = [c.mapTo(d.bell_parameters, c.rect().center()) for c in controls]
                self.assertLessEqual(max(p.y() for p in positions) - min(p.y() for p in positions), 1)
                self.assertEqual([p.x() for p in positions], sorted(p.x() for p in positions))
                for control in controls:
                    self.assertTrue(d.bell_parameters.rect().contains(
                        control.mapTo(d.bell_parameters, control.rect().bottomRight())))
                    label = next(label for label in control.parentWidget().findChildren(QLabel)
                                 if label.buddy() is control)
                    self.assertLess(label.geometry().right(), control.geometry().left())
                    # Qt 的行高取整允许 1px 差异，不能挤掉整行换行文字
                    self.assertGreaterEqual(label.height() + 1, label.heightForWidth(label.width()))

    def test_body_appearance_config_rejects_unknown_options(self):
        self.assertEqual(OracleConfig().body_appearance, 'bell')
        for value in ('other', '', None, True):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'bell / custom'):
                OracleConfig(body_appearance=value)

    def test_small_workarea_keeps_save_buttons_visible(self):
        d = self.dialog(assets=self.assets)
        d.fit_workarea(QRect(-800, 0, 800, 480))
        self.addCleanup(language_manager().set_language, self.config.ui.language)
        for language in ('zh', 'en'):
            language_manager().set_language(language)
            for _ in range(3):
                self.app.processEvents()
            self.assertLessEqual(d.height(), 450)
            for button in (d.apply_button, d.save_button, d.reset_all_button):
                self.assertTrue(d.rect().contains(button.mapTo(d, button.rect().bottomRight())))
            self.assertLess(d.apply_button.mapTo(d, d.apply_button.rect().topRight()).x(),
                            d.save_button.mapTo(d, d.save_button.rect().topLeft()).x())

    def test_wheel_scrolls_page_without_changing_focused_or_unfocused_numbers(self):
        d = self.dialog(assets=self.assets)
        d.fit_workarea(QRect(0, 0, 800, 480))
        d.tabs.setCurrentIndex(4)
        self.app.processEvents()
        area = d.tabs.currentWidget()
        control = d.controls['oracle.edge_fraction']
        control.setValue(23.5)
        original = control.value()
        for focused in (False, True):
            area.verticalScrollBar().setValue(0)
            control.setFocus() if focused else d.game_dir.setFocus()
            self.app.processEvents()
            position = control.rect().center()
            wheel = QWheelEvent(QPointF(position), QPointF(control.mapToGlobal(position)),
                                QPoint(), QPoint(0, -120), Qt.MouseButton.NoButton,
                                Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
            QApplication.sendEvent(control, wheel)
            self.assertEqual(control.value(), original)
            self.assertGreater(area.verticalScrollBar().value(), 0)
        control.setFocus()
        QTest.keyClick(control, Qt.Key.Key_Up)
        self.assertGreater(control.value(), original)
        control.selectAll()
        QTest.keyClicks(control, '25.5')
        QTest.keyClick(control, Qt.Key.Key_Tab)
        self.assertEqual(control.value(), 25.5)

    def test_tray_shortcuts_persist_same_preferences_as_dialog(self):
        w = self.desktop()
        w.set_pearl_matrix(not w.config.oracle.pearl_matrix_enabled)
        w.set_pearl_orbits(not w.config.oracle.pearl_orbits_enabled)
        w.drag_action.trigger()
        w.scale_actions[2.].trigger()
        w.configure_voice(enabled=False)
        w.configure_voice(volume=.5)
        saved = self.store.load()
        self.assertTrue(saved.oracle.pearl_matrix_enabled)
        self.assertTrue(saved.oracle.pearl_orbits_enabled)
        self.assertTrue(saved.interaction.drag_enabled)
        self.assertEqual(saved.desktop.scale, 2.)
        self.assertFalse(saved.audio.enabled)
        self.assertEqual(saved.audio.volume, .5)

    def test_changing_game_directory_replaces_assets_only_after_preparation(self):
        w = self.desktop()
        new_game = self.config.game_dir.parent/'另一个游戏'
        (new_game/'RainWorld_Data').mkdir(parents=True)
        (new_game/'RainWorld_Data/resources.assets').write_bytes(b'fixture')
        new_assets = OracleAssets(OracleRenderer(), 'new assets', {'bell': new_game/'voice.wav'}, '')
        w.settings_action.trigger()
        d = w.settings_dialog
        d.game_dir.setText(str(new_game))
        with patch('rw_creature_pet.oracle.ui.settings.prepare_oracle_assets', return_value=new_assets):
            d.save()
            self.assertIs(w.renderer, self.assets.renderer)
            self.wait_worker(d)
        self.assertIs(w.renderer, new_assets.renderer)
        self.assertEqual(w.voice_player.clips, new_assets.voice_paths)
        self.assertEqual(self.store.load().game_dir, new_game)

    def test_reset_game_directory_prepares_defaults_assets_before_applying(self):
        w = self.desktop()
        new_game = self.config.game_dir.parent/'默认游戏'
        (new_game/'RainWorld_Data').mkdir(parents=True)
        (new_game/'RainWorld_Data/resources.assets').touch()
        defaults = replace(self.config, game_dir=new_game)
        new_assets = OracleAssets(OracleRenderer(), 'default assets', {}, '')
        w.open_settings()
        d = w.settings_dialog
        with patch('rw_creature_pet.oracle.ui.settings.load_defaults', return_value=defaults):
            d.reset_all_button.click()
        self.assertEqual(d.game_dir.text(), str(new_game))
        self.assertIs(w.renderer, self.assets.renderer)
        with patch('rw_creature_pet.oracle.ui.settings.prepare_oracle_assets', return_value=new_assets) as prepare:
            d.save()
            self.assertIs(w.renderer, self.assets.renderer)
            self.wait_worker(d)
        prepare.assert_called_once_with(defaults)
        self.assertIs(w.renderer, new_assets.renderer)
        self.assertEqual(self.store.load().game_dir, new_game)
