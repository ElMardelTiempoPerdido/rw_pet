"""延迟躲避：慢速同边移动、输入优先级、许可和恢复静止"""
from dataclasses import replace
from math import atan2, degrees
import unittest
from unittest.mock import patch

from rw_creature_pet.interaction.config import InteractionConfig
from rw_creature_pet.oracle.behavior.controller import Activity
from rw_creature_pet.oracle.config import OracleConfig
from rw_creature_pet.oracle.ui.desktop import OracleDesktopMotion, OracleDesktopViewport
from rw_creature_pet.oracle.scene import OracleScene
from rw_creature_pet.shared.geometry import Vec2


WATCH = InteractionConfig(hover_dwell_seconds=.25, hover_probability=1., hover_open_probability=1.)


class MouseAvoidanceTests(unittest.TestCase):
    def until(self, scene, predicate, limit=1500):
        for _ in range(limit):
            scene.step()
            if predicate():
                return
        self.fail(f'{scene.behavior.state}: arrived={scene.arrived}, lean={scene.mouse_reaction.avoidance.lean}')

    def scene(self, *, render_motion=False, **config):
        config.setdefault('pearl_fixed_count', 0)
        scene = OracleScene(OracleConfig(physics_backend='python', hide_cords=True, halo_enabled=False, **config))
        if not render_motion:
            scene.appearance.step = lambda _: None
        self.until(scene, lambda: scene.arrived and scene.pose.settled)
        scene.set_autonomous(True)
        scene.behavior.duration = 100000
        self.until(scene, lambda: scene.arrived and scene.pose.settled)
        scene.mouse_reaction.configure(scene, WATCH)
        avoidance = scene.mouse_reaction.avoidance
        avoidance.DELAY = (3., 3.)
        avoidance.PROBABILITY = avoidance.STEP_SHARE = 1.
        return scene

    def start(self, scene, offset=Vec2(100, 0)):
        scene.mouse_reaction.pointer = scene.body.chunks[0].position+offset
        self.until(scene, lambda: scene.mouse_reaction.avoidance.attempted, limit=250)
        return scene.mouse_reaction.avoidance

    def test_ordinary_limit_applies_before_avoidance_offset(self):
        for sign in (-1, 1):
            with self.subTest(sign=sign):
                s = self.scene()
                s.set_tilt(sign*20.)
                s.behavior.enter(Activity.ROAM)
                s.navigator.velocity = Vec2(sign*s.config.float_speed, 0)
                for offset, expected in ((0., 25.), (60., 85.), (0., 25.)):
                    s.mouse_reaction.avoidance.lean = sign*offset
                    for _ in range(400):
                        s.pose.step(s)
                    self.assertAlmostEqual(s.pose.angle+s.tilt_degrees, sign*expected, places=4)
                    self.assertTrue(s.pose.settled)

    def test_large_lean_reaches_angle_on_all_edges_then_returns_continuously(self):
        for side in ('top', 'right', 'bottom', 'left'):
            for sign in (-1, 1):
                with self.subTest(side=side, sign=sign):
                    s = self.scene(base_side=side)
                    a = s.mouse_reaction.avoidance
                    a.LEAN = (60., 60.)
                    a.LEAN_SPEED = 10.
                    a.STEP_SHARE = 0.
                    self.start(s, Vec2(sign*100, 0))
                    self.assertAlmostEqual(a.lean_goal, -sign*60.)
                    peak = 0.
                    for _ in range(1200):
                        previous = s.body.direction
                        s.step()
                        axis = s.body.direction
                        peak = max(peak, -sign*degrees(atan2(axis.x, -axis.y)))
                        self.assertGreater(axis.x*previous.x+axis.y*previous.y, .998)
                        self.assertTrue(s.navigator.region.contains(s.body.chunks[0].position))
                        self.assertLessEqual((s.body.chunks[0].position-s.base).length(), s.arm.maximum_reach+1e-6)
                    self.assertAlmostEqual(peak, 60., delta=.5)
                    self.assertAlmostEqual(s.pose.angle, 0., places=4)
                    self.assertAlmostEqual(degrees(atan2(s.body.direction.x, -s.body.direction.y)), 0., places=4)
                    self.assertFalse(a.busy)
                    self.assertTrue(s.arrived and s.pose.settled)

    def test_dwell_then_extra_delay_one_attempt_and_direction_latched(self):
        s = self.scene()
        r, a = s.mouse_reaction, s.mouse_reaction.avoidance
        origin = s.target
        r.pointer = origin+Vec2(100, 0)
        for _ in range(120):
            s.step()
            self.assertFalse(a.attempted)
            self.assertFalse(a.busy)
            self.assertEqual(s.target, origin)
        self.assertTrue(r.active)
        self.until(s, lambda: a.moving, 20)
        self.assertLess(a.lean_goal, 0.)
        self.assertLess(s.target.x, origin.x)
        target, rng, route = s.target, a.random.getstate(), s.navigator.route
        r.pointer = origin-Vec2(100, 0)
        for _ in range(40):
            s.step()
        self.assertIs(s.navigator.route, route)
        self.assertEqual(s.target, target)
        self.assertLess(s.pose.angle, 0.)
        self.assertLess(s.look_direction.x, 0.)
        self.until(s, lambda: not a.busy and s.arrived and s.pose.settled)
        for _ in range(200):
            s.step()
        self.assertEqual(a.random.getstate(), rng)
        self.assertEqual(s.target, target)
        self.assertTrue(r.active)

    def test_failed_roll_does_not_retry_until_leave_and_return(self):
        s = self.scene()
        a, r = s.mouse_reaction.avoidance, s.mouse_reaction
        a.PROBABILITY = 0.
        self.start(s)
        rng = a.random.getstate()
        a.PROBABILITY = 1.
        for _ in range(400):
            s.step()
        self.assertFalse(a.busy)
        self.assertEqual(a.random.getstate(), rng)
        r.pointer = None
        s.step()
        self.assertFalse(a.attempted)
        self.start(s)
        self.assertTrue(a.moving)

    def test_short_slow_path_stays_in_same_band_on_all_edges_and_corners(self):
        for side, offset in (('top', Vec2(100, 0)), ('right', Vec2(0, 100)),
                             ('bottom', Vec2(-100, 0)), ('left', Vec2(0, -100))):
            for fraction in (.03, .5, .97):
                with self.subTest(side=side, fraction=fraction):
                    s = self.scene(base_side=side, base_fraction=fraction)
                    start = s.body.chunks[0].position
                    edge = s.behavior.current_edge(s)
                    box = s.navigator.region.edge_boxes[edge]
                    a = self.start(s, offset)
                    target = s.target
                    self.assertTrue(a.moving)
                    self.assertLessEqual((target-start).length(), 32.01)
                    self.assertGreater((target-start).length(), 6.)
                    self.assertLess((target-start).x*offset.x+(target-start).y*offset.y, 0.)
                    for curve in s.navigator.route.curves:
                        self.assertTrue(all(box.contains(p) for p in (curve.a, curve.b, curve.c, curve.d)))
                    for _ in range(1200):
                        s.step()
                        self.assertTrue(box.contains(s.body.chunks[0].position))
                        self.assertLessEqual(s.navigator.speed, .45+1e-6)
                        self.assertLess(max(c.velocity.length() for c in s.body.chunks), .6)
                        self.assertLessEqual((s.body.chunks[0].position-s.base).length(), s.arm.maximum_reach+1e-6)
                        if not a.busy and s.arrived and s.pose.settled:
                            break
                    self.assertTrue(s.arrived)
                    self.assertFalse(a.moving)
                    self.assertLess((s.body.chunks[0].position-target).length(), .3)

    def test_stationary_policy_and_reading_allow_lean_without_navigation(self):
        for reading in (False, True):
            with self.subTest(reading=reading):
                s = self.scene(pearl_fixed_count=1)
                s.set_autonomous_movement(False)
                if reading:
                    s.observe_pearl('recall')
                pearl, target = s.observed_pearl, s.target
                a = self.start(s)
                self.assertLess(a.lean_goal, 0.)
                self.assertFalse(a.moving)
                for _ in range(80):
                    s.step()
                self.assertEqual(s.target, target)
                self.assertLess(s.pose.angle, -1.)
                self.assertTrue(s.mouse_reaction.active)
                if reading:
                    self.assertTrue(s.behavior.looking)
                    self.assertIs(s.observed_pearl, pearl)

    def test_matrix_space_and_free_drift_do_not_get_a_new_avoidance_route(self):
        s = self.scene()
        target = s.target
        with patch.object(s.behavior, 'matrix_clear', return_value=False):
            a = self.start(s)
        self.assertFalse(a.moving)
        self.assertNotEqual(a.lean_goal, 0.)
        self.assertEqual(s.target, target)
        s = self.scene()
        s.drift()
        a = self.start(s)
        self.assertTrue(s.behavior.drift_active)
        self.assertFalse(a.busy)

    def test_disable_leave_and_movement_switch_brake_without_teleport(self):
        for action in ('disable', 'leave', 'movement'):
            with self.subTest(action=action):
                s = self.scene()
                a = self.start(s)
                for _ in range(12):
                    s.step()
                before = [c.position for c in s.body.chunks]
                target = s.target
                if action == 'disable':
                    s.mouse_reaction.configure(s, replace(WATCH, hover_avoidance_enabled=False))
                    self.assertTrue(s.mouse_reaction.active)
                elif action == 'leave':
                    s.mouse_reaction.pointer = None
                else:
                    s.set_autonomous_movement(False)
                self.assertEqual(before, [c.position for c in s.body.chunks])
                s.step()
                self.assertFalse(a.moving)
                self.assertNotEqual(s.target, target)
                for old, c in zip(before, s.body.chunks):
                    self.assertLess((c.position-old).length(), .6)
                self.until(s, lambda: s.arrived and s.pose.settled)

    def test_manual_navigation_and_drag_take_priority(self):
        s = self.scene()
        a = self.start(s)
        target = s.project_target(s.target+Vec2(60, 0))
        s.set_target(target)
        route = s.navigator.route
        s.step()
        self.assertFalse(a.moving)
        self.assertEqual(s.target, target)
        self.assertIs(s.navigator.route, route)
        for early in (True, False):
            with self.subTest(early=early):
                s = self.scene()
                a = s.mouse_reaction.avoidance
                s.mouse_reaction.pointer = s.head.position
                if early:
                    for _ in range(40):
                        s.step()
                else:
                    self.start(s)
                s.drag.set_enabled(True)
                self.assertTrue(s.drag.press(s.head.position, lambda _: True))
                s.step()
                self.assertFalse(a.busy)
                self.assertIsNone(a.delay)
                self.assertFalse(s.mouse_reaction.active)
                s.drag.release()
                s.mouse_reaction.pointer = s.head.position
                s.step()
                self.assertFalse(a.busy)
                self.assertIsNone(a.delay)

    def test_reset_rebuild_keep_random_stream_not_pending_reaction(self):
        s = self.scene()
        self.start(s)
        rng = s.mouse_reaction.avoidance.random.getstate()
        s.reset()
        a = s.mouse_reaction.avoidance
        self.assertEqual(a.random.getstate(), rng)
        self.assertFalse(a.busy)
        self.assertIsNone(a.delay)
        new = OracleDesktopMotion(s.config, OracleDesktopViewport(0, 0, 1280, 720), s).scene
        self.assertEqual(new.mouse_reaction.avoidance.random.getstate(), rng)
        self.assertIsNone(new.mouse_reaction.pointer)

    def test_finished_avoidance_allows_sleep_while_mouse_stays(self):
        s = self.scene(render_motion=True)
        self.start(s)
        for _ in range(1400):
            s.step()
        self.assertTrue(s.mouse_reaction.active)
        self.assertFalse(s.mouse_reaction.avoidance.busy)
        self.assertTrue(s.arrived)
        self.assertTrue(s.appearance.sleeping)
        revision = s.appearance.revision
        for _ in range(100):
            s.step()
        self.assertEqual(s.appearance.revision, revision)


if __name__ == '__main__':
    unittest.main()
