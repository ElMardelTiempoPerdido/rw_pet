"""触须保持长度、自由末端和反复伸缩的稳定性。"""
from dataclasses import replace
import math
import unittest

from rw_creature_pet.overseer.config import OverseerConfig
from rw_creature_pet.overseer.model import Anchor, Edge, Overseer, dot
from rw_creature_pet.shared.geometry import Bounds, Vec2


def arc_length(strand):
    return sum((b.position-a.position).length() for a, b in zip(strand, strand[1:]))


class FilamentTests(unittest.TestCase):
    def test_full_extension_keeps_length_across_sizes_and_gaze_directions(self):
        for size in (.5, .6, 1.):
            for look in (Vec2(0, 24), Vec2(0, 180), Vec2(400, 60), Vec2(0, 500)):
                with self.subTest(size=size, look=look):
                    model = Overseer(config=OverseerConfig(size=size))
                    model.show()
                    for tick in range(320):
                        model.step(model.root+model.local_vector(look))
                        if tick >= 160:
                            self.assertEqual(model.extended, 1)
                            for strand in model.filaments:
                                length = arc_length(strand)
                                self.assertGreater(length, model.filament_length*.88)
                                self.assertLessEqual(length, model.filament_length+1e-6)
                    # 正常观察时自由末端可以伸过引导点，而不是被强拉回引导点上。
                    if look == Vec2(0, 180):
                        offsets = [(s[-1].position-tip).length()
                                   for s, tip in zip(model.filaments, model._filament_tips())]
                        self.assertGreater(max(offsets), model.filament_length*.15)

    def test_filament_motion_is_equivalent_on_four_edges(self):
        models = [Overseer(Bounds(0, 0, 500, 500)) for _ in Edge]
        for edge, model in zip(Edge, models):
            model.show(anchor=Anchor(edge, .5))
        for tick in range(240):
            poses = []
            for model in models:
                model.step(model.root+model.local_vector(Vec2(200*math.sin(tick/31), 100)))
                poses.append([Vec2(dot(p.position-model.root, model.tangent),
                                   dot(p.position-model.root, model.normal))
                              for strand in model.filaments for p in strand])
            for pose in poses[1:]:
                for a, b in zip(poses[0], pose):
                    self.assertLess((a-b).length(), 1e-6)

    def test_repeated_hide_and_mid_motion_reversal_recovers_length(self):
        for edge in Edge:
            model = Overseer(config=replace(OverseerConfig(), safe_delay=0))
            model.show(anchor=Anchor(edge, .5))
            for tick in range(400):
                near = 60 <= tick % 160 < 100 or 105 <= tick % 160 < 120
                target = model.root+model.local_vector(Vec2(150*math.sin(tick/13), 100))
                threat = model.root+model.normal*(10 if near else 180)
                previous = [[p.position for p in strand] for strand in model.filaments]
                old_base, old_extension = model.filament_base(), model.extended
                model.step(target, threat=threat)
                # 原版分段伸缩会快速移动附着点；把这部分和收短量计入连续运动预算。
                movement_budget = ((model.filament_base()-old_base).length()
                                   +abs(model.extended-old_extension)*model.filament_length+3.)
                for old, strand in zip(previous, model.filaments):
                    self.assertLessEqual(arc_length(strand), model.filament_length*model.extended+1e-6)
                    for before, p in zip(old, strand):
                        self.assertTrue(math.isfinite(p.position.x) and math.isfinite(p.position.y))
                        self.assertLess((p.position-before).length(), movement_budget)
                        if model.visible:
                            self.assertEqual(p.sample(0), before)
            for _ in range(100):
                model.step(model.root+model.normal*180)
            for strand in model.filaments:
                self.assertGreater(arc_length(strand), model.filament_length*.88)


if __name__ == '__main__':
    unittest.main()
