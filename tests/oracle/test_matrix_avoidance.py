"""自主落点避让矩阵，保留手动接管、矩阵迁移及受限活动带。"""
from dataclasses import replace
import unittest
from unittest.mock import patch

from rw_creature_pet.oracle.behavior import Activity
from rw_creature_pet.oracle.config import OracleConfig
from rw_creature_pet.oracle.scene import OracleScene
from rw_creature_pet.shared.geometry import Vec2


class MatrixAvoidanceTests(unittest.TestCase):
    def scene(self, **options):
        config = replace(OracleConfig(pearl_matrix_enabled=True, pearl_matrix_count=7), **options)
        scene = OracleScene(config)
        scene.appearance.step = lambda scene: None
        return scene

    def assert_clear(self, scene, point):
        matrix, radius = scene.pearl_matrix, scene.config.pearl_matrix_avoid_radius
        self.assertGreaterEqual((point-matrix.anchor.position).length(), radius)
        self.assertGreaterEqual((point-matrix.home_for(point)).length(), radius)
        self.assertEqual(scene.project_target(point), point)

    def test_radius_validation_and_disabled_modes_preserve_destinations(self):
        for value in (-1, 301, float('nan'), float('inf'), True, '80'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                OracleConfig(pearl_matrix_avoid_radius=value)
        baseline = self.scene(pearl_matrix_enabled=False)
        scenes = [self.scene(pearl_matrix_count=0), self.scene(pearl_matrix_avoid_radius=0)]
        for _ in range(25):
            point = baseline.behavior.short_point(baseline)
            for scene in scenes:
                self.assertEqual(scene.behavior.short_point(scene), point)

    def test_preview_has_no_effect_on_anchor_route_or_revision(self):
        scene = self.scene()
        matrix = scene.pearl_matrix
        before = (matrix.anchor.position, matrix.anchor.home, matrix.anchor.target,
                  matrix.anchor.route, matrix.follow_bounds, matrix.revision, matrix._replan_ticks)
        point = scene.navigator.region.edge_boxes[1].clamp(Vec2(900, 260))
        preview = matrix.home_for(point)
        self.assertNotEqual(preview, matrix.anchor.home)
        self.assertEqual(before, (matrix.anchor.position, matrix.anchor.home, matrix.anchor.target,
                                  matrix.anchor.route, matrix.follow_bounds, matrix.revision,
                                  matrix._replan_ticks))
        matrix.step(point)
        self.assertEqual(matrix.anchor.home, preview)

    def test_rejects_overlap_after_matrix_follows_even_if_current_center_is_far(self):
        scene = self.scene()
        matrix = scene.pearl_matrix
        box = scene.navigator.region.edge_boxes[1]
        candidates = [box.clamp(Vec2(860, y)) for y in range(150, 500, 10)]
        point = next(p for p in candidates if (p-matrix.anchor.position).length() > 300
                     and (p-matrix.home_for(p)).length() < 80)
        self.assertFalse(scene.behavior.matrix_clear(scene, point))

    def test_short_drift_and_neighbor_destinations_respect_clearance_on_all_edges(self):
        for size in ((640, 480), (960, 600), (1920, 1040)):
            for side in ('top', 'right', 'bottom', 'left'):
                for count in (7, 14, 64):
                    with self.subTest(size=size, side=side, count=count):
                        scene = self.scene(world_width=size[0], world_height=size[1],
                                           base_side=side, pearl_matrix_count=count)
                        behavior = scene.behavior
                        edge = behavior.current_edge(scene)
                        behavior.drift_edge = edge
                        for _ in range(10):
                            for point in (behavior.short_point(scene),
                                          behavior.drift_point(scene, scene.body.chunks[0].position)):
                                if point is not None:
                                    self.assert_clear(scene, point)
                                    self.assertTrue(scene.navigator.region.edge_boxes[edge].contains(point))
                        result = behavior.adjacent_route(scene)
                        if result is not None:
                            dest, point, route = result
                            self.assertIn(dest, ((edge-1) % 4, (edge+1) % 4))
                            self.assert_clear(scene, point)
                            self.assertEqual(route.curves[-1].d, point)

    def test_single_edge_and_fixed_base_keep_original_reach_constraints(self):
        for sliding in (True, False):
            scene = self.scene(sliding_base=sliding, allowed_edges=('top',))
            for _ in range(30):
                point = scene.behavior.short_point(scene)
                self.assertIsNotNone(point)
                self.assert_clear(scene, point)
                self.assertTrue(scene.body_region.edge_boxes[0].contains(point))
            self.assertIsNone(scene.behavior.adjacent_route(scene))

    def test_arrival_stays_clear_after_matrix_migration(self):
        for side in ('top', 'right', 'bottom', 'left'):
            scene = self.scene(base_side=side)
            for _ in range(600):
                scene.step()
            for adjacent in (False, False, True, False):
                self.assertTrue(scene.behavior.start_roam(scene, adjacent=adjacent))
                for _ in range(2000):
                    scene.step()
                    if (scene.behavior.state == Activity.IDLE and scene.arrived
                            and scene.pearl_matrix.settled):
                        break
                else:
                    self.fail(f'{side}: movement or matrix migration did not settle')
                self.assertGreaterEqual((scene.body.chunks[0].position
                                         - scene.pearl_matrix.anchor.position).length(), 80.)

    def test_no_space_falls_back_without_moving_or_forcing_a_crossing(self):
        scene = self.scene(pearl_matrix_avoid_radius=300, allowed_edges=('top',))
        behavior, target = scene.behavior, scene.target
        self.assertIsNone(behavior.short_point(scene))
        self.assertFalse(behavior.start_roam(scene))
        self.assertEqual(scene.target, target)
        behavior.start_meditation(scene)
        self.assertEqual(behavior.state, Activity.IDLE)
        self.assertEqual(scene.target, target)
        self.assertIsNone(behavior.approach_point(scene))

    def test_meditation_moves_away_and_manual_targets_remain_available(self):
        scene = self.scene()
        matrix = scene.pearl_matrix
        start = scene.body.chunks[0].position
        matrix.anchor.position = matrix.anchor.home = matrix.region.clamp(start)
        scene.behavior.start_meditation(scene)
        self.assertEqual(scene.behavior.state, Activity.MEDITATE)
        self.assert_clear(scene, scene.target)
        scene.set_target(start)
        self.assertEqual(scene.target, scene.project_target(start))
        self.assertFalse(scene.behavior.matrix_clear(scene, scene.target))

    def test_idle_overlap_waits_until_normal_decision_then_moves_away(self):
        scene = self.scene()
        for _ in range(800):
            scene.step()
        scene.set_autonomous(True)
        behavior, matrix = scene.behavior, scene.pearl_matrix
        matrix.anchor.position = matrix.anchor.home = matrix.region.clamp(scene.body.chunks[0].position)
        behavior.duration = 20
        behavior.state_ticks = 0
        with patch.object(behavior, 'choose_activity', return_value=Activity.IDLE) as choose:
            for _ in range(19):
                behavior.step(scene)
                self.assertEqual(behavior.state, Activity.IDLE)
            behavior.step(scene)
        self.assertEqual(choose.call_count, 0)
        self.assertEqual(behavior.state, Activity.ROAM)
        self.assert_clear(scene, scene.target)

    def test_orbit_endpoint_inside_matrix_is_not_used(self):
        scene = self.scene(pearl_matrix_enabled=False)
        scene.observe_pearl('orbit')
        behavior = scene.behavior
        point = behavior.approach_point(scene)
        self.assertIsNotNone(point)
        # 使用真实局部弧线，把矩阵中心放到其落点，检查停止观察处的筛选。
        scene.body.chunks[0].position = point
        edge = behavior.current_edge(scene)
        route = scene.navigator.planner.local_arc(point, scene.observed_pearl.position,
                                                  scene.navigator.region.edge_boxes[edge], behavior.orbit_sign)
        self.assertIsNotNone(route)
        scene.set_pearl_matrix(True)
        matrix = scene.pearl_matrix
        matrix.anchor.position = matrix.anchor.home = matrix.region.clamp(route.curves[-1].d)
        self.assertFalse(behavior.start_orbit(scene))


if __name__ == '__main__':
    unittest.main()
