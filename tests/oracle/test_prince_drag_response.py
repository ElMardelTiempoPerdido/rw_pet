"""Prince 跟手设置的实际节点、连续形变、支撑极限及恢复"""
from math import isfinite, sin, cos, degrees
import unittest

from rw_creature_pet.interaction.config import InteractionConfig
from rw_creature_pet.oracle.motion.prince_spine import HEAD, WAIST, CHEST
from rw_creature_pet.oracle.motion.prince import PrincePosture
from rw_creature_pet.shared.geometry import Vec2
from tests.oracle.test_prince_autonomous_support import scene_at
from tests.oracle.test_prince_drag import bends
from tests.oracle import test_prince_drag_limit as limit_checks


class PrinceDragResponseTests(unittest.TestCase):
    def scene(self, value=1., side='right', index=HEAD):
        scene = scene_at(side)
        scene.drag.configure(InteractionConfig(drag_enabled=True, drag_responsiveness=value))
        for _ in range(160):
            scene.step()
        frame = scene.prince_posture.frame(scene.appearance.upper, scene.appearance.direction)
        start = frame.points[index]+Vec2(.5, 0.)
        self.assertTrue(scene.drag.press(start, lambda _: True))
        self.assertEqual(scene.drag.controller.handle.key, ('prince', index))
        return scene, start

    def check_lengths(self, scene):
        spine = scene.prince_posture.spine
        for a, b, c, d in zip(spine.points, spine.points[1:], spine.targets, spine.targets[1:]):
            self.assertLess(abs((a.position-b.position).length()-(c-d).length()), .2)
        self.assertTrue(all(isfinite(p.position.x) and isfinite(p.position.y) for p in spine.points))

    def test_maximum_tracks_actual_head_waist_chest_and_tail_in_one_step(self):
        for side in ('top', 'right', 'bottom', 'left'):
            for index in (HEAD, WAIST, CHEST, 0):
                with self.subTest(side=side, index=index):
                    scene, start = self.scene(side=side, index=index)
                    normal = scene.base_normal()
                    tangent = Vec2(-normal.y, normal.x)
                    for depth, sideways in ((70, 20), (10, -20), (130, 30), (20, 0)):
                        previous = [p.position for p in scene.prince_posture.points]
                        robe_previous = [p.position for p in scene.appearance.prince_robe.points]
                        scene.drag.move(start+normal*depth+tangent*sideways)
                        scene.step()
                        actual = scene.prince_posture.points[index].position
                        self.assertLess((actual-scene.drag.controller.target).length(), 1e-7)
                        frame = scene.prince_posture.frame(scene.appearance.upper, scene.appearance.direction)
                        self.assertLess((frame.points[index]-actual).length(), 1e-7)
                        self.assertEqual([p.previous_position for p in scene.prince_posture.points], previous)
                        self.assertEqual([p.previous_position for p in scene.appearance.prince_robe.points], robe_previous)
                        self.check_lengths(scene)

    def test_response_reduces_lag_and_zero_still_moves(self):
        for index in (HEAD, 0):
            errors = []
            for value in (0., .5, .75, 1.):
                scene, start = self.scene(value, index=index)
                total = 0.
                for tick in range(1, 51):
                    scene.drag.move(start+Vec2(-tick*2., 0.))
                    scene.step()
                    total += (scene.prince_posture.points[index].position-scene.drag.controller.target).length()
                errors.append(total)
                self.assertGreater((scene.prince_posture.points[index].position-start).length(), 5.)
            self.assertEqual(errors, sorted(errors, reverse=True))
            self.assertLess(errors[-1], 1e-6)

    def test_extreme_hold_reversal_and_release_preserve_support_and_sleep(self):
        for side, index in (('top', HEAD), ('right', 0), ('bottom', HEAD), ('left', 0)):
            with self.subTest(side=side, index=index):
                scene, start = self.scene(side=side, index=index)
                far = start+scene.base_normal()*900.
                scene.drag.move(far)
                for _ in range(1050):
                    scene.step()
                    limit_checks.PrinceDragLimitTests.check_support(self, scene)
                    self.check_lengths(scene)
                before = [p.position for p in scene.prince_posture.points]
                for _ in range(80):
                    scene.step()
                self.assertLess(max((p.position-old).length() for p, old in zip(scene.prince_posture.points, before)), .05)
                self.assertLess(scene.body.chunks[0].velocity.length(), .01)
                # 回到可达区应立即恢复跟手，不能锁死在限位处
                scene.drag.move(start+scene.base_normal()*60.)
                scene.step()
                self.assertLess((scene.prince_posture.points[index].position-scene.drag.controller.target).length(), 1e-7)
                scene.drag.release()
                for _ in range(1800):
                    scene.step()
                    if not scene.drag.controlling and scene.appearance.sleeping:
                        break
                self.assertFalse(scene.drag.controlling)
                self.assertTrue(scene.appearance.sleeping)
                self.assertTrue(scene.prince_posture.settled)

    def test_intermediate_response_retains_bending_and_regrabs_without_snap(self):
        scene, start = self.scene(.75)
        peak = 0.
        for tick in range(100):
            scene.drag.move(start+Vec2(-min(tick, 40)*2., min(tick, 40)))
            scene.step()
            peak = max(peak, sum(bends(scene.prince_posture.points)))
        self.assertGreater(peak, 5.)
        for _ in range(1000):
            scene.step()
        self.assertTrue(scene.prince_posture.settled)
        self.assertTrue(scene.appearance.sleeping)
        scene.drag.release(cancel=True)
        point = scene.prince_posture.frame(scene.appearance.upper, scene.appearance.direction).points[0]
        self.assertTrue(scene.drag.press(point, lambda _: True))
        self.assertEqual(scene.drag.controller.handle.key, ('prince', 0))
        for _ in range(20):
            scene.step()
            self.check_lengths(scene)
        scene.drag.set_enabled(False)
        self.assertIsNone(scene.drag.prince_grab())
        self.assertFalse(scene.drag.active)

    def test_tilted_tail_and_head_stay_at_grip_without_exchanging_ends(self):
        for angle, index in ((.6, HEAD), (-.6, 0), (2.4, 0)):
            with self.subTest(angle=angle, index=index):
                scene = scene_at()
                scene.drag.configure(InteractionConfig(drag_enabled=True, drag_responsiveness=1.))
                upper, lower = scene.body.chunks
                direction = Vec2(sin(angle), -cos(angle))
                lower.position = lower.previous_position = upper.position-direction*scene.body.connection_length
                scene.pose.angle = scene.pose.target = degrees(angle)-scene.tilt_degrees
                scene.prince_posture = PrincePosture(upper.position, direction, Vec2(), scene.prince_posture.neck_length)
                scene.prince_posture.reset_head(scene.head)
                scene.appearance.step(scene)
                start = scene.prince_posture.frame(scene.appearance.upper, scene.appearance.direction).points[index]
                scene.drag.press(start, lambda _: True)
                scene.drag.move(start+Vec2(-60, 20))
                for _ in range(40):
                    scene.step()
                    self.assertLess((scene.prince_posture.points[index].position-scene.drag.controller.target).length(), 1e-7)
                    axis = scene.prince_posture.points[HEAD].position-scene.prince_posture.points[0].position
                    self.assertGreater(axis.x*direction.x+axis.y*direction.y, 0.)
                    self.check_lengths(scene)


if __name__ == '__main__':
    unittest.main()
