"""双触须共根、独立长度、四边运动和外观切换"""
from math import cos, isfinite, sin
import unittest
from unittest.mock import patch

from rw_creature_pet.overseer.config import OverseerConfig
from rw_creature_pet.overseer.graphics.friend.filaments import BASE_DEPTH, BASE_OFFSET
from rw_creature_pet.overseer.graphics.friend import filaments as friend_filaments
from rw_creature_pet.overseer.model import Anchor, Edge, Overseer, dot, perpendicular, unit
from rw_creature_pet.shared.geometry import Bounds, Vec2


def arc_length(strand):
    return sum((b.position-a.position).length() for a, b in zip(strand, strand[1:]))


class FriendFilamentTests(unittest.TestCase):
    def model(self, edge=Edge.TOP, size=.6):
        model = Overseer(Bounds(0, 0, 500, 500), OverseerConfig(size=size, observation_probability=0))
        model.set_appearance('friend')
        model.show(anchor=Anchor(edge, .5))
        return model

    def test_common_attachment_and_distinct_lengths_survive_gaze_and_retraction(self):
        for size in (.5, .6, 1.):
            model = self.model(size=size)
            self.assertEqual(len(model.filaments), 2)
            self.assertLess(model.filament_lengths[0], model.filament_lengths[1])
            for tick in range(320):
                if tick == 150:
                    model.request_withdraw()
                if tick == 210:
                    model.request_emerge()
                model.step(model.root+model.local_vector(Vec2(240*sin(tick/33), 180)))
                base = model.filament_base()
                for strand, length in zip(model.filaments, model.filament_lengths):
                    if model.visible:
                        self.assertEqual(strand[0].position, base)
                    self.assertLessEqual(arc_length(strand), length*model.extended+1e-6)
                    for point in strand:
                        self.assertTrue(isfinite(point.position.x) and isfinite(point.position.y))
                        self.assertTrue(model.visual_bounds().contains(point.position))
                if model.extended == 1:
                    axis, side, rear = friend_filaments.frame(model)
                    offset = base-model.eye_position()
                    self.assertAlmostEqual(dot(offset, axis), -BASE_OFFSET*(.75+.25*size))
                    self.assertAlmostEqual(dot(offset, side), BASE_DEPTH*rear*(.75+.25*size))
            for strand, length in zip(model.filaments, model.filament_lengths):
                self.assertGreater(arc_length(strand), length*.88)

    def test_equivalent_four_edge_motion_and_local_desktop_bounds(self):
        models = [self.model(edge) for edge in Edge]
        for tick in range(180):
            poses = []
            for model in models:
                model.step(model.root+model.local_vector(Vec2(200*sin(tick/31), 180)))
                extent = model.reach+model.head_extra_extent+max(
                    model.filament_length+24, model.observation_extent+4)
                poses.append([Vec2(dot(p.position-model.root, model.tangent),
                                   dot(p.position-model.root, model.normal))
                              for strand in model.filaments for p in strand])
                self.assertTrue(all(abs(p.x) < extent and abs(p.y) < extent for p in poses[-1]))
            for pose in poses[1:]:
                for a, b in zip(poses[0], pose):
                    self.assertLess((a-b).length(), 1e-6)

    def test_switch_rebuilds_only_filaments_and_preserves_event_body_and_random_state(self):
        model = self.model()
        for _ in range(100):
            model.step(model.root+model.normal*180)
        before = model.head.position, model.extended, model.lens.remaining, model.random.getstate()
        for appearance, count in (('standard', 4), ('friend', 2), ('standard', 4)):
            model.set_appearance(appearance)
            self.assertEqual(len(model.filaments), count)
            self.assertTrue(all(strand[0].position == model.filament_base() for strand in model.filaments))
            self.assertEqual(before, (model.head.position, model.extended, model.lens.remaining,
                                      model.random.getstate()))

    def test_resting_short_c_and_long_s_remain_gentle_at_different_sizes(self):
        for size in (.5, .6, 1.):
            model = self.model(size=size)
            for tick in range(400):
                # 侧视给长须留出离墙空间，弧线幅度随深度投影缩短
                model.step(model.root+model.local_vector(Vec2(-400, 240)))
                if tick < 300:
                    continue
                rear = friend_filaments.frame(model)[2]
                for index, strand in enumerate(model.filaments):
                    normal = perpendicular(unit(strand[-1].position-strand[0].position))
                    offsets = [dot(p.position-strand[0].position, normal) for p in strand[1:-1]]
                    if index == 0:
                        self.assertGreater(min(offsets), .5*rear)
                    else:
                        self.assertLess(offsets[0], -.5*rear)
                        self.assertGreater(offsets[-1], .5*rear)
                    self.assertLess(max(abs(x) for x in offsets), model.filament_lengths[index]*.2)

    def test_depth_attachment_and_targets_cross_neck_continuously_on_four_edges(self):
        for edge in Edge:
            model = self.model(edge)
            model.extended = model.last_extended = 1.
            # 固定颈部，只改变花冠侧视，排除身体摆动造成的假换边
            with patch('rw_creature_pet.overseer.graphics.friend.filaments.neck_offset', return_value=model.normal*8):
                samples = []
                for angle in (-.8, -.000001, 0., .000001, .8):
                    with patch.object(model, 'head_gaze', return_value=(model.tangent*sin(angle), cos(angle))):
                        axis, side, rear = friend_filaments.frame(model)
                        base = model.filament_base()
                        samples.append((base, friend_filaments.tip_targets(model), model.filament_lengths))
                        self.assertAlmostEqual(dot(base-model.eye_position(), side),
                                               BASE_DEPTH*rear*(.75+.25*model.config.size))
                        for target in samples[-1][1]:
                            if angle:
                                self.assertLess(dot(target-base, side)*angle, 0.)
                            else:
                                self.assertAlmostEqual(dot(target-base, side), 0.)
                self.assertTrue(all(a < b for a, b in zip(samples[2][2], samples[0][2])))
                self.assertLess((samples[1][0]-samples[3][0]).length(), 1e-4)
                for a, b in zip(samples[1][1], samples[3][1]):
                    self.assertLess((a-b).length(), 1e-3)
                # 即使看向屏幕平面内的极远正前方，小幅左右变化也不会瞬间交换两侧
                results = []
                for epsilon in (-1e-7, 1e-7):
                    with patch.object(model, 'head_gaze', return_value=(model.normal+model.tangent*epsilon, 0.)):
                        results.append(friend_filaments.tip_targets(model))
                self.assertTrue(all((a-b).length() < 1e-4 for a, b in zip(*results)))

    def test_visibility_boost_reveals_slight_side_gaze_without_extending_nominal_lengths(self):
        model = self.model()
        model.extended = model.last_extended = 1.
        with patch('rw_creature_pet.overseer.graphics.friend.filaments.neck_offset', return_value=model.normal*8):
            for angle in (-1.3, -.1, 0., .1, 1.3):
                with patch.object(model, 'head_gaze', return_value=(model.tangent*sin(angle), cos(angle))):
                    with patch.object(friend_filaments, 'SIDE_VISIBILITY_GAIN', 1.):
                        original = friend_filaments.tip_targets(model)
                        original_lengths = model.filament_lengths
                    with patch.object(friend_filaments, 'SIDE_VISIBILITY_GAIN', 3.):
                        boosted = friend_filaments.tip_targets(model)
                        for before, after in zip(original, boosted):
                            before_side = dot(before-model.eye_position(), model.tangent)
                            after_side = dot(after-model.eye_position(), model.tangent)
                            if angle == 0:
                                self.assertAlmostEqual(after_side, 0.)
                            else:
                                self.assertGreater(after_side*before_side, 0.)
                                self.assertGreater(abs(after_side), abs(before_side))
                                if abs(angle) == .1:
                                    self.assertGreater(abs(after_side), 2*abs(before_side))
                        for before, after, nominal in zip(original_lengths, model.filament_lengths,
                                                          friend_filaments.lengths(model.config.size)):
                            self.assertGreaterEqual(after, before)
                            self.assertLessEqual(after, nominal)

    def test_physical_strands_follow_turn_to_opposite_side_without_teleporting(self):
        model = self.model()
        side_positions = []
        for sign in (-1, 1):
            for _ in range(400):
                old = [[p.position for p in s] for s in model.filaments]
                old_base = model.filament_base()
                old_lengths = model.filament_lengths
                old_extension = model.extended
                model.step(model.root+model.local_vector(Vec2(sign*300, 240)))
                movement = ((model.filament_base()-old_base).length()
                            +abs(model.extended-old_extension)*model.filament_length
                            +max(abs(a-b) for a, b in zip(old_lengths, model.filament_lengths))+3.)
                for before, strand in zip(old, model.filaments):
                    self.assertTrue(all((p.position-v).length() < movement for p, v in zip(strand, before)))
            _, side, _ = friend_filaments.frame(model)
            side_positions.append([dot(s[-1].position-model.filament_base(), side) for s in model.filaments])
        self.assertTrue(all(x > 1. for x in side_positions[0]))
        self.assertTrue(all(x < -1. for x in side_positions[1]))


if __name__ == '__main__':
    unittest.main()
