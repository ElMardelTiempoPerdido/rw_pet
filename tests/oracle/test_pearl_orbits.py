"""数量、确定性配色、轨道范围、归位兼容、桌面恢复及绘制缓存。"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from collections import Counter
from dataclasses import replace
from math import tau
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
from rw_creature_pet.oracle.pearl_layout import balanced_colors
from rw_creature_pet.oracle.pearl_matrix import PearlMatrix
from rw_creature_pet.oracle.pearl_orbits import PearlOrbits
from rw_creature_pet.oracle.render import OracleRenderer
from rw_creature_pet.oracle.scene import OracleScene, OracleWorld


class PearlCountTests(unittest.TestCase):
    def test_config_rejects_invalid_counts_and_loads_zero(self):
        for name, maximum in (('pearl_matrix_count', 64), ('pearl_inner_count', 32), ('pearl_outer_count', 32)):
            for value in (-1, True, 2.5, '3', maximum+1):
                with self.subTest(name=name, value=value), self.assertRaises(ValueError):
                    OracleConfig.from_mapping({name: value})
            self.assertEqual(getattr(OracleConfig.from_mapping({name: 0}), name), 0)
        with self.assertRaises(ValueError):
            OracleConfig.from_mapping({'pearl_orbits_enabled': 1})

    def test_color_quotas_round_proportionally_for_all_supported_counts(self):
        for weights in ((0, 12, 2), (3, 2, 1), (1, 0, 1)):
            for count in range(65):
                colors = balanced_colors(count, weights)
                self.assertEqual(colors, balanced_colors(count, weights))
                self.assertEqual(len(colors), count)
                for slot, weight in enumerate(weights):
                    actual = colors.count(slot)
                    self.assertLess(abs(actual-count*weight/sum(weights)), 1.)
                    if weight == 0:
                        self.assertEqual(actual, 0)
        self.assertEqual(Counter(balanced_colors(3, (3, 2, 1))), {0: 1, 1: 1, 2: 1})
        self.assertEqual(Counter(balanced_colors(4, (3, 2, 1))), {0: 2, 1: 1, 2: 1})
        self.assertEqual(Counter(balanced_colors(8, (0, 12, 2))), {1: 7, 2: 1})

    def assert_samples_safe(self, group, world):
        inner = world.inner
        for alpha in (0., .5, 1.):
            for p, _, _ in group.samples(alpha):
                self.assertGreaterEqual(min(p.x-4, p.y-15), -1e-6)
                self.assertLessEqual(p.x+15, world.width+1e-6)
                self.assertLessEqual(p.y+4, world.height+1e-6)
                self.assertTrue(p.x+15 <= inner.left or p.x-4 >= inner.right
                                or p.y+4 <= inner.top or p.y-15 >= inner.bottom, p)

    def test_matrix_all_counts_have_exact_members_and_safe_layout(self):
        for size in ((640, 480), (1920, 1040)):
            world = OracleWorld(*size, .2)
            region = EdgeRegion(world)
            for count in range(1, 65):
                for edge, box in enumerate(region.boxes):
                    center = box.clamp(Vec2(36, 36))
                    matrix = PearlMatrix(world, region, center, Vec2(0, 1), 160, 160, count)
                    self.assertEqual(len(matrix.pearls), count)
                    self.assertEqual(len({p.slot for p in matrix.pearls}), count)
                    self.assert_samples_safe(matrix, world)
                    matrix.step(center)
                    self.assert_samples_safe(matrix, world)

    def test_counts_zero_single_pearl_repeat_and_count_change_during_reading(self):
        scene = OracleScene(OracleConfig(pearl_matrix_enabled=True, pearl_orbits_enabled=True,
                                        pearl_matrix_count=1, pearl_inner_count=0, pearl_outer_count=0))
        scene.appearance.step = lambda _: None
        self.assertIsNone(scene.pearl_orbits)
        for _ in range(2):
            scene.observe_matrix_pearl()
            self.assertEqual(scene.behavior.last_matrix_slot, (0, 0))
            for tick in range(1500):
                scene.step()
                if scene.behavior.state == Activity.IDLE:
                    break
            self.assertLess(tick, 1499)
        scene.observe_matrix_pearl()
        scene.set_autonomous(True)
        scene.set_pearl_counts(matrix=8, inner=4, outer=2)
        self.assertIsNone(scene.behavior.observation_pearl)
        self.assertTrue(scene.behavior.enabled)
        self.assertEqual(len(scene.pearl_matrix.pearls), 8)
        self.assertEqual(len(scene.pearl_orbits.pearls), 6)
        scene.set_pearl_counts(matrix=0, inner=0, outer=0)
        self.assertIsNone(scene.pearl_matrix)
        self.assertIsNone(scene.pearl_orbits)
        self.assertFalse(scene.observe_matrix_pearl())
        scene.reset()
        self.assertIsNone(scene.pearl_matrix)
        self.assertIsNone(scene.pearl_orbits)
        old = scene.config
        with self.assertRaises(ValueError):
            scene.set_pearl_counts(matrix=8, inner=-1)
        self.assertIs(scene.config, old)

    def test_orbits_original_color_templates_and_counter_rotation(self):
        scene = OracleScene(OracleConfig(pearl_orbits_enabled=True, pearl_inner_count=6))
        group = scene.pearl_orbits
        self.assertEqual([p.color_slot for p in group.pearls], [0, 0, 1, 1, 0, 2, 0, 2])
        before = tuple(group.samples()), list(group.phases)
        group.step(scene.body.chunks[0].position, scene.orbit_center)
        for i in (0, 1):
            delta = (group.phases[i]-before[1][i]+tau/2) % tau-tau/2
            self.assertAlmostEqual(delta, group.ANGULAR_SPEEDS[i])
        self.assertEqual(tuple(group.samples(0)), before[0])
        self.assertNotEqual(tuple(group.samples(1)), before[0])

    def test_orbits_both_directions_all_corners_and_quantity_extremes(self):
        for size, follow, counts in (((640, 480), 160, (1, 1)), ((960, 600), 280, (4, 2)),
                                    ((1920, 1040), 160, (32, 32))):
            for clockwise in (True, False):
                with self.subTest(size=size, counts=counts, clockwise=clockwise):
                    world = OracleWorld(*size, .2)
                    region = EdgeRegion(world)
                    center = region.boxes[0].clamp(Vec2(size[0]/2, 70))
                    group = PearlOrbits(world, region, center, center+Vec2(0, -34), follow, follow, *counts)
                    route = EdgePlanner(world, region).lap(center, clockwise)
                    members = group.pearls
                    seen = set()
                    with patch.object(group.anchor.planner, 'plan', wraps=group.anchor.planner.plan) as plan:
                        for tick in range(int(route.length/2)+600):
                            center = route.sample(min(route.length, tick*2))
                            group.step(center, center+Vec2(0, -34))
                            self.assertTrue(group.region.segment_safe(group.anchor.previous_position, group.anchor.position))
                            seen.update(i for i, box in enumerate(group.region.boxes) if box.contains(group.anchor.position))
                            if tick % 12 == 0:
                                self.assert_samples_safe(group, world)
                        self.assertLess(plan.call_count, tick/11)
                    self.assertEqual(seen, {0, 1, 2, 3})
                    self.assertEqual(members, group.pearls)
                    self.assertTrue(group.anchor.settled)

    def test_orbits_do_not_block_autonomy_or_meditation(self):
        scene = OracleScene(OracleConfig(pearl_orbits_enabled=True))
        scene.appearance.step = lambda _: None
        for _ in range(300):
            scene.step()
        self.assertFalse(scene.pearls_settled)
        self.assertTrue(scene.observation_pearls_settled)
        scene.set_autonomous(True)
        scene.behavior.duration = 1
        with patch.object(scene.behavior, 'choose_activity', return_value=Activity.NOTICE):
            for _ in range(50):
                scene.step()
                if scene.behavior.state == Activity.NOTICE:
                    break
        self.assertEqual(scene.behavior.state, Activity.NOTICE)
        scene.meditate()
        scene.behavior.duration = 5
        for tick in range(1200):
            scene.step()
            if scene.behavior.state == Activity.IDLE:
                break
        self.assertLess(tick, 1199)

    def test_resize_preserves_runtime_counts_and_disabling_both_rings(self):
        scene = OracleScene(OracleConfig())
        scene.set_pearl_counts(matrix=9, inner=3, outer=5)
        scene.set_pearl_matrix(True)
        scene.set_pearl_orbits(True)
        colors = [p.color_slot for p in scene.pearl_orbits.pearls]
        for viewport in (OracleDesktopViewport(0, 0, 640, 480), OracleDesktopViewport(-1000, 0, 1080, 1920)):
            new = OracleDesktopMotion(OracleConfig(), viewport, scene).scene
            self.assertEqual(len(new.pearl_matrix.pearls), 9)
            self.assertEqual([p.color_slot for p in new.pearl_orbits.pearls], colors)
            self.assertEqual(new.pearl_orbits.previous_positions, new.pearl_orbits.positions)
            self.assert_samples_safe(new.pearl_orbits, new.world)
        scene.set_pearl_orbits(False)
        new = OracleDesktopMotion(OracleConfig(pearl_orbits_enabled=True), viewport, scene).scene
        self.assertIsNone(new.pearl_orbits)


class PearlOrbitRenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_orbit_rotation_reuses_body_cache_and_zero_counts_restore_sleep(self):
        scene = OracleScene(OracleConfig(pearl_orbits_enabled=True))
        for _ in range(900):
            scene.step()
        self.assertTrue(scene.appearance.sleeping)
        renderer = OracleRenderer()
        image = QImage(960, 600, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        try:
            renderer.draw(painter, scene)
            frame, revision = renderer._frame, scene.appearance.revision
            for _ in range(60):
                scene.step()
                renderer.draw(painter, scene)
                self.assertIs(renderer._frame, frame)
                self.assertEqual(scene.appearance.revision, revision)
            before = scene.pearl_visual_revision, scene.pearl_orbits.positions
            for alpha in (0., .5, 1.):
                renderer.draw(painter, scene, alpha)
            self.assertEqual(before, (scene.pearl_visual_revision, scene.pearl_orbits.positions))
        finally:
            painter.end()
        scene.set_pearl_counts(inner=0, outer=0)
        revision = scene.pearl_visual_revision
        for _ in range(200):
            scene.step()
        self.assertEqual(scene.pearl_visual_revision, revision)
        self.assertTrue(scene.pearls_settled)

    def test_live_counts_pause_reset_and_checkbox(self):
        window = OracleDebugWindow(AppConfig(), load_atlas=False)
        window.timer.stop()
        try:
            window.set_paused(True)
            window.orbits_box.setChecked(True)
            window.matrix_box.setChecked(True)
            window.pearl_count_inputs['matrix'].setValue(8)
            window.pearl_count_inputs['inner'].setValue(3)
            window.pearl_count_inputs['outer'].setValue(0)
            scene = window.scene
            self.assertEqual(len(scene.pearl_matrix.pearls), 8)
            self.assertEqual(len(scene.pearl_orbits.pearls), 3)
            before = scene.ticks, scene.pearl_visual_revision
            window.on_timer()
            self.assertEqual(before, (scene.ticks, scene.pearl_visual_revision))
            window.reset_scene()
            self.assertEqual(len(scene.pearl_matrix.pearls), 8)
            self.assertEqual(len(scene.pearl_orbits.pearls), 3)
            window.pearl_count_inputs['matrix'].setValue(0)
            self.assertFalse(window.matrix_pearl_button.isEnabled())
            window.orbits_box.setChecked(False)
            self.assertIsNone(scene.pearl_orbits)
        finally:
            window.close()


if __name__ == '__main__':
    unittest.main()
