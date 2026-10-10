"""花冠贴图比例、曲面遮挡、连续转头和有界缓存"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'

from math import atan2, cos, degrees, pi, sin
import unittest
from unittest.mock import patch

import numpy as np
from PySide6.QtGui import QImage

from rw_creature_pet.overseer.graphics.friend import head as friend_head
from rw_creature_pet.overseer.graphics.friend import body as friend
from rw_creature_pet.overseer.graphics.friend.body import DISC_RADIUS
from rw_creature_pet.overseer.model import Anchor, Edge, Overseer
from rw_creature_pet.shared.geometry import Bounds, Vec2


def pixels(image):
    image = image.convertToFormat(QImage.Format.Format_RGBA8888)
    return np.frombuffer(image.constBits(), dtype=np.uint8).reshape(image.height(), image.width(), 4).copy()


class FriendHeadTests(unittest.TestCase):
    def test_front_at_2x_preserves_authored_opaque_pixels_exactly(self):
        source = pixels(QImage(str(friend_head.TEXTURE_PATH)))
        image, _ = friend_head.head_image(Vec2(), 1., Vec2(0, -1), 2.)
        result = pixels(image)
        y, x = (result.shape[0]-source.shape[0])//2, (result.shape[1]-source.shape[1])//2
        cropped = result[y:y+source.shape[0], x:x+source.shape[1]]
        opaque = source[:, :, 3] > 0
        np.testing.assert_array_equal(cropped[opaque], source[opaque])
        self.assertEqual(tuple(result[result.shape[0]//2, result.shape[1]//2]), (228, 225, 207, 255))

    def test_torus_depth_occludes_disc_and_is_not_flat_ellipse_transform(self):
        gaze, depth, up = Vec2(sin(pi/3), 0), cos(pi/3), Vec2(0, -1)
        curved, _ = friend_head.head_image(gaze, depth, up, 2.)
        surface, colors, extent = friend_head._surface()
        flat = surface.copy()
        flat[:, :, 2] = 0
        matrix = tuple(round(v, 3) for v in friend_head.view_matrix(gaze, depth, up))
        with patch.object(friend_head, '_surface', return_value=(flat, colors, extent)):
            flat_image, _ = friend_head._project.__wrapped__(matrix, 2.)
        a, b = pixels(curved), pixels(flat_image)
        # 花冠拱起后，有些原本露出的浅黄色脸盘像素被近侧黑色花瓣遮住
        was_disc = np.all(b == (228, 225, 207, 255), axis=-1)
        now_black = np.all(a[:, :, :3] == 0, axis=-1) & (a[:, :, 3] == 255)
        self.assertTrue(np.any(was_disc & now_black))
        self.assertGreater(np.count_nonzero(np.any(a != b, axis=-1)), 10)

    def test_front_crossing_has_no_pattern_flip_and_extension_does_not_change_view(self):
        a = np.asarray(friend_head.view_matrix(Vec2(-1e-6, 0), 1, Vec2(0, -1)))
        b = np.asarray(friend_head.view_matrix(Vec2(1e-6, 0), 1, Vec2(0, -1)))
        self.assertLess(np.max(np.abs(a-b)), 1e-5)
        np.testing.assert_allclose(friend_head.view_matrix(Vec2(.6, 0), .8, Vec2(0, -1)),
                                   friend_head.view_matrix(Vec2(.06, 0), .08, Vec2(0, -1)))

    def test_views_scaling_and_roll_fit_bounds_and_keep_binary_alpha(self):
        for density in (1., 1.5, 2., 4.):
            for up in (Vec2(0, -1), Vec2(1, 0), Vec2(0, 1), Vec2(-1, 0)):
                for angle in (0., pi/4, pi/2):
                    image, half = friend_head.head_image(Vec2(sin(angle), 0), cos(angle), up, density)
                    rgba = pixels(image)
                    self.assertGreater(half, DISC_RADIUS)
                    self.assertLess(half, 12.)  # 模型的眼部包围盒余量
                    self.assertTrue(np.any(rgba[:, :, 3]))
                    self.assertEqual(set(np.unique(rgba[:, :, 3])), {0, 255})
                    self.assertFalse(np.any(rgba[[0, -1], :, 3]))
                    self.assertFalse(np.any(rgba[:, [0, -1], 3]))

    def test_projection_cache_reuses_images_and_evicts_old_views(self):
        friend_head._project.cache_clear()
        for i in range(150):
            a = i*.029
            friend_head.head_image(Vec2(.8*cos(a), .8*sin(a)), .6, Vec2(0, -1), 2.)
        first = friend_head.head_image(Vec2(.8, 0), .6, Vec2(0, -1), 2.)[0]
        second = friend_head.head_image(Vec2(.8, 0), .6, Vec2(0, -1), 2.)[0]
        self.assertIs(first, second)
        info = friend_head._project.cache_info()
        self.assertEqual(info.currsize, info.maxsize)
        self.assertGreater(info.hits, 0)


class FriendHeadGazeTests(unittest.TestCase):
    def setUp(self):
        # 曲线回归使用固定样例，允许用户独立调整实际运行的外观常量
        for name, value in (('HEAD_GAZE_DISTANCE_FRACTION', .9),
                            ('HEAD_GAZE_NEAR_FRACTION', .2),
                            ('HEAD_GAZE_NEAR_ANGLE', 30.), ('HEAD_GAZE_POWER', 2.)):
            patcher = patch.object(friend, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def make_model(self, width=1920, height=1080, edge=Edge.BOTTOM):
        model = Overseer(Bounds(-300, 50, width-300, height+50))
        model.set_appearance('friend')
        model.show(anchor=Anchor(edge, .5))
        model.extended = model.last_extended = 1.
        return model

    def look(self, model, delta):
        # 目标距离以实际脸盘为起点，迭代消除颈部随视线产生的小幅位移
        for _ in range(12):
            model.look_at = model.previous_look = model.eye_position()+delta
        return model.head_gaze()

    def test_tilt_reaches_maximum_only_near_full_screen_span(self):
        for edge in Edge:
            for width, height in ((1920, 1080), (1080, 1920)):
                model = self.make_model(width, height, edge)
                for direction in (Vec2(width, 0), Vec2(0, height), Vec2(width, height)):
                    angles = []
                    for fraction in (0., .25, .5, .75, .9, 1.):
                        gaze, depth = self.look(model, direction*fraction)
                        angles.append(degrees(atan2(gaze.length(), depth)))
                    self.assertLess(angles[0], .001)
                    self.assertLess(angles[2], 45.)
                    self.assertLess(angles[3], 70.)
                    self.assertGreater(angles[4], 89.9)
                    self.assertAlmostEqual(angles[5], 90.)
                    self.assertEqual(angles, sorted(angles))

    def test_scale_and_work_area_changes_preserve_relative_angle(self):
        model = self.make_model()
        angles = []
        for scale in (.75, 1., 1.5, 2.):
            width, height = 1920/scale, 1040/scale
            model.show(Bounds(12, -400, width+12, height-400), Anchor(Edge.LEFT, .5))
            model.extended = model.last_extended = 1.
            gaze, depth = self.look(model, Vec2(.7*width, .4*height))
            angles.append(atan2(gaze.length(), depth))
        for angle in angles:
            self.assertAlmostEqual(angle, angles[0], places=7)

    def test_gaze_stays_continuous_across_front_and_clamp(self):
        model = self.make_model()
        gazes = [self.look(model, Vec2(x, 0))[0] for x in (-.001, 0., .001)]
        self.assertLess((gazes[0]-gazes[-1]).length(), 1e-5)
        results = [self.look(model, Vec2(x*1920, 0)) for x in (.899999, .9, .900001)]
        for (gaze_a, depth_a), (gaze_b, depth_b) in zip(results, results[1:]):
            self.assertLess((gaze_a-gaze_b).length(), 1e-5)
            self.assertLess(abs(depth_a-depth_b), 1e-5)
        gaze, depth = results[-1]
        self.assertAlmostEqual(gaze.length()**2+depth**2, 1.)

    def test_near_targets_show_visible_tilt_without_using_up_far_range(self):
        model = self.make_model()
        angles = []
        for fraction in (.05, .1, .2, .5, .75, .9):
            gaze, depth = self.look(model, Vec2(1920*fraction, 0))
            angles.append(degrees(atan2(gaze.length(), depth)))
        self.assertGreater(angles[0], 10.)
        self.assertGreater(angles[1], 20.)
        self.assertAlmostEqual(angles[2], 30., places=5)
        self.assertLess(angles[3], 45.)
        self.assertLess(angles[4], 70.)
        self.assertAlmostEqual(angles[5], 90.)
        # 确认最终投影也产生可见厚度变化，不只是内部角度变了
        gaze, depth = self.look(model, Vec2(192, 0))
        matrix = friend_head.view_matrix(gaze, depth, Vec2(0, -1))
        self.assertLess(matrix[-1], .95)

    def test_near_transition_is_monotonic_and_has_no_angle_or_slope_jump(self):
        near = friend.HEAD_GAZE_NEAR_FRACTION
        step = 1e-6
        left, center, right = [friend.head_tilt_angle(t) for t in (near-step, near, near+step)]
        self.assertLess(abs((center-left)/step-(right-center)/step), 1e-4)
        angles = [friend.head_tilt_angle(i/2000) for i in range(2001)]
        self.assertEqual(angles, sorted(angles))
        self.assertEqual(angles[0], 0.)
        with patch.object(friend, 'HEAD_GAZE_NEAR_FRACTION', 0.):
            self.assertLess(degrees(friend.head_tilt_angle(.2)), 5.)
            self.assertAlmostEqual(friend.head_tilt_angle(.9), pi/2)

    def test_head_curve_does_not_change_body_and_standard_keeps_original_gaze(self):
        model = self.make_model()
        for _ in range(100):
            model.step(model.root+model.local_vector(Vec2(300, 300)))
        before = friend.body_centers(model, 1.), model.head, model.friend_bend.side
        original_gaze = model.head_gaze()
        with patch.object(friend, 'HEAD_GAZE_DISTANCE_FRACTION', .3), patch.object(friend, 'HEAD_GAZE_POWER', 1.):
            self.assertNotEqual(model.head_gaze(), original_gaze)
            self.assertEqual(before, (friend.body_centers(model, 1.), model.head, model.friend_bend.side))
        model.set_appearance('standard')
        self.assertEqual(model.head_gaze(), model.gaze())


if __name__ == '__main__':
    unittest.main()
