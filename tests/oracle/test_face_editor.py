"""面部草稿、实时预览、恢复默认与保存边界"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from copy import deepcopy
from dataclasses import replace
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
from rw_creature_pet.oracle.graphics.face_assets import face_image, read_face_png
from rw_creature_pet.oracle.ui.settings import OracleSettingsDialog
from rw_creature_pet.settings_store import SettingsStore
from rw_creature_pet.presets.personal import PersonalState
from rw_creature_pet.presets.startup import CharacterInitialization
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
        saved = self.store.load().oracle.custom_appearance.face
        self.assertEqual(replace(saved, image_path=decal.image_path), decal)
        self.assertEqual(Path(saved.image_path).read_bytes(), Path(decal.image_path).read_bytes())
        self.assertEqual(d.original.oracle.custom_appearance.face, saved)
        with patch('rw_creature_pet.oracle.ui.settings.load_defaults', return_value=self.config):
            d.restore_defaults(d.tabs.indexOf(d.pages['appearance']))
        self.assertEqual(editor.value(), FaceDecal())
        self.assertEqual(self.store.load().oracle.custom_appearance.face, saved)
        d.reject()
        self.assertEqual(self.store.load().oracle.custom_appearance.face, saved)

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

    def test_fixed_body_does_not_read_hidden_custom_images_but_switching_back_reports_missing(self):
        d = self.dialog
        d.open_face_preview()
        d.controls['oracle.body_appearance'].setValue('bell')
        self.app.processEvents()
        missing = FaceDecal(enabled=True, image_path=str(self.root/'removed-generation/mark.png'))
        face_image.cache_clear()
        with patch('rw_creature_pet.oracle.graphics.face_assets.read_face_png', wraps=read_face_png) as read:
            d.face_editors['forehead'].setValue(missing)
            language_manager().set_language('en')
            self.app.processEvents()
            read.assert_not_called()
            self.assertEqual(d.face_editors['forehead'].value(), missing)
            self.assertFalse(d.face_editors['forehead'].message.text())
            with self.assertLogs('rw_creature_pet.oracle.graphics.face_assets', level='WARNING'):
                d.controls['oracle.body_appearance'].setValue('custom')
            self.assertTrue(read.called)
            self.assertTrue(d.face_editors['forehead'].message.text())

    def test_reopening_uses_committed_image_paths_before_constructing_editors(self):
        d = self.dialog
        d.face_editors['forehead'].import_file(self.source)
        d.save(close=False)
        current = self.store.load()
        invalid = replace(current.oracle.custom_appearance.forehead,
                          image_path=str(self.root/'removed-generation/mark.png'))
        stale = replace(current, oracle=replace(current.oracle,
                        custom_appearance=replace(current.oracle.custom_appearance, forehead=invalid)))
        init = CharacterInitialization(stale, PersonalState(self.store.load_preset_state()))
        face_image.cache_clear()
        extra = None
        try:
            with patch('rw_creature_pet.oracle.graphics.face_assets.read_face_png', wraps=read_face_png) as read:
                extra = OracleSettingsDialog(stale, self.store, assets=self.assets, initialization=init)
                self.assertNotIn(invalid.image_path, [str(call.args[0]) for call in read.call_args_list])
                self.assertEqual(extra.face_editors['forehead'].value(), current.oracle.custom_appearance.forehead)
        finally:
            if extra:
                extra.shutdown()
                extra.deleteLater()

    def test_explicit_save_stabilizes_inactive_image_paths_for_runtime(self):
        d = self.dialog
        d.face_editors['forehead'].import_file(self.source)
        d.save(close=False)
        d.controls['oracle.body_appearance'].setValue('bell')
        config, entry, state = d.preset_workflow.prepare_commit(d.candidate())
        path = Path(config.oracle.custom_appearance.forehead.image_path)
        self.assertEqual(path.parent, d.preset_workflow.directory)
        self.assertTrue(path.is_file())

    def test_all_hidden_image_editors_preserve_values_without_loading(self):
        d = self.dialog
        for body in ('bell', 'prince'):
            d.controls['oracle.body_appearance'].setValue(body)
            with patch('rw_creature_pet.oracle.graphics.face_assets.read_face_png') as read:
                for editor in d.image_editors:
                    prior = editor.value()
                    changes = dict(enabled=True, image_path=str(self.root/'absent.png'))
                    if hasattr(prior, 'kind'):
                        changes['kind'] = 'png'
                    expected = replace(prior, **changes)
                    editor.setValue(expected)
                    editor.refresh()
                    self.assertEqual(editor.value(), expected)
                    self.assertFalse(editor.message.text())
                read.assert_not_called()

    def test_install_keeps_rebased_paths_after_atomic_profile_save(self):
        d = self.dialog
        d.face_editors['forehead'].import_file(self.source)
        d.save(close=False)
        workflow = d.preset_workflow
        workflow.state.autosave = True
        workflow.install(workflow.key, deepcopy(workflow.entry), d.candidate())
        self.assertEqual(d.original.oracle.custom_appearance.forehead,
                         workflow.applied.oracle.custom_appearance.forehead)
        self.assertEqual(d.face_editors['forehead'].value(),
                         workflow.applied.oracle.custom_appearance.forehead)
