"""正式固定珠、卫星树、零目标行为、整族过角和数量变更。"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from collections import Counter
from dataclasses import replace
import unittest
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication

from rw_creature_pet.config import AppConfig
from rw_creature_pet.shared.geometry import Vec2
from rw_creature_pet.oracle.behavior import Activity
from rw_creature_pet.oracle.config import OracleConfig
from rw_creature_pet.oracle.debug_window import OracleDebugWindow
from rw_creature_pet.oracle.desktop import OracleDesktopMotion, OracleDesktopViewport
from rw_creature_pet.oracle.navigation import EdgePlanner, EdgeRegion
from rw_creature_pet.oracle.pearl_fixed import FixedPearls
from rw_creature_pet.oracle.render import OracleRenderer
from rw_creature_pet.oracle.scene import OracleScene, OracleWorld


class FixedSatelliteTests(unittest.TestCase):
    def scene(self, **settings):
        scene = OracleScene(replace(OracleConfig(), **settings))
        scene.appearance.step = lambda _: None
        return scene

    def assert_safe(self, group, world):
        hole = world.inner
        for alpha in (0., .5, 1.):
            for p, _, _ in group.samples(alpha):
                self.assertGreaterEqual(min(p.x-4, p.y-15), -1e-6)
                self.assertLessEqual(p.x+15, world.width+1e-6)
                self.assertLessEqual(p.y+4, world.height+1e-6)
                self.assertTrue(p.x+15 <= hole.left or p.x-4 >= hole.right
                                or p.y+4 <= hole.top or p.y-15 >= hole.bottom, p)

    def test_config_and_original_topology_color_counts(self):
        for name in ('pearl_fixed_count', 'pearl_satellite_count'):
            for value in (True, -1, 33, 1.5, '2'):
                with self.assertRaises(ValueError):
                    OracleConfig.from_mapping({name: value})
        scene = self.scene(world_width=1920, world_height=1040, pearl_fixed_count=11, pearl_satellite_count=5)
        group = scene.fixed_pearls
        self.assertEqual(Counter(p.color_slot for p in group.roots), {0: 3, 1: 4, 2: 4})
        self.assertEqual(Counter(p.color_slot for p in group.satellites), {0: 2, 1: 2, 2: 1})
        self.assertEqual([s.root for s in group.satellites], [1, 2, 2, 10, 10])
        self.assertEqual([s.parent for s in group.satellites], [None, None, None, None, 3])
        self.assertEqual([s.radius for s in group.satellites], [18, 38, 38, 42, 12])
        pair = group.satellites[1:3]
        self.assertAlmostEqual(pair[1].phase-pair[0].phase, 3.141592653589793)
        self.assert_safe(group, scene.world)

    def test_configured_members_only_no_hidden_debug_pearl(self):
        scene = self.scene(pearl_fixed_count=2, pearl_satellite_count=1)
        self.assertEqual(len(tuple(scene.fixed_pearls.samples())), 3)
        self.assertIs(scene.pearl, scene.fixed_pearls.roots[0])
        scene.set_pearl_counts(fixed=0)
        self.assertEqual(tuple(scene.fixed_pearls.samples()), ())
        self.assertIsNone(scene.pearl)
        self.assertIsNone(scene.observed_pearl)
        self.assertFalse(scene.observe_pearl())
        self.assertFalse(scene.set_pearl_home(Vec2(100, 50)))
        for action in (lambda: scene.roam(), scene.drift, scene.meditate, scene.stop):
            action()
            for _ in range(10):
                scene.step()
        scene.set_pearl_counts(fixed=1)
        self.assertEqual(len(scene.fixed_pearls.satellites), 1)

    def test_matrix_only_observation_and_orbit_only_skip(self):
        scene = self.scene(pearl_fixed_count=0, pearl_matrix_enabled=True, pearl_matrix_count=1)
        self.assertTrue(scene.observe_pearl('approach'))
        self.assertTrue(scene.behavior.matrix_observation)
        for tick in range(2000):
            scene.step()
            if scene.behavior.completed_cycles:
                break
        self.assertLess(tick, 1999)
        scene.set_pearl_counts(matrix=0)
        scene.set_pearl_orbits(True)
        scene.set_autonomous(True)
        scene.behavior.duration = 1
        with patch.object(scene.behavior, 'choose_activity', return_value=Activity.NOTICE) as choose:
            for _ in range(100):
                scene.step()
            self.assertLessEqual(choose.call_count, 1)
        self.assertEqual(scene.behavior.state, Activity.IDLE)
        self.assertTrue(scene.behavior.enabled)

    def test_families_migrate_both_directions_without_cutting_corners(self):
        for size, counts in (((640, 480), (2, 5)), ((1920, 1040), (11, 5)), ((640, 480), (1, 32))):
            for clockwise in (True, False):
                world = OracleWorld(*size, .2)
                region = EdgeRegion(world)
                center = region.boxes[0].clamp(Vec2(size[0]/2, 60))
                group = FixedPearls(world, region, center, Vec2(0, 1), 160, 160, *counts)
                members = group.satellites
                route = EdgePlanner(world, region).lap(center, clockwise)
                for tick in range(int(route.length/2)+750):
                    center = route.sample(min(route.length, tick*2))
                    group.step(center)
                    for root in group.roots:
                        self.assertTrue(root.region.segment_safe(root.previous_position, root.position))
                    if tick % 16 == 0:
                        self.assert_safe(group, world)
                self.assertTrue(group.roots_settled)
                self.assertEqual(group.satellites, members)

    def test_parent_observation_preserves_satellites_at_all_edges(self):
        for side in ('top', 'right', 'bottom', 'left'):
            scene = self.scene(world_width=640, world_height=480, base_side=side,
                               pearl_fixed_count=1, pearl_satellite_count=5)
            group = scene.fixed_pearls
            home = scene.pearl.home
            scene.observe_pearl('recall')
            for tick in range(2000):
                scene.step()
                if tick % 8 == 0:
                    self.assert_safe(group, scene.world)
                if scene.behavior.completed_cycles:
                    break
            self.assertLess(tick, 1999)
            self.assertEqual(scene.pearl.position, scene.pearl.home)
            self.assertLess((home-scene.pearl.home).length(), 1e-5)
            self.assertEqual(len(group.satellites), 5)

    def test_live_changes_cancel_only_removed_family_and_resize_preserves_identity(self):
        scene = self.scene(pearl_fixed_count=2, pearl_satellite_count=5)
        scene.observe_pearl('recall')
        scene.set_autonomous(True)
        for _ in range(80):
            scene.step()
        original = [(p.glyph_id, p.color_slot) for p in scene.fixed_pearls.roots]
        for viewport in (OracleDesktopViewport(0, 0, 640, 480), OracleDesktopViewport(-1000, 0, 1080, 1920)):
            new = OracleDesktopMotion(OracleConfig(), viewport, scene).scene
            self.assertEqual(original, [(p.glyph_id, p.color_slot) for p in new.fixed_pearls.roots])
            self.assertEqual(new.config.pearl_satellite_count, 5)
            self.assertEqual(new.fixed_pearls.positions, new.fixed_pearls.previous_positions)
            self.assertIsNone(new.behavior.observation_pearl)
            self.assert_safe(new.fixed_pearls, new.world)
        scene.set_pearl_counts(fixed=0)
        self.assertIsNone(scene.observed_pearl)
        self.assertTrue(scene.behavior.enabled)
        self.assertEqual(scene.behavior.state, Activity.IDLE)
        scene.set_pearl_matrix(True)
        scene.observe_matrix_pearl()
        target = scene.observed_pearl
        scene.set_pearl_counts(fixed=3, satellite=1)
        self.assertIs(scene.observed_pearl, target)

    def test_fixed_colors_scale_for_all_counts_and_stationary_roots_do_not_replan(self):
        world = OracleWorld(960, 600, .2)
        region = EdgeRegion(world)
        center = Vec2(480, 60)
        for count in range(1, 33):
            group = FixedPearls(world, region, center, Vec2(0, 1), 360, 280, count, count)
            for members, weights in ((group.roots, (3, 4, 4)), (group.satellites, (2, 2, 1))):
                colors = Counter(p.color_slot for p in members)
                for i, weight in enumerate(weights):
                    self.assertLess(abs(colors[i]-count*weight/sum(weights)), 1)
            self.assert_safe(group, world)
        group = FixedPearls(world, region, center, Vec2(0, 1), 360, 280, 2, 1)
        with patch.object(group.roots[0].planner, 'plan', wraps=group.roots[0].planner.plan) as plan:
            for _ in range(800):
                group.step(center)
            self.assertEqual(plan.call_count, 0)

    def test_manual_home_selects_nearest_fixed_and_auto_visits_both(self):
        scene = self.scene(pearl_fixed_count=2)
        first, second = scene.fixed_pearls.roots
        original = first.home
        point = second.position+Vec2(12, 0)
        scene.set_pearl_home(point)
        self.assertEqual(first.home, original)
        self.assertEqual(second.home, point)
        seen = set()
        for _ in range(8):
            scene.behavior.notice(scene)
            seen.add(scene.behavior.last_fixed_index)
            scene.behavior.cancel(scene)
        self.assertEqual(seen, {0, 1})


class FixedSatelliteRenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_draw_exact_count_body_cache_and_zero_counts_sleep(self):
        scene = OracleScene(OracleConfig(pearl_fixed_count=2, pearl_satellite_count=1))
        for _ in range(900):
            scene.step()
        renderer = OracleRenderer()
        image = QImage(960, 600, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        try:
            with patch.object(renderer, 'draw_pearl_at', wraps=renderer.draw_pearl_at) as draw:
                renderer.draw(painter, scene)
                self.assertEqual(draw.call_count, 3)
            frame = renderer._frame
            for _ in range(80):
                scene.step()
                renderer.draw(painter, scene)
                self.assertIs(renderer._frame, frame)
            scene.set_pearl_counts(fixed=0)
            with patch.object(renderer, 'draw_pearl_at', wraps=renderer.draw_pearl_at) as draw:
                renderer.draw(painter, scene)
                self.assertEqual(draw.call_count, 0)
            revision = scene.pearl_visual_revision
            for _ in range(200):
                scene.step()
            self.assertEqual(revision, scene.pearl_visual_revision)
            self.assertTrue(scene.pearls_settled)
        finally:
            painter.end()

    def test_debug_zero_counts_pause_and_reset(self):
        window = OracleDebugWindow(AppConfig(), load_atlas=False)
        window.timer.stop()
        try:
            window.set_paused(True)
            window.pearl_count_inputs['satellite'].setValue(1)
            window.pearl_count_inputs['fixed'].setValue(0)
            window.refresh()
            self.assertFalse(window.recall_pearl_button.isEnabled())
            window.canvas.grab()
            window.pearl_count_inputs['fixed'].setValue(2)
            self.assertTrue(window.recall_pearl_button.isEnabled())
            scene = window.scene
            before = scene.ticks, scene.pearl_visual_revision
            window.on_timer()
            self.assertEqual(before, (scene.ticks, scene.pearl_visual_revision))
            window.reset_scene()
            self.assertEqual(len(scene.fixed_pearls.roots), 2)
            self.assertEqual(len(scene.fixed_pearls.satellites), 1)
        finally:
            window.close()


if __name__ == '__main__':
    unittest.main()
