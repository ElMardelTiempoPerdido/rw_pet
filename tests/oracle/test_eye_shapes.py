"""像素眼形的图案、锚点、角色保存及共享编辑器"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from dataclasses import replace
from math import cos, radians, sin
from pathlib import Path
import tempfile
import unittest

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

from rw_creature_pet.config import AppConfig
from rw_creature_pet.i18n import language_manager
from rw_creature_pet.oracle.config import CustomAppearance, OracleConfig
from rw_creature_pet.oracle.eye_config import EYE_KINDS, EyeAppearance
from rw_creature_pet.oracle.graphics.render import OracleRenderer
from rw_creature_pet.oracle.ui.settings import OracleSettingsDialog
from rw_creature_pet.presets.appearance import appearance_mapping, validate_config
from rw_creature_pet.presets.profile_library import ProfileLibrary
from rw_creature_pet.presets.workspace import read_entry
from rw_creature_pet.settings_store import SettingsStore
from rw_creature_pet.shared.geometry import Vec2
from tests.oracle.character_fixture import geometry_assets, isolate_characters


# 独立按用户示意图写出图案，不能从绘制常量反推测试期望
PATTERNS = {
    'squeezed': (('#.', '.#', '#.'), ('.#', '#.', '.#')),
    'slant_in': (('#.', '.#'), ('.#', '#.')),
    'slant_out': (('.#', '#.'), ('#.', '.#')),
    'round': (('.#.', '#w#', '.#.'),)*2,
    'chevron_up': (('.#.', '#.#'),)*2,
    'chevron_down': (('#.#', '.#.'),)*2,
}


class EyeShapesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def shape(self, kind='normal'):
        return CustomAppearance(eye_1=EyeAppearance('#ff0000', default_open=True, kind=kind),
                                eye_2=EyeAppearance('#0000ff', default_open=True, kind=kind))

    def render(self, shape, *, renderer=None, scale=1., dpr=1., angle=0., gx=0., openness=0., closure=0.):
        renderer = renderer or OracleRenderer()
        image = QImage(round(64*scale), round(64*scale), QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(0)
        image.setDevicePixelRatio(dpr)
        painter = QPainter(image)
        direction = Vec2(sin(radians(angle)), -cos(radians(angle)))
        look = Vec2(-direction.y, direction.x)*gx
        head = Vec2(32, 32)
        try:
            painter.scale(scale/dpr, scale/dpr)
            renderer.draw_head(painter, head, head-direction*14, direction, look, openness,
                               shape=shape, eye_closure=closure, pixelated=True, raster_scale=scale)
        finally:
            painter.end()
        return image

    def pixels(self, image, color):
        target = QColor(color).rgba()
        return {(x, y) for y in range(image.height()) for x in range(image.width()) if image.pixel(x, y) == target}

    def test_native_pixels_match_diagram_and_each_open_eye_top_left_anchor(self):
        normal = self.render(self.shape())
        for kind, pair in PATTERNS.items():
            image = self.render(self.shape(kind))
            for color, rows in zip(('#ff0000', '#0000ff'), pair):
                original = self.pixels(normal, color)
                left, top = min(x for x, _ in original), min(y for _, y in original)
                expected = {(left+x, top+y) for y, row in enumerate(rows) for x, cell in enumerate(row) if cell == '#'}
                with self.subTest(kind=kind, color=color):
                    self.assertEqual(self.pixels(image, color), expected)
                    if kind == 'round':
                        self.assertEqual(image.pixelColor(left+1, top+1), QColor('#ffffff'))

    def test_fixed_shapes_ignore_eye_animation_and_preserve_visibility_and_white_center(self):
        for kind in PATTERNS:
            shape = self.shape(kind)
            reference = self.render(shape)
            for openness, closure in ((0., 1.), (.5, .5), (1., 0.)):
                self.assertEqual(self.render(shape, openness=openness, closure=closure), reference)
            lower = replace(shape, eye_1=replace(shape.eye_1, height_mode='lower', default_open=False),
                            eye_2=replace(shape.eye_2, height_mode='lower', default_open=False))
            self.assertEqual(self.render(lower), reference)
            hidden = replace(shape, eye_1=replace(shape.eye_1, visible=False))
            self.assertFalse(self.pixels(self.render(hidden), '#ff0000'))
        shape = self.shape('round')
        recolored = replace(shape, eye_1=replace(shape.eye_1, color='#00ff00'))
        first, second = self.render(shape), self.render(recolored)
        self.assertEqual(self.pixels(first, '#ffffff'), self.pixels(second, '#ffffff'))
        self.assertEqual(self.pixels(first, '#ff0000'), self.pixels(second, '#00ff00'))

    def test_each_eye_can_mix_normal_and_fixed_without_changing_other_eye(self):
        shape = replace(self.shape('round'), eye_2=EyeAppearance('#0000ff', default_open=True))
        opened, closed = self.render(shape), self.render(shape, closure=1.)
        self.assertEqual(self.pixels(opened, '#ff0000'), self.pixels(closed, '#ff0000'))
        self.assertEqual(len(self.pixels(opened, '#0000ff')), 2*len(self.pixels(closed, '#0000ff')))

    def test_cache_scale_dpi_and_turning_keep_pixelated_shapes(self):
        renderer = OracleRenderer()
        for kind in PATTERNS:
            shape = self.shape(kind)
            for scale in (1., 1.5, 2., 3., 4.):
                for angle, gx in ((0., 0.), (35., -.7), (180., .7)):
                    with self.subTest(kind=kind, scale=scale, angle=angle):
                        kw = dict(scale=scale, angle=angle, gx=gx)
                        image = self.render(shape, renderer=renderer, **kw)
                        self.assertEqual(set(bytes(image.constBits())[3::4]), {0, 255})
                        self.assertEqual(image, self.render(shape, **kw))
                        with_dpi = self.render(shape, renderer=renderer, dpr=1.5, **kw)
                        self.assertEqual(bytes(image.constBits()), bytes(with_dpi.constBits()))
                        for color in ('#ff0000', '#0000ff'):
                            self.assertTrue(self.pixels(image, color))
        old = self.render(self.shape('normal'), renderer=renderer)
        self.render(self.shape('round'), renderer=renderer)
        self.assertEqual(old, self.render(self.shape('normal'), renderer=renderer))

    def test_legacy_default_validation_appearance_and_role_share_roundtrip(self):
        for bad in ('unknown', '', None, True, [], {}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                EyeAppearance(kind=bad)
        legacy = OracleConfig.from_mapping({'body_appearance': 'custom', 'custom_appearance': {
            'eye_1': {'color': '#123456', 'default_open': True, 'height_mode': 'lower'}}})
        self.assertEqual(legacy.custom_appearance.eye_1, EyeAppearance('#123456', True, True, 'lower'))
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            sender, receiver = ProfileLibrary(root/'sender'), ProfileLibrary(root/'receiver')
            for kind in PATTERNS:
                oracle = OracleConfig(body_appearance='custom', custom_appearance=self.shape(kind))
                self.assertEqual(validate_config(appearance_mapping(oracle)).custom_appearance, oracle.custom_appearance)
                config = AppConfig(oracle=oracle)
                role = sender.export(config, kind)
                archive = sender.export_share(config, root/(kind+'.zip'), name=kind, preset_id=role.id)
                imported = receiver.import_file(archive)
                entry = read_entry(imported.path)
                for eye in ('eye_1', 'eye_2'):
                    path = 'oracle.custom_appearance.'+eye+'.kind'
                    self.assertEqual(entry.values[path], kind)
                    self.assertEqual(entry.defaults[path], kind)

    def test_settings_and_preview_share_shape_save_restore_and_hidden_values(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root/'RainWorld_Data').mkdir()
            (root/'RainWorld_Data/resources.assets').touch()
            oracle = OracleConfig(body_appearance='custom', custom_appearance=replace(self.shape(),
                eye_1=EyeAppearance('#ff0000', default_open=True, height_mode='lower')))
            config = AppConfig(game_dir=root, oracle=oracle)
            store = SettingsStore(root/'settings.json')
            store.save(config)
            isolate_characters(self, root)
            dialog = OracleSettingsDialog(config, store, assets=geometry_assets())
            try:
                dialog.open_face_preview()
                first = dialog.eye_editors['eye_1']
                mirror = dialog.face_preview.eye_editors['eye_1']
                self.assertEqual([first.kind.itemText(i) for i in range(first.kind.count())],
                                 [label for _, label in EYE_KINDS])
                mirror.kind.setCurrentIndex(mirror.kind.findData('round'))
                self.app.processEvents()
                self.assertEqual(first.value().kind, 'round')
                self.assertFalse(first.layout().isRowVisible(first.state))
                self.assertFalse(mirror.layout().isRowVisible(mirror.height_mode))
                self.assertTrue(first.value().default_open)
                self.assertEqual(first.value().height_mode, 'lower')
                self.assertEqual(dialog.eye_editors['eye_2'].value().kind, 'normal')
                self.assertTrue(first.kind.property('default_reset_bound'))
                self.assertTrue(mirror.kind.property('default_reset_bound'))
                language_manager().set_language('en')
                self.assertEqual(mirror.kind.itemText(0), 'Normal')
                self.assertEqual(mirror.kind.currentText(), 'o o')
                dialog.save(close=False)
                self.assertEqual(store.load().oracle.custom_appearance.eye_1.kind, 'round')
                dialog.preset_workflow.reset_parameter('oracle.custom_appearance.eye_1.kind')
                self.app.processEvents()
                self.assertEqual(first.value(), oracle.custom_appearance.eye_1)
                self.assertEqual(mirror.value(), first.value())
                self.assertTrue(first.layout().isRowVisible(first.state))
                self.assertTrue(mirror.layout().isRowVisible(mirror.height_mode))
            finally:
                dialog.shutdown()
                dialog.deleteLater()
                QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
                self.app.processEvents()
                language_manager().set_language('zh')


if __name__ == '__main__':
    unittest.main()
