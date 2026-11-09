"""拖动表情的设置保存、风格隔离与临时绘制覆盖"""
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
from PySide6.QtWidgets import QApplication, QComboBox, QLabel

from rw_creature_pet.config import AppConfig
from rw_creature_pet.i18n import language_manager
from rw_creature_pet.oracle.config import CustomAppearance, OracleConfig
from rw_creature_pet.oracle.drag_expression_config import DragExpressionConfig, ExpressionChoice, EXPRESSION_KINDS
from rw_creature_pet.oracle.eye_config import EYE_KINDS, EyeAppearance
from rw_creature_pet.oracle.graphics.render import OracleRenderer
from rw_creature_pet.oracle.interaction.input import PuppetHitMap
from rw_creature_pet.oracle.scene import OracleScene
from rw_creature_pet.oracle.ui.desktop import OracleDesktopMotion, OracleDesktopViewport
from rw_creature_pet.oracle.ui.sections import CollapsibleSection
from rw_creature_pet.oracle.ui.settings import OracleSettingsDialog
from rw_creature_pet.presets.behavior_styles import DIMENSION_PATHS
from rw_creature_pet.settings_store import SettingsStore
from rw_creature_pet.shared.geometry import Vec2
from tests.oracle.character_fixture import geometry_assets, isolate_characters

PREFIX = 'oracle.drag_expressions.'


class DragExpressionSettingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        isolate_characters(self, self.root)
        self.enterContext(patch('rw_creature_pet.presets.library.default_appearance_directory',
                                return_value=self.root/'appearances'))
        game = self.root/'game'
        (game/'RainWorld_Data').mkdir(parents=True)
        (game/'RainWorld_Data/resources.assets').touch()
        self.store = SettingsStore(self.root/'settings.json')
        self.d = OracleSettingsDialog(AppConfig(game_dir=game), self.store, assets=geometry_assets())
        self.d.preset_workflow.set_autosave(False)
        self.enterContext(patch.object(self.d, 'space_assessment', return_value=None))

    def tearDown(self):
        self.d.shutdown()
        self.d.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()
        language_manager().set_language('zh')

    def test_expression_edit_and_action_style_never_change_each_other(self):
        d, c = self.d, self.d.controls
        group = d.behavior_styles.groups['drag_reactions']
        self.assertIn('拖动动作', [w.text() for w in group.findChildren(QLabel)])
        self.assertFalse(d.drag_expression_panel.findChildren(QComboBox))
        self.assertEqual(len(d.behavior_styles.groups), 7)
        self.assertFalse(any(path.startswith(PREFIX) for paths in DIMENSION_PATHS.values() for path in paths))
        for path in c:
            if path.startswith(PREFIX):
                self.assertTrue(d.drag_expression_panel.isAncestorOf(c[path]))
                self.assertFalse(group.content.isAncestorOf(c[path]))
        c[PREFIX+'round.enabled'].setChecked(True)
        c[PREFIX+'round.weight'].setValue(9)
        c[PREFIX+'round.large_only'].setChecked(True)
        c[PREFIX+'probability'].setValue(77.5)
        expression = d.candidate().oracle.drag_expressions
        self.assertEqual(expression.probability, .775)
        combo = group.selector
        for style in d.behavior_styles.library.for_dimension('drag_reactions'):
            combo.setCurrentIndex(combo.findData(style.id))
            combo.activated.emit(combo.currentIndex())
            self.assertEqual(d.candidate().oracle.drag_expressions, expression)
        marker = d.candidate().oracle.behavior_styles.drag_reactions
        c[PREFIX+'round.weight'].setValue(7)
        self.assertEqual(d.candidate().oracle.behavior_styles.drag_reactions, marker)
        c['oracle.drag_reactions.enabled'].setChecked(False)
        self.assertTrue(c[PREFIX+'round.weight'].isEnabled())
        self.assertTrue(c[PREFIX+'probability'].isEnabled())
        before = d.candidate()
        for show in (True, False):
            group.advanced.setChecked(show)
            self.assertFalse(d.drag_expression_panel.isHidden())
            self.assertEqual(d.candidate(), before)

    def test_disabled_rows_retain_values_and_profile_save_reload(self):
        d, c = self.d, self.d.controls
        for kind in EXPRESSION_KINDS:
            self.assertFalse(c[PREFIX+kind+'.enabled'].isChecked())
            self.assertFalse(c[PREFIX+kind+'.weight'].isEnabled())
        c[PREFIX+'slant_out.enabled'].setChecked(True)
        c[PREFIX+'slant_out.weight'].setValue(17)
        c[PREFIX+'slant_out.large_only'].setChecked(True)
        c[PREFIX+'slant_out.enabled'].setChecked(False)
        self.assertEqual(c[PREFIX+'slant_out.weight'].value(), 17)
        c[PREFIX+'round.enabled'].setChecked(True)
        for kind, label, weight in (('fixed_open', '· ·', 5), ('fixed_closed', '- -', 8)):
            self.assertIn(label, [w.text() for w in d.drag_expression_panel.findChildren(QLabel)])
            c[PREFIX+kind+'.enabled'].setChecked(True)
            c[PREFIX+kind+'.weight'].setValue(weight)
            c[PREFIX+kind+'.large_only'].setChecked(True)
        expected = d.candidate().oracle.drag_expressions
        self.assertTrue(d.preset_workflow.flush())
        self.assertEqual(self.store.load().oracle.drag_expressions, expected)
        d.preset_workflow.reset_parameter(PREFIX+'slant_out.weight')
        self.assertEqual(d.candidate().oracle.drag_expressions.slant_out.weight, 1)

    def test_language_and_folded_actions_do_not_stretch_or_clip_expression_rows(self):
        d = self.d
        page = d.pages['behavior']
        d.tabs.setCurrentWidget(page)
        sections = page.findChildren(CollapsibleSection)
        drag = next(s for s in sections if s.heading.text() == '拖动反应')
        for section in sections:
            section.set_expanded(section is drag)
        before = d.candidate()
        d.show()
        for language, width in (('zh', 800), ('en', 800), ('zh', 960)):
            language_manager().set_language(language)
            d.resize(width, 760)
            QTest.qWait(60)
            self.assertEqual(page.horizontalScrollBar().maximum(), 0)
            self.assertTrue(d.drag_expression_panel.isVisible())
            self.assertEqual(d.candidate().oracle, before.oracle)
            controls = [d.controls[PREFIX+kind+'.weight'] for kind in EXPRESSION_KINDS]
            ys = [widget.mapTo(d.drag_expression_panel, widget.rect().topLeft()).y() for widget in controls]
            gaps = [b-a for a, b in zip(ys, ys[1:])]
            self.assertLessEqual(max(gaps)-min(gaps), 1)


class DragExpressionRenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def render(self, renderer, shape, kind, scale, gx, *, openness=0., closure=1.):
        image = QImage(round(64*scale), round(64*scale), QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(0)
        painter = QPainter(image)
        try:
            painter.scale(scale, scale)
            renderer.draw_head(painter, Vec2(32, 32), Vec2(32, 46), Vec2(0, -1), Vec2(gx, 0),
                openness, shape=shape, eye_closure=closure, eye_expression=kind,
                pixelated=True, raster_scale=scale)
        finally:
            painter.end()
        return image

    def test_overlay_preserves_colors_hidden_eye_white_center_and_restores_asymmetric_base(self):
        renderer = OracleRenderer()
        shape = CustomAppearance(eye_1=EyeAppearance('#ff0000', kind='slant_in'),
            eye_2=EyeAppearance('#0000ff', height_mode='lower', default_open=True))
        for visible in (True, False):
            base = replace(shape, eye_2=replace(shape.eye_2, visible=visible))
            for scale in (1., 1.5, 2., 3., 4.):
                for gx in (-.7, 0., .7):
                    original = self.render(renderer, base, None, scale, gx)
                    for kind, _ in EYE_KINDS[1:]:
                        expected = replace(base, eye_1=replace(base.eye_1, kind=kind),
                                           eye_2=replace(base.eye_2, kind=kind))
                        self.assertEqual(self.render(renderer, base, kind, scale, gx),
                                         self.render(OracleRenderer(), expected, None, scale, gx))
                    self.assertEqual(self.render(renderer, base, None, scale, gx), original)

    def test_fixed_open_closed_sizes_ignore_base_shape_height_and_animation(self):
        plain = CustomAppearance(eye_1=EyeAppearance('#ff0000', default_open=True),
                                 eye_2=EyeAppearance('#0000ff', default_open=True))
        for base_kind in ('normal', 'round'):
            base = replace(plain, eye_1=replace(plain.eye_1, kind=base_kind, height_mode='lower'),
                           eye_2=replace(plain.eye_2, kind='slant_in', default_open=False))
            renderer = OracleRenderer()
            renderer.OPEN_EYE_HEIGHT = 5.
            for kind, height in (('fixed_open', 2), ('fixed_closed', 1)):
                for scale in (1., 1.5, 2., 3., 4.):
                    for gx in (-.7, 0., .7):
                        with self.subTest(base=base_kind, kind=kind, scale=scale, gx=gx):
                            original = self.render(renderer, base, None, scale, gx)
                            expected = self.render(OracleRenderer(), plain, None, scale, gx,
                                                   closure=float(kind == 'fixed_closed'))
                            for openness, closure in ((0., 1.), (.5, .5), (1., 0.)):
                                actual = self.render(renderer, base, kind, scale, gx,
                                                     openness=openness, closure=closure)
                                self.assertEqual(actual, expected)
                            if gx == 0. and scale.is_integer():
                                for color in ('#ff0000', '#0000ff'):
                                    pixels = {(x, y) for y in range(actual.height())
                                              for x in range(actual.width())
                                              if actual.pixel(x, y) == QColor(color).rgba()}
                                    self.assertEqual(len(pixels), 2*height*scale*scale)
                                    self.assertEqual(max(x for x, _ in pixels)-min(x for x, _ in pixels)+1, 2*scale)
                                    self.assertEqual(max(y for _, y in pixels)-min(y for _, y in pixels)+1, height*scale)
                            hidden = replace(base, eye_2=replace(base.eye_2, visible=False))
                            expected_hidden = replace(plain, eye_2=replace(plain.eye_2, visible=False))
                            self.assertEqual(self.render(renderer, hidden, kind, scale, gx),
                                self.render(OracleRenderer(), expected_hidden, None, scale, gx,
                                            closure=float(kind == 'fixed_closed')))
                            self.assertEqual(self.render(renderer, base, None, scale, gx), original)

    def test_sleeping_head_and_hit_cache_update_once_on_expression_change(self):
        for appearance in ('bell', 'custom'):
            s = OracleScene(OracleConfig(body_appearance=appearance, hide_cords=True, halo_enabled=False,
                physics_backend='python'))
            s.appearance.sleeping = True
            renderer, hit = OracleRenderer(), PuppetHitMap()
            original = hit.get(renderer, s)
            s.eyes.set_expression('round')
            expression = hit.get(renderer, s)
            self.assertIsNot(original, expression)
            self.assertNotEqual(original.image, expression.image)
            self.assertIs(hit.get(renderer, s), expression)
            s.eyes.set_expression('round')
            self.assertIs(hit.get(renderer, s), expression)
            s.eyes.set_expression(None)
            self.assertEqual(hit.get(renderer, s).image, original.image)

    def test_workspace_rebuild_clears_active_expression_but_preserves_random_streams(self):
        config = OracleConfig(hide_cords=True, halo_enabled=False, physics_backend='python',
            drag_expressions=DragExpressionConfig(probability=1., round=ExpressionChoice(True)))
        before = OracleDesktopMotion(config, OracleDesktopViewport(0, 0, 1920, 1080))
        s = before.scene
        s.drag.set_enabled(True)
        s.drag.press(s.head.position, lambda _: True)
        s.drag_expressions.wait = 0.
        s.drag_expressions.step(s)
        self.assertEqual(s.eyes.expression, 'round')
        after = OracleDesktopMotion(config, OracleDesktopViewport(0, 0, 1600, 900), s)
        self.assertIsNone(after.scene.eyes.expression)
        self.assertFalse(after.scene.drag_expressions.held)
        for name in ('random', 'timing_random'):
            self.assertEqual(getattr(s.drag_expressions, name).getstate(),
                             getattr(after.scene.drag_expressions, name).getstate())
        # 相同逻辑路程经不同倍率/DPI 映射回来后仍触发相同判定
        for scale, dpr in ((1., 1.), (1., 1.5), (2., 1.), (2., 1.5)):
            v = OracleDesktopViewport(20, 30, 3840, 2160, dpr, scale)
            r = after.scene.drag_expressions
            r.cancel(after.scene)
            r.sample_motion(v.to_world(v.to_global(Vec2(100, 100))), .025)
            r.sample_motion(v.to_world(v.to_global(Vec2(150, 100))), .025)
            self.assertGreater(r.large_remaining, 0)


if __name__ == '__main__':
    unittest.main()
