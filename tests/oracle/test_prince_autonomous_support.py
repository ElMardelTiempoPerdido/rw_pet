"""Prince 自主支撑余量、被动悬空、选点收尾与水平拖拽回归"""
from dataclasses import replace
import unittest

from rw_creature_pet.oracle.config import OracleConfig
from rw_creature_pet.oracle.scene import OracleScene
from rw_creature_pet.shared.geometry import Vec2


def scene_at(side='right', **values):
    return OracleScene(OracleConfig(body_appearance='prince', physics_backend='auto',
        world_width=1200, world_height=900, edge_fraction=.499, base_side=side,
        base_fraction=.5, pearl_fixed_count=0, pearl_matrix_enabled=False,
        pearl_orbits_enabled=False, halo_enabled=False, **values))


class PrinceAutonomousSupportTests(unittest.TestCase):
    def check_support(self, scene):
        support = scene.prince_tentacles
        upper = scene.body.chunks[0]
        self.assertLess((upper.position-upper.previous_position).length(), 4.)
        self.assertGreaterEqual(sum(p.attached for p in support.parts), 1)
        self.assertLessEqual(sum(not p.attached for p in support.parts), 2)
        longest = max(support.parts, key=lambda p: p.reference_length)
        if longest.attached:
            self.assertLessEqual((longest.grip-support.part_root(longest.definition)).length(),
                                 longest.reference_length*.90+.1)
        for part in support.parts:
            self.assertLessEqual(part.path(1).length, part.reference_length+1e-6)

    def test_deep_destinations_float_then_return_and_finish_on_all_edges(self):
        for side in ('top', 'right', 'bottom', 'left'):
            with self.subTest(side=side):
                scene = scene_at(side)
                for _ in range(250):
                    scene.step()
                start = scene.body.chunks[0].position
                inward = scene.base_normal()
                scene.set_target(start+inward*300)
                floated = set()
                for _ in range(1100):
                    scene.step()
                    self.check_support(scene)
                    for i, part in enumerate(scene.prince_tentacles.parts):
                        if part.free and not part.reaching:
                            floated.add(i)
                            self.assertTrue(part.passive)
                            self.assertEqual(part.wall_probe.weight, 0.)
                            self.assertEqual(part.wall_probe.remaining, 0)
                            self.assertEqual(part.free_search.tick, 0)
                    if scene.arrived:
                        break
                self.assertTrue(scene.arrived)
                self.assertEqual(len(floated), 2)
                # 停在深处不要求短触手强行抓回；可以正常休眠并开始下一次移动
                self.assertTrue(scene.prince_tentacles.settled)
                scene.set_target(start)
                for _ in range(1100):
                    scene.step()
                    self.check_support(scene)
                    if scene.arrived:
                        break
                self.assertTrue(scene.arrived)
                self.assertTrue(all(p.attached for p in scene.prince_tentacles.parts))

    def test_passive_free_tips_enter_drag_search_and_stop_search_after_recovery(self):
        scene = scene_at()
        scene.set_target(scene.body.chunks[0].position+Vec2(-300, 0))
        for _ in range(700):
            scene.step()
        free = [p for p in scene.prince_tentacles.parts if p.free]
        self.assertEqual(len(free), 2)
        scene.drag.set_enabled(True)
        self.assertTrue(scene.drag.press(scene.head.position, lambda _: True))
        for part in free:
            self.assertFalse(part.passive)
            part.wall_probe.wait = 1
        for _ in range(100):
            scene.step()
        self.assertTrue(any(p.wall_probe.weight > .5 for p in free if p.free))
        scene.drag.release()
        for _ in range(1300):
            scene.step()
            if not scene.drag.controlling:
                break
        self.assertFalse(scene.drag.controlling)
        scene.step()
        self.assertTrue(all(p.passive for p in scene.prince_tentacles.parts))

    def test_adjacent_navigation_and_autonomous_destination_selection(self):
        for side, edge in (('right', 2), ('top', 1), ('left', 0), ('bottom', 3)):
            with self.subTest(side=side):
                scene = scene_at(side)
                for _ in range(250):
                    scene.step()
                for _ in range(20):
                    point = scene.behavior.short_point(scene)
                    if point is not None:
                        self.assertTrue(scene.navigator.region.contains(point))
                        self.assertLess((scene.project_target(point)-point).length(), .01)
                self.assertTrue(scene.behavior.start_roam(scene, adjacent=True, target_edge=edge))
                for _ in range(2400):
                    scene.step()
                    self.check_support(scene)
                    if scene.arrived:
                        break
                self.assertTrue(scene.arrived)
                self.assertTrue(scene.navigator.region.edge_boxes[edge].contains(scene.body.chunks[0].position))

    def test_horizontal_drag_reaches_long_tentacle_limit_without_hidden_arm(self):
        for side in ('left', 'right'):
            for slope in (0., .4):
                with self.subTest(side=side, slope=slope):
                    scene = scene_at(side, arm_scale=.35)
                    for _ in range(250):
                        scene.step()
                    start = scene.head.position
                    scene.drag.set_enabled(True)
                    scene.drag.press(start, lambda _: True)
                    direction = Vec2(1 if side == 'left' else -1, slope)
                    for tick in range(340):
                        scene.drag.move(start+direction*min(1000., tick*5.))
                        scene.step()
                        for part in scene.prince_tentacles.parts:
                            self.assertLessEqual(part.path(1).length, part.reference_length*1.2+1e-6)
                    support = scene.prince_tentacles
                    longest = max(support.parts, key=lambda p: p.reference_length)
                    self.assertTrue(longest.attached)
                    self.assertGreater((longest.grip-support.part_root(longest.definition)).length(),
                                       longest.reference_length*1.05)
                    self.assertTrue(scene.drag.outer.contains(scene.body.chunks[0].position))

    def test_drift_uses_same_slack_and_passive_support_rules(self):
        scene = scene_at('top')
        for _ in range(250):
            scene.step()
        scene.behavior.start_drift(scene)
        scene.behavior.drift_next_move = 0
        for _ in range(1800):
            scene.step()
            self.check_support(scene)
            for part in scene.prince_tentacles.parts:
                if part.free and not part.reaching:
                    self.assertTrue(part.passive)
                    self.assertEqual(part.wall_probe.weight, 0.)

    def test_character_switch_restores_mechanical_navigation_region(self):
        scene = scene_at(arm_scale=.35)
        prince_depth = scene.navigator.region.hole.left
        scene.set_target(scene.body.chunks[0].position+Vec2(-300, 0))
        for _ in range(700):
            scene.step()
        scene.config = replace(scene.config, body_appearance='bell')
        scene.sync_character()
        self.assertIsNone(scene.prince_tentacles)
        self.assertEqual(scene.movement_reach, scene.arm.maximum_reach)
        self.assertLess(scene.navigator.region.hole.left, prince_depth)
        scene.step()
        self.assertTrue(scene.navigator.region.contains(scene.body.chunks[0].position))
        scene.config = replace(scene.config, body_appearance='prince')
        scene.sync_character()
        self.assertAlmostEqual(scene.navigator.region.hole.left, prince_depth)


if __name__ == '__main__':
    unittest.main()
