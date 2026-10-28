"""观察前伸、恢复和四边避让过渡，保持触须的自由链与原有休眠边界"""
from math import isfinite, sin
import unittest

from rw_creature_pet.overseer.config import OverseerConfig
from rw_creature_pet.overseer.model import Anchor, Edge, Overseer, dot, unit
from rw_creature_pet.shared.geometry import Bounds, Vec2
from tests.overseer.test_filaments import arc_length


def make_model(appearance, edge=Edge.TOP, size=.6):
    model = Overseer(Bounds(0, 0, 640, 640), OverseerConfig(
        size=size, observation_probability=1, observation_interval=999))
    model.set_appearance(appearance)
    model.show(anchor=Anchor(edge, .5))
    return model


def forward_tips(model):
    direction = unit(model.head_gaze()[0])
    return [dot(strand[-1].position-model.filament_base(), direction)
            for strand in model.filaments]


class FilamentObservationTests(unittest.TestCase):
    def test_observing_reaches_forward_and_closing_recovers_without_changing_head_or_rng(self):
        for appearance in ('standard',):
            for size in (.5, 1.):
                with self.subTest(appearance=appearance, size=size):
                    resting, observing = [make_model(appearance, size=size) for _ in range(2)]
                    target = resting.root+resting.local_vector(Vec2(-200, 180))
                    for _ in range(200):
                        for model in (resting, observing):
                            model.step(target)
                    observing.lens.remaining = 6
                    for _ in range(120):
                        for model in (resting, observing):
                            model.step(target)
                    self.assertEqual(observing.lens.up, 1.)
                    opened = forward_tips(observing)
                    for tip, length in zip(opened, observing.filament_lengths):
                        self.assertGreater(tip, length*.2)
                    self.assertGreater(sum(opened)-sum(forward_tips(resting)), observing.filament_length*.5)
                    self.assertEqual(observing.head.position, resting.head.position)
                    self.assertEqual(observing.random.getstate(), resting.random.getstate())
                    observing.lens.remaining = 0
                    for _ in range(240):
                        for model in (resting, observing):
                            model.step(target)
                    self.assertEqual(observing.lens.up, 0.)
                    self.assertLess(sum(forward_tips(observing)), sum(opened)-observing.filament_length*.5)

    def test_friend_observes_with_rear_filaments_and_preserves_light_and_resting_curves(self):
        for size in (.5, 1.):
            for edge in Edge:
                with self.subTest(size=size, edge=edge):
                    model = make_model('friend', edge, size)
                    target = model.root+model.local_vector(Vec2(-200, 180))
                    for _ in range(180):
                        model.step(target)
                    model.lens.remaining = 6
                    for _ in range(140):
                        model.step(target)
                        self.assertTrue(all(tip < 0 for tip in forward_tips(model)))
                    self.assertEqual(model.lens.up, 1.)
                    self.assertGreater(model.lens.remaining, 0)
                    self.assertIsNotNone(model.friend_light_pixels)
                    self.assertTrue(all(len(s) == 5 for s in model.filaments))
                    model.lens.remaining = 0
                    for _ in range(120):
                        model.step(target)
                    self.assertEqual(model.lens.up, 0.)
                    self.assertTrue(all(tip < 0 for tip in forward_tips(model)))

    def test_four_edge_equivalence_and_continuity_through_turning_and_withdrawal(self):
        for appearance in ('standard', 'friend'):
            models = [make_model(appearance, edge) for edge in Edge]
            for tick in range(330):
                poses = []
                for model in models:
                    if tick in (65, 205):
                        model.lens.remaining = 6
                    if tick == 150:
                        model.request_withdraw()
                    if tick == 185:
                        model.request_emerge()
                    old = [[p.position for p in strand] for strand in model.filaments]
                    base, extension, lengths = model.filament_base(), model.extended, model.filament_lengths
                    model.step(model.root+model.local_vector(Vec2(220*sin(tick/39), 180)))
                    budget = ((model.filament_base()-base).length()
                              +abs(model.extended-extension)*model.filament_length
                              +max(abs(a-b) for a, b in zip(lengths, model.filament_lengths))+3.)
                    for before, strand, length in zip(old, model.filaments, model.filament_lengths):
                        self.assertLessEqual(arc_length(strand), length*model.extended+1e-6)
                        for previous, point in zip(before, strand):
                            self.assertTrue(isfinite(point.position.x) and isfinite(point.position.y))
                            self.assertLess((point.position-previous).length(), budget)
                            if model.visible:
                                self.assertEqual(point.sample(0), previous)
                    poses.append([Vec2(dot(p.position-model.root, model.tangent),
                                       dot(p.position-model.root, model.normal))
                                  for strand in model.filaments for p in strand])
                for pose in poses[1:]:
                    for a, b in zip(poses[0], pose):
                        self.assertLess((a-b).length(), 1e-6)
            for model in models:
                model.request_withdraw()
                for _ in range(100):
                    model.step()
                points = [[p.position for p in s] for s in model.filaments]
                state = model.random.getstate()
                for _ in range(20):
                    model.step()
                self.assertEqual(points, [[p.position for p in s] for s in model.filaments])
                self.assertEqual(state, model.random.getstate())


if __name__ == '__main__':
    unittest.main()
