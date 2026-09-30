"""独立显示层的坐标、穿透契约、单一时钟交接与静止开销回归。"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from dataclasses import replace
import unittest
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QRect, Qt
from PySide6.QtWidgets import QApplication

from rw_creature_pet.config import AppConfig
from rw_creature_pet.shared.geometry import Vec2
from rw_creature_pet.oracle.desktop import OracleDesktopWindow
from rw_creature_pet.oracle.render import OracleRenderer
from rw_creature_pet.oracle.overseer import puppet_position
from rw_creature_pet.overseer.events import EventPhase
from rw_creature_pet.overseer.model import Anchor, Edge
from tests.oracle.test_desktop import FakeScreen


class OverseerDesktopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        config = AppConfig()
        config = replace(config, oracle=replace(config.oracle, halo_enabled=False),
                         desktop=replace(config.desktop, autonomous=False))
        with patch('rw_creature_pet.oracle.desktop.QSystemTrayIcon.isSystemTrayAvailable', return_value=True):
            self.w = OracleDesktopWindow(config, renderer=OracleRenderer())
        self.w.timer.stop()
        self.screen = FakeScreen(QRect(-1280, 40, 1280, 680), 1.5)
        self.w.bind_screen(self.screen)
        self.layer = self.w.overseer_layer

    def tearDown(self):
        self.w.close()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()

    def show_watcher(self, edge=Edge.BOTTOM):
        layer = self.layer
        layer.events.preview(layer.model.bounds, Anchor(edge, .8))
        for _ in range(65):
            layer.model.step()
        layer.refresh(1.)
        self.app.processEvents()

    def settle(self):
        for _ in range(850):
            self.w.motion.step()
        self.assertTrue(self.w.motion.scene.appearance.sleeping)
        self.w.advance()
        self.app.processEvents()

    def test_small_overlay_flags_scaling_four_edges_and_global_mouse(self):
        layer, w = self.layer, self.w
        for flag in (Qt.WindowType.Tool, Qt.WindowType.WindowTransparentForInput,
                     Qt.WindowType.WindowDoesNotAcceptFocus, Qt.WindowType.WindowStaysOnTopHint):
            self.assertTrue(layer.windowFlags() & flag)
        self.assertTrue(layer.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents))
        self.assertTrue(layer.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground))
        self.assertTrue(layer.isWindow())
        self.assertTrue(layer.mask().isEmpty())
        for dpr in (1., 1.5, 2.):
            for scale in (1., 1.5, 2.):
                self.screen.dpr = dpr
                w.requested_scale = scale
                w.rebuild()
                for edge in Edge:
                    self.show_watcher(edge)
                    root = w.motion.viewport.to_global(layer.model.root)
                    expected = {Edge.TOP: self.screen.rect.y(),
                                Edge.RIGHT: self.screen.rect.x()+self.screen.rect.width(),
                                Edge.BOTTOM: self.screen.rect.y()+self.screen.rect.height(),
                                Edge.LEFT: self.screen.rect.x()}[edge]
                    self.assertAlmostEqual(root.y if edge in (Edge.TOP, Edge.BOTTOM) else root.x, expected)
                    self.assertTrue(self.screen.rect.contains(layer.geometry()))
                    self.assertLess(layer.width()*layer.height(), self.screen.rect.width()*self.screen.rect.height()*.15)
                    p = w.motion.viewport.to_global(layer.model.root+layer.model.normal*15)
                    with patch('rw_creature_pet.overseer.desktop.QCursor.pos', return_value=QPoint(round(p.x), round(p.y))):
                        self.assertLess((layer.mouse_world()-layer.model.root-layer.model.normal*15).length(), 2)
                    image = layer.grab().toImage()
                    self.assertTrue(any(bytes(image.constBits())))
                    # 验证可见根部也贴边，不仅验证锚点；允许不足一个像素的栅格取整。
                    horizontal = edge in (Edge.TOP, Edge.BOTTOM)
                    along = image.width() if horizontal else image.height()
                    def edge_alpha(offset, i):
                        x, y = {Edge.TOP: (i, offset), Edge.BOTTOM: (i, image.height()-1-offset),
                                Edge.LEFT: (offset, i), Edge.RIGHT: (image.width()-1-offset, i)}[edge]
                        return image.pixelColor(x, y).alpha()
                    self.assertTrue(any(edge_alpha(offset, i) for offset in (0, 1) for i in range(along)),
                                    (edge, dpr, scale))

    def test_reads_mouse_without_drag_and_without_adding_hit_region(self):
        w, layer = self.w, self.layer
        self.show_watcher()
        self.assertFalse(w.drag_action.isChecked())
        p = w.motion.viewport.to_global(layer.model.root+layer.model.normal*12)
        hit = w.drag_hit
        with patch('rw_creature_pet.overseer.desktop.QCursor.pos', return_value=QPoint(round(p.x), round(p.y))):
            w.step_scene()
        self.assertTrue(layer.model.scared)
        self.assertIsNotNone(layer.model.target)
        self.assertIs(w.drag_hit, hit)
        self.assertFalse(w.drag_input.isVisible())
        w.set_drag_enabled(True)
        hit = w.drag_hit
        layer.refresh(1.)
        self.assertIs(w.drag_hit, hit)
        self.assertFalse(hit.get(w.renderer, w.motion.scene, 1.).contains(layer.model.eye_position()))

    def test_activity_does_not_repaint_or_wake_sleeping_puppet(self):
        w, layer = self.w, self.layer
        self.settle()
        self.show_watcher(Edge.BOTTOM)
        s = w.motion.scene
        revision = s.appearance.revision
        far = QPoint(round(w.motion.viewport.x+w.motion.viewport.width/2),
                     round(w.motion.viewport.y+w.motion.viewport.height/2))
        with patch.object(w, 'update') as puppet_update, patch.object(w.renderer, 'draw') as puppet_draw, \
             patch.object(s.appearance, 'step_cloth') as cloth, patch.object(s.appearance.cords, 'step') as cords, \
             patch.object(layer, 'update', wraps=layer.update) as watcher_update, \
             patch('rw_creature_pet.overseer.desktop.QCursor.pos', return_value=far):
            for _ in range(80):
                w.last_time -= .025
                w._next_render_time = 0.
                w.advance()
                self.app.processEvents()
            self.assertGreater(watcher_update.call_count, 20)
            puppet_update.assert_not_called()
            puppet_draw.assert_not_called()
            cloth.assert_not_called()
            cords.assert_not_called()
        self.assertEqual(s.appearance.revision, revision)
        self.assertTrue(s.appearance.sleeping)

    def test_absent_event_has_no_cursor_physics_or_paint_work(self):
        w, layer = self.w, self.layer
        self.settle()
        with patch('rw_creature_pet.overseer.desktop.QCursor.pos') as cursor, \
             patch.object(layer.model, 'step') as physics, patch.object(layer, 'update') as update, \
             patch.object(w, 'update') as puppet_update, \
             patch('rw_creature_pet.oracle.desktop.puppet_position') as puppet_center:
            for enabled in (False, True):
                layer.events.configure(replace(layer.model.config, enabled=enabled, check_interval=30))
                for _ in range(10):
                    w.last_time -= .025
                    w._next_render_time = 0.
                    w.advance()
            cursor.assert_not_called()
            physics.assert_not_called()
            update.assert_not_called()
            puppet_update.assert_not_called()
            puppet_center.assert_not_called()

    def test_live_puppet_center_triggers_avoidance_without_mouse_or_drag(self):
        w, layer = self.w, self.layer
        for scale in (1., 2.):
            w.requested_scale = scale
            w.rebuild()
            for edge in Edge:
                self.show_watcher(edge)
                scene = w.motion.scene
                near = layer.model.root+layer.model.normal*90
                delta = near-puppet_position(scene)
                for chunk in scene.body.chunks:
                    chunk.position += delta
                with patch.object(w.motion, 'step'), patch.object(layer, 'mouse_world', return_value=None):
                    w.step_scene()
                self.assertTrue(layer.model.scared, (scale, edge))
                self.assertIsNone(layer.model.target)  # 人偶不是注视目标。
                self.assertFalse(w.drag_action.isChecked())

    def test_relocation_keeps_one_small_layer_and_sleeping_puppet_cache(self):
        w, layer = self.w, self.layer
        self.settle()
        layer.events.configure(replace(layer.model.config, relocation_probability=1,
                                       duration_min=30, duration_max=30))
        self.assertTrue(layer.events.start(w.overseer_spawn_context()))
        for _ in range(64):
            layer.model.step()
        layer.refresh(1.)
        root, rect = layer.model.root, layer.geometry()
        scene, hit = w.motion.scene, w.drag_hit
        revision = scene.appearance.revision
        point = w.motion.viewport.to_global(root)
        with patch('rw_creature_pet.overseer.desktop.QCursor.pos', return_value=QPoint(round(point.x), round(point.y))), \
             patch.object(w, 'update') as puppet_update, patch.object(w.renderer, 'draw') as puppet_draw, \
             patch.object(scene.appearance, 'step_cloth') as cloth, patch.object(scene.appearance.cords, 'step') as cords:
            for _ in range(100):
                w.last_time -= .025
                w._next_render_time = 0.
                w.advance()
                self.app.processEvents()
            puppet_update.assert_not_called()
            puppet_draw.assert_not_called()
            cloth.assert_not_called()
            cords.assert_not_called()
        self.assertEqual(layer.events.event_count, 1)
        self.assertEqual(layer.events.relocation_count, 1)
        self.assertNotEqual(layer.model.root, root)
        self.assertNotEqual(layer.geometry(), rect)
        self.assertTrue(layer.isVisible())
        self.assertTrue(self.screen.rect.contains(layer.geometry()))
        self.assertLess(layer.width()*layer.height(), self.screen.rect.width()*self.screen.rect.height()*.15)
        self.assertIs(w.overseer_layer, layer)
        self.assertIs(w.drag_hit, hit)
        self.assertEqual(scene.appearance.revision, revision)
        self.assertTrue(scene.appearance.sleeping)

    def test_origin_shift_preserves_event_but_size_change_removes_old_layer(self):
        w, layer = self.w, self.layer
        w.config = replace(w.config, overseer=replace(w.config.overseer, enabled=True))
        w.sync_overseer()
        layer.events.start(w.overseer_spawn_context())
        for _ in range(60):
            layer.model.step()
        layer.refresh(1.)
        old_rect, root, remaining = layer.geometry(), layer.model.root, layer.events.remaining
        self.screen.rect.translate(50, -20)
        w.rebuild()
        self.assertEqual(layer.geometry(), old_rect.translated(50, -20))
        self.assertEqual(layer.model.root, root)
        self.assertEqual(layer.events.remaining, remaining)
        count = layer.events.event_count
        self.screen.rect = QRect(0, 0, 640, 480)
        w.rebuild()
        self.assertFalse(layer.isVisible())
        self.assertFalse(layer.model.active)
        self.assertEqual(layer.events.phase, EventPhase.COOLDOWN)
        self.assertEqual(layer.events.event_count, count)
        self.assertEqual(layer.viewport.world_size, w.motion.viewport.world_size)
        w.bind_screen(None)
        self.assertFalse(layer.isVisible())
        self.assertTrue(w.clock.paused)
        w.bind_screen(self.screen)
        self.assertFalse(layer.isVisible())
        self.assertEqual(layer.events.phase, EventPhase.COOLDOWN)

    def test_debug_handoff_has_one_controller_and_freezes_desktop_owner(self):
        w, layer = self.w, self.layer
        layer.events.start(w.overseer_spawn_context())
        events = layer.events
        count, remaining = events.event_count, events.remaining
        w.open_debug()
        debug = w.debug_window
        debug.timer.stop()
        self.assertIs(debug.canvas.overseer_events, events)
        self.assertIs(debug.canvas.overseer, layer.model)
        self.assertEqual(debug.canvas.overseer_bounds(), layer.model.bounds)
        self.assertFalse(layer.isVisible())
        w.clock.advance(10, w.step_scene)
        self.assertEqual(events.remaining, remaining)
        debug.step_scene()
        self.assertAlmostEqual(events.remaining, remaining-.025)
        debug.close()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()
        self.assertIsNone(w.debug_window)
        self.assertIs(layer.events, events)
        self.assertEqual(events.event_count, count)
        self.assertTrue(layer.model.active)
        self.assertTrue(layer.isVisible())

    def test_debug_preview_and_workspace_change_do_not_leave_old_positions(self):
        w, layer = self.w, self.layer
        w.open_debug()
        debug = w.debug_window
        debug.timer.stop()
        debug.open_overseer_debug()
        debug.overseer_panel.show_button.click()
        self.screen.rect = QRect(0, 0, 800, 600)
        w.rebuild()
        self.assertFalse(layer.isVisible())
        debug.close()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()
        self.assertFalse(layer.model.active)
        self.assertFalse(layer.isVisible())
        self.assertEqual(layer.model.bounds, w.overseer_spawn_context().bounds)

    def test_pause_keeps_visible_pose_and_freezes_event_lifetime(self):
        w, layer = self.w, self.layer
        layer.events.start(w.overseer_spawn_context())
        for _ in range(40):
            layer.model.step()
        layer.refresh(1.)
        w.set_paused(True)
        snapshot = layer.events.remaining, layer.model.extended, layer.model.revision
        w.last_time -= 5
        w.advance()
        self.assertEqual((layer.events.remaining, layer.model.extended, layer.model.revision), snapshot)
        self.assertTrue(layer.isVisible())


if __name__ == '__main__':
    unittest.main()
