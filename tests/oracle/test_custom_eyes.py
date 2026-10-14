"""单眼外观、旧配色迁移和面部预览的同步编辑"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

from rw_creature_pet.config import AppConfig
from rw_creature_pet.i18n import language_manager
from rw_creature_pet.oracle.assets import OracleAssets
from rw_creature_pet.oracle.config import CustomAppearance, OracleColors, OracleConfig
from rw_creature_pet.oracle.eye_config import EyeAppearance
from rw_creature_pet.oracle.graphics.render import OracleRenderer
from rw_creature_pet.oracle.ui.settings import OracleSettingsDialog
from rw_creature_pet.oracle.ui.debug_window import OracleDebugWindow
from rw_creature_pet.settings_store import SettingsStore
from rw_creature_pet.shared.geometry import Vec2


class CustomEyesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def shape(self):
        return CustomAppearance(eye_1=EyeAppearance('#ff0000', default_open=True),
                                eye_2=EyeAppearance('#0000ff'))

    def render(self, shape, openness=0., gx=0., *, renderer=None, angle=0.):
        renderer = renderer or OracleRenderer()
        image = QImage(160, 160, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(0)
        painter = QPainter(image)
        try:
            painter.translate(80, 80)
            painter.scale(4, 4)
            painter.rotate(angle)
            renderer.draw_head(painter, Vec2(), Vec2(0, 10), Vec2(0, -1), Vec2(gx, 0),
                               openness, pixelated=True, raster_scale=2., shape=shape)
        finally:
            painter.end()
        return image

    @staticmethod
    def pixels(image, color):
        target = QColor(color)
        return [(x, y) for y in range(image.height()) for x in range(image.width())
                if image.pixelColor(x, y) == target]

    def test_validation_and_old_toml_inherits_shared_color(self):
        for kw in ({'color': ''}, {'color': '#abcd'}, {'visible': 1}, {'default_open': 'open'}):
            with self.subTest(kw=kw), self.assertRaises(ValueError):
                EyeAppearance(**kw)
        legacy = OracleConfig.from_mapping({'colors': {'eyes': '#123456'}})
        self.assertEqual(legacy.custom_appearance.eye_1.color, '#123456')
        self.assertEqual(legacy.custom_appearance.eye_2.color, '#123456')
        explicit = OracleConfig.from_mapping({'custom_colors': {'eyes': '#abcdef'},
            'custom_appearance': {'eye_1': {'color': '#010203', 'default_open': True},
                                  'eye_2': {'visible': False}}})
        self.assertEqual(explicit.custom_appearance.eye_1, EyeAppearance('#010203', default_open=True))
        self.assertEqual(explicit.custom_appearance.eye_2, EyeAppearance('#abcdef', visible=False))

    def test_saved_profile_migration_keeps_each_eye_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            template = root/'config.toml'
            template.write_text("[oracle.custom_colors]\neyes='#111111'\n"
                                "[oracle.custom_appearance.eye_1]\ncolor='#222222'\n"
                                "[oracle.custom_appearance.eye_2]\ncolor='#333333'\n", encoding='utf-8')
            store = SettingsStore(root/'settings.json')
            legacy = {'version': 1, 'config': {'oracle': {'custom_colors': {'eyes': '#abcdef'},
                'custom_appearance': {'eye_1': {'color': '#102030'},
                                      'eye_2': {'visible': False, 'default_open': True}}}}}
            store.path.write_text(json.dumps(legacy), encoding='utf-8')
            with patch('rw_creature_pet.settings_store.default_template_path', return_value=template):
                config, first, error = store.startup()
                self.assertEqual((first, error), (False, ''))
                self.assertEqual(config.oracle.custom_appearance.eye_1.color, '#102030')
                self.assertEqual(config.oracle.custom_appearance.eye_2, EyeAppearance('#abcdef', False, True))
                self.assertEqual(json.loads(store.path.with_suffix('.json.bak').read_text()), legacy)
                migrated = store.path.read_bytes()
                self.assertEqual(store.startup()[0], config)
                self.assertEqual(store.path.read_bytes(), migrated)

    def test_idle_asymmetry_reaction_and_hidden_eye(self):
        shape = self.shape()
        idle = self.render(shape)
        one, two = self.pixels(idle, '#ff0000'), self.pixels(idle, '#0000ff')
        self.assertTrue(one and two)
        self.assertEqual(len(one), 2*len(two))
        self.assertLess(max(x for x, _ in one), min(x for x, _ in two))
        reacting = self.render(shape, 1.)
        self.assertEqual(len(self.pixels(reacting, '#ff0000')), len(one))
        self.assertEqual(len(self.pixels(reacting, '#0000ff')), len(one))
        self.assertEqual(self.render(shape, 0.), idle)
        hidden = replace(shape, eye_1=replace(shape.eye_1, visible=False))
        self.assertFalse(self.pixels(self.render(hidden, 1.), '#ff0000'))

    def test_eye_identity_stays_attached_when_turning_and_rotating(self):
        shape = self.shape()
        for gaze in (-.8, 0., .8):
            image = self.render(shape, gx=gaze)
            one, two = self.pixels(image, '#ff0000'), self.pixels(image, '#0000ff')
            self.assertTrue(one and two)
            self.assertLess(sum(x for x, _ in one)/len(one), sum(x for x, _ in two)/len(two))
            rotated = self.render(shape, gx=gaze, angle=180.)
            one, two = self.pixels(rotated, '#ff0000'), self.pixels(rotated, '#0000ff')
            self.assertGreater(sum(x for x, _ in one)/len(one), sum(x for x, _ in two)/len(two))

    def test_each_field_invalidates_head_cache_and_bell_stays_unchanged(self):
        renderer, shape = OracleRenderer(), self.shape()
        bell = self.render(None, renderer=renderer)
        before = self.render(shape, renderer=renderer)
        for name, value in (('color', '#00ff00'), ('visible', False), ('default_open', False)):
            edited = replace(shape, eye_1=replace(shape.eye_1, **{name: value}))
            self.assertNotEqual(self.render(edited, renderer=renderer), before)
            self.assertEqual(self.render(edited, renderer=renderer), self.render(edited))
            self.assertEqual(self.render(None, renderer=renderer), bell)
            self.assertEqual(self.render(shape, renderer=renderer), before)

    def test_debug_color_changes_do_not_change_visibility_or_default_state(self):
        shape = replace(self.shape(), eye_2=EyeAppearance('#abcdef', visible=False, default_open=True))
        window = OracleDebugWindow(AppConfig(oracle=OracleConfig(body_appearance='custom',
            custom_appearance=shape, hide_cords=True)), load_atlas=False)
        window.timer.stop()
        try:
            self.assertNotIn('eyes', window.color_buttons)
            self.assertIn('eye_1', window.color_buttons)
            window.set_eye_colors({'eye_2': '#123456'})
            self.assertEqual(window.scene.config.custom_appearance.eye_2, EyeAppearance('#123456', False, True))
            window.reset_colors()
            self.assertEqual(window.scene.config.custom_appearance.eye_2,
                             EyeAppearance(EyeAppearance().color, False, True))
        finally:
            window.close()

    def test_preview_sync_apply_reset_translation_and_temporary_expression(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root/'RainWorld_Data').mkdir()
            (root/'RainWorld_Data/resources.assets').touch()
            config = AppConfig(game_dir=root, oracle=OracleConfig(body_appearance='custom'))
            store = SettingsStore(root/'settings.json')
            store.save(config)
            before = store.path.read_bytes()
            d = OracleSettingsDialog(config, store, assets=OracleAssets(OracleRenderer(), '', {}, ''))
            try:
                d.open_face_preview()
                preview = d.face_preview
                first, second = preview.eye_editors['eye_1'], d.eye_editors['eye_2']
                first.color.setValue('#ff0000')
                first.state.setCurrentIndex(first.state.findData(True))
                second.color.setValue('#0000ff')
                self.app.processEvents()
                self.assertEqual(d.eye_editors['eye_1'].value(), self.shape().eye_1)
                self.assertEqual(preview.eye_editors['eye_2'].value(), self.shape().eye_2)
                default = preview.actual.image.copy()
                draft = d.candidate()
                for mode in ('closed', 'open'):
                    preview.eye_state.setCurrentIndex(preview.eye_state.findData(mode))
                    self.assertNotEqual(preview.actual.image, default)
                    self.assertEqual(d.candidate(), draft)
                preview.eye_state.setCurrentIndex(0)
                self.assertEqual(preview.actual.image, default)
                self.assertEqual(store.path.read_bytes(), before)
                language_manager().set_language('en')
                self.assertEqual(first.state.itemText(first.state.findData(True)), 'Open')
                self.assertEqual(first.value(), self.shape().eye_1)
                d.save(close=False)
                self.assertEqual(store.load().oracle.custom_appearance.eye_1, self.shape().eye_1)
                d.controls['oracle.body_appearance'].setValue('bell')
                d.save(close=False)
                self.assertIsNone(store.load().oracle.active_custom_appearance)
                self.assertEqual(store.load().oracle.custom_appearance.eye_1, self.shape().eye_1)
                with patch('rw_creature_pet.oracle.ui.settings.load_defaults', return_value=config):
                    d.restore_defaults(1)
                self.assertEqual(first.value(), config.oracle.custom_appearance.eye_1)
                self.assertEqual(second.value(), config.oracle.custom_appearance.eye_2)
            finally:
                d.shutdown()
                d.deleteLater()
                QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
                self.app.processEvents()
                language_manager().set_language('zh')
