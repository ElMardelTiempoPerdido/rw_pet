"""设置表单、资源准备和托盘保存后的真实场景更新。"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QPointF, QRect, Qt
from PySide6.QtGui import QColor, QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog
from rw_creature_pet.config import AppConfig
from rw_creature_pet.oracle.assets import OracleAssets
from rw_creature_pet.oracle.desktop import OracleDesktopWindow
from rw_creature_pet.oracle.render import OracleRenderer
from rw_creature_pet.oracle.settings import OracleSettingsDialog
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
        with patch('rw_creature_pet.oracle.settings.prepare_oracle_assets', side_effect=RuntimeError('bad atlas')):
            d.save()
            self.assertFalse(d.save_button.isEnabled())
            self.wait_worker(d)
        self.assertIn('bad atlas', d.status.text())
        self.assertFalse(self.store.path.exists())
        with patch('rw_creature_pet.oracle.settings.prepare_oracle_assets', return_value=self.assets):
            d.save()
            self.wait_worker(d)
        self.assertEqual(self.store.load(), self.config)
        self.assertEqual(d.result(), QDialog.DialogCode.Accepted)

    def desktop(self):
        with patch('rw_creature_pet.oracle.desktop.QSystemTrayIcon.isSystemTrayAvailable', return_value=True):
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
        self.assertFalse(w.motion.scene.behavior.enabled)
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
        d.controls['oracle.glow_enabled'].setChecked(True)
        self.assertTrue(color.isEnabled())
        with patch('rw_creature_pet.oracle.settings.QColorDialog.getColor', return_value=QColor('#73ddff')):
            color.choose_color()
        with patch('rw_creature_pet.oracle.settings.QColorDialog.getColor', return_value=QColor()):
            color.choose_color()
        self.assertEqual(color.value(), '#73ddff')
        d.controls['oracle.glow_radius'].setValue(9.)
        d.save()
        self.assertIs(w.motion.scene, scene)
        self.assertTrue(scene.behavior.drift_active)
        self.assertTrue(scene.config.glow_enabled)
        saved = self.store.load()
        self.assertEqual(saved.oracle.glow_color, '#73ddff')
        self.assertEqual(saved.oracle.glow_radius, 9.)
        w.open_settings()
        self.assertEqual(w.settings_dialog.controls['oracle.glow_color'].value(), '#73ddff')

    def test_small_workarea_keeps_save_buttons_visible(self):
        d = self.dialog(assets=self.assets)
        d.fit_workarea(QRect(-800, 0, 800, 480))
        self.app.processEvents()
        self.assertLessEqual(d.height(), 450)
        self.assertTrue(d.rect().contains(d.save_button.mapTo(d, d.save_button.rect().bottomRight())))

    def test_wheel_scrolls_page_without_changing_focused_or_unfocused_numbers(self):
        d = self.dialog(assets=self.assets)
        d.fit_workarea(QRect(0, 0, 800, 480))
        d.tabs.setCurrentIndex(3)
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
        with patch('rw_creature_pet.oracle.settings.prepare_oracle_assets', return_value=new_assets):
            d.save()
            self.assertIs(w.renderer, self.assets.renderer)
            self.wait_worker(d)
        self.assertIs(w.renderer, new_assets.renderer)
        self.assertEqual(w.voice_player.clips, new_assets.voice_paths)
        self.assertEqual(self.store.load().game_dir, new_game)
