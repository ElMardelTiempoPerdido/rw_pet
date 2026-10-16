"""面部草稿、实时预览、恢复默认与保存边界"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

from rw_creature_pet.config import AppConfig
from rw_creature_pet.i18n import language_manager
from rw_creature_pet.oracle.assets import OracleAssets
from rw_creature_pet.oracle.config import OracleConfig
from rw_creature_pet.oracle.face_config import FaceDecal
from rw_creature_pet.oracle.graphics.render import OracleRenderer
from rw_creature_pet.oracle.ui.settings import OracleSettingsDialog
from rw_creature_pet.settings_store import SettingsStore
from tests.oracle.character_fixture import isolate_characters


class FaceEditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        isolate_characters(self, self.root)
        (self.root/'RainWorld_Data').mkdir()
        (self.root/'RainWorld_Data/resources.assets').touch()
        self.config = AppConfig(game_dir=self.root, oracle=OracleConfig(body_appearance='custom'))
        self.store = SettingsStore(self.root/'settings.json')
        self.store.save(self.config)
        self.assets = OracleAssets(OracleRenderer(), '', {}, '')
        self.dialog = OracleSettingsDialog(self.config, self.store, assets=self.assets)
        self.source = self.root/'头部.png'
        image = QImage(5, 3, QImage.Format.Format_ARGB32)
        image.fill(QColor('#ff0000'))
        image.save(str(self.source))

    def tearDown(self):
        self.dialog.shutdown()
        self.dialog.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()
        language_manager().set_language('zh')

    def test_preview_tracks_unsaved_edits_and_keeps_live_renderer_and_settings_unchanged(self):
        self.dialog.personal_controls.autosave.setChecked(False)
        before = self.store.path.read_bytes()
        d = self.dialog
        d.open_face_preview()
        preview = d.face_preview
        plain = preview.actual.image.copy()
        editor = d.face_editors['forehead']
        self.assertTrue(editor.import_file(self.source))
        self.app.processEvents()
        self.assertNotEqual(preview.actual.image, plain)
        self.assertIsNot(preview.renderer, self.assets.renderer)
        self.assertIsNone(self.assets.renderer._head_image)
        self.assertFalse(self.config.oracle.custom_appearance.forehead.enabled)
        self.assertEqual(self.store.path.read_bytes(), before)
        first = preview.actual.image.copy()
        editor.x_input.setValue(2.)
        self.app.processEvents()
        self.assertNotEqual(preview.actual.image, first)
        for index, scale in enumerate((1., 1.5, 2.)):
            preview.scale.setCurrentIndex(index)
            self.assertEqual(preview.actual.image.width(), round(64*scale))
            for view in range(5):
                preview.view.setCurrentIndex(view)
                closed = preview.actual.image.copy()
                preview.eye_state.setCurrentIndex(preview.eye_state.findData('open'))
                self.assertNotEqual(preview.actual.image, closed)
                self.assertEqual(preview.renderer._head_image, preview.magnified.image)
                preview.eye_state.setCurrentIndex(preview.eye_state.findData('default'))
        d.reject()
        self.assertFalse(preview.isVisible())
        self.assertEqual(self.store.path.read_bytes(), before)

    def test_failed_import_keeps_previous_image_and_clear_keeps_offsets(self):
        editor = self.dialog.face_editors['face']
        self.assertTrue(editor.import_file(self.source))
        editor.x_input.setValue(1.25)
        prior = editor.value()
        bad = self.root/'invalid.png'
        bad.write_bytes(b'bad')
        self.assertFalse(editor.import_file(bad))
        self.assertEqual(editor.value(), prior)
        self.assertTrue(editor.message.text())
        editor.clear_button.click()
        self.assertEqual(editor.value(), FaceDecal(offset_x=1.25))

    def test_save_roundtrip_reset_and_bell_switch_preserve_independent_data(self):
        d = self.dialog
        d.personal_controls.autosave.setChecked(False)
        editor = d.face_editors['face']
        editor.import_file(self.source)
        editor.x_input.setValue(-1.25)
        decal = editor.value()
        d.controls['oracle.body_appearance'].setValue('bell')
        self.assertEqual(d.candidate().oracle.custom_appearance.face, decal)
        d.controls['oracle.body_appearance'].setValue('custom')
        d.save(close=False)
        self.assertEqual(self.store.load().oracle.custom_appearance.face, decal)
        self.assertEqual(d.original.oracle.custom_appearance.face, decal)
        with patch('rw_creature_pet.oracle.ui.settings.load_defaults', return_value=self.config):
            d.restore_defaults(d.tabs.indexOf(d.pages['appearance']))
        self.assertEqual(editor.value(), FaceDecal())
        self.assertEqual(self.store.load().oracle.custom_appearance.face, decal)
        d.reject()
        self.assertEqual(self.store.load().oracle.custom_appearance.face, decal)

    def test_enabled_missing_file_blocks_custom_save_but_not_bell(self):
        d = self.dialog
        editor = d.face_editors['face']
        editor.enabled.setChecked(True)
        with self.assertRaises(ValueError):
            d.candidate()
        editor.import_file(self.source)
        Path(editor.value().image_path).unlink()
        with self.assertRaises(OSError):
            d.candidate()
        d.controls['oracle.body_appearance'].setValue('bell')
        self.assertEqual(d.candidate().oracle.body_appearance, 'bell')

    def test_preview_does_not_require_game_assets_and_translates_without_losing_filename(self):
        d = self.dialog
        d.game_dir.setText(str(self.root/'no-game'))
        d.face_editors['face'].import_file(self.source)
        d.open_face_preview()
        language_manager().set_language('en')
        self.app.processEvents()
        self.assertEqual(d.face_preview.windowTitle(), 'Adjust Face in Preview Window')
        self.assertEqual(d.face_preview.view.itemText(0), 'Front')
        self.assertEqual(d.face_editors['face'].import_button.text(), 'Import PNG')
        self.assertIn('头部.png', d.face_editors['face'].file_label.text())
        language_manager().set_language('zh')
        self.assertEqual(d.face_preview.view.itemText(0), '正面')
        self.assertIn('头部.png', d.face_editors['face'].file_label.text())
