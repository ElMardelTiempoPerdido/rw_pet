"""语言选择、旧配置升级以及三个桌面界面的原位切换。"""
import json
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from PySide6.QtCore import QCoreApplication, QEvent, QRect
from PySide6.QtWidgets import QApplication, QDialogButtonBox

from rw_creature_pet.config import AppConfig
from rw_creature_pet.i18n import TRANSLATIONS, language_manager, tr
from rw_creature_pet.oracle.assets import OracleAssets
from rw_creature_pet.oracle.desktop import OracleDesktopWindow
from rw_creature_pet.oracle.render import OracleRenderer
from rw_creature_pet.oracle.settings import OracleSettingsDialog
from rw_creature_pet.settings_store import SettingsStore
from rw_creature_pet.shared.messages import Message
from rw_creature_pet.ui_config import UiConfig, system_language
from tests.oracle.test_desktop import FakeScreen
from tools.update_translations import placeholders, sources


class LanguageConfigTests(unittest.TestCase):
    def test_default_uses_primary_ui_language_not_region_or_fallback_languages(self):
        for tags, expected in ((['zh-Hans-CN', 'en-US'], 'zh'), (['zh-Hant-TW'], 'zh'),
                               (['zh_HK'], 'zh'), (['zh-SG'], 'zh'), (['en-CN', 'zh-Hans'], 'en'),
                               (['ja-JP'], 'en'), (['de-DE'], 'en'), ([], 'en')):
            with self.subTest(tags=tags), patch('PySide6.QtCore.QLocale.system') as locale:
                locale.return_value.uiLanguages.return_value = tags
                self.assertEqual(system_language(), expected)
                self.assertEqual(UiConfig().language, expected)
        with patch('rw_creature_pet.ui_config.system_language', side_effect=OSError):
            self.assertEqual(UiConfig().language, 'en')
            self.assertEqual(UiConfig('zh').language, 'zh')

    def test_old_profile_gets_concrete_language_once_and_keeps_user_values(self):
        with tempfile.TemporaryDirectory() as temp:
            store = SettingsStore(Path(temp)/'settings.json')
            old = {'version': 1, 'config': {'desktop': {'scale': 1.5}, 'audio': {'volume': .12345}}}
            store.path.write_text(json.dumps(old), encoding='utf-8')
            with patch('rw_creature_pet.settings_store.default_template_path', return_value=None):
                with patch('rw_creature_pet.ui_config.system_language', return_value='en'):
                    config, first, message = store.startup()
                self.assertEqual((first, message, config.ui.language), (False, '', 'en'))
                self.assertEqual(config.desktop.scale, 1.5)
                self.assertEqual(config.audio.volume, .12345)
                self.assertEqual(json.loads(store.path.read_text())['config']['ui'], {'language': 'en'})
                self.assertEqual(json.loads(store.path.with_suffix('.json.bak').read_text()), old)
                stamp = store.path.stat().st_mtime_ns
                with patch('rw_creature_pet.ui_config.system_language', return_value='zh'):
                    self.assertEqual(store.startup()[0].ui.language, 'en')
                self.assertEqual(store.path.stat().st_mtime_ns, stamp)

    def test_auto_in_existing_profile_is_resolved_and_invalid_language_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            store = SettingsStore(Path(temp)/'settings.json')
            store.path.write_text(json.dumps({'version': 1, 'config': {'ui': {'language': 'auto'}}}), encoding='utf-8')
            with patch('rw_creature_pet.ui_config.system_language', return_value='zh'):
                self.assertEqual(store.startup()[0].ui.language, 'zh')
            self.assertEqual(json.loads(store.path.read_text())['config']['ui']['language'], 'zh')
        for invalid in ('fr', None, 1):
            with self.assertRaises(ValueError):
                UiConfig(invalid)


class TranslationUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyle('Fusion')
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root/'RainWorld_Data').mkdir()
        (self.root/'RainWorld_Data/resources.assets').write_bytes(b'fixture')
        self.config = AppConfig(game_dir=self.root, ui=UiConfig('zh'))
        self.store = SettingsStore(self.root/'settings.json')
        self.assets = OracleAssets(OracleRenderer(), '', {}, '')
        self.windows = []
        language_manager().set_language('zh')

    def tearDown(self):
        for window in self.windows:
            window.close()
            window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()
        language_manager().set_language('zh')
        self.app.processEvents()

    def dialog(self, language='zh', **kwargs):
        d = OracleSettingsDialog(replace(self.config, ui=UiConfig(language)), self.store, assets=self.assets, **kwargs)
        self.windows.append(d)
        d.show()
        self.flush()
        return d

    def desktop(self):
        with patch('rw_creature_pet.oracle.desktop.QSystemTrayIcon.isSystemTrayAvailable', return_value=True):
            w = OracleDesktopWindow(self.config, config_store=self.store, assets=self.assets)
        w.timer.stop()
        w.bind_screen(FakeScreen(QRect(0, 0, 1280, 720), 1.))
        self.windows.append(w)
        return w

    def flush(self):
        for _ in range(3):
            self.app.processEvents()

    def test_catalog_covers_sources_and_compiled_text_matches_ts(self):
        language_manager().set_language('en')
        catalog = {m.findtext('source'): m.findtext('translation')
                   for m in ET.parse(TRANSLATIONS/'en.ts').findall('./context/message')}
        self.assertEqual(set(sources()), set(catalog))
        for source, target in catalog.items():
            with self.subTest(source=source):
                self.assertTrue(target)
                self.assertEqual(placeholders(source), placeholders(target))
                self.assertEqual(tr(source), target)

    def test_deferred_errors_keep_parameters_and_can_be_retranslated(self):
        from rw_creature_pet.overseer.config import OverseerConfig
        with self.assertRaises(ValueError) as error:
            OverseerConfig(duration_min=100, duration_max=2)
        message = Message('保存失败：{error}', error=error.exception)
        language_manager().set_language('en')
        self.assertIn('overseer.duration_min must not exceed duration_max', tr(message))
        self.assertNotIn('不能', tr(message))
        language_manager().set_language('zh')
        self.assertIn('保存失败', tr(message))

    def test_form_switch_keeps_dirty_values_tab_scroll_and_pending_save_language(self):
        d = self.dialog()
        d.fit_workarea(QRect(0, 0, 800, 480))
        d.tabs.setCurrentIndex(1)
        d.controls['oracle.pearl_matrix_enabled'].setChecked(True)
        d.controls['oracle.pearl_matrix_count'].setValue(23)
        d.controls['oracle.pearl_bubble_color'].setValue('#123456')
        d.game_dir.setText(str(self.root))
        self.flush()
        bar = d.tabs.currentWidget().verticalScrollBar()
        bar.setValue(40)
        scroll = bar.value()
        controls = dict(d.controls)
        d.pending = d.candidate()
        language_manager().set_language('en')
        self.flush()
        self.assertEqual(d.tabs.currentIndex(), 1)
        self.assertEqual(bar.value(), scroll)
        self.assertEqual(d.controls, controls)
        self.assertEqual(d.controls['oracle.pearl_matrix_count'].value(), 23)
        self.assertEqual(d.controls['oracle.pearl_bubble_color'].value(), '#123456')
        self.assertEqual(d.game_dir.text(), str(self.root))
        self.assertEqual(d.pending.ui.language, 'en')
        self.assertEqual(d.candidate().ui.language, 'en')
        self.assertEqual(d.save_button.text(), tr('保存并应用'))
        self.assertEqual(d.buttons.button(QDialogButtonBox.StandardButton.Cancel).text(), 'Cancel')
        for _, source in d._texts.bindings:
            self.assertNotEqual(tr(source), source, source)
        d.save()
        self.assertEqual(self.store.load().ui.language, 'en')
        self.assertEqual(self.store.load().oracle.pearl_matrix_count, 23)

    def test_initial_english_and_validation_and_failed_save_messages(self):
        d = self.dialog('en', first_run=True)
        self.assertEqual(d.windowTitle(), 'Bell · First-time Setup')
        self.assertEqual(d.tabs.tabText(1), 'Pearls')
        for edge, button in d.edge_checks.items():
            button.setChecked(edge in ('top', 'bottom'))
        d.save()
        self.assertIn('connected', d.status.text())
        language_manager().set_language('zh')
        self.flush()
        self.assertIn('连续', d.status.text())
        for edge, button in d.edge_checks.items():
            button.setChecked(edge in self.config.oracle.allowed_edges)
        language_manager().set_language('en')
        with patch.object(self.store, 'save', side_effect=PermissionError('locked')):
            d.save()
        self.assertEqual(d.status.text(), 'Could not save: locked')

    def test_expanding_english_dialog_stays_inside_small_workarea(self):
        d = self.dialog()
        rect = QRect(-800, 0, 800, 480)
        d.fit_workarea(rect)
        self.flush()
        self.assertTrue(rect.contains(d.frameGeometry()))
        language_manager().set_language('en')
        self.flush()
        self.assertTrue(rect.contains(d.frameGeometry()), d.frameGeometry())

    def test_tray_switch_preserves_scene_pause_and_toolbar_feedback(self):
        w = self.desktop()
        w.set_toolbar_visible(True)
        w.trigger_toolbar_action('pulse')
        w.pause_action.trigger()
        scene, appearance = w.motion.scene, w.motion.scene.appearance
        state = (scene.body.chunks[0].position, scene.halo.pulse_ticks, scene.behavior.enabled)
        w.language_actions['en'].trigger()
        self.flush()
        self.assertIs(w.motion.scene, scene)
        self.assertIs(w.motion.scene.appearance, appearance)
        self.assertEqual(state, (scene.body.chunks[0].position, scene.halo.pulse_ticks, scene.behavior.enabled))
        self.assertTrue(w.clock.paused)
        self.assertEqual(w.pause_action.text(), 'Resume')
        self.assertEqual(w.language_menu.title(), '语言/language')
        self.assertTrue(w.language_actions['en'].isChecked())
        self.assertFalse(w.language_actions['zh'].isChecked())
        self.assertEqual(self.store.load().ui.language, 'en')
        self.assertIn('paused', w.action_toolbar.status.text())
        w.pause_action.trigger()
        self.assertEqual(w.action_toolbar.status.text(), 'Halo expansion triggered.')
        self.assertIn('Settings > Pearls', w.action_toolbar.buttons['matrix'].toolTip())
        self.assertTrue(w.screen.availableGeometry().contains(w.action_toolbar.frameGeometry()))

    def test_language_save_failure_restores_choice_and_unsaved_settings(self):
        w = self.desktop()
        self.store.save(self.config)
        old = self.store.path.read_bytes()
        w.open_settings()
        d = w.settings_dialog
        d.controls['audio.volume'].setValue(42)
        with patch.object(self.store, 'save', side_effect=PermissionError('locked')), patch.object(w.tray, 'showMessage') as warning:
            w.language_actions['en'].trigger()
        self.flush()
        warning.assert_called_once()
        self.assertEqual(language_manager().language, 'zh')
        self.assertEqual(w.config.ui.language, 'zh')
        self.assertTrue(w.language_actions['zh'].isChecked())
        self.assertEqual(d.candidate().ui.language, 'zh')
        self.assertEqual(d.controls['audio.volume'].value(), 42)
        self.assertEqual(self.store.path.read_bytes(), old)

    def test_missing_catalog_does_not_remove_current_translator(self):
        language_manager().set_language('zh')
        with patch('rw_creature_pet.i18n.TRANSLATIONS', self.root), self.assertRaises(RuntimeError):
            language_manager().set_language('en')
        self.assertEqual(language_manager().language, 'zh')
        self.assertEqual(tr('取消'), '取消')


if __name__ == '__main__':
    unittest.main()
