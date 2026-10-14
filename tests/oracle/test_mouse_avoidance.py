"""持续躲避：真实支点、近距离分支、滞后跟随、退出宽限和重复位移"""
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
        a = scene.mouse_reaction.avoidance
        self.fail(f'{scene.behavior.state}: arrived={scene.arrived}, engaged={a.engaged}, lean={a.lean}')

    def scene(self, *, appearance=False, **config):
        config.setdefault('pearl_fixed_count', 0)
        config.setdefault('edge_fraction', .3)
        scene = OracleScene(OracleConfig(physics_backend='python', hide_cords=True, halo_enabled=False, **config))
        if not appearance:
            scene.appearance.step = lambda _: None
        self.until(scene, lambda: scene.arrived and scene.pose.settled)
        scene.set_autonomous(True)
        scene.behavior.duration = 100000
        self.until(scene, lambda: scene.arrived and scene.pose.settled)
        scene.mouse_reaction.configure(scene, WATCH)
        a = scene.mouse_reaction.avoidance
        a.DELAY = (3., 3.)
        a.LEAN = (60., 60.)
        a.PROBABILITY = 1.
        a.MOVE_PROBABILITY = 0.
        a.LEAN_MOVE_PROBABILITY = 0.
        return scene

    def start(self, scene, offset=Vec2(30, 0)):
        scene.mouse_reaction.pointer = scene.body.chunks[0].position+offset
        self.until(scene, lambda: scene.mouse_reaction.avoidance.engaged, limit=250)
        return scene.mouse_reaction.avoidance

    def test_ordinary_limit_applies_before_avoidance_offset(self):
        for sign in (-1, 1):
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

    def test_near_radius_is_smaller_than_attention_and_keeps_initial_delay(self):
        s = self.scene()
        r, a = s.mouse_reaction, s.mouse_reaction.avoidance
        r.pointer = s.head.position+Vec2(120, 0)
        for _ in range(400):
            s.step()
        self.assertTrue(r.active)
        self.assertFalse(a.busy)
        r.pointer = s.body.chunks[0].position+Vec2(30, 0)
        for _ in range(100):
            s.step()
            self.assertFalse(a.engaged)
        self.until(s, lambda: a.engaged, 30)
        self.assertTrue(a.leaning)
        self.assertFalse(a.moving)

    def test_failed_avoidance_can_retry_without_reentering_or_rerolling_eyes(self):
        s = self.scene()
        r, a = s.mouse_reaction, s.mouse_reaction.avoidance
        a.PROBABILITY = 0.
        r.pointer = s.body.chunks[0].position+Vec2(30, 0)
        for _ in range(160):
            s.step()
        rng = r.attention.random.getstate()
        self.assertTrue(r.active)
        self.assertFalse(a.engaged)
        a.PROBABILITY = 1.
        self.until(s, lambda: a.engaged, 200)
        self.assertEqual(r.attention.random.getstate(), rng)

    def test_upper_branch_rotates_around_feet_on_all_edges_and_recovers(self):
        for side in ('top', 'right', 'bottom', 'left'):
            for sign in (-1, 1):
                with self.subTest(side=side, sign=sign):
                    s = self.scene(base_side=side)
                    a = s.mouse_reaction.avoidance
                    origin = s.body.chunks[0].position
                    pivot = origin-s.body.direction*a.PIVOT_LENGTH
                    self.start(s, Vec2(sign*30, 0))
                    for _ in range(600):
                        previous = s.body.direction
                        s.step()
                        axis = s.body.direction
                        self.assertGreater(axis.x*previous.x+axis.y*previous.y, .998)
                        self.assertLess((s.body.chunks[0].position-axis*a.PIVOT_LENGTH-pivot).length(), .3)
                        self.assertTrue(s.navigator.region.contains(s.body.chunks[0].position))
                        self.assertLessEqual((s.body.chunks[0].position-s.base).length(), s.arm.maximum_reach+1e-6)
                    self.assertAlmostEqual(degrees(atan2(s.body.direction.x, -s.body.direction.y)), -sign*60., delta=.1)
                    self.assertGreater((s.head.position-s.mouse_reaction.pointer).length(), 35.)
                    self.assertTrue(a.engaged)
                    s.mouse_reaction.pointer = None
                    self.until(s, lambda: not a.busy and s.arrived and s.pose.settled)
                    self.assertAlmostEqual(s.pose.angle, 0., places=4)
                    self.assertLess((s.body.chunks[0].position-origin).length(), .3)

    def test_following_lags_and_crossing_midline_does_not_flip_immediately(self):
        s = self.scene()
        a = self.start(s)
        self.until(s, lambda: s.pose.settled)
        origin = a.neutral_position(s)
        s.mouse_reaction.pointer = origin+Vec2(-30, 0)
        old = s.pose.angle
        s.step()
        self.assertLess(a.lean_goal, 0.)
        self.assertLess(abs(s.pose.angle-old), 1.)
        for _ in range(350):
            old_axis = s.body.direction
            s.step()
            self.assertGreater(old_axis.x*s.body.direction.x+old_axis.y*s.body.direction.y, .998)
        self.assertGreater(s.pose.angle, 59.)
        self.assertTrue(a.leaning)
        s.mouse_reaction.pointer = origin+Vec2(-30, 35)
        for _ in range(60):
            s.step()
        self.assertTrue(a.leaning, '进入侧倾后不因鼠标短暂移到下半身而切断动作')

    def test_grace_preserves_gaze_eyes_and_window_priority_outside_hover(self):
        s = self.scene()
        a = self.start(s)
        r = s.mouse_reaction
        rng = r.attention.random.getstate()
        near = r.pointer
        r.pointer = a.neutral_position(s)+Vec2(-250, 0)
        for _ in range(30):
            s.step()
        self.assertTrue(a.engaged)
        self.assertEqual(a.gaze_target, r.pointer)
        self.assertEqual(s.eyes.attention_target, 1.)
        s.window_reaction.attention.probability = 1.
        s.window_reaction.notice(s, (1, 2), Vec2(), changed=True)
        self.assertFalse(s.window_reaction.busy)
        r.pointer = near
        s.step()
        self.assertEqual(a.away_elapsed, 0.)
        self.assertEqual(r.attention.random.getstate(), rng)
        r.pointer = None
        for _ in range(65):
            s.step()
        self.assertFalse(a.engaged)
        self.assertFalse(r.active)
        self.assertIsNone(s.eyes.attention_target)

    def test_return_checks_neutral_body_so_leaning_away_does_not_end_itself(self):
        s = self.scene()
        a = s.mouse_reaction.avoidance
        self.start(s)
        s.mouse_reaction.pointer = a.neutral_position(s)+Vec2(40, -70)
        for _ in range(800):
            s.step()
        self.assertGreater(a.clearance(s.mouse_reaction.pointer, s.body.chunks[0].position, s.body.direction), a.EXIT_DISTANCE)
        self.assertLess(a.clearance(s.mouse_reaction.pointer, a.neutral_position(s), a.pivot_axis), a.EXIT_DISTANCE)
        self.assertTrue(a.engaged)
        self.assertLess(s.pose.angle, -59.)

    def test_lower_branch_selects_move_even_when_impatience_probability_is_zero(self):
        for fixed in (False, True):
            s = self.scene(sliding_base=not fixed)
            origin = s.target
            a = self.start(s, Vec2(30, 18))
            self.assertFalse(a.leaning)
            self.assertTrue(a.moving)
            self.assertEqual(a.lean, 0.)
            self.assertGreater((s.target-origin).length(), 6.)
            self.until(s, lambda: not a.moving)
            self.assertTrue(a.engaged)

    def test_close_pursuit_repeats_short_moves_without_rerouting_each_frame(self):
        s = self.scene()
        a = s.mouse_reaction.avoidance
        a.IMPATIENCE_TIME = (1., 1.)
        a.RETRY = (.3, .3)
        a.MOVE_PROBABILITY = 1.
        self.start(s)
        routes = []
        previous_target = s.target
        for _ in range(1200):
            s.mouse_reaction.pointer = s.body.chunks[0].position+Vec2(25, 0)
            prior_route, was_moving = s.navigator.route, a.moving
            s.step()
            if a.moving and not was_moving:
                self.assertGreater((s.target-previous_target).length(), 6.)
                self.assertLessEqual((s.target-previous_target).length(), 33.)
                previous_target = s.target
                routes.append(s.navigator.route)
            elif a.moving and was_moving:
                self.assertIs(prior_route, s.navigator.route)
            self.assertTrue(s.navigator.region.contains(s.body.chunks[0].position))
            if len(routes) >= 3:
                break
        self.assertGreaterEqual(len(routes), 3)
        self.assertTrue(a.leaning)
        self.assertLess(s.pose.angle, -10.)

    def test_lean_can_move_with_initial_turn_and_again_with_a_new_turn(self):
        s = self.scene()
        a = s.mouse_reaction.avoidance
        a.LEAN_MOVE_DISTANCE = (6., 12.)
        a.LEAN_MOVE_PROBABILITY = 1.
        a.IMPATIENCE_TIME = (1000., 1000.)
        start = s.target
        self.start(s)
        self.assertTrue(a.moving)
        self.assertTrue(a.leaning)
        self.assertLess(abs(s.pose.angle), 1., '开始侧倾时即可挪动，无须等侧倾完成')
        self.assertGreaterEqual((s.target-start).length(), a.LEAN_MOVE_DISTANCE[0]-1e-6)
        self.assertLessEqual((s.target-start).length(), a.LEAN_MOVE_DISTANCE[1]+1e-6)
        self.assertLess((s.target-start).length(), a.DISTANCE[0])
        route = s.navigator.route
        for _ in range(25):
            s.mouse_reaction.pointer = a.neutral_position(s)+Vec2(-30, 0)
            s.step()
            self.assertIs(s.navigator.route, route)
        self.until(s, lambda: not a.moving and s.pose.settled and a.retry_seconds == 0.)
        start = s.target
        s.mouse_reaction.pointer = a.neutral_position(s)+Vec2(30, 0)
        self.until(s, lambda: a.moving, 100)
        self.assertIsNot(s.navigator.route, route)
        self.assertLessEqual((s.target-start).length(), a.LEAN_MOVE_DISTANCE[1]+1e-6)

    def test_move_direction_varies_within_small_angle_and_still_avoids_mouse(self):
        for small in (True, False):
            for jitter in (-22., 0., 22.):
                with self.subTest(small=small, jitter=jitter):
                    s = self.scene(base_side='top')
                    a = s.mouse_reaction.avoidance
                    start = a.neutral_position(s)
                    pointer = start+Vec2(30, 0)
                    original = a.random.uniform
                    with patch.object(a.random, 'uniform', side_effect=lambda lo, hi:
                                      jitter if (lo, hi) == (-a.MOVE_ANGLE_JITTER, a.MOVE_ANGLE_JITTER)
                                      else original(lo, hi)):
                        self.assertTrue(a.start_move(s, pointer, small=small))
                    delta = s.target-start
                    distance = a.LEAN_MOVE_DISTANCE if small else a.DISTANCE
                    self.assertGreaterEqual(delta.length(), distance[0]-1e-6)
                    self.assertLessEqual(delta.length(), distance[1]+1e-6)
                    self.assertLess(delta.x, 0., '随机偏角仍然远离鼠标')
                    self.assertAlmostEqual(degrees(atan2(-delta.y, -delta.x)), jitter, places=5)

    def test_stationary_pointer_and_small_jitter_do_not_reroll_lean_moves(self):
        for probability in (0., 1.):
            with self.subTest(probability=probability):
                s = self.scene()
                a = s.mouse_reaction.avoidance
                a.LEAN_MOVE_PROBABILITY = probability
                a.IMPATIENCE_TIME = (1000., 1000.)
                with patch.object(a, 'start_move', wraps=a.start_move) as move:
                    self.start(s, Vec2(10, 0))
                    pointer = s.mouse_reaction.pointer
                    self.assertEqual(move.call_count, int(probability))
                    for i in range(500):
                        s.mouse_reaction.pointer = pointer+Vec2(.2 if i % 2 else -.2, 0)
                        s.step()
                    self.assertEqual(move.call_count, int(probability))
                    self.assertFalse(a.moving)
                    rng = a.random.getstate()
                    for _ in range(100):
                        s.step()
                    self.assertEqual(a.random.getstate(), rng, '保持同一倾角时不逐帧补抽签')

    def test_far_cursor_does_not_trigger_impatient_move_during_grace(self):
        s = self.scene()
        a = self.start(s)
        a.impatience = a.impatience_threshold*1.5
        a.MOVE_PROBABILITY = 1.
        a.LEAN_MOVE_PROBABILITY = 1.
        s.mouse_reaction.pointer = a.neutral_position(s)+Vec2(250, 0)
        for _ in range(30):
            s.step()
        self.assertTrue(a.engaged)
        self.assertFalse(a.moving)
        self.assertGreater(a.impatience, 0.)

    def test_movement_disabled_and_matrix_blockage_are_respected(self):
        for action in ('disabled', 'blocked'):
            s = self.scene()
            if action == 'disabled':
                s.set_autonomous_movement(False)
            a = s.mouse_reaction.avoidance
            a.IMPATIENCE_TIME = (.5, .5)
            a.MOVE_PROBABILITY = 1.
            a.LEAN_MOVE_PROBABILITY = 1.
            target = s.target
            with patch.object(s.behavior, 'matrix_clear', return_value=False):
                self.start(s)
                for _ in range(500):
                    s.step()
            self.assertFalse(a.moving)
            self.assertEqual(s.target, target)
            self.assertLess(s.pose.angle, -30.)

    def test_disable_and_manual_target_do_not_teleport_or_override_new_route(self):
        for command in ('disable', 'target'):
            s = self.scene()
            a = self.start(s)
            for _ in range(200):
                s.step()
            positions = [c.position for c in s.body.chunks]
            if command == 'disable':
                s.mouse_reaction.configure(s, replace(WATCH, hover_avoidance_enabled=False))
                self.assertTrue(s.mouse_reaction.active)
            else:
                s.set_target(s.project_target(a.neutral_position(s)+Vec2(60, 0)))
            self.assertEqual(positions, [c.position for c in s.body.chunks])
            target, route = s.target, s.navigator.route
            self.until(s, lambda: not a.busy and s.arrived and s.pose.settled)
            self.assertEqual(s.target, target)
            self.assertIs(s.navigator.route, route)

    def test_drag_pause_and_reset_cancel_pending_and_active_reactions(self):
        for phase in ('waiting', 'leaning', 'moving', 'lean-moving'):
            s = self.scene()
            a = s.mouse_reaction.avoidance
            if phase == 'waiting':
                s.mouse_reaction.pointer = s.head.position
                for _ in range(30):
                    s.step()
            else:
                a.LEAN_MOVE_PROBABILITY = float(phase == 'lean-moving')
                self.start(s, Vec2(30, 18) if phase == 'moving' else Vec2(30, 0))
                for _ in range(20):
                    s.step()
            s.drag.set_enabled(True)
            self.assertTrue(s.drag.press(s.head.position, lambda _: True))
            s.step()
            self.assertFalse(a.busy)
            self.assertFalse(s.mouse_reaction.active)
            self.assertEqual(a.offset, Vec2())
            s.drag.release()
            s.mouse_reaction.pointer = s.head.position
            s.step()
            self.assertFalse(a.engaged)
        s = self.scene()
        a = self.start(s)
        rng = a.random.getstate()
        s.mouse_reaction.cancel(s)
        self.assertFalse(a.engaged)
        self.assertIsNone(a.delay)
        new = OracleDesktopMotion(s.config, OracleDesktopViewport(0, 0, 1280, 720), s).scene
        self.assertEqual(new.mouse_reaction.avoidance.random.getstate(), rng)
        self.assertFalse(new.mouse_reaction.avoidance.busy)
        new.reset()
        self.assertEqual(new.mouse_reaction.avoidance.offset, Vec2())

    def test_stationary_hold_and_release_allow_sleep_and_pearl_reading(self):
        s = self.scene(appearance=True, pearl_fixed_count=1)
        s.set_autonomous_movement(False)
        a = self.start(s)
        for _ in range(1200):
            s.step()
        self.assertTrue(a.engaged)
        self.assertTrue(s.arrived and s.pose.settled)
        self.assertTrue(s.appearance.sleeping)
        revision = s.appearance.revision
        for _ in range(100):
            s.step()
        self.assertEqual(s.appearance.revision, revision)
        s.behavior.duration = 0
        with patch.object(s.behavior.random, 'random', return_value=0.):
            s.step()
        self.assertTrue(s.behavior.looking)
        self.assertEqual(s.behavior.mode, 'recall')
        self.assertTrue(a.engaged)
        s.mouse_reaction.pointer = None
        self.until(s, lambda: not a.busy)

    def test_edges_corners_and_single_edge_keep_motion_and_arm_in_bounds(self):
        for side in ('top', 'right', 'bottom', 'left'):
            for fraction in (.03, .97):
                with self.subTest(side=side, fraction=fraction):
                    s = self.scene(base_side=side, base_fraction=fraction, allowed_edges=(side,))
                    s.mouse_reaction.avoidance.LEAN_MOVE_PROBABILITY = 1.
                    a = self.start(s)
                    for i in range(600):
                        s.mouse_reaction.pointer = a.neutral_position(s)+Vec2(30 if i < 300 else -30, 0)
                        s.step()
                        self.assertTrue(s.navigator.region.contains(s.body.chunks[0].position))
                        self.assertLessEqual((s.body.chunks[0].position-s.base).length(), s.arm.maximum_reach+1e-6)
                    s.mouse_reaction.pointer = None
                    self.until(s, lambda: not a.busy and s.arrived and s.pose.settled)


if __name__ == '__main__':
    unittest.main()
