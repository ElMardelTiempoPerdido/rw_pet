"""中下段弯曲传递、单一身体曲线和上下衣料接缝回归"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from math import sin, pi, degrees
import unittest
from unittest.mock import patch

from rw_creature_pet.oracle.motion.prince import PrincePosture, turn, WAIST_DEPTH
from rw_creature_pet.oracle.motion.prince_spine import WAIST, CHEST, bend_angle, BEND_LIMITS
from rw_creature_pet.oracle.motion.prince_robe import COLUMNS
from rw_creature_pet.oracle.scene import OracleHead
from rw_creature_pet.shared.geometry import Vec2
from tests.oracle.test_prince_autonomous_support import scene_at


class PrinceBodyCurveTests(unittest.TestCase):
    def test_manual_upper_length_keeps_the_same_attachment(self):
        for length in (10., 14., 18.):
            with self.subTest(length=length), patch(
                    'rw_creature_pet.oracle.motion.prince_robe.UPPER_LENGTH', length):
                scene = scene_at()
                app, robe = scene.appearance, scene.appearance.prince_robe
                frame = scene.prince_posture.frame(app.upper, app.direction)
                for p, (x, y) in zip(app.cloth[-app.CLOTH_DIVS:], app._cloth_local[-app.CLOTH_DIVS:]):
                    self.assertAlmostEqual(y, -length)
                    self.assertEqual(p.position, frame.cloth_point(x, y))
                for uv, p in zip(robe.coords, robe.front.points):
                    if uv.y == robe.art.join_y:
                        expected = frame.cloth_point(uv.x-(robe.art.left+robe.art.right)/2, -length)
                        self.assertEqual(p.position, expected)

    def test_lower_body_bends_between_landmarks_and_settles_without_stretch(self):
        posture = PrincePosture(Vec2(), Vec2(0, -1), Vec2(), 19.)
        head = OracleHead.at(posture.target)
        self.assertEqual(len(posture.points), 9)
        self.assertGreater(WAIST, 1)
        self.assertGreater(CHEST-WAIST, 1)
        peak = 0.
        for tick in range(600):
            direction = turn(Vec2(0, -1), sin(tick/42)*1.4)
            posture.step(head, Vec2(sin(tick/37)*35, 0), direction, Vec2(), gravity=.04)
            points = [p.position for p in posture.points]
            chord = points[WAIST]-points[0]
            for p in points[1:WAIST]:
                delta = p-points[0]
                peak = max(peak, abs(chord.x*delta.y-chord.y*delta.x)/chord.length())
            for a, b, g, h in zip(points, points[1:], posture.spine.targets, posture.spine.targets[1:]):
                self.assertLess(abs((b-a).length()-(h-g).length()), .08)
            for a, b, c, limit in zip(points, points[1:], points[2:], BEND_LIMITS):
                self.assertLess(abs(degrees(bend_angle(b-a, c-b))), limit+2.)
        self.assertGreater(peak, .5)
        for _ in range(700):
            posture.step(head, Vec2(), Vec2(0, -1), Vec2(), gravity=.04)
        self.assertTrue(posture.settled)
        self.assertEqual(head.position, posture.target)

    def test_upper_and_png_share_seam_including_initial_and_interpolated_frames(self):
        scene = scene_at()
        app = scene.appearance
        robe, n = app.prince_robe, app.CLOTH_DIVS
        art = robe.art
        row = next(i for i, uv in enumerate(robe.coords[::COLUMNS]) if uv.y == art.join_y)

        def check():
            for alpha in (0., .5, 1.):
                for col in range(COLUMNS):
                    uv = robe.coords[row*COLUMNS+col]
                    x = (uv.x-art.left)/(art.right-art.left)*(n-1)
                    index = max(0, min(n-2, int(x)))
                    a, b = app.cloth[(n-1)*n+index:(n-1)*n+index+2]
                    upper = a.sample(alpha).lerp(b.sample(alpha), x-index)
                    for layer in robe.layers:
                        self.assertLess((layer.points[row*COLUMNS+col].sample(alpha)-upper).length(), 1e-8)
            frame = scene.prince_posture.frame(app.upper, app.direction)
            before, after = frame.axis(-WAIST_DEPTH-1e-4), frame.axis(-WAIST_DEPTH+1e-4)
            self.assertLess((before[1]-after[1]).length(), .001)
            goals, _ = robe.goals(app)
            for r in range(len(robe.coords)//COLUMNS):
                self.assertAlmostEqual((goals[r*COLUMNS+COLUMNS-1]-goals[r*COLUMNS]).length(), art.width)

        check()
        origin = scene.body.chunks[0].position
        for tick in range(300):
            angle = tick*pi/150
            direction = turn(Vec2(0, -1), angle)
            for i, p in enumerate(scene.body.chunks):
                p.previous_position = p.position
                p.position = origin+Vec2(12*sin(tick/30), 0)-direction*(i*9.)
                p.velocity = p.position-p.previous_position
            scene.prince_posture.step(scene.head, scene.body.chunks[0].position, direction,
                                      turn(Vec2(.6, .7), angle), gravity=.04)
            app.step(scene)
            check()


if __name__ == '__main__':
    unittest.main()
