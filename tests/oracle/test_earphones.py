"""自定义耳机的几何、贴图、边界、缓存和双入口编辑"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from rw_creature_pet.config import AppConfig
from rw_creature_pet.i18n import language_manager
from rw_creature_pet.oracle.assets import OracleAssets
from rw_creature_pet.oracle.config import CustomAppearance, OracleConfig
from rw_creature_pet.oracle.ear_config import EAR_PART_FIELDS, EarPart, ear_radius
from rw_creature_pet.oracle.graphics.damage import body_bounds
from rw_creature_pet.oracle.graphics.render import OracleRenderer
from rw_creature_pet.oracle.interaction.input import PuppetHitMap
from rw_creature_pet.oracle.scene import OracleScene
from rw_creature_pet.oracle.ui.settings import OracleSettingsDialog
from tests.oracle.character_fixture import isolate_characters
from rw_creature_pet.settings_store import SettingsStore
from rw_creature_pet.shared.geometry import Vec2


class EarphoneTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.windows = []

    def tearDown(self):
        for window in self.windows:
            window.shutdown()
            window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()
        language_manager().set_language('zh')

    def paint(self, renderer, shape, *, density=2., gaze=Vec2(), direction=Vec2(0, -1)):
        image = QImage(512, 512, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(0)
        painter = QPainter(image)
        try:
            painter.translate(256, 256)
            painter.scale(density, density)
            renderer.draw_head(painter, Vec2(), direction*-10, direction, gaze,
                               shape=shape, raster_scale=density, pixelated=True)
        finally:
            painter.end()
        return image

    def png(self):
        path = self.root/'耳机.png'
        image = QImage(3, 5, QImage.Format.Format_ARGB32)
        image.fill(0)
        for y in range(5):
            image.setPixelColor(0, y, QColor('#ff0000'))
            image.setPixelColor(1, y, QColor('#00ff00'))
        image.save(str(path))
        return path

    def dialog(self):
        (self.root/'RainWorld_Data').mkdir(exist_ok=True)
        (self.root/'RainWorld_Data/resources.assets').touch()
        config = AppConfig(game_dir=self.root, oracle=OracleConfig(body_appearance='custom'))
        store = SettingsStore(self.root/'settings.json')
        store.save(config)
        isolate_characters(self, store.path.parent)
        dialog = OracleSettingsDialog(config, store, assets=OracleAssets(OracleRenderer(), '', {}, ''))
        self.windows.append(dialog)
        dialog.open_face_preview()
        return dialog

    def test_config_limits_legacy_defaults_and_independent_roundtrip(self):
        for key, bad in (('kind', 'bad'), ('tone', 'bad'), ('width', 0), ('height', 33),
                          ('rotation', 181), ('offset_x', 33), ('width', float('nan')), ('height', True)):
            with self.subTest(key=key), self.assertRaises(ValueError):
                EarPart(**{key: bad})
        self.assertEqual(CustomAppearance.from_mapping({}), CustomAppearance())
        part = EarPart(enabled=True, kind='triangle', width=8.12345, height=9.12345, offset_x=1., rotation=45.)
        shape = CustomAppearance(ear_part_2=part)
        config = AppConfig(oracle=OracleConfig(custom_appearance=shape))
        store = SettingsStore(self.root/'settings.json')
        store.save(config)
        loaded = store.load().oracle
        self.assertEqual(loaded.custom_appearance.ear_part_2, part)
        self.assertIsNone(loaded.active_custom_appearance)
        self.assertEqual(replace(loaded, body_appearance='custom').active_custom_appearance, shape)

    def test_all_geometry_types_change_pixels_and_bell_stays_identical(self):
        renderer = OracleRenderer()
        bell = self.paint(renderer, None)
        shapes = {}
        for kind in ('ellipse', 'rectangle', 'trapezoid', 'triangle', 'line'):
            part = EarPart(enabled=True, kind=kind, width=1 if kind == 'line' else 6., height=10., offset_x=5.)
            shapes[kind] = self.paint(renderer, CustomAppearance(ear_body=part))
        self.assertEqual(len({bytes(image.constBits()) for image in shapes.values()}), 5)
        self.assertEqual(self.paint(renderer, None), bell)

    def test_png_is_mirrored_keeps_colors_and_cache_updates_on_geometry_changes(self):
        path = self.png()
        renderer = OracleRenderer()
        part = EarPart(enabled=True, kind='png', image_path=str(path), width=3, height=5, offset_x=8)
        shape = CustomAppearance(ear_body=part)
        image = self.paint(renderer, shape)
        for color in ('#ff0000', '#00ff00'):
            points = {(x,y) for y in range(image.height()) for x in range(image.width())
                      if image.pixelColor(x,y) == QColor(color)}
            self.assertTrue(points)
            self.assertEqual(points, {(511-x,y) for x,y in points})
        cached = renderer._head_image
        self.assertEqual(self.paint(renderer, shape), image)
        self.assertIs(renderer._head_image, cached)
        with patch('rw_creature_pet.oracle.graphics.face_assets.read_face_png', side_effect=AssertionError('disk read')):
            changed = replace(shape, ear_body=replace(part, rotation=30.))
            self.assertNotEqual(self.paint(renderer, changed), image)
            self.paint(renderer, changed, gaze=Vec2(.8, .2))

    def test_attachments_are_above_core_and_far_ear_is_behind_the_face(self):
        renderer = OracleRenderer()
        base = EarPart(enabled=True, width=8, height=6, tone='shell')
        part = replace(base, tone='highlight')
        shape = CustomAppearance(ear_body=base, ear_part_1=part)
        image = self.paint(renderer, shape, gaze=Vec2(1, 0))
        # 右侧为远侧，重叠位置由皮肤遮挡；左侧为近侧，配件覆盖底色与皮肤
        self.assertEqual(image.pixelColor(256-4, 256), QColor(renderer.colors.head_highlight))
        self.assertEqual(image.pixelColor(256+8, 256), QColor(renderer.colors.skin))

    def test_extreme_parts_fit_head_canvas_and_expand_damage_and_hit_map(self):
        part = EarPart(enabled=True, width=32, height=32, offset_x=32, offset_y=-32, rotation=45.)
        shape = CustomAppearance(ear_body=part)
        renderer = OracleRenderer()
        for direction in (Vec2(0,-1), Vec2(1,0), Vec2(0,1), Vec2(.7,-.7)):
            self.paint(renderer, shape, direction=direction, gaze=Vec2(.8,-.5))
            image = renderer._head_image
            for x in range(image.width()):
                self.assertEqual(image.pixelColor(x,0).alpha(), 0)
                self.assertEqual(image.pixelColor(x,image.height()-1).alpha(), 0)
            for y in range(image.height()):
                self.assertEqual(image.pixelColor(0,y).alpha(), 0)
                self.assertEqual(image.pixelColor(image.width()-1,y).alpha(), 0)
        scene = OracleScene(OracleConfig(body_appearance='custom', custom_appearance=shape,
                                        hide_cords=True, physics_backend='python'))
        bounds = body_bounds(scene)
        head = scene.appearance.head.position
        self.assertLessEqual(bounds.left(), head.x-ear_radius(shape))
        hit = PuppetHitMap().get(renderer, scene)
        self.assertGreater(hit.image.width(), 100)

    def test_preview_and_settings_edit_both_ways_then_save_once(self):
        d = self.dialog()
        p = d.face_preview
        source = self.png()
        before = d.store.path.read_bytes()
        self.assertTrue(p.face_editors['face'].import_file(source))
        p.face_editors['face'].x_input.setValue(2.5)
        self.app.processEvents()
        self.assertEqual(d.face_editors['face'].value(), p.face_editors['face'].value())
        text_input = p.face_editors['face'].x_input.lineEdit()
        text_input.setFocus()
        text_input.selectAll()
        QTest.keyClicks(text_input, '1.5')
        self.app.processEvents()
        self.assertEqual(d.face_editors['face'].value().offset_x, 1.5)
        self.assertEqual(p.shape.face.offset_x, 1.5)
        d.face_editors['face'].y_input.setValue(-2.)
        self.assertEqual(p.face_editors['face'].y_input.value(), -2.)
        editor, mirror = d.ear_editors['ear_part_1'], p.ear_editors['ear_part_1']
        editor.enabled.setChecked(True)
        mirror.kind.setCurrentIndex(mirror.kind.findData('trapezoid'))
        mirror.width_input.setValue(6.)
        editor.rotation_input.setValue(40.)
        self.app.processEvents()
        self.assertEqual(editor.value(), mirror.value())
        self.assertEqual(p.shape.ear_part_1, editor.value())
        self.assertEqual(d.store.path.read_bytes(), before)
        with patch.object(d.store, 'save', wraps=d.store.save) as save:
            p.apply_button.click()
            save.assert_called_once()
        self.assertEqual(d.store.load().oracle.custom_appearance.ear_part_1, mirror.value())
        p.close()
        self.assertTrue(d.original.oracle.custom_appearance.ear_part_1.enabled)

    def test_import_failure_reset_language_and_save_failure_keep_shared_draft(self):
        d = self.dialog()
        p = d.face_preview
        editor = p.ear_editors['ear_part_2']
        self.assertTrue(editor.import_file(self.png()))
        self.assertEqual(editor.value().kind, 'png')
        self.assertEqual((editor.value().width, editor.value().height), (3.,5.))
        prior = editor.value()
        self.assertFalse(editor.import_file(self.root/'missing.png'))
        self.assertEqual(editor.value(), prior)
        self.assertEqual(d.ear_editors['ear_part_2'].value(), prior)
        self.assertTrue(editor.import_file(self.png()))
        self.assertEqual(editor.message.text(), '')
        language_manager().set_language('en')
        self.assertEqual(p.ear_selector.itemText(0), 'Earphone body')
        self.assertEqual(editor.kind.currentText(), 'PNG image')
        self.assertIn('耳机.png', editor.file_label.text())
        with patch.object(d.store, 'save', side_effect=OSError('locked')):
            p.apply_button.click()
        self.assertIn('locked', p.status.text())
        self.assertEqual(editor.value(), prior)
        self.assertTrue(p.apply_button.isEnabled())
        defaults = d.original
        with patch('rw_creature_pet.oracle.ui.settings.load_defaults', return_value=defaults):
            d.restore_defaults(d.tabs.indexOf(d.pages['appearance']))
        self.assertEqual(editor.value(), defaults.oracle.custom_appearance.ear_part_2)
        d.busy(True)
        self.assertFalse(p.editors.isEnabled())
        d.busy(False)
        self.assertTrue(p.editors.isEnabled())

    def test_reimport_same_png_restores_missing_asset_in_both_editors(self):
        from rw_creature_pet.oracle.graphics.face_assets import face_image
        d = self.dialog()
        editor = d.face_preview.ear_editors['ear_part_1']
        source = self.png()
        editor.import_file(source)
        original = editor.value()
        Path(original.image_path).unlink()
        face_image.cache_clear()
        with self.assertLogs('rw_creature_pet.oracle.graphics.face_assets', level='WARNING'):
            d.refresh_face_preview()
        missing = d.face_preview.actual.image.copy()
        editor.import_file(source)
        self.app.processEvents()
        self.assertEqual(editor.value(), original)
        self.assertFalse(d.ear_editors['ear_part_1'].thumbnail.pixmap().isNull())
        self.assertNotEqual(d.face_preview.actual.image, missing)

    def test_missing_png_only_blocks_active_png_parts_and_closing_preview_keeps_edits(self):
        d = self.dialog()
        p = d.face_preview
        editor = p.ear_editors['ear_part_3']
        editor.kind.setCurrentIndex(editor.kind.findData('png'))
        editor.enabled.setChecked(True)
        with self.assertRaises(ValueError):
            d.candidate()
        editor.kind.setCurrentIndex(editor.kind.findData('triangle'))
        d.candidate()
        expected = editor.value()
        p.close()
        d.open_face_preview()
        self.assertEqual(p.ear_editors['ear_part_3'].value(), expected)
        d.controls['oracle.body_appearance'].setValue('bell')
        self.app.processEvents()
        self.assertFalse(p.editors.isEnabled())
        self.assertIsNone(p.shape)
        self.assertEqual(d.candidate().oracle.custom_appearance.ear_part_3, expected)
