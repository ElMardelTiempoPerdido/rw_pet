"""Prince 弓身投影、头部滞后、停止收敛和衣袍/绘制同步"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from math import atan2, degrees, pi
import unittest

from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication
from rw_creature_pet.oracle.config import OracleConfig
from rw_creature_pet.oracle.graphics.appearance import rotate
from rw_creature_pet.oracle.graphics.damage import body_bounds
from rw_creature_pet.oracle.graphics.render import OracleRenderer
from rw_creature_pet.oracle.motion.prince import PrincePosture, WAIST_DEPTH
from rw_creature_pet.oracle.scene import OracleHead, OracleScene
from rw_creature_pet.shared.geometry import Vec2


class PrincePostureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def scene(self):
        return OracleScene(OracleConfig(body_appearance='prince', hide_cords=True, physics_backend='python',
                                       pearl_fixed_count=0, halo_enabled=False))

    def test_bend_starts_at_waist_mirrors_and_preserves_cross_section_widths(self):
        frames = [PrincePosture(Vec2(), Vec2(0, -1), Vec2(gaze, .7), 21.).frame(Vec2(), Vec2(0, -1))
                  for gaze in (-.7, 0., .7)]
        left, front, right = frames
        self.assertAlmostEqual(left.chest.x, -right.chest.x)
        self.assertGreater(front.chest.y, 0.)
        self.assertGreater(right.chest.x, 1.)
        self.assertGreater(right.chest_direction.x, 0.)
        self.assertGreater(right.chest.x, 7.)
        for frame in frames:
            self.assertEqual(frame.cloth_point(0., -WAIST_DEPTH), Vec2(0., WAIST_DEPTH))
            for y in (-50., -14., -10., 0., 5.):
                span = frame.cloth_point(4., y)-frame.cloth_point(-4., y)
                self.assertAlmostEqual(span.length(), 8.)
        self.assertGreater(right.cloth_point(0., -8.).x, 1.)
        root, c1, c2, head = right.neck_controls(Vec2(8., -20.))
        chord, tangent = head-root, c1-root
        self.assertGreater(abs(chord.x*tangent.y-chord.y*tangent.x), 1.)
        self.assertGreater((head-c2).length(), 0.)

    def test_level_and_upper_gaze_turn_neck_with_only_a_small_body_bend(self):
        direction = Vec2(0., -1.)
        for side in (-1., 1.):
            with self.subTest(side=side):
                poses = [PrincePosture(Vec2(), direction, Vec2(side*.7, y), 19.)
                         for y in (-.7, 0., .7)]
                for posture in poses[:2]:
                    tail, waist, chest, neck, head = (p.position for p in posture.points)
                    self.assertGreater(side*chest.x, 0.)
                    self.assertLess(side*chest.x, 2.)
                    chest_angle = abs(degrees(atan2(chest.x-waist.x, waist.y-chest.y)))
                    neck_angle = abs(degrees(atan2(neck.x-chest.x, chest.y-neck.y)))
                    head_angle = abs(degrees(atan2(head.x-neck.x, neck.y-head.y)))
                    self.assertLess(chest_angle, 8.)
                    self.assertGreater(neck_angle-chest_angle, 10.)
                    self.assertGreater(head_angle-chest_angle, 10.)
                self.assertGreater(side*poses[2].points[2].position.x, 7.)
                self.assertGreater(side*poses[2].target.x, side*poses[1].target.x)

    def test_height_response_is_continuous_and_low_gaze_recovers_to_level(self):
        origin, direction = Vec2(), Vec2(0., -1.)
        near_level = [PrincePosture(origin, direction, Vec2(.7, y), 19.)
                      for y in (-.001, .001)]
        self.assertLess((near_level[0].points[2].position-near_level[1].points[2].position).length(), .02)
        posture = PrincePosture(origin, direction, Vec2(.7, .7), 19.)
        head = OracleHead.at(posture.target)
        for y in (0., -.7, .7, 0.):
            for _ in range(400):
                previous = posture.points[2].position
                posture.step(head, origin, direction, Vec2(.7, y))
                self.assertLess((posture.points[2].position-previous).length(), 1.5)
                self.assert_segment_lengths(posture)
            self.assertTrue(posture.settled)
            self.assertEqual(head.position, posture.target)
            if y <= 0.:
                self.assertLess(posture.points[2].position.x, 2.)
            else:
                self.assertGreater(posture.points[2].position.x, 7.)

    def test_neck_bows_before_body_and_can_reach_near_horizontal(self):
        direction = Vec2(0., -1.)
        angles = []
        for low in (0., .5, 1.):
            # 固定完整侧向投影，单独比较低头输入对三段几何转角的影响
            posture = PrincePosture(Vec2(), direction, Vec2(1., low), 19.)
            segments = [b.position-a.position for a, b in zip(posture.points[1:], posture.points[2:])]
            angles.append(tuple(degrees(atan2(v.x, -v.y)) for v in segments))
        for i in range(3):
            progress = (angles[1][i]-angles[0][i])/(angles[2][i]-angles[0][i])
            if i == 0:
                self.assertLess(progress, .5)
                self.assertGreater(progress, .3)
            else:
                self.assertGreater(progress, .7)
                self.assertLess(progress, .9)
        self.assertLess(angles[0][0], 8.)
        self.assertGreater(angles[2][1], 80.)
        self.assertLess(angles[2][1], 90.)
        self.assertGreater(angles[2][2], 70.)
        self.assertLess(angles[2][2], 85.)

    def test_head_lags_chest_and_all_segments_settle(self):
        origin, direction = Vec2(100., 100.), Vec2(0., -1.)
        posture = PrincePosture(origin, direction, Vec2(), 21.)
        head = OracleHead.at(posture.target)
        posture.step(head, origin, direction, Vec2(.8, 0.))
        self.assertLess(posture.head_facing, posture.facing)
        self.assertLess(head.position.x, posture.target.x)
        for tick in range(400):
            posture.step(head, origin, direction, Vec2(.8, 0.))
            self.assert_segment_lengths(posture)
        self.assertEqual(posture.maximum_speed, 0.)
        self.assertEqual(head.position, posture.target)
        samples = []
        for tick in range(250):
            posture.step(head, origin, direction, Vec2())
            samples.append(head.position.x-origin.x)
        self.assertLess(max(abs(x) for x in samples[-40:]), .001)
        self.assertEqual(head.position, posture.target)
        self.assertEqual(head.velocity, Vec2())

    def assert_segment_lengths(self, posture):
        points, goals = posture.points, posture.spine.targets
        for i in range(len(points)-1):
            actual = (points[i+1].position-points[i].position).length()
            ideal = (goals[i+1]-goals[i]).length()
            self.assertLess(abs(actual-ideal), .06)

    def test_lower_gaze_bows_further_without_side_flip_at_front(self):
        direction = Vec2(0., -1.)
        poses = [PrincePosture(Vec2(), direction, look, 19.) for look in
                 (Vec2(.7, 0.), Vec2(.7, .7), Vec2(), Vec2(0., 1.))]
        self.assertGreater(poses[1].target.x, poses[0].target.x)
        self.assertGreater(poses[1].target.y, poses[0].target.y)
        self.assertEqual(poses[3].target.x, 0.)
        self.assertGreater(poses[3].target.y, poses[2].target.y+4.)

    def test_same_downward_gaze_keeps_bow_strength_across_horizontal_directions(self):
        origin = Vec2(100., 100.)
        for angle in (0., .6, pi):
            direction = rotate(Vec2(0., -1.), angle)
            for low in (.3, .7, 1.):
                drops = []
                for horizontal in (-.7, -.3, 0., .3, .7):
                    with self.subTest(angle=angle, low=low, horizontal=horizontal):
                        # 直接指定各分量，隔离高度响应和外部注视距离限幅
                        level = PrincePosture(origin, direction,
                                              rotate(Vec2(horizontal, 0.), angle), 19.)
                        bowed = PrincePosture(origin, direction,
                                              rotate(Vec2(horizontal, low), angle), 19.)
                        delta = [b.position-a.position for a, b in zip(level.points[2:], bowed.points[2:])]
                        drops.append(tuple(-d.x*direction.x-d.y*direction.y for d in delta))
                        for value, expected in zip(drops[-1], drops[0]):
                            self.assertAlmostEqual(value, expected, places=8)
                # 正下方必须有可见的头肩下沉，不能只剩轻微的缩短
                if low >= .7:
                    self.assertGreater(drops[2][0], 3.)
                    self.assertGreater(drops[2][-1], 8.)

    def test_downward_sweep_crosses_front_smoothly_and_sleeps(self):
        origin, direction = Vec2(), Vec2(0., -1.)
        posture = PrincePosture(origin, direction, Vec2(-.6, .8), 19.)
        head = OracleHead.at(posture.target)
        head_heights = []
        for tick in range(241):
            posture.step(head, origin, direction, Vec2(-.6+1.2*tick/240, .8))
            self.assert_segment_lengths(posture)
            self.assertLess(posture.maximum_speed, .5)
            head_heights.append(head.position.y)
        self.assertLess(max(head_heights)-min(head_heights), 1.5)
        for _ in range(500):
            posture.step(head, origin, direction, Vec2(0., 1.))
        self.assertTrue(posture.settled)
        self.assertAlmostEqual(head.position.x, 0.)
        self.assertEqual(head.position, posture.target)
        for _ in range(500):
            posture.step(head, origin, direction, Vec2())
        self.assertTrue(posture.settled)
        self.assertEqual(head.position, posture.target)

    def test_full_rotation_and_teleport_do_not_stretch_or_leave_trails(self):
        origin = Vec2(100., 100.)
        posture = PrincePosture(origin, Vec2(0., -1.), Vec2(.6, 0.), 21.)
        head = OracleHead.at(posture.target)
        for tick in range(241):
            direction = rotate(Vec2(0., -1.), tick*pi/120)
            posture.step(head, origin, direction, rotate(Vec2(.6, 0.), tick*pi/120))
            self.assert_segment_lengths(posture)
            self.assertLess((head.position-origin).length(), 50.)
        posture.step(head, origin+Vec2(900., 400.), direction, Vec2())
        self.assertEqual(head.position, head.previous_position)
        self.assertEqual(head.position, posture.target)
        self.assertEqual(posture.offset, Vec2())

    def test_idle_sleeps_turning_wakes_and_lower_navigation_stays_independent(self):
        scene = self.scene()
        for _ in range(850):
            scene.step()
        self.assertTrue(scene.appearance.sleeping)
        body = tuple(p.position for p in scene.body.chunks)
        scene.look_target = body[0]+Vec2(100., 0.)
        scene.step()
        self.assertFalse(scene.appearance.sleeping)
        self.assertEqual(tuple(p.position for p in scene.body.chunks), body)
        for _ in range(850):
            scene.step()
        self.assertTrue(scene.appearance.sleeping)
        self.assertLess((scene.appearance.head.position-scene.head.position).length(), .001)
        self.assertGreater(scene.prince_posture.frame(body[0], scene.body.direction).chest.x, body[0].x)

    def test_render_cache_interpolation_and_bounds_include_bent_neck(self):
        scene = self.scene()
        scene.look_target = scene.body.chunks[0].position+Vec2(100., 0.)
        for _ in range(15):
            scene.step()
        renderer = OracleRenderer(colors=scene.config.active_colors)
        def paint(alpha, cached, head_only=False):
            image = QImage(960, 600, QImage.Format.Format_ARGB32_Premultiplied)
            image.fill(0)
            painter = QPainter(image)
            try:
                if head_only:
                    renderer.draw_scene_head(painter, scene, alpha)
                else:
                    renderer.draw_geometry(painter, scene, alpha, cache_body=cached,
                                           arm=False, cords=False, pearl=False, halo=False)
            finally:
                painter.end()
            return image
        before = scene.head.position, scene.prince_posture.facing, scene.prince_posture.offset
        for alpha in (0., .5, 1.):
            self.assertEqual(paint(alpha, False), paint(alpha, True))
            bounds = body_bounds(scene)
            image = paint(alpha, True)
            head_image = paint(alpha, False, True)
            for y in range(image.height()):
                for x in range(image.width()):
                    if image.pixelColor(x, y).alpha():
                        self.assertTrue(bounds.contains(x, y))
                    if head_image.pixelColor(x, y).alpha():
                        self.assertEqual(image.pixelColor(x, y), head_image.pixelColor(x, y))
        self.assertEqual(before, (scene.head.position, scene.prince_posture.facing, scene.prince_posture.offset))


if __name__ == '__main__':
    unittest.main()
