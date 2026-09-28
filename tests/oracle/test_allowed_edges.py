"""允许边缘：配置连通性、完整路径与开放底座轨道、不越界的自主/手动行为。"""
from itertools import combinations
import unittest

from rw_creature_pet.oracle.config import EDGE_NAMES, OracleConfig
from rw_creature_pet.oracle.navigation import EdgePlanner, EdgeRegion, RoundedRail, SlidingBase
from rw_creature_pet.oracle.scene import OracleScene, OracleWorld
from rw_creature_pet.shared.geometry import Vec2


def center(box):
    return Vec2((box.left+box.right)/2, (box.top+box.bottom)/2)


def selections():
    for count in range(1, 5):
        for edges in combinations(EDGE_NAMES, count):
            if set(edges) not in ({'top', 'bottom'}, {'left', 'right'}):
                yield edges


class AllowedEdgesTests(unittest.TestCase):
    def test_config_rejects_disconnected_empty_unknown_and_missing_default(self):
        for edges, base in (([], 'top'), (['top', 'bottom'], 'top'), (['left', 'right'], 'left'),
                            (['top', 'unknown'], 'top'), (['top', 'top'], 'top'),
                            (['bottom'], 'top'), ('top', 'top')):
            with self.subTest(edges=edges), self.assertRaises(ValueError):
                OracleConfig(allowed_edges=edges, base_side=base)
        self.assertEqual(OracleConfig.from_mapping({}).allowed_edges, EDGE_NAMES)
        self.assertEqual(OracleConfig.from_mapping({'allowed_edges': ['left', 'top']}).allowed_edges,
                         ('top', 'left'))

    def test_all_contiguous_selections_route_and_rail_stay_in_enabled_corridors(self):
        for edges in selections():
            with self.subTest(edges=edges):
                world = OracleWorld(960, 600, .2, allowed_edges=edges)
                region = EdgeRegion(world)
                planner, rail = EdgePlanner(world, region), RoundedRail(world)
                for a in region.boxes:
                    for b in region.boxes:
                        route = planner.plan(center(a), center(b))
                        for point in route.samples:
                            self.assertTrue(region.contains(point))
                        for start, end in zip(route.samples, route.samples[1:]):
                            self.assertTrue(region.segment_safe(start, end))
                arm_region = EdgeRegion(world, body=False)
                for index in range(301):
                    point = rail.sample(rail.length*index/300)[0]
                    self.assertTrue(arm_region.contains(point))
                if len(edges) < 4:
                    self.assertEqual(rail.sample(-100), rail.sample(0))
                    self.assertEqual(rail.sample(rail.length+100), rail.sample(rail.length))
                    self.assertEqual(rail.delta(1, rail.length-1), rail.length-2)
                    for start in (0., rail.length):
                        base = SlidingBase(rail, rail.sample(start)[0], 2.8)
                        base.velocity = -2. if start == 0 else 2.
                        base.step(rail.sample(start)[0], rail.sample(start)[0], 300.)
                        self.assertGreaterEqual(base.s, 0.)
                        self.assertLessEqual(base.s, rail.length)

    def test_three_sides_cannot_take_shortcut_across_disabled_fourth_side(self):
        world = OracleWorld(960, 600, .2, allowed_edges=('top', 'right', 'left'))
        region = EdgeRegion(world)
        a, b = Vec2(70, 550), Vec2(890, 550)
        self.assertTrue(region.contains(a) and region.contains(b))
        self.assertFalse(region.segment_safe(a, b))
        route = EdgePlanner(world, region).plan(a, b)
        self.assertLess(min(point.y for point in route.samples), 100)
        self.assertTrue(all(region.contains(point) for point in route.samples))

    def test_autonomy_drift_pearl_targets_and_drag_recovery_use_selected_edges(self):
        for edges in (('left',), ('top', 'left'), ('top', 'right', 'bottom')):
            with self.subTest(edges=edges):
                scene = OracleScene(OracleConfig(allowed_edges=edges, base_side=edges[0],
                    world_width=640, world_height=480, pearl_matrix_enabled=True, pearl_orbits_enabled=True))
                region = scene.navigator.region
                for name in EDGE_NAMES:
                    point = center(region.edge_boxes[EDGE_NAMES.index(name)])
                    self.assertTrue(region.contains(scene.project_target(point)))
                source = scene.behavior.current_edge(scene)
                for target in ((source-1) % 4, (source+1) % 4):
                    result = scene.behavior.adjacent_route(scene, target)
                    if target not in region.allowed_edges:
                        self.assertIsNone(result)
                    elif result:
                        self.assertTrue(all(region.contains(p) for p in result[2].samples))
                scene.drift()
                for _ in range(600):
                    scene.step()
                    self.assertTrue(region.contains(scene.body.chunks[0].position))
                    self.assertTrue(scene.arm_region.contains(scene.base))
                scene.drag.set_enabled(True)
                scene.drag.press(scene.body.chunks[0].position, lambda point: True)
                scene.drag.move(Vec2(320, 240))
                for _ in range(20):
                    scene.step()
                scene.drag.release(cancel=True)
                self.assertTrue(region.contains(scene.drag.home))
                for _ in range(900):
                    scene.step()
                    if not scene.drag.controlling:
                        break
                self.assertFalse(scene.drag.controlling)
                self.assertTrue(region.contains(scene.body.chunks[0].position))
