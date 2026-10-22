"""Prince 抓取身体不同区域、分段传力、边界和恢复休眠"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from dataclasses import replace
from math import acos, atan2, cos, degrees, sin
import unittest

from PySide6.QtWidgets import QApplication
from rw_creature_pet.oracle.config import OracleConfig
from rw_creature_pet.oracle.motion.prince import PrincePosture
from rw_creature_pet.oracle.scene import OracleHead, OracleScene
from rw_creature_pet.shared.geometry import Vec2


def bends(points):
    segments = [b.position-a.position for a, b in zip(points, points[1:])]
    return [degrees(acos(max(-1., min(1., (a.x*b.x+a.y*b.y)/(a.length()*b.length())))))
            for a, b in zip(segments, segments[1:])]


class PrinceDragTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def scene(self, **settings):
        scene = OracleScene(OracleConfig(body_appearance='prince', hide_cords=True,
            physics_backend='python', pearl_fixed_count=0, halo_enabled=False, **settings))
        scene.drag.set_enabled(True)
        return scene

    def test_grab_uses_actual_region_and_tail_remains_flexible(self):
        scene = self.scene()
        frame = scene.prince_posture.frame(scene.appearance.upper, scene.appearance.direction)
        for index, position in enumerate(frame.points):
            self.assertTrue(scene.drag.press(position, lambda _: True))
            self.assertEqual(scene.drag.controller.handle.key, ('prince', index))
            scene.drag.release(cancel=True)
        start = frame.points[0]
        scene.drag.press(start, lambda _: True)
        scene.drag.move(start+Vec2(40., -20.))
        largest_bend = 0.
        for _ in range(80):
            scene.step()
            largest_bend = max(largest_bend, bends(scene.prince_posture.points)[0])
        self.assertGreater((scene.prince_posture.points[0].position-start).length(), 10.)
        # 验证运动中的弯曲，不要求鼠标停止后仍维持大幅摆动
        self.assertGreater(largest_bend, 10.)
        self.assertFalse(scene.appearance.sleeping)

    def test_lower_grabs_settle_after_small_movement_on_all_edges(self):
        for side in ('top', 'right', 'bottom', 'left'):
            for index in (0, 1):
                with self.subTest(side=side, index=index):
                    scene = self.scene(base_side=side)
                    for _ in range(400):
                        scene.step()
                    start = scene.prince_posture.frame(
                        scene.appearance.upper, scene.appearance.direction).points[index]
                    self.assertTrue(scene.drag.press(start, lambda _: True))
                    self.assertEqual(scene.drag.controller.handle.key, ('prince', index))
                    target = start+Vec2(4., 0.)
                    scene.drag.move(target)
                    history = []
                    # 30 秒长按能覆盖原先下半身持续绕抓取点旋转的反馈
                    for tick in range(1200):
                        scene.step()
                        if tick >= 1080:
                            history.append(tuple(p.position for p in scene.prince_posture.points))
                    self.assertTrue(scene.prince_posture.settled)
                    self.assertTrue(scene.appearance.sleeping)
                    self.assertLess((scene.prince_posture.points[index].position-target).length(), .05)
                    for points in history:
                        for a, b in zip(points, history[0]):
                            self.assertLess((a-b).length(), .01)
                    scene.drag.move(target+Vec2(32., -12.))
                    scene.step()
                    self.assertFalse(scene.prince_posture.settled)
                    self.assertFalse(scene.appearance.sleeping)
                    for _ in range(80):
                        scene.step()
                    self.assertGreater((scene.prince_posture.points[index].position-target).length(), 10.)

    def test_tilted_grab_stays_at_pointer_and_regrab_uses_new_reference(self):
        scene = self.scene()
        for angle, index in ((.6, 1), (-.6, 0), (2.4, 0)):
            with self.subTest(angle=angle, index=index):
                upper, lower = scene.body.chunks
                direction = Vec2(sin(angle), -cos(angle))
                lower.position = lower.previous_position = upper.position-direction*scene.body.connection_length
                for point in scene.body.chunks:
                    point.velocity = Vec2()
                scene.pose.angle = scene.pose.target = degrees(angle)-scene.tilt_degrees
                scene.prince_posture = PrincePosture(upper.position, direction, Vec2(),
                                                    scene.prince_posture.neck_length)
                scene.prince_posture.reset_head(scene.head)
                scene.appearance.step(scene)
                start = scene.prince_posture.frame(
                    scene.appearance.upper, scene.appearance.direction).points[index]
                self.assertTrue(scene.drag.press(start, lambda _: True))
                self.assertEqual(scene.drag.controller.handle.key, ('prince', index))
                self.assertLess((scene.drag.prince_reference_direction-direction).length(), 1e-8)
                target = start+Vec2(4., 0.)
                scene.drag.move(target)
                for _ in range(1000):
                    scene.step()
                self.assertTrue(scene.prince_posture.settled)
                self.assertTrue(scene.appearance.sleeping)
                # 柔性末端允许少量受力偏移，但不随导航方向改变而滑离抓取点
                self.assertLess((scene.prince_posture.points[index].position-target).length(), .5)
                before = tuple(p.position for p in scene.prince_posture.points)
                scene.drag.release(cancel=True)
                self.assertIsNone(scene.drag.prince_reference_direction)
                self.assertEqual(tuple(p.position for p in scene.prince_posture.points), before)
        scene.drag.press(scene.head.position, lambda _: True)
        scene.drag.set_enabled(False)
        self.assertFalse(scene.drag.active)
        self.assertIsNone(scene.drag.prince_reference_direction)

    def test_head_grab_bends_without_folding_back_and_recovers_to_sleep(self):
        scene = self.scene()
        for _ in range(400):
            scene.step()
        scene.drag.press(scene.head.position, lambda _: True)
        target = scene.head.position+Vec2(80., 40.)
        scene.drag.move(target)
        largest_bend = 0.
        for _ in range(300):
            scene.step()
            spine = scene.prince_posture
            angles = bends(spine.points)
            largest_bend = max(largest_bend, angles[0])
            for angle, maximum in zip(angles, (105., 70., 75.)):
                self.assertLess(angle, maximum)
            for a, b, g, h in zip(spine.points, spine.points[1:], spine.spine.targets,
                                   spine.spine.targets[1:]):
                self.assertLess(abs((a.position-b.position).length()-(g-h).length()), .2)
        # 实际牵拉仍产生明显弯曲，但不再依赖重力把短颈段压到反折上限
        self.assertGreater(largest_bend, 20.)
        self.assertLess((scene.head.position-target).length(), .5)
        before = scene.head.position
        scene.drag.release()
        self.assertEqual(scene.head.position, before)
        for _ in range(1000):
            scene.step()
            if not scene.drag.controlling and scene.appearance.sleeping:
                break
        self.assertFalse(scene.drag.controlling)
        self.assertTrue(scene.appearance.sleeping)
        self.assertTrue(scene.prince_posture.settled)
        self.assertTrue(scene.appearance.prince_robe.settled)
        self.assertEqual(scene.head.position, scene.prince_posture.target)

    def test_four_edges_respect_tentacle_reach_for_all_grab_regions(self):
        for side in ('top', 'right', 'bottom', 'left'):
            for index in (0, 1, 4):
                with self.subTest(side=side, index=index):
                    scene = self.scene(base_side=side, arm_scale=.35)
                    start = scene.prince_posture.frame(
                        scene.appearance.upper, scene.appearance.direction).points[index]
                    self.assertTrue(scene.drag.press(start, lambda _: True))
                    self.assertEqual(scene.drag.controller.handle.key, ('prince', index))
                    scene.drag.move(scene.base+scene.base_normal()*3000.)
                    for _ in range(180):
                        scene.step()
                        # Prince 已由触手支撑，隐藏机械臂不再是有效的限长依据
                        support = scene.prince_tentacles
                        self.assertGreaterEqual(sum(p.attached for p in support.parts), 1)
                        self.assertLessEqual(sum(not p.attached for p in support.parts), 2)
                        self.assertTrue(support.guard.attached)
                        for part in support.parts:
                            self.assertLessEqual(part.path(1).length,
                                                 part.reference_length*support.MAX_DRAG_STRETCH+1e-6)
                            if part.attached:
                                self.assertEqual(part.nodes[-1].position, part.grip)
                        self.assertTrue(scene.drag.outer.contains(scene.body.chunks[0].position, .001))
                    scene.drag.release(cancel=True)

    def test_switching_character_during_drag_clears_old_body_handle(self):
        scene = self.scene()
        scene.drag.press(scene.head.position, lambda _: True)
        scene.config = replace(scene.config, body_appearance='bell')
        scene.sync_character()
        scene.appearance.sync_shape(scene)
        self.assertFalse(scene.drag.active)
        self.assertIsNone(scene.drag.prince_grab())
        self.assertIsNone(scene.drag.prince_reference_direction)
        self.assertIsNone(scene.prince_posture)
        self.assertIsNone(scene.appearance.prince_robe)
        scene.step()
        self.assertTrue(scene.drag.press(scene.head.position, lambda _: True))
        self.assertIsInstance(scene.drag.controller.handle.key, int)

    def test_stationary_grab_does_not_buckle_from_a_tiny_left_or_right_offset(self):
        for index in range(5):
            for offset in (-.01, .01):
                with self.subTest(index=index, offset=offset):
                    posture = PrincePosture(Vec2(), Vec2(0, -1), Vec2(), 19.)
                    head = OracleHead.at(posture.target)
                    target = posture.points[index].position
                    posture.points[2].position += Vec2(offset, 0.)
                    for _ in range(400):
                        posture.step(head, Vec2(), Vec2(0, -1), Vec2(), grab=(index, target))
                    self.assertTrue(posture.settled)
                    for a, b in zip(posture.points, posture.points[1:]):
                        segment = b.position-a.position
                        self.assertLess(abs(degrees(atan2(segment.x, -segment.y))), .1)
                    before = tuple(p.position for p in posture.points)
                    for _ in range(120):
                        posture.step(head, Vec2(), Vec2(0, -1), Vec2(), grab=(index, target))
                    self.assertEqual(tuple(p.position for p in posture.points), before)

    def test_stationary_pointer_settles_after_side_look_and_wakes_on_movement(self):
        scene = self.scene()
        scene.look_target = scene.body.chunks[0].position+Vec2(100, 0)
        for _ in range(400):
            scene.step()
        start = scene.head.position
        scene.drag.press(start, lambda _: True)
        history = []
        for tick in range(650):
            scene.step()
            if tick >= 530:
                history.append(tuple(p.position for p in scene.prince_posture.points))
        self.assertTrue(scene.prince_posture.settled)
        self.assertTrue(scene.appearance.sleeping)
        self.assertIsNone(scene.look_target)
        self.assertLess(scene.look_direction.length(), 1e-8)
        self.assertLess((scene.head.position-start).length(), .05)
        for points in history:
            for a, b in zip(points, history[0]):
                self.assertLess((a-b).length(), .01)
        scene.drag.move(start+Vec2(35, 15))
        scene.step()
        self.assertFalse(scene.prince_posture.settled)
        self.assertFalse(scene.appearance.sleeping)
        for _ in range(40):
            scene.step()
        self.assertGreater((scene.head.position-start).length(), 20.)

    def test_held_sleep_wakes_for_gravity_and_release(self):
        posture = PrincePosture(Vec2(), Vec2(.6, -.8), Vec2(), 19.)
        head = OracleHead.at(posture.target)
        grab = (1, posture.points[1].position)
        for _ in range(600):
            posture.step(head, Vec2(), Vec2(.6, -.8), Vec2(), grab=grab)
        self.assertTrue(posture.settled)
        self.assertGreater((posture.points[0].position-posture.spine.targets[0]).length(), .1)
        posture.step(head, Vec2(), Vec2(.6, -.8), Vec2(), grab=grab, gravity=0.)
        self.assertFalse(posture.settled)
        self.assertGreater(posture.maximum_speed, .001)
        for _ in range(600):
            posture.step(head, Vec2(), Vec2(.6, -.8), Vec2(), grab=grab, gravity=0.)
        self.assertTrue(posture.settled)
        posture.step(head, Vec2(), Vec2(.6, -.8), Vec2(), gravity=0.)
        self.assertFalse(posture.settled)


if __name__ == '__main__':
    unittest.main()
