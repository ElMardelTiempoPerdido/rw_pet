"""多屏设置：设备身份、保存/重启、热插拔、混合 DPI 与负坐标。"""
import json
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QRect
from PySide6.QtWidgets import QApplication, QDialog

from rw_creature_pet.config import AppConfig, DesktopConfig
from rw_creature_pet.i18n import language_manager, tr
from rw_creature_pet.oracle.assets import OracleAssets
from rw_creature_pet.oracle.ui.desktop import OracleDesktopWindow
from rw_creature_pet.oracle.graphics.render import OracleRenderer
from rw_creature_pet.oracle.ui.settings import OracleSettingsDialog
from rw_creature_pet.settings_store import SettingsStore
from rw_creature_pet.shared.screens import find_screen, preferred_screen, screen_key
from tests.oracle.test_desktop import FakeScreen


class Monitor(FakeScreen):
    def __init__(self, name, rect, dpr=1., serial=''):
        super().__init__(rect, dpr)
        self.display_name, self.serial = name, serial

    def name(self):
        return self.display_name

    def manufacturer(self):
        return 'Test'

    def model(self):
        return 'Monitor'

    def serialNumber(self):
        return self.serial


class ScreenSelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        game = root/'游戏'
        (game/'RainWorld_Data').mkdir(parents=True)
        (game/'RainWorld_Data/resources.assets').touch()
        self.config = AppConfig(game_dir=game)
        self.store = SettingsStore(root/'settings.json')
        self.assets = OracleAssets(OracleRenderer(), '', {}, '')
        self.a = Monitor('DISPLAY1', QRect(0, 0, 1600, 900), serial='A')
        self.b = Monitor('DISPLAY2', QRect(-1280, -40, 1280, 680), 1.5, 'B')
        self.screens, self.primary = [self.a, self.b], self.a
        self.enterContext(patch.object(QApplication, 'screens', side_effect=lambda: self.screens.copy()))
        self.enterContext(patch.object(QApplication, 'primaryScreen', side_effect=lambda: self.primary))
        self.enterContext(patch('rw_creature_pet.oracle.ui.desktop.QSystemTrayIcon.isSystemTrayAvailable', return_value=True))
        self.windows = []

    def tearDown(self):
        for window in reversed(self.windows):
            window.close()
            window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()

    def desktop(self, config=None):
        window = OracleDesktopWindow(config or self.config, assets=self.assets, config_store=self.store)
        window.timer.stop()
        self.windows.append(window)
        return window

    def dialog(self, config=None, **kwargs):
        dialog = OracleSettingsDialog(config or self.config, self.store, assets=self.assets, **kwargs)
        self.windows.append(dialog)
        return dialog

    def test_identity_survives_order_port_and_primary_changes(self):
        key = screen_key(self.b)
        self.b.display_name = 'DISPLAY9'
        self.assertIs(find_screen([self.b, self.a], key), self.b)
        self.assertIs(preferred_screen([self.b, self.a], self.a, key), self.b)
        self.assertIs(preferred_screen([self.a], self.a, key), self.a)
        self.assertIsNone(preferred_screen([], None, key))
        # 新设备占用同一系统名称，不能冒充已断开的有序列号设备。
        self.a.display_name = 'DISPLAY2'
        self.assertIsNone(find_screen([self.a], key))
        self.a.serial = ''
        name_key = screen_key(self.a)
        self.assertIs(find_screen([self.a], name_key), self.a)
        self.assertIs(find_screen([self.a], 'DISPLAY2'), self.a)

    def test_save_is_transactional_and_restart_uses_selected_display(self):
        window = self.desktop()
        window.set_paused(True)
        old_motion, old_rect = window.motion, window.geometry()
        dialog = self.dialog(commit=window.apply_settings)
        combo = dialog.controls['desktop.screen']
        key = screen_key(self.b)
        combo.setCurrentIndex(combo.findData(key))
        dialog.controls['oracle.edge_fraction'].setValue(25.)
        dialog.controls['desktop.scale'].setCurrentIndex(1)
        self.assertIs(window.screen, self.a)  # 选择后、保存前仍留在原屏。
        with patch.object(self.store, 'save', side_effect=PermissionError('locked')):
            dialog.save()
        self.assertIs(window.motion, old_motion)
        self.assertEqual(window.geometry(), old_rect)
        self.assertEqual(combo.currentData(), key)
        dialog.save()
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        self.assertIs(window.screen, self.b)
        self.assertEqual(window.geometry(), self.b.rect)
        self.assertTrue(window.clock.paused)
        self.assertEqual(window.motion.scene.config.edge_fraction, .25)
        self.assertEqual(window.motion.viewport.dpr, 1.5)
        self.assertEqual(window.motion.viewport.scale, 1.)
        point = window.motion.scene.body.chunks[0].position
        self.assertEqual(window.motion.viewport.to_world(window.motion.viewport.to_global(point)), point)
        self.assertTrue(window.motion.scene.body_region.contains(point))
        self.assertEqual(window.overseers.layers[1].viewport, window.motion.viewport)
        window.set_paused(False)
        window.drag_action.setChecked(True)
        window.sync_drag_input()
        self.assertEqual(window.drag_input.viewport, window.motion.viewport)
        self.assertTrue(window.geometry().contains(window.drag_input.geometry()))
        self.assertEqual(self.store.load().desktop.screen, key)
        window.close()
        self.screens.reverse()
        restarted = self.desktop(self.store.load())
        self.assertIs(restarted.screen, self.b)
        self.assertEqual(restarted.geometry(), self.b.rect)

    def test_hotplug_keeps_preference_and_reconnect_returns_without_restarting(self):
        key = screen_key(self.b)
        config = replace(self.config, desktop=replace(self.config.desktop, screen=key))
        self.store.save(config)
        window = self.desktop(config)
        window.set_paused(True)
        # 列表尚未移除旧对象也应立即回退；旧屏幕信号已经断开。
        window.screen_removed(self.b)
        self.assertIs(window.screen, self.a)
        window.rebuild_timer.stop()
        self.b.availableGeometryChanged.emit(self.b.rect)
        self.assertFalse(window.rebuild_timer.isActive())
        self.screens = [self.a]
        window.persist_settings()
        self.assertEqual(self.store.load().desktop.screen, key)
        dialog = self.dialog(window.current_settings())
        combo = dialog.controls['desktop.screen']
        self.assertEqual(combo.currentData(), key)
        self.assertIn(tr('未连接：{name}', name=self.b.name()), combo.currentText())
        self.b.display_name = 'DISPLAY7'
        self.screens = [self.b, self.a]
        window.select_screen()
        combo.refresh()
        self.assertIs(window.screen, self.b)
        self.assertEqual(combo.currentData(), key)
        self.assertTrue(window.clock.paused)
        # 改主屏不抢走显式指定的设备。
        self.primary = self.a
        window.select_screen()
        self.assertIs(window.screen, self.b)
        self.screens, self.primary = [], None
        window.select_screen()
        self.assertFalse(window._screen_valid)
        self.screens, self.primary = [self.a, self.b], self.a
        window.select_screen()
        self.assertIs(window.screen, self.b)
        self.assertTrue(window._screen_valid)

    def test_auto_primary_updates_and_origin_only_change_keeps_motion(self):
        window = self.desktop()
        self.primary = self.b
        window.select_screen()
        self.assertIs(window.screen, self.b)
        scene = window.motion.scene
        self.b.rect.translate(-300, 200)
        window.rebuild()
        self.assertIs(window.motion.scene, scene)
        self.assertEqual(window.geometry(), self.b.rect)
        self.assertEqual(window.config.desktop.screen, '')

    def test_combo_shares_row_preserves_draft_translation_and_resets_with_page(self):
        language = language_manager().language
        self.addCleanup(language_manager().set_language, language)
        dialog = self.dialog()
        dialog.show()
        index = next(i for i in range(dialog.tabs.count()) if dialog.tabs.tabText(i) == tr('移动'))
        dialog.tabs.setCurrentIndex(index)
        self.app.processEvents()
        combo = dialog.controls['desktop.screen']
        band = dialog.controls['oracle.edge_fraction']
        self.assertLess(abs(combo.mapTo(dialog, combo.rect().center()).y()-band.mapTo(dialog, band.rect().center()).y()), 3)
        self.assertGreater(combo.mapTo(dialog, QPoint()).x(), band.mapTo(dialog, QPoint()).x())
        key = screen_key(self.b)
        combo.setCurrentIndex(combo.findData(key))
        language_manager().set_language('en')
        self.assertEqual(combo.currentData(), key)
        self.assertEqual(combo.itemText(0), 'Primary (automatic)')
        self.screens = [self.a]
        combo.screen_removed(self.b)
        self.assertEqual(dialog.candidate().desktop.screen, key)
        dialog.restore_defaults(index)
        self.assertEqual(dialog.candidate().desktop.screen, '')
        self.assertFalse(self.store.path.exists())

    def test_missing_field_upgrade_preserves_user_values_and_validates_type(self):
        self.store.path.write_text(json.dumps({'version': 1, 'config': {
            'game_dir': str(self.config.game_dir), 'desktop': {'scale': 2., 'autonomous': False}
        }}), encoding='utf-8')
        config, first, error = self.store.startup()
        self.assertFalse(first)
        self.assertEqual(error, '')
        self.assertEqual(config.desktop, DesktopConfig(2., False, ''))
        self.assertEqual(json.loads(self.store.path.read_text(encoding='utf-8'))['config']['desktop']['screen'], '')
        for value in (0, False, None, []):
            with self.assertRaises(ValueError):
                DesktopConfig(screen=value)

    def test_space_recommendation_is_draft_only_and_applies_true_four_times(self):
        self.a.rect, self.a.dpr = QRect(0, 0, 1707, 1027), 1.5
        config = replace(self.config, oracle=replace(self.config.oracle, arm_scale=.75),
                         desktop=replace(self.config.desktop, scale=4.))
        dialog = self.dialog(config)
        self.assertFalse(dialog.space_panel.isHidden())
        self.assertFalse(dialog.space_assessment().valid)
        self.assertAlmostEqual(dialog.controls['oracle.edge_fraction'].maximum(), 49.9)
        self.assertEqual(dialog.space_assessment().recommendation, (.75, .3))
        with self.assertRaises(ValueError):
            dialog.candidate()
        dialog.fill_space_recommendation()
        self.assertEqual(dialog.controls['oracle.arm_scale'].value(), 75.)
        self.assertEqual(dialog.controls['oracle.edge_fraction'].value(), 30.)
        self.assertFalse(self.store.path.exists())
        self.assertEqual(dialog.original.oracle.edge_fraction, .2)
        dialog.save()
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        saved = self.store.load()
        self.assertEqual(saved.oracle.edge_fraction, .3)
        self.assertEqual(saved.desktop.scale, 4.)
        window = OracleDesktopWindow(saved, scale=4., assets=self.assets, config_store=self.store)
        self.windows.append(window)
        window.timer.stop()
        self.assertEqual(window.motion.viewport.physical_scale, 4.)
        self.assertAlmostEqual(window.motion.scene.world.height, 385.125)

    def test_space_hint_tracks_target_screen_resize_and_translation(self):
        self.a.rect, self.a.dpr = QRect(0, 0, 1707, 1027), 1.5
        self.b.rect, self.b.dpr = QRect(-3000, 0, 3000, 2000), 1.
        dialog = self.dialog(replace(self.config, desktop=replace(self.config.desktop, scale=4.)))
        combo = dialog.controls['desktop.screen']
        self.assertFalse(dialog.space_panel.isHidden())
        combo.setCurrentIndex(combo.findData(screen_key(self.b)))
        self.assertTrue(dialog.space_panel.isHidden())
        self.b.rect.setHeight(1500)
        self.b.availableGeometryChanged.emit(self.b.rect)
        self.assertFalse(dialog.space_panel.isHidden())
        language = language_manager().language
        self.addCleanup(language_manager().set_language, language)
        language_manager().set_language('en')
        self.assertIn('logical pixels', dialog.space_hint.text())
        self.assertEqual(dialog.recommend_button.text(), 'Fill recommended settings')
        self.assertEqual(combo.currentData(), screen_key(self.b))
        dialog.show()
        for _ in range(3):
            self.app.processEvents()
        self.assertGreaterEqual(dialog.space_hint.height(), dialog.space_hint.heightForWidth(dialog.space_hint.width()))

    def test_tray_invalid_scale_opens_draft_and_resize_protection_preserves_saved_preferences(self):
        self.a.rect, self.a.dpr = QRect(0, 0, 1707, 1027), 1.5
        config = replace(self.config, oracle=replace(self.config.oracle, arm_scale=.75))
        window = self.desktop(config)
        self.store.save(config)
        window.change_scale(4.)
        self.assertEqual(window.requested_scale, 1.)
        self.assertEqual(self.store.load().desktop.scale, 1.)
        dialog = window.settings_dialog
        self.assertEqual(dialog.controls['desktop.scale'].currentData(), 4.)
        dialog.fill_space_recommendation()
        dialog.save()
        self.assertEqual(window.requested_scale, 4.)
        self.assertEqual(window.motion.viewport.physical_scale, 4.)
        persisted = self.store.path.read_bytes()
        self.a.rect.setHeight(500)
        with patch.object(window.tray, 'showMessage') as notice:
            window.rebuild()
            window.notify_space()
            count = notice.call_count
            window.notify_space()
            self.assertEqual(notice.call_count, count)
            self.assertGreater(count, 0)
        self.assertLess(window.motion.viewport.physical_scale, 4.)
        self.assertEqual(self.store.path.read_bytes(), persisted)
        self.assertEqual(window.config.oracle.edge_fraction, .3)
        self.a.rect.setHeight(1027)
        window.rebuild()
        self.assertEqual(window.motion.viewport.physical_scale, 4.)


if __name__ == '__main__':
    unittest.main()
