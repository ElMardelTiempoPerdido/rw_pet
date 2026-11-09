"""全局拖动手感：旧值等价、直接抓取、边界、保存及运行入口"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from dataclasses import replace
from math import isfinite
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QEvent, QRect, Qt
from PySide6.QtWidgets import QApplication

from rw_creature_pet.config import AppConfig
from rw_creature_pet.interaction.config import InteractionConfig
from rw_creature_pet.interaction.drag import follow_velocity, limited
from rw_creature_pet.i18n import language_manager
from rw_creature_pet.oracle.config import OracleConfig
from rw_creature_pet.oracle.scene import OracleScene
from rw_creature_pet.oracle.ui.debug_window import OracleDebugWindow
from rw_creature_pet.oracle.ui.desktop import OracleDesktopWindow
from rw_creature_pet.oracle.ui.settings import OracleSettingsDialog
from rw_creature_pet.presets.fields import FieldScope, scope_for
from rw_creature_pet.presets.profile import apply_profile
from rw_creature_pet.presets.profile_library import ProfileLibrary
from rw_creature_pet.settings_store import SettingsStore
from rw_creature_pet.shared.geometry import Vec2
from tests.oracle.character_fixture import geometry_assets, isolate_characters
from tests.oracle.test_desktop import FakeScreen


class DragResponseTests(unittest.TestCase):
    def scene(self, value, **kwargs):
        s = OracleScene(OracleConfig(hide_cords=True, halo_enabled=False, physics_backend='python', **kwargs))
        s.drag.configure(InteractionConfig(drag_enabled=True, drag_responsiveness=value))
        return s

    def test_defaults_validation_and_local_share_scope(self):
        self.assertEqual(InteractionConfig().drag_responsiveness, .5)
        for bad in (True, None, -1., 1.01, float('nan'), float('inf'), '0.5'):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                InteractionConfig(drag_responsiveness=bad)
        self.assertEqual(scope_for('interaction.drag_responsiveness'), FieldScope.LOCAL)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root/'old.toml'
            path.write_text('[interaction]\ndrag_enabled = true\n', encoding='utf-8')
            self.assertEqual(AppConfig.load(path).interaction.drag_responsiveness, .5)
            config = AppConfig(interaction=InteractionConfig(drag_enabled=True, drag_responsiveness=.83))
            store = SettingsStore(root/'settings.json')
            store.save(config)
            self.assertEqual(store.load().interaction, config.interaction)
            library = ProfileLibrary(root/'profiles')
            entry = library.export(config, 'Response')
            target = replace(config, interaction=replace(config.interaction, drag_responsiveness=.21))
            actual = apply_profile(target, entry, root/'cache')
            self.assertEqual(actual.interaction.drag_responsiveness, .21)

    def test_default_matches_original_equation_exactly_and_higher_values_reduce_lag(self):
        for speed, acceleration in ((7., .8), (2., .18)):
            p, v = Vec2(), Vec2()
            for target in (Vec2(100, 20),)*80+(Vec2(-80, -10),)*80:
                expected = limited(v+limited((limited((target-p)*.24, speed)-v)*.5, acceleration), speed)
                actual = follow_velocity(p, v, target, speed=speed, acceleration=acceleration)
                self.assertEqual(actual, expected)
                p, v = p+actual, actual
        errors = []
        for value in (0., .25, .5, .75, .99, 1.):
            p, v = Vec2(), Vec2()
            for tick in range(1, 121):
                target = Vec2(tick*2., 0.)
                v = follow_velocity(p, v, target, responsiveness=value)
                p += v
            errors.append((target-p).length())
            for _ in range(300):
                v = follow_velocity(p, v, target, responsiveness=value)
                p += v
            self.assertLess((target-p).length(), .001)
            self.assertLess(v.length(), .001)
        self.assertEqual(errors, sorted(errors, reverse=True))
        self.assertEqual(errors[-1], 0.)

    def test_maximum_tracks_anchor_with_offset_and_preserves_body_and_neck(self):
        for side in ('top', 'right', 'bottom', 'left'):
            for selected in (0, 1):
                with self.subTest(side=side, selected=selected):
                    s = self.scene(1., base_side=side, sliding_base=False)
                    start = s.body.chunks[selected].position
                    pointer = start+Vec2(1., 0.)
                    self.assertTrue(s.drag.press(pointer, lambda _: True))
                    self.assertEqual(s.drag.controller.handle.key, selected)
                    for distance in (80., 5., 110., 0., 40.):
                        s.drag.move(pointer+s.base_normal()*distance)
                        s.step()
                        self.assertLess((s.body.chunks[selected].position-s.drag.controller.target).length(), 1e-8)
                        self.assertAlmostEqual((s.body.chunks[0].position-s.body.chunks[1].position).length(), 9.)
                        self.assertGreater((s.head.position-s.body.chunks[0].position).length(), 8.)
                        self.assertLess(s.arm.constraint_error, .03)
                        self.assertTrue(all(c.velocity.length() <= 7.000001 for c in s.body.chunks))

    def test_extreme_targets_reversal_release_and_sleep(self):
        for side, arm_scale in (('top', .35), ('right', .35), ('bottom', .35),
                                ('left', .35), ('left', .55), ('left', .75)):
            with self.subTest(side=side, arm_scale=arm_scale):
                s = self.scene(1., base_side=side, arm_scale=arm_scale)
                s.drag.press(s.body.chunks[0].position, lambda _: True)
                for pointer in (s.base+s.base_normal()*10000, Vec2(-10000, -10000),
                                Vec2(10000, 10000), s.base+s.base_normal()*10000):
                    s.drag.move(pointer)
                    for _ in range(70):
                        s.step()
                        upper = s.body.chunks[0]
                        self.assertTrue(s.drag.outer.contains(upper.position, .01))
                        self.assertLess(s.arm.constraint_error, .12)
                        self.assertTrue(all(isfinite(p.position.x) and isfinite(p.position.y) for p in s.appearance.points))
                for _ in range(900):
                    s.step()
                self.assertLess(s.body.chunks[0].velocity.length(), .03)
                s.drag.release()
                self.assertTrue(all(c.velocity.length() <= 3.000001 for c in s.body.chunks))
                for _ in range(1600):
                    s.step()
                    if not s.drag.controlling and s.appearance.sleeping:
                        break
                self.assertFalse(s.drag.controlling)
                self.assertTrue(s.appearance.sleeping)

    def test_recovery_ignores_global_response_and_reset_retains_value(self):
        first, second = self.scene(0.), self.scene(1.)
        for s in (first, second):
            s.drag.press(s.body.chunks[0].position, lambda _: True)
            s.drag.release()
        for _ in range(100):
            for s in (first, second):
                s.step()
            self.assertEqual(first.body.chunks, second.body.chunks)
        second.reset()
        self.assertEqual(second.drag.responsiveness, 1.)
        self.assertTrue(second.drag.enabled)


class DragResponseSettingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def test_same_row_display_save_disabled_retention_and_debug_reset(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        isolate_characters(self, root)
        self.enterContext(patch('rw_creature_pet.presets.library.default_appearance_directory', return_value=root/'appearances'))
        config = AppConfig(interaction=InteractionConfig(drag_enabled=True, drag_responsiveness=.83))
        store = SettingsStore(root/'settings.json')
        dialog = OracleSettingsDialog(config, store, assets=geometry_assets())
        debug = None
        try:
            dialog.preset_workflow.set_autosave(False)
            dialog.show()
            self.app.processEvents()
            enabled = dialog.controls['interaction.drag_enabled']
            response = dialog.controls['interaction.drag_responsiveness']
            self.assertEqual(response.value(), 83)
            for language in ('zh', 'en'):
                language_manager().set_language(language)
                dialog.resize(800, 760)
                self.app.processEvents()
                self.assertLess(abs(enabled.mapTo(dialog, enabled.rect().center()).y()
                                    -response.mapTo(dialog, response.rect().center()).y()), 5)
                self.assertEqual(dialog.pages['general'].horizontalScrollBar().maximum(), 0)
            response.setValue(100)
            enabled.setChecked(False)
            self.assertFalse(response.isEnabled())
            self.assertEqual(dialog.candidate().interaction.drag_responsiveness, 1.)
            enabled.setChecked(True)
            self.assertTrue(response.isEnabled())
            store.save(dialog.candidate())
            saved = store.load()
            self.assertEqual(saved.interaction.drag_responsiveness, 1.)
            debug = OracleDebugWindow(saved, load_atlas=False)
            self.assertEqual(debug.scene.drag.responsiveness, 1.)
            debug.reset_scene()
            self.assertEqual(debug.scene.drag.responsiveness, 1.)
        finally:
            if debug is not None:
                debug.close()
            dialog.shutdown()
            dialog.deleteLater()
            language_manager().set_language('zh')
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            self.app.processEvents()

    def test_desktop_applies_global_value_and_preserves_it_across_scale_and_workarea(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        isolate_characters(self, root)
        config = AppConfig(interaction=InteractionConfig(drag_enabled=True, drag_responsiveness=.75))
        assets, store = geometry_assets(), SettingsStore(root/'settings.json')
        with patch('rw_creature_pet.oracle.ui.desktop.QSystemTrayIcon.isSystemTrayAvailable', return_value=True):
            window = OracleDesktopWindow(config, config_store=store, assets=assets)
        window.timer.stop()
        try:
            window.bind_screen(FakeScreen(QRect(-1920, 40, 1920, 1080), 1.5))
            self.assertEqual(window.motion.scene.drag.responsiveness, .75)
            before = window.motion.scene
            updated = replace(window.current_settings(), interaction=replace(config.interaction, drag_responsiveness=1.))
            window.apply_settings(updated, assets)
            self.assertIs(window.motion.scene, before)
            self.assertEqual(before.drag.responsiveness, 1.)
            window.change_scale(2.)
            self.assertIsNot(window.motion.scene, before)
            self.assertEqual(window.motion.scene.drag.responsiveness, 1.)
            window.bind_screen(FakeScreen(QRect(100, 20, 1600, 900), 1.))
            self.assertEqual(window.motion.scene.drag.responsiveness, 1.)
            self.assertEqual(store.load().interaction.drag_responsiveness, 1.)
            self.assertTrue(window.windowFlags() & Qt.WindowType.WindowTransparentForInput)
        finally:
            window.close()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            self.app.processEvents()


if __name__ == '__main__':
    unittest.main()
