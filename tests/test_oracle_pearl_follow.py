"""珍珠跟随活动范围、绕角、行为接管与静止开销。"""
from dataclasses import replace
import unittest
from unittest.mock import patch

from rw_creature_pet.geometry import Vec2
from rw_creature_pet.oracle import OracleScene
from rw_creature_pet.oracle_behavior import Activity
from rw_creature_pet.oracle_config import OracleConfig
from rw_creature_pet.oracle_pearl import PearlState


class OraclePearlFollowTests(unittest.TestCase):
    def scene(self, **settings):
        scene = OracleScene(replace(OracleConfig(), **settings))
        scene.appearance.step = lambda scene: None
        return scene

    def assert_safe(self, scene):
        p = scene.pearl
        self.assertTrue(p.follow_bounds.contains(p.home))
        self.assertTrue(p.region.contains(p.home))
        self.assertTrue(p.region.segment_safe(p.previous_position, p.position))
        self.assertLessEqual(p.velocity.length(), p.FOLLOW_SPEED+1e-7)

    def test_config_and_clipped_home_at_all_edges(self):
        for name in ('pearl_follow_width', 'pearl_follow_height'):
            for value in (True, float('inf'), float('nan'), 0, 159, '300'):
                with self.subTest(name=name, value=value), self.assertRaises(ValueError):
                    OracleConfig.from_mapping({name: value})
        for side in ('top', 'right', 'bottom', 'left'):
            scene = self.scene(world_width=640, world_height=480, base_side=side,
                               pearl_follow_width=160, pearl_follow_height=160)
            p = scene.pearl
            self.assert_safe(scene)
            for point in (Vec2(0, 0), Vec2(640, 480), Vec2(320, 240), Vec2(-999, 999)):
                before = p.position
                scene.set_pearl_home(point)
                self.assertEqual(p.position, before, '手动设点也不能瞬移')
                self.assert_safe(scene)

    def test_short_movement_and_idle_do_not_reanchor_or_plan(self):
        scene = self.scene()
        p = scene.pearl
        before = (p.home, p.position, p.revision, p.route)
        with patch.object(p.planner, 'plan', wraps=p.planner.plan) as plan:
            scene.set_target(scene.body.chunks[0].position+Vec2(45, -10))
            for _ in range(650):
                scene.step()
                self.assert_safe(scene)
            self.assertTrue(scene.arrived)
            self.assertEqual((p.home, p.position, p.revision, p.route), before)
            self.assertEqual(plan.call_count, 0)

    def test_max_speed_long_straight_follow_catches_up_with_bounded_replanning(self):
        scene = self.scene(world_width=4000, world_height=1040)
        p, center = scene.pearl, scene.body.chunks[0].position
        peak, acceleration = 0., 0.
        with patch.object(p.planner, 'plan', wraps=p.planner.plan) as plan:
            for tick in range(700):
                center += Vec2(2, 0)
                velocity = p.velocity
                p.follow_home(center, 360, 280)
                p.step()
                peak = max(peak, abs(center.x-p.position.x))
                acceleration = max(acceleration, (p.velocity-velocity).length())
                self.assert_safe(scene)
            self.assertLess(peak, 270)
            self.assertLessEqual(acceleration, .091)
            self.assertLess(plan.call_count, 30, '不可每帧重建整条曲线')
            for _ in range(600):
                p.follow_home(center, 360, 280)
                p.step()
            self.assertTrue(p.settled)
            self.assertEqual(p.position, p.home)
            saved = (p.position, p.home, p.revision, plan.call_count)
            for _ in range(200):
                p.follow_home(center, 360, 280)
                p.step()
            self.assertEqual((p.position, p.home, p.revision, plan.call_count), saved)

    def test_both_directions_at_four_corners_then_return_to_new_home(self):
        sides = ('top', 'right', 'bottom', 'left')
        for edge, side in enumerate(sides):
            for direction in (-1, 1):
                with self.subTest(side=side, direction=direction):
                    scene = self.scene(base_side=side, float_speed=2.)
                    p, old_home = scene.pearl, scene.pearl.home
                    destination = (edge+direction) % 4
                    scene.behavior.start_roam(scene, adjacent=True, target_edge=destination)
                    for tick in range(4000):
                        scene.step()
                        self.assert_safe(scene)
                        if scene.behavior.state == Activity.IDLE and scene.arrived and p.settled:
                            break
                    self.assertLess(tick, 3999)
                    self.assertNotEqual(p.home, old_home)
                    self.assertEqual(p.position, p.home)
                    self.assertTrue(p.region.segment_safe(scene.body.chunks[0].position, p.home))
                    self.assertTrue(all(c.certified_safe(p.region) for c in p.route.curves))
                    home, glyph = p.home, p.glyph_id
                    scene.observe_pearl('recall')
                    for tick in range(3000):
                        scene.step()
                        self.assert_safe(scene)
                        if scene.behavior.completed_cycles:
                            break
                    self.assertLess(tick, 2999)
                    self.assertEqual(p.position, home)
                    self.assertEqual(p.glyph_id, glyph)

    def test_full_lap_at_max_body_speed_does_not_leave_pearl_on_old_edge(self):
        scene = self.scene(float_speed=2.)
        scene.start_lap()
        for tick in range(5000):
            scene.step()
            self.assert_safe(scene)
            p, center = scene.pearl, scene.body.chunks[0].position
            self.assertTrue(p.region.segment_safe(center, p.home))
            # 圆角和加速允许短暂落后，但不会在旧边越落越远。
            self.assertLess(abs(p.position.x-center.x), 300)
            self.assertLess(abs(p.position.y-center.y), 260)
            if scene.arrived and p.settled:
                break
        self.assertLess(tick, 4999)
        self.assertTrue(p.follow_bounds.contains(p.position))

    def test_reading_controls_pearl_while_home_can_update_then_cancel_follows(self):
        scene = self.scene()
        p = scene.pearl
        scene.observe_pearl('recall')
        for _ in range(700):
            scene.step()
            if scene.behavior.state == Activity.OBSERVE:
                break
        self.assertEqual(scene.behavior.state, Activity.OBSERVE)
        target, position = p.target, p.position
        # 模拟观察期间变更活动中心：只改虚拟悬浮点，不抢读珠目标。
        center = scene.body.chunks[0].position+Vec2(400, 0)
        p.follow_home(center, 360, 280, allow_motion=False)
        self.assertEqual((p.target, p.position), (target, position))
        scene.set_target(Vec2(850, 250))
        self.assertEqual(p.position, position)
        self.assertFalse(scene.behavior.active)
        for tick in range(4000):
            scene.step()
            self.assert_safe(scene)
            if scene.arrived and p.settled:
                break
        self.assertLess(tick, 3999)
        self.assertEqual(p.position, p.home)

    def test_standalone_pearl_far_route_remains_safe(self):
        scene = self.scene()
        p = scene.pearl
        p.move_to(Vec2(480, 535))
        self.assertGreater(p.route.length, 1000)
        for tick in range(4000):
            p.step()
            self.assertTrue(p.region.segment_safe(p.previous_position, p.position))
            if p.settled:
                break
        self.assertLess(tick, 3999)
        self.assertEqual(p.position, p.target)


if __name__ == '__main__':
    unittest.main()
