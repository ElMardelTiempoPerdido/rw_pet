"""腰腿跟随衣袍：旋转一致性、限幅、收敛，以及独立于头颈和导航。"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'

from math import pi
import unittest

from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication

from rw_creature_pet.shared.geometry import Vec2
from rw_creature_pet.oracle.appearance import perpendicular, rotate
from rw_creature_pet.oracle.render import OracleRenderer
from rw_creature_pet.oracle.scene import OracleScene


class WaistFollowTests(unittest.TestCase):
    def swing(self, appearance, amount):
        n = appearance.CLOTH_DIVS
        side = perpendicular(appearance.direction)
        for i, (p, goal) in enumerate(zip(appearance.cloth, appearance.cloth_goals())):
            p.position = p.previous_position = goal+side*(amount*(i//n)/(n-1))

    def test_swing_moves_hips_and_foot_targets_consistently_on_all_axes(self):
        local_offsets = []
        for angle in (0., pi/2, pi, -pi/2):
            scene = OracleScene()
            a = scene.appearance
            a.direction = rotate(Vec2(0, -1), angle)
            a.lower = a.upper-a.direction*9
            head, body = a.head.position, [p.position for p in scene.body.chunks]
            self.swing(a, 8.)
            cloth = [p.position for p in a.cloth]
            for _ in range(120):
                a.step_waist()
                self.assertLessEqual(abs(a.waist_velocity), a.WAIST_MAX_SPEED+1e-12)
            side = perpendicular(a.direction)
            hip = a.lower-a.upper
            feet = a.foot_goals()[0].lerp(a.foot_goals()[1], .5)-a.upper
            across = lambda v: v.x*side.x+v.y*side.y
            self.assertGreater(across(hip), 2.)
            self.assertGreater(across(feet), across(hip)*1.5)
            self.assertAlmostEqual(hip.length(), 9.)
            local_offsets.append(across(feet))
            self.assertEqual(a.head.position, head)
            self.assertEqual([p.position for p in scene.body.chunks], body)
            self.assertEqual([p.position for p in a.cloth], cloth)
            self.swing(a, 0.)
            for _ in range(180):
                a.step_waist()
            self.assertAlmostEqual(a.waist_angle, 0., places=8)
            self.assertLess(abs(a.waist_velocity), 1e-9)
        for value in local_offsets[1:]:
            self.assertAlmostEqual(value, local_offsets[0], places=8)

    def test_hem_corner_does_not_drive_waist_and_extreme_fold_cannot_flip_it(self):
        a = OracleScene().appearance
        self.swing(a, 0.)
        a.cloth[-1].position += Vec2(100, 0)
        for _ in range(10):
            a.step_waist()
        self.assertAlmostEqual(a.waist_angle, 0., places=9)
        for sign in (-1, 1):
            for p in a.cloth:
                p.position = a.upper+a.direction*30+perpendicular(a.direction)*(sign*100)
            for _ in range(90):
                before = a.waist_angle
                a.step_waist()
                self.assertLessEqual(abs(a.waist_angle-before), a.WAIST_MAX_SPEED+1e-12)
                self.assertLessEqual(abs(a.waist_angle), a.WAIST_MAX_ANGLE)
                for alpha in (0., .5, 1.):
                    direction = a.waist_direction(a.direction, alpha)
                    self.assertAlmostEqual(direction.length(), 1.)
                    self.assertGreater(direction.x*a.direction.x+direction.y*a.direction.y, .86)

    def test_waist_interpolation_invalidates_body_cache_without_paint_advancing_motion(self):
        app = QApplication.instance() or QApplication([])
        scene, renderer = OracleScene(), OracleRenderer()
        a = scene.appearance
        a.previous_waist_angle, a.waist_angle = 0., .3
        before = (a.previous_waist_angle, a.waist_angle, a.waist_velocity, a.lower)
        frames = []
        for alpha in (0., .5, 1.):
            image = QImage(960, 600, QImage.Format.Format_ARGB32_Premultiplied)
            image.fill(0)
            painter = QPainter(image)
            try:
                renderer.draw_geometry(painter, scene, alpha, cords=False, arm=False,
                                       pearl=False, halo=False, cache_body=True)
            finally:
                painter.end()
            frames.append(renderer._body_frame)
        self.assertEqual(len({id(frame) for frame in frames}), 3)
        self.assertEqual(before, (a.previous_waist_angle, a.waist_angle, a.waist_velocity, a.lower))


if __name__ == '__main__':
    unittest.main()
