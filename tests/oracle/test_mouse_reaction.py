"""邻近注视的优先级、睡眠唤醒、坐标、设置与暂停/拖动边界。"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtWidgets import QApplication

from rw_creature_pet.config import AppConfig
from rw_creature_pet.interaction.config import InteractionConfig
from rw_creature_pet.oracle.assets import OracleAssets
from rw_creature_pet.oracle.config import OracleConfig
from rw_creature_pet.oracle.ui.debug_window import OracleDebugWindow
from rw_creature_pet.oracle.ui.desktop import OracleDesktopWindow, OracleDesktopMotion, OracleDesktopViewport
from rw_creature_pet.oracle.graphics.render import OracleRenderer
from rw_creature_pet.oracle.scene import OracleScene
from rw_creature_pet.oracle.ui.settings import OracleSettingsDialog
from tests.oracle.character_fixture import isolate_characters
from rw_creature_pet.settings_store import SettingsStore
from rw_creature_pet.shared.geometry import Vec2
from tests.oracle.test_desktop import FakeScreen


HOVER = InteractionConfig(hover_dwell_seconds=.25, hover_probability=1., hover_open_probability=1.,
                          hover_avoidance_enabled=False)


class OracleMouseReactionTests(unittest.TestCase):
    def scene(self):
        s = OracleScene(OracleConfig(physics_backend='python', hide_cords=True, halo_enabled=False))
        s.appearance.step = lambda _: None
        s.mouse_reaction.configure(s, HOVER)
        return s

    def test_hover_preempts_window_without_cancelling_pearl_or_movement_choice(self):
        s = self.scene()
        s.set_autonomous_movement(False)
        s.observe_pearl('recall')
        pearl, target = s.observed_pearl, s.target
        s.eyes.begin_reaction(True)
        r, window = s.mouse_reaction, s.window_reaction
        r.configure(s, replace(HOVER, hover_open_probability=0.))
        window.attention.probability = 1.
        window.notice(s, (1, 2), Vec2(0, 0), changed=True)
        r.pointer = s.body.chunks[0].position+Vec2(140, 0)
        for _ in range(40):
            s.step()
        self.assertTrue(r.active)
        self.assertFalse(window.busy)
        self.assertIs(s.observed_pearl, pearl)
        self.assertEqual(s.target, target)
        self.assertFalse(s.behavior.movement_enabled)
        self.assertGreater(s.look_direction.x, .9)
        self.assertEqual(s.eyes.openness, 0.)
        self.assertEqual(s.eyes.target, 1.)
        rng = window.attention.random.getstate()
        window.notice(s, (2, 2), Vec2(0, 0), changed=True)
        self.assertFalse(window.busy)
        self.assertEqual(window.attention.random.getstate(), rng)
        r.pointer = s.body.chunks[0].position+Vec2(-140, 0)
        for _ in range(40):
            s.step()
        self.assertLess(s.look_direction.x, -.9)
        r.pointer = None
        for _ in range(12):
            s.step()
        self.assertFalse(r.active)
        self.assertIsNone(s.eyes.attention_target)
        self.assertEqual(s.eyes.openness, 1.)
        self.assertIs(s.observed_pearl, pearl)

    def test_drag_and_return_cancel_hover_and_rebuild_preserves_config_rng_only(self):
        s = self.scene()
        r = s.mouse_reaction
        r.pointer = s.head.position
        for _ in range(20):
            s.step()
        self.assertTrue(r.active)
        rng = r.attention.random.getstate()
        s.drag.set_enabled(True)
        s.drag.press(s.head.position, lambda _: True)
        s.step()
        self.assertFalse(r.active)
        self.assertIsNone(s.eyes.attention_target)
        s.drag.release()
        r.pointer = s.head.position
        s.step()
        self.assertFalse(r.active)
        self.assertEqual(r.attention.elapsed, 0.)
        new = OracleDesktopMotion(s.config, OracleDesktopViewport(0, 0, 1280, 720), s).scene
        self.assertEqual(new.mouse_reaction.config, HOVER)
        self.assertEqual(new.mouse_reaction.attention.random.getstate(), rng)
        self.assertFalse(new.mouse_reaction.active)
        self.assertIsNone(new.mouse_reaction.pointer)
        new.reset()
        self.assertEqual(new.mouse_reaction.config, HOVER)
        self.assertEqual(new.mouse_reaction.attention.random.getstate(), rng)

    def test_stationary_cursor_and_departure_allow_sleep(self):
        s = OracleScene(OracleConfig(physics_backend='python', hide_cords=True,
                                    halo_enabled=False, pearl_fixed_count=0))
        s.mouse_reaction.configure(s, HOVER)
        for _ in range(350):
            s.step()
        r = s.mouse_reaction
        r.pointer = s.head.position+Vec2(120, 0)
        for _ in range(700):
            s.step()
        self.assertTrue(r.active)
        self.assertEqual(s.eyes.openness, 1.)
        self.assertTrue(s.appearance.sleeping)
        revision = s.appearance.revision
        for _ in range(100):
            s.step()
        self.assertEqual(s.appearance.revision, revision)
        r.pointer = None
        for _ in range(700):
            s.step()
        self.assertTrue(s.appearance.sleeping)
        self.assertEqual(s.eyes.openness, 0.)


class OracleMouseWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def window(self, config):
        with patch('rw_creature_pet.oracle.ui.desktop.QSystemTrayIcon.isSystemTrayAvailable', return_value=True):
            w = OracleDesktopWindow(config, scale=config.desktop.scale, renderer=OracleRenderer())
        w.timer.stop()
        self.addCleanup(w.close)
        return w

    def test_desktop_pointer_mapping_pause_and_click_through_without_drag(self):
        config = AppConfig(interaction=HOVER)
        config = replace(config, desktop=replace(config.desktop, autonomous=False, scale=1.5))
        w = self.window(config)
        w.bind_screen(FakeScreen(QRect(-1280, 40, 1280, 680), 1.5))
        s = w.motion.scene
        s.appearance.step = lambda _: None
        point = s.body.chunks[0].position+Vec2(100, 0)
        global_pos = w.motion.viewport.to_global(point)
        with patch('rw_creature_pet.oracle.ui.desktop.QCursor.pos', return_value=QPoint(round(global_pos.x), round(global_pos.y))):
            for _ in range(20):
                w.step_scene()
            self.assertTrue(s.mouse_reaction.active)
            self.assertLess((s.mouse_reaction.attention.target-point).length(), 2.)
            self.assertFalse(s.drag.enabled)
            self.assertFalse(s.behavior.movement_enabled)
            self.assertTrue(w.windowFlags() & Qt.WindowType.WindowTransparentForInput)
            self.assertFalse(w.drag_input.isVisible())
            w.set_paused(True)
            self.assertFalse(s.mouse_reaction.active)
            w.clock.advance(5., w.step_scene)
            self.assertEqual(s.mouse_reaction.attention.elapsed, 0.)
            w.set_paused(False)
            for _ in range(5):
                w.step_scene()
            self.assertFalse(s.mouse_reaction.active)

    def test_debug_sampling_respects_canvas_zoom_and_pause(self):
        w = OracleDebugWindow(AppConfig(interaction=HOVER), load_atlas=False)
        self.addCleanup(w.close)
        w.timer.stop()
        w.show()
        self.app.processEvents()
        w.canvas.magnifier = False
        point = w.scene.head.position+Vec2(80, 0)
        for scale in (1., 1.5, 2.):
            w.canvas.set_view_scale(scale)
            w.canvas.center_on_pet()
            local = w.canvas.world_to_view(point)
            global_pos = w.canvas.mapToGlobal(QPoint(round(local.x), round(local.y)))
            with patch('rw_creature_pet.oracle.ui.debug_window.QCursor.pos', return_value=global_pos):
                w.scene.mouse_reaction.cancel(w.scene)
                for _ in range(15):
                    w.step_scene()
                self.assertTrue(w.scene.mouse_reaction.active)
                self.assertLess((w.scene.mouse_reaction.attention.target-point).length(), 2.)
        w.set_paused(True)
        self.assertFalse(w.scene.mouse_reaction.active)

    def test_settings_save_reload_apply_and_zero_probability_without_rebuild(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            (root/'RainWorld_Data').mkdir()
            (root/'RainWorld_Data/resources.assets').touch()
            config = replace(AppConfig(interaction=HOVER), game_dir=root)
            store = SettingsStore(root/'settings.json')
            w = self.window(config)
            w.config_store = store
            s = w.motion.scene
            s.mouse_reaction.pointer = s.head.position
            for _ in range(15):
                s.step()
            self.assertTrue(s.mouse_reaction.active)
            assets = OracleAssets(w.renderer, '', {}, '')
            isolate_characters(self, store.path.parent)
            d = OracleSettingsDialog(config, store, assets=assets, commit=w.apply_settings)
            self.addCleanup(d.close)
            d.controls['interaction.hover_radius'].setValue(240.)
            d.controls['interaction.hover_dwell_seconds'].setValue(2.5)
            d.controls['interaction.hover_probability'].setValue(0.)
            d.controls['interaction.hover_open_probability'].setValue(35.)
            d.controls['interaction.hover_avoidance_enabled'].setChecked(True)
            d.save()
            self.assertIs(w.motion.scene, s)
            self.assertFalse(s.mouse_reaction.active)
            self.assertIsNone(s.eyes.attention_target)
            loaded = store.load()
            self.assertEqual(loaded.interaction, replace(HOVER, hover_radius=240., hover_dwell_seconds=2.5,
                                                       hover_probability=0., hover_open_probability=.35,
                                                       hover_avoidance_enabled=True))
            self.assertEqual(s.mouse_reaction.config, loaded.interaction)
            d2 = OracleSettingsDialog(loaded, store, assets=assets)
            self.addCleanup(d2.close)
            self.assertEqual(d2.controls['interaction.hover_open_probability'].value(), 35.)
            self.assertTrue(d2.controls['interaction.hover_avoidance_enabled'].isChecked())
            d2.tabs.setCurrentWidget(d2.pages['behavior'])
            d2.show()
            self.app.processEvents()
            checkbox = d2.controls['interaction.hover_avoidance_enabled']
            probability = d2.controls['interaction.hover_probability']
            self.assertTrue(d2.behavior_styles.groups['mouse_avoidance'].content.isAncestorOf(checkbox))
            self.assertTrue(d2.behavior_styles.groups['mouse_attention'].content.isAncestorOf(probability))
            checkbox.setChecked(False)
            d2.save()
            self.assertFalse(store.load().interaction.hover_avoidance_enabled)
            w.bind_screen(FakeScreen(QRect(0, 0, 1280, 720)))
            self.assertEqual(w.motion.scene.mouse_reaction.config, loaded.interaction)


if __name__ == '__main__':
    unittest.main()
