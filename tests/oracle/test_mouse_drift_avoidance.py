"""失重漫游中的鼠标漂开：路线接管、自由朝向、活动带和行为恢复"""
from dataclasses import replace
import unittest
from unittest.mock import patch

from rw_creature_pet.oracle.behavior.controller import Activity
from rw_creature_pet.shared.geometry import Vec2
from . import test_mouse_avoidance as ordinary


class DriftMouseAvoidanceTests(unittest.TestCase):
    def setUp(self):
        self.fixture = ordinary.MouseAvoidanceTests()

    def scene(self, **config):
        config.setdefault('cross_edge_probability', 0.)
        s = self.fixture.scene(**config)
        s.drift()
        s.behavior.drift_next_move = s.behavior.drift_next_observation = 100000
        for _ in range(160):
            s.step()
        s.mouse_reaction.avoidance.DELAY = (.25, .25)
        return s

    def pointer(self, s):
        offset = Vec2(0, 30) if s.behavior.drift_edge % 2 else Vec2(30, 0)
        return s.body.chunks[0].position+offset

    def engage(self, s, limit=150):
        for _ in range(limit):
            s.mouse_reaction.pointer = self.pointer(s)
            s.step()
            if s.mouse_reaction.avoidance.moving:
                return s.mouse_reaction.avoidance
        self.fail(f'未漂开: {s.behavior.state}, {s.target}')

    def test_manual_drift_can_dodge_at_rest_or_in_flight_without_adding_lean(self):
        for in_flight in (False, True):
            with self.subTest(in_flight=in_flight):
                s = self.scene(base_side='top')
                b = s.behavior
                self.assertFalse(b.enabled, '手动漫游不依赖自主循环开关')
                if in_flight:
                    b.drift_move_to(s, s.body.chunks[0].position+Vec2(80, 0))
                    for _ in range(30):
                        s.step()
                    self.assertFalse(s.navigator.done)
                original = s.navigator.route
                deadline = b.drift_duration
                a = self.engage(s)
                self.assertTrue(a.drifting)
                self.assertIsNot(s.navigator.route, original)
                route, speed = s.navigator.route, s.travel_speed
                ticks = b.drift_ticks
                for tick in range(320):
                    axis = s.body.direction
                    s.mouse_reaction.pointer = self.pointer(s)
                    s.step()
                    self.assertEqual(b.drift_ticks, ticks+tick+1)
                    self.assertEqual(b.drift_duration, deadline)
                    self.assertTrue(b.drift_active)
                    self.assertFalse(b.drift_recovering)
                    self.assertLess(s.pose.gravity_scale, .05)
                    self.assertEqual((a.lean, a.lean_goal, a.pivot_weight), (0., 0., 0.))
                    self.assertIsNone(a.pivot_axis)
                    self.assertEqual(a.offset, Vec2())
                    self.assertFalse(a.leaning)
                    self.assertGreater(axis.x*s.body.direction.x+axis.y*s.body.direction.y, .998)
                    self.assertIs(s.navigator.route, route)
                    self.assertEqual(s.travel_speed, speed)
                    if not a.moving:
                        break
                else:
                    self.fail('漂开没有按时结束')
                self.assertTrue(s.mouse_reaction.active)
                self.assertEqual(s.eyes.attention_target, 1.)

    def test_repeated_dodges_stay_on_current_edge_with_sliding_or_fixed_base(self):
        for side in ('top', 'right', 'bottom', 'left'):
            for sliding in (True, False):
                with self.subTest(side=side, sliding=sliding):
                    s = self.scene(base_side=side, sliding_base=sliding, allowed_edges=(side,))
                    a = s.mouse_reaction.avoidance
                    a.IMPATIENCE_TIME = (.4, .4)
                    a.MOVE_PROBABILITY = 1.
                    region = s.navigator.region if s.navigator else s.body_region
                    edge = s.behavior.drift_edge
                    box = region.edge_boxes[edge]
                    segments = 0
                    for _ in range(650):
                        s.mouse_reaction.pointer = self.pointer(s)
                        was_moving = a.moving
                        start = s.body.chunks[0].position
                        s.step()
                        if a.moving and not was_moving:
                            segments += 1
                            self.assertLessEqual((s.target-start).length(), a.DISTANCE[1]+1e-6)
                            if s.navigator:
                                self.assertTrue(all(box.contains(p) for p in s.navigator.route.samples))
                        self.assertEqual(s.behavior.drift_edge, edge)
                        self.assertTrue(box.contains(s.body.chunks[0].position))
                        self.assertTrue(box.contains(s.target))
                        self.assertLessEqual((s.body.chunks[0].position-s.base).length(), s.arm.maximum_reach+1e-6)
                        self.assertAlmostEqual((s.body.chunks[0].position-s.body.chunks[1].position).length(), 9.)
                        self.assertEqual(a.offset, Vec2())
                        if segments >= 3:
                            break
                    self.assertGreaterEqual(segments, 3)

    def test_dodge_route_finishes_before_autonomous_pearl_notice_then_resumes_drift(self):
        s = self.scene(pearl_fixed_count=1)
        b = s.behavior
        b.NOTICE_TICKS = (2, 2)
        b.OBSERVE_TICKS = (4, 4)
        a = self.engage(s)
        route = s.navigator.route
        deadline = b.drift_duration
        b.drift_next_observation = b.drift_next_move = 0
        b.drift_bout_until = 100000
        for _ in range(320):
            s.mouse_reaction.pointer = self.pointer(s)
            s.step()
            if not a.moving:
                break
            self.assertIs(s.navigator.route, route)
            self.assertEqual(b.state, Activity.DRIFT)
        self.assertEqual(b.state, Activity.NOTICE)
        s.step()
        self.assertFalse(a.busy)
        s.mouse_reaction.pointer = None
        self.fixture.until(s, lambda: b.completed_cycles == 1, 1800)
        self.assertTrue(b.drift_active)
        self.assertEqual(b.drift_duration, deadline)
        self.assertEqual(b.state, Activity.DRIFT)
        self.assertTrue(s.pearl.settled)

    def test_finishing_dodge_resumes_navigation_without_restoring_old_target(self):
        s = self.scene(base_side='top')
        b = s.behavior
        b.drift_move_to(s, s.body.chunks[0].position+Vec2(80, 0))
        old_target = s.target
        b.drift_next_move = 0
        a = self.engage(s)
        dodge_target = s.target
        self.assertNotEqual(old_target, dodge_target)
        self.fixture.until(s, lambda: not a.moving, 320)
        s.mouse_reaction.pointer = None
        self.fixture.until(s, lambda: s.target != dodge_target, 300)
        self.assertTrue(b.drift_active)
        self.assertFalse(b.drift_recovering)
        self.assertEqual(b.state, Activity.DRIFT)
        self.assertNotEqual(s.target, old_target)

    def test_manual_pearl_and_crossing_take_priority_over_dodge(self):
        for command in ('pearl', 'cross'):
            with self.subTest(command=command):
                s = self.scene(base_side='top', pearl_fixed_count=1)
                a = self.engage(s)
                if command == 'pearl':
                    s.observe_pearl('recall')
                else:
                    self.assertTrue(s.behavior.start_drift_crossing(s, 1))
                route = s.navigator.route
                for _ in range(25):
                    s.mouse_reaction.pointer = self.pointer(s)
                    s.step()
                    self.assertFalse(a.busy)
                    self.assertIs(s.navigator.route, route)
                    self.assertTrue(s.behavior.drift_active)

    def test_movement_permission_disabled_option_and_matrix_blockage_prevent_dodge(self):
        for reason in ('movement', 'option', 'matrix'):
            with self.subTest(reason=reason):
                s = self.scene()
                a = s.mouse_reaction.avoidance
                if reason == 'movement':
                    s.behavior.movement_enabled = False
                elif reason == 'option':
                    s.mouse_reaction.configure(s, replace(ordinary.WATCH, hover_avoidance_enabled=False))
                route, target = s.navigator.route, s.target
                with patch.object(s.behavior, 'matrix_clear', return_value=reason != 'matrix'):
                    for _ in range(160):
                        s.mouse_reaction.pointer = self.pointer(s)
                        s.step()
                        self.assertFalse(a.moving)
                        self.assertEqual(a.lean, 0.)
                        self.assertEqual(a.offset, Vec2())
                self.assertIs(s.navigator.route, route)
                self.assertEqual(s.target, target)

    def test_deadline_ends_dodge_and_recovers_upright(self):
        s = self.scene()
        a = self.engage(s)
        s.behavior.drift_duration = s.behavior.drift_ticks+1
        s.mouse_reaction.pointer = None
        s.step()
        self.assertTrue(s.behavior.drift_recovering)
        s.step()
        self.assertFalse(a.busy)
        self.fixture.until(s, lambda: not s.behavior.drift_active and s.arrived and s.pose.settled)
        self.assertAlmostEqual(s.pose.angle, 0., places=4)
        self.assertEqual(a.offset, Vec2())

    def test_drag_and_pause_cancel_drift_dodge_without_position_jump(self):
        for command in ('drag', 'pause'):
            with self.subTest(command=command):
                s = self.scene()
                a = self.engage(s)
                positions = [c.position for c in s.body.chunks]
                if command == 'drag':
                    s.drag.set_enabled(True)
                    self.assertTrue(s.drag.press(s.head.position, lambda _: True))
                else:
                    s.mouse_reaction.cancel(s)
                self.assertEqual(positions, [c.position for c in s.body.chunks])
                s.step()
                self.assertFalse(a.busy)
                self.assertIsNone(a.delay)

    def test_switch_from_lean_to_drift_discards_pivot_without_teleporting(self):
        s = self.fixture.scene()
        a = self.fixture.start(s)
        for _ in range(200):
            s.step()
        self.assertGreater(a.offset.length(), 1.)
        positions = [c.position for c in s.body.chunks]
        s.drift()
        self.assertEqual(positions, [c.position for c in s.body.chunks])
        self.assertEqual(a.offset, Vec2())
        self.assertEqual(a.lean, 0.)
        self.assertIsNone(a.pivot_axis)
        s.behavior.drift_next_move = s.behavior.drift_next_observation = 100000
        a.DELAY = (.25, .25)
        self.engage(s)
        self.assertTrue(a.drifting)
        self.assertFalse(a.leaning)


if __name__ == '__main__':
    unittest.main()
