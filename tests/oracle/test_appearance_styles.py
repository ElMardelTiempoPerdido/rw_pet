"""外观独立配色、旧配置迁移、绘制分支与缓存切换"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication

from rw_creature_pet.config import AppConfig
from rw_creature_pet.oracle.config import CustomAppearance, OracleColors, OracleConfig
from rw_creature_pet.oracle.graphics.render import OracleRenderer
from rw_creature_pet.oracle.interaction.input import PuppetHitMap
from rw_creature_pet.oracle.scene import OracleScene
from rw_creature_pet.oracle.ui.debug_window import OracleDebugWindow
from rw_creature_pet.oracle.ui.settings import OracleSettingsDialog
from tests.oracle.character_fixture import isolate_characters
from rw_creature_pet.settings_store import SettingsStore
from rw_creature_pet.shared.geometry import Vec2


class AppearanceStyleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_old_user_palette_is_copied_once_before_defaults_are_filled(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            template = root/'config.toml'
            template.write_text("[oracle.colors]\nskin='#123456'\n[oracle.custom_colors]\nskin='#987654'\n",
                                encoding='utf-8')
            store = SettingsStore(root/'settings.json')
            legacy = {'version': 1, 'config': {'oracle': {
                'body_appearance': 'custom', 'colors': {'robe_top': '#abcdef', 'pearl_glyph': '#010203'},
                'custom_appearance': {'head_length': 1.2, 'neck_width': 5.}}}}
            store.path.write_text(json.dumps(legacy), encoding='utf-8')
            with patch('rw_creature_pet.settings_store.default_template_path', return_value=template):
                config, first, message = store.startup()
                self.assertEqual((first, message), (False, ''))
                self.assertEqual(config.oracle.custom_colors, config.oracle.colors)
                self.assertEqual(config.oracle.active_colors.robe_top, '#abcdef')
                self.assertEqual(config.oracle.active_colors.skin, '#123456')
                self.assertEqual(config.oracle.custom_appearance.neck_width, 5.)
                self.assertEqual(json.loads(store.path.with_suffix('.json.bak').read_text()), legacy)
                data = json.loads(store.path.read_text())
                data['config']['oracle']['colors']['robe_top'] = '#ff0000'
                store.path.write_text(json.dumps(data), encoding='utf-8')
                before = store.path.read_bytes()
                loaded, _, _ = store.startup()
                self.assertEqual(loaded.oracle.custom_colors.robe_top, '#abcdef')
                self.assertEqual(loaded.oracle.colors.robe_top, '#ff0000')
                self.assertEqual(store.path.read_bytes(), before)

    def test_toml_legacy_and_explicit_palettes_have_distinct_ownership(self):
        legacy = OracleConfig.from_mapping({'colors': {'skin': '#123456'}})
        self.assertEqual(legacy.custom_colors, legacy.colors)
        explicit = OracleConfig.from_mapping({'colors': {'skin': '#123456'},
                                               'custom_colors': {'skin': '#abcdef'}})
        self.assertEqual(explicit.active_colors.skin, '#123456')
        self.assertEqual(replace(explicit, body_appearance='custom').active_colors.skin, '#abcdef')

    def test_projection_reset_only_changes_current_palette_and_cancel_keeps_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'RainWorld_Data').mkdir()
            (root/'RainWorld_Data/resources.assets').touch()
            colors = OracleColors(pearl_glyph='#112233')
            custom = OracleColors(pearl_glyph='#445566')
            config = AppConfig(game_dir=root, oracle=OracleConfig(body_appearance='custom',
                                colors=colors, custom_colors=custom))
            store = SettingsStore(root/'settings.json')
            store.save(config)
            before = store.path.read_bytes()
            isolate_characters(self, store.path.parent)
            dialog = OracleSettingsDialog(config, store)
            try:
                defaults = replace(config, oracle=replace(config.oracle,
                    colors=replace(colors, pearl_glyph='#aabbcc'),
                    custom_colors=replace(custom, pearl_glyph='#ddeeff')))
                with patch('rw_creature_pet.oracle.ui.settings.load_defaults', return_value=defaults):
                    dialog.restore_defaults(dialog.tabs.indexOf(dialog.pages['projection']))
                    self.assertEqual(dialog.candidate().oracle.colors, colors)
                    self.assertEqual(dialog.candidate().oracle.custom_colors.pearl_glyph, '#ddeeff')
                    dialog.controls['oracle.body_appearance'].setValue('bell')
                    dialog.restore_defaults(dialog.tabs.indexOf(dialog.pages['appearance']))
                    self.assertEqual(dialog.candidate().oracle.colors.pearl_glyph, '#aabbcc')
                    self.assertEqual(dialog.candidate().oracle.custom_colors.pearl_glyph, '#ddeeff')
                dialog.reject()
                self.assertEqual(store.path.read_bytes(), before)
            finally:
                dialog.close()

    def head_image(self, renderer, shape=None, density=1.5):
        image = QImage(192, 192, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(0)
        painter = QPainter(image)
        painter.translate(96, 96)
        painter.scale(6, 6)
        renderer.draw_head(painter, Vec2(), Vec2(0, 10), Vec2(0, -1), Vec2(.4, .2),
                           raster_scale=density, shape=shape)
        painter.end()
        return bytes(image.constBits())

    def test_custom_head_does_not_call_bell_geometry_or_use_its_density_tricks(self):
        renderer = OracleRenderer()
        for density in (1., 1.5, 2.):
            with self.subTest(density=density):
                bell = self.head_image(renderer, density=density)
                with patch.object(renderer, 'draw_head_parts', side_effect=AssertionError('Bell entry')):
                    custom = self.head_image(renderer, CustomAppearance(), density)
                    self.assertNotEqual(custom, bell)
                    with patch.object(renderer, 'PHONE_PIXEL_WIDTHS', {1.5: (8., 8.)}), \
                            patch.object(renderer, 'FACE_MARK_PIXEL_WIDTHS', {1.5: 8.}):
                        renderer._head_geometry_key = renderer._head_key = None
                        self.assertEqual(custom, self.head_image(renderer, CustomAppearance(), density))
                self.assertEqual(bell, self.head_image(renderer, density=density))

    def test_necklace_and_hitmap_follow_style_switch_without_a_physics_tick(self):
        scene = OracleScene(OracleConfig(hide_cords=True, physics_backend='python'))
        renderer, hit = OracleRenderer(), PuppetHitMap()
        bell = hit.get(renderer, scene)
        bell_head = renderer._head_image
        with patch.object(renderer, 'draw_necklace', wraps=renderer.draw_necklace) as necklace:
            scene.config = replace(scene.config, body_appearance='custom')
            custom = hit.get(renderer, scene)
            self.assertIsNot(custom, bell)
            self.assertIsNot(renderer._head_image, bell_head)
            necklace.assert_not_called()
            self.assertIs(hit.get(renderer, scene), custom)
            scene.config = replace(scene.config, body_appearance='bell')
            hit.get(renderer, scene)
            necklace.assert_called_once()
            self.assertEqual(renderer._head_image, bell_head)
        self.assertEqual(scene.ticks, 0)

    def test_debug_preview_and_reload_use_custom_palette(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            custom = OracleColors(skin='#abcdef')
            config = AppConfig(game_dir=root, oracle=OracleConfig(body_appearance='custom',
                                custom_colors=custom, hide_cords=True))
            window = OracleDebugWindow(config, load_atlas=False)
            try:
                window.timer.stop()
                self.assertEqual(window.renderer.colors, custom)
                self.assertNotIn('third_eye', window.color_buttons)
                path = root/'config.toml'
                path.write_text("[oracle.colors]\nskin='#ff0000'\n[oracle.custom_colors]\nskin='#00ff00'\n",
                                encoding='utf-8')
                window.config_path = path
                window.reload_colors()
                self.assertEqual(window.renderer.colors.skin, '#00ff00')
                self.assertEqual(window.scene.config.body_appearance, 'custom')
            finally:
                window.close()
