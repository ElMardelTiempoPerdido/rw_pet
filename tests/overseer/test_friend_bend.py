"""S 形中心线、姿态滞后、四边一致性和伸缩连续性"""
from dataclasses import replace
from math import atan2, degrees
import unittest
from unittest.mock import patch

from rw_creature_pet.overseer.config import OverseerConfig
from rw_creature_pet.overseer.graphics.friend import body as appearance
from rw_creature_pet.overseer.graphics.friend.body import (ROOT_EXIT_ANGLE, FriendBend,
                                           body_centers, body_curve, neck_offset)
from rw_creature_pet.overseer.model import Anchor, Edge, Overseer
from rw_creature_pet.shared.geometry import Bounds, Vec2


def dot(a, b):
    return a.x*b.x+a.y*b.y


class FriendBendTests(unittest.TestCase):
    def make_model(self, edge=Edge.TOP, size=.6, appearance='friend'):
        model = Overseer(Bounds(0, 0, 600, 600),
                         OverseerConfig(size=size, observation_probability=0), seed=73)
        model.set_appearance(appearance)
        model.show(anchor=Anchor(edge, .5))
        model.wander_wait = 10000
        return model

    def settle(self, model, side=180):
        target = model.root+model.local_vector(Vec2(side, 200))
        for _ in range(180):
            model.step(target)

    def test_root_is_a_single_arc_without_reverse_curvature(self):
        model = self.make_model()
        self.settle(model)
        for split in (.2, .35, .5, .7):
            with patch.object(appearance, 'BEND_ROOT_FRACTION', split):
                for side in (-1., 1.):
                    model.friend_bend = FriendBend(side, side)
                    curve = body_curve(model, 1.)
                    root = [curve.sample(split*i/100) for i in range(101)]
                    slopes = [dot(b-a, model.tangent)*side/dot(b-a, model.normal)
                              for a, b in zip(root, root[1:])]
                    # 从出墙处到交界处曲率同号，不再先产生一段相反的小弧
                    self.assertTrue(all(b < a+1e-8 for a, b in zip(slopes, slopes[1:])))
                    self.assertGreater(slopes[0]-slopes[-1], .01)
                    chord = curve.join-curve.root
                    start = curve.root_control-curve.root
                    chord_angle = atan2(dot(chord, model.tangent), dot(chord, model.normal))
                    start_angle = atan2(dot(start, model.tangent), dot(start, model.normal))
                    self.assertGreater((start_angle-chord_angle)*side, 0.)
                    self.assertLessEqual(abs(degrees(start_angle-chord_angle)), ROOT_EXIT_ANGLE+1e-8)

    def test_join_is_tangent_continuous_and_head_keeps_its_direction(self):
        model = self.make_model()
        self.settle(model)
        model.friend_bend = FriendBend(.9, .9)
        for split in (.2, .35, .5, .7):
            with patch.object(appearance, 'BEND_ROOT_FRACTION', split):
                curve = body_curve(model, 1.)
                step = 1e-6
                left = (curve.sample(split)-curve.sample(split-step))*(1/step)
                right = (curve.sample(split+step)-curve.sample(split))*(1/step)
                self.assertLess((left-right).length()/left.length(), 1e-4)
                self.assertEqual(curve.sample(0.), model.root)
                self.assertEqual(curve.sample(1.), model.eye_position())
                direction = curve.sample(1.)-curve.sample(1.-step)
                reference = model.eye_position()-model.stem(1.-1e-5, head_offset=neck_offset(model))
                self.assertGreater(dot(direction, reference)/(direction.length()*reference.length()), .99999)

    def test_root_tilt_can_be_disabled_without_moving_endpoints(self):
        model = self.make_model()
        self.settle(model)
        before = body_curve(model, 1.)
        with patch.object(appearance, 'ROOT_EXIT_ANGLE', 0.):
            curve = body_curve(model, 1.)
        self.assertEqual(curve.root, before.root)
        self.assertEqual(curve.head, before.head)
        self.assertLess((curve.root_control-curve.root.lerp(curve.join, .5)).length(), 1e-8)

    def test_gaze_crossing_head_does_not_flip_neck(self):
        model = self.make_model()
        self.settle(model)
        curves = []
        for side in (-.001, 0., .001):
            model.look_at = model.previous_look = model.head.position+model.tangent*side
            curves.append(body_centers(model, 1.))
        for a, b in zip(curves, curves[1:]):
            self.assertLess(max((p-q).length() for p, q in zip(a, b)), .01)

    def test_change_of_gaze_crosses_zero_smoothly_and_settles(self):
        model = self.make_model()
        self.settle(model)
        start = model.friend_bend.side
        self.assertGreater(start, .5)
        # 隔离姿态弹簧，注视点瞬时换边也不能瞬时翻转身体
        model.look_at = model.previous_look = model.root+model.local_vector(Vec2(-180, 200))
        model.friend_bend.step(model)
        self.assertEqual(model.friend_bend.previous_side, start)
        self.assertGreater(model.friend_bend.side, 0.)
        history = [model.friend_bend.side]
        for _ in range(180):
            model.friend_bend.step(model)
            history.append(model.friend_bend.side)
        self.assertLess(history[-1], -.5)
        self.assertLess(max(abs(b-a) for a, b in zip(history, history[1:])), .2)
        self.assertTrue(all(-1 <= value <= 1 for value in history))
        self.assertTrue(all(b <= a+1e-8 for a, b in zip(history, history[1:])))
        self.assertEqual(history[-20], history[-1])
        self.assertEqual(model.friend_bend.velocity, 0.)

    def test_all_edges_have_same_local_shape(self):
        reference = None
        for edge in Edge:
            model = self.make_model(edge)
            self.settle(model)
            shape = [(dot(p-model.root, model.tangent), dot(p-model.root, model.normal))
                     for p in body_centers(model, 1.)]
            if reference is None:
                reference = shape
            for a, b in zip(reference, shape):
                self.assertAlmostEqual(a[0], b[0], places=8)
                self.assertAlmostEqual(a[1], b[1], places=8)

    def test_retraction_scales_bend_and_bounds_include_shape(self):
        for edge in Edge:
            for size in (.5, 1.):
                model = self.make_model(edge, size)
                self.settle(model)
                model.friend_bend = FriendBend(-.9, .9)
                for extension in (0., .01, .1, .5, 1.):
                    model.extended = model.last_extended = extension
                    for alpha in (0., .5, 1.):
                        bent = body_centers(model, alpha)
                        curve = body_curve(model, alpha)
                        root_bow = (curve.root_control-curve.root.lerp(curve.join, .5)).length()/2
                        self.assertLessEqual(root_bow, appearance.BEND_ROOT_AMPLITUDE*extension**2+1e-8)
                        self.assertLessEqual(abs(curve.body_bow), appearance.BEND_BODY_AMPLITUDE*extension**2+1e-8)
                        self.assertEqual(bent[-1], model.eye_position(alpha))
                        bounds = model.visual_bounds(alpha)
                        self.assertTrue(all(bounds.contains(p) for p in bent))
                # 快速缩回中途反向不重置弯身量
                before = replace(model.friend_bend)
                model.request_withdraw()
                model.request_emerge()
                self.assertEqual(before, model.friend_bend)

    def test_body_follows_less_than_head_and_settled_motion_is_reduced(self):
        sweeps = []
        for influence in (1., appearance.BODY_GAZE_FOLLOW):
            with patch.object(appearance, 'BODY_GAZE_FOLLOW', influence):
                poses = []
                for side in (-180, 180):
                    model = self.make_model()
                    self.settle(model, side)
                    poses.append((body_centers(model, 1.), model.gaze()[0]))
                sweeps.append(poses)
        full, reduced = sweeps
        full_motion = max((a-b).length() for a, b in zip(full[0][0], full[1][0]))
        reduced_motion = max((a-b).length() for a, b in zip(reduced[0][0], reduced[1][0]))
        self.assertGreater(reduced_motion, 0.)
        self.assertLess(reduced_motion, full_motion*.65)
        for (_, original_gaze), (_, gaze) in zip(full, reduced):
            # 身体真正减小稳态摆幅，花冠却仍保持完整注视方向和接近原有的侧视程度
            self.assertGreater(dot(gaze, original_gaze)/(gaze.length()*original_gaze.length()), .999)
            self.assertAlmostEqual(gaze.length(), original_gaze.length(), delta=.02)

    def test_zero_body_follow_keeps_body_still_but_head_turns(self):
        with patch.object(appearance, 'BODY_GAZE_FOLLOW', 0.):
            model = self.make_model()
            self.settle(model)
            initial = body_centers(model, 1.)
            gazes = []
            for side in (-300, 0, 300):
                self.settle(model, side)
                gazes.append(model.gaze()[0])
                for before, after in zip(initial, body_centers(model, 1.)):
                    self.assertLess((before-after).length(), 1e-8)
            self.assertGreater((gazes[0]-gazes[-1]).length(), 1.)
            model.request_withdraw()
            for _ in range(120):
                model.step(model.look_at)
            self.assertEqual(model.extended, 0.)

    def test_body_follow_parameter_does_not_affect_standard(self):
        poses = []
        for influence in (0., 1.):
            with patch.object(appearance, 'BODY_GAZE_FOLLOW', influence):
                model = self.make_model(appearance='standard')
                self.settle(model)
                poses.append((model.head, model.gaze(), [model.stem(i/20) for i in range(21)]))
        self.assertEqual(*poses)

    def test_full_follow_preserves_original_head_physics_and_resets_on_relocation(self):
        friend, standard = self.make_model(), self.make_model(appearance='standard')
        with patch.object(appearance, 'BODY_GAZE_FOLLOW', 1.):
            for tick in range(220):
                target = friend.root+friend.local_vector(Vec2(200 if tick < 100 else -170, 210))
                friend.step(target)
                standard.step(target)
                self.assertEqual(friend.head, standard.head)
                self.assertEqual(friend.look_at, standard.look_at)
                self.assertEqual(friend.extended, standard.extended)
        friend.set_appearance('standard')
        self.assertEqual(friend.friend_bend, FriendBend())
        friend.set_appearance('friend')
        self.settle(friend)
        friend.show(anchor=Anchor(Edge.RIGHT, .5))
        self.assertEqual(friend.friend_bend, FriendBend())
        self.settle(friend)
        friend.clear()
        self.assertEqual(friend.friend_bend, FriendBend())


if __name__ == '__main__':
    unittest.main()
