"""定长头颈在移动、观察与休眠之间保持稳定，不反向驱动身体。"""
import unittest

from rw_creature_pet.shared.geometry import Vec2
from rw_creature_pet.oracle.scene import MotionPoint, OracleHead, OracleScene, dot
from rw_creature_pet.oracle.appearance import rotate


class OracleHeadTests(unittest.TestCase):
    def assert_connection(self, head, upper, direction):
        anchor = upper.position+direction*head.NECK_BASE_OFFSET
        self.assertAlmostEqual((head.position-anchor).length(), head.CONNECTION_LENGTH, places=8)
        self.assertGreater(dot(head.position-upper.position, direction), 10.)

    def test_cardinal_motion_does_not_stretch_and_stop_settles(self):
        for velocity in (Vec2(0, 1.6), Vec2(0, -1.6), Vec2(1.6, 0), Vec2(-1.6, 0)):
            with self.subTest(velocity=velocity):
                upper = MotionPoint.at(Vec2())
                direction = Vec2(0, -1)
                head = OracleHead.at(direction*14, radius=5)
                for tick in range(550):
                    upper.previous_position = upper.position
                    upper.velocity = velocity if tick < 300 else Vec2()
                    upper.position += upper.velocity
                    head.step(upper, direction, Vec2())
                    self.assert_connection(head, upper, direction)
                    self.assertLess(head.velocity.length(), 2.)
                    if 200 < tick < 300:
                        self.assertAlmostEqual((head.position-upper.position).length(), 14., delta=.03)
                self.assertLess(head.velocity.length(), 1e-7)
                self.assertAlmostEqual((head.position-upper.position).length(), 14., places=7)

    def test_gaze_and_tilt_turn_neck_without_compressing_connection(self):
        upper = MotionPoint.at(Vec2(100, 100))
        head = OracleHead.at(upper.position+Vec2(0, -14), radius=5)
        current_angle = 0.
        for angle in (-.436, .436, 0.):
            for look in (Vec2(-1, 0), Vec2(1, 0), Vec2(0, -1), Vec2(0, 1), Vec2()):
                for _ in range(220):
                    # 与实际躯干相同的角速度上限，不能一步跳转 50 度。
                    current_angle += max(-.055, min(.055, angle-current_angle))
                    direction = rotate(Vec2(0, -1), current_angle)
                    head.step(upper, direction, look)
                    self.assert_connection(head, upper, direction)
                self.assertLess(head.velocity.length(), 1e-6)
                if look in (Vec2(), direction, direction*-1):
                    self.assertAlmostEqual((head.position-upper.position).length(), 14., places=6)

    def test_vertical_look_wakes_face_even_when_head_stays_in_place(self):
        scene = OracleScene()
        for _ in range(650):
            scene.step()
        self.assertTrue(scene.appearance.sleeping)
        head = scene.head.position
        upper = scene.body.chunks[0].position
        scene.set_look_target(upper+Vec2(0, -200))
        scene.step()
        self.assertFalse(scene.appearance.sleeping)
        self.assertLess((scene.head.position-head).length(), 1e-8)
        self.assertEqual(scene.body.chunks[0].position, upper)
        for _ in range(650):
            scene.step()
        self.assertTrue(scene.appearance.sleeping)
        self.assertEqual(scene.head.velocity, Vec2())
        scene.reset()
        fresh = OracleScene(scene.config)
        self.assertEqual(scene.head, fresh.head)


if __name__ == '__main__':
    unittest.main()
