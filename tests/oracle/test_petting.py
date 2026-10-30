"""摸摸接管头眼，保留任务、拖动和常睁眼默认值"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import QPoint, QRect, Qt, QCoreApplication, QEvent
from PySide6.QtGui import QImage, QPainter, QColor
from PySide6.QtWidgets import QApplication

from rw_creature_pet.config import AppConfig
from rw_creature_pet.interaction.config import InteractionConfig
from rw_creature_pet.oracle.config import OracleConfig, CustomAppearance
from rw_creature_pet.oracle.eye_config import EyeAppearance
from rw_creature_pet.oracle.scene import OracleScene
from rw_creature_pet.oracle.graphics.render import OracleRenderer
from rw_creature_pet.oracle.interaction.input import PuppetHitMap
from rw_creature_pet.oracle.ui.desktop import OracleDesktopWindow
from rw_creature_pet.oracle.ui.debug_window import OracleDebugWindow
from rw_creature_pet.oracle.ui.settings import OracleSettingsDialog
from rw_creature_pet.presets.profile_library import ProfileLibrary
from rw_creature_pet.settings_store import SettingsStore
from rw_creature_pet.shared.geometry import Vec2
from tests.oracle.test_desktop import FakeScreen
from tests.oracle.character_fixture import geometry_assets, isolate_characters


PET = InteractionConfig(hover_probability=0, petting_seconds=.3, petting_grace_seconds=.4)


class PettingSceneTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def scene(self, *, appearance=True, **kwargs):
        scene = OracleScene(OracleConfig(physics_backend='python', hide_cords=True, halo_enabled=False, **kwargs))
        scene.mouse_reaction.configure(scene, PET)
        if not appearance:
            scene.appearance.step = lambda _: None
        return scene

    def stroke(self, s, ticks=28, *, inside=True):
        for i in range(ticks):
            p = s.head.position+Vec2(2 if i % 2 else -2, 0)
            s.mouse_reaction.sample_input(p, inside=inside)
            s.step()

    def test_only_head_eyes_override_movement_and_pearl_task_continue(self):
        s = self.scene(appearance=False)
        s.set_autonomous_movement(False)
        s.observe_pearl('recall')
        pearl = s.observed_pearl
        s.behavior.duration = 10000
        state, target = s.behavior.state, s.target
        s.eyes.begin_reaction(True)
        rng = s.eyes.random.getstate()
        self.stroke(s, 45)
        self.assertTrue(s.mouse_reaction.petting.active)
        self.assertEqual(s.eyes.closure, 1.)
        self.assertEqual(s.eyes.openness, 0.)
        self.assertEqual(s.behavior.state, state)
        self.assertEqual(s.target, target)
        self.assertIs(s.observed_pearl, pearl)
        self.assertEqual(s.eyes.random.getstate(), rng)
        self.assertLess((s.look_direction-s.body.direction*-.4).length(), .07)
        s.mouse_reaction.sample_input(s.head.position+Vec2(200, 0))
        for _ in range(45):
            s.step()
        self.assertFalse(s.mouse_reaction.petting.busy)
        self.assertEqual(s.eyes.closure, 0.)
        self.assertEqual(s.eyes.openness, 1.)

    def test_window_and_avoidance_cede_then_restart_timing(self):
        s = self.scene(appearance=False)
        s.mouse_reaction.configure(s, replace(PET, hover_probability=1, hover_dwell_seconds=.25))
        s.window_reaction.attention.probability = 1
        s.window_reaction.notice(s, (1, 1), Vec2(), changed=True)
        self.stroke(s)
        self.assertTrue(s.mouse_reaction.petting.active)
        self.assertFalse(s.window_reaction.busy)
        self.assertFalse(s.mouse_reaction.avoidance.engaged)
        self.assertEqual(s.mouse_reaction.avoidance.elapsed, 0.)
        s.mouse_reaction.sample_input(s.head.position+Vec2(80, 0))
        for _ in range(16):
            s.step()
        self.assertFalse(s.mouse_reaction.petting.busy)
        self.assertFalse(s.mouse_reaction.attention.active)
        self.assertLess(s.mouse_reaction.attention.elapsed, .1)

    def test_still_pointer_under_moving_puppet_is_not_movement(self):
        s = self.scene(appearance=False)
        for i in range(80):
            s.mouse_reaction.sample_input(Vec2(i, 0), inside=True, motion_pointer=Vec2(100, 100))
            s.step()
        self.assertFalse(s.mouse_reaction.petting.busy)

    def test_drag_pause_and_reconfigure_cancel_and_do_not_queue_reactions(self):
        s = self.scene(appearance=False)
        self.stroke(s)
        s.drag.set_enabled(True)
        self.assertTrue(s.drag.press(s.head.position, lambda _: True))
        s.step()
        self.assertFalse(s.mouse_reaction.petting.busy)
        self.assertFalse(s.eyes.forced_closed)
        s.drag.release()
        self.assertTrue(s.drag.recovering)
        self.stroke(s, 1)
        self.assertFalse(s.mouse_reaction.petting.busy)  # 归位优先
        s.mouse_reaction.configure(s, replace(PET, petting_enabled=False))
        self.assertFalse(s.mouse_reaction.wants_pointer)

    def test_drift_keeps_motion_and_low_head_uses_body_axis(self):
        s = self.scene(appearance=False)
        s.drift()
        state = s.behavior.state
        self.stroke(s, 22)
        self.assertTrue(s.behavior.drift_active)
        self.assertEqual(s.behavior.state, state)
        self.assertTrue(s.mouse_reaction.petting.active)
        for axis in (Vec2(1, 0), Vec2(0, 1), Vec2(-1, 0)):
            s.body.chunks[1].position = s.body.chunks[0].position-axis*s.body.connection_length
            self.assertEqual(s.mouse_reaction.desired_look(s, Vec2()), axis*-.4)

    def test_default_open_render_closes_both_eyes_and_cache_restores(self):
        shape = CustomAppearance(eye_1=EyeAppearance('#ff0000', default_open=True),
                                 eye_2=EyeAppearance('#0000ff', default_open=True))
        renderer = OracleRenderer()
        def draw(closure):
            image = QImage(160, 160, QImage.Format.Format_ARGB32_Premultiplied)
            image.fill(0)
            p = QPainter(image)
            p.translate(80, 80)
            p.scale(4, 4)
            renderer.draw_head(p, Vec2(), Vec2(0, 10), Vec2(0, -1), Vec2(),
                               shape=shape, eye_closure=closure)
            p.end()
            return image
        opened, closed = draw(0), draw(1)
        for color in ('#ff0000', '#0000ff'):
            rgb = QColor(color).rgb()
            count = lambda img: sum(img.pixel(x, y) == rgb for y in range(160) for x in range(160))
            self.assertEqual(count(opened), count(closed)*2)
        self.assertEqual(draw(0), opened)
        self.assertTrue(shape.eye_1.default_open)

    def test_hit_map_ignores_remote_parts_and_reuses_sleeping_outline(self):
        s = self.scene()
        for _ in range(500):
            s.step()
        renderer, hit = OracleRenderer(), PuppetHitMap()
        with patch.object(hit, 'get', wraps=hit.get) as get:
            for _ in range(50):
                self.assertFalse(hit.contains(renderer, s, Vec2(-500, -500)))
            self.assertEqual(get.call_count, 0)
        self.assertTrue(hit.contains(renderer, s, s.appearance.head.position))
        cached = hit.value
        for _ in range(30):
            self.assertTrue(hit.contains(renderer, s, s.appearance.head.position))
            self.assertIs(hit.value, cached)


class PettingInputAndSettingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        isolate_characters(self, self.root)
        self.enterContext(patch('rw_creature_pet.presets.library.default_appearance_directory', return_value=self.root/'appearances'))
        self.windows = []

    def tearDown(self):
        for w in self.windows:
            if isinstance(w, OracleSettingsDialog):
                w.shutdown()
            w.close()
            w.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()

    def test_desktop_drag_disabled_scale_dpi_origin_and_pause(self):
        config = AppConfig(interaction=PET)
        for scale in (1., 1.5, 2.):
            config = replace(config, desktop=replace(config.desktop, autonomous=False, scale=scale))
            with patch('rw_creature_pet.oracle.ui.desktop.QSystemTrayIcon.isSystemTrayAvailable', return_value=True):
                w = OracleDesktopWindow(config, scale=scale, renderer=OracleRenderer())
            self.windows.append(w)
            w.timer.stop()
            w.bind_screen(FakeScreen(QRect(-1280, 40, 1280, 680), 1.5))
            s = w.motion.scene
            s.behavior.enabled = False
            for i in range(35):
                p = s.appearance.head.position+Vec2(-2 if i % 2 else 2, 0)
                raw = w.motion.viewport.to_global(p)
                with patch('rw_creature_pet.oracle.ui.desktop.QCursor.pos', return_value=QPoint(round(raw.x), round(raw.y))), \
                        patch('rw_creature_pet.oracle.ui.desktop.mouse_button_down', return_value=False):
                    w.step_scene()
            self.assertTrue(s.mouse_reaction.petting.active, scale)
            self.assertFalse(w.drag_input.isVisible())
            self.assertTrue(w.windowFlags() & Qt.WindowType.WindowTransparentForInput)
            w.set_paused(True)
            self.assertFalse(s.mouse_reaction.petting.busy)
            w.clock.advance(5, w.step_scene)
            self.assertEqual(s.mouse_reaction.petting.elapsed, 0.)

    def test_debug_view_scaling_and_pressed_button_cancels(self):
        w = OracleDebugWindow(AppConfig(interaction=PET), load_atlas=False)
        self.windows.append(w)
        w.timer.stop()
        w.show()
        self.app.processEvents()
        w.canvas.magnifier = False
        for scale in (1., 1.5, 2.):
            w.canvas.set_view_scale(scale)
            w.canvas.center_on_pet()
            w.scene.mouse_reaction.cancel(w.scene)
            for i in range(30):
                p = w.scene.appearance.head.position+Vec2(-2 if i % 2 else 2, 0)
                local = w.canvas.world_to_view(p)
                raw = w.canvas.mapToGlobal(QPoint(round(local.x), round(local.y)))
                with patch('rw_creature_pet.oracle.ui.debug_window.QCursor.pos', return_value=raw), \
                        patch('rw_creature_pet.oracle.ui.debug_window.mouse_button_down', return_value=False):
                    w.step_scene()
            self.assertTrue(w.scene.mouse_reaction.petting.active, scale)
            with patch('rw_creature_pet.oracle.ui.debug_window.mouse_button_down', return_value=True):
                w.step_scene()
            self.assertFalse(w.scene.mouse_reaction.petting.busy)

    def test_settings_profile_roundtrip_custom_marker_and_fold_preserves_values(self):
        game = self.root/'game'
        (game/'RainWorld_Data').mkdir(parents=True)
        (game/'RainWorld_Data/resources.assets').touch()
        store = SettingsStore(self.root/'settings.json')
        d = OracleSettingsDialog(AppConfig(game_dir=game), store, assets=geometry_assets())
        self.windows.append(d)
        d.preset_workflow.set_autosave(False)
        group = d.behavior_styles.groups['mouse_attention']
        group.selector.setCurrentIndex(group.selector.findData('mouse_attention.curious'))
        group.selector.activated.emit(group.selector.currentIndex())
        group.advanced.setChecked(True)
        d.controls['interaction.petting_seconds'].setValue(2.25)
        self.assertEqual(group.selector.currentData(), '')
        d.controls['interaction.petting_grace_seconds'].setValue(.85)
        before = d.candidate()
        group.advanced.setChecked(False)
        self.assertEqual(d.candidate(), before)
        d.controls['interaction.petting_enabled'].setChecked(False)
        self.assertFalse(d.controls['interaction.petting_seconds'].isEnabled())
        self.assertEqual(d.candidate().interaction.petting_seconds, 2.25)
        self.assertTrue(d.preset_workflow.flush())
        self.assertEqual(store.load().interaction, d.candidate().interaction)
        role = ProfileLibrary(self.root/'export').export(d.candidate(), 'Petting')
        self.assertEqual(role.config.interaction, d.candidate().interaction)

    def test_debug_dpi_matches_render_and_zoom_does_not_count_as_mouse_movement(self):
        w = OracleDebugWindow(AppConfig(interaction=replace(PET, petting_seconds=.1)), load_atlas=False)
        self.windows.append(w)
        w.timer.stop()
        w.show()
        self.app.processEvents()
        scene = w.scene
        with patch.object(w.canvas, 'devicePixelRatioF', return_value=1.5), \
                patch.object(w.canvas, 'mouse_world', return_value=scene.head.position), \
                patch('rw_creature_pet.oracle.ui.debug_window.QCursor.pos', return_value=QPoint(489, 520)), \
                patch('rw_creature_pet.oracle.ui.debug_window.mouse_button_down', return_value=False), \
                patch.object(w.canvas.drag_hit, 'contains', return_value=True) as hit:
            for scale in (1., 1.5, 2.):
                w.canvas.set_view_scale(scale)
                for _ in range(10):
                    w.step_scene()
                self.assertEqual(hit.call_args.kwargs['raster_scale'], scale)
                self.assertFalse(scene.mouse_reaction.petting.busy)


if __name__ == '__main__':
    unittest.main()
