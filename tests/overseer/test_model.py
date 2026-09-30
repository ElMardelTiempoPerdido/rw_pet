import math
import unittest

from rw_creature_pet.shared.geometry import Bounds, Vec2
from rw_creature_pet.overseer.config import OverseerConfig
from rw_creature_pet.overseer.model import Anchor, Edge, Overseer, dot


class OverseerModelTests(unittest.TestCase):
    def test_hidden_is_inactive_and_show_resets_reproducibly(self):
        model = Overseer()
        revision, rng = model.revision, model.random.getstate()
        for _ in range(100):
            model.step(Vec2(10, 20))
        self.assertEqual(model.revision, revision)
        self.assertEqual(model.random.getstate(), rng)
        poses = []
        for _ in range(2):
            model.show()
            for _ in range(240):
                model.step(Vec2(500, 300))
            poses.append((model.head.position, model.look_at,
                          tuple(p.position for s in model.filaments for p in s)))
            model.clear()
        self.assertEqual(*poses)
        self.assertFalse(model.visible)
        self.assertIsNone(model.target)

    def test_four_edges_extreme_targets_and_long_idle_stay_bounded(self):
        for size in (.5, .6, 1.):
            for edge in Edge:
                with self.subTest(size=size, edge=edge):
                    model = Overseer(Bounds(12, 12, 652, 492), OverseerConfig(size=size))
                    model.show(anchor=Anchor(edge, 0))
                    for _ in range(64):
                        model.step()
                    root = model.root
                    for i in range(1400):
                        target = (Vec2(10000 if i % 2 else -10000, 10000)
                                  if i < 200 else root if i < 300 else None)
                        old = model.head.position
                        model.step(target)
                        self.assertEqual(model.root, root)
                        self.assertLessEqual((model.head.position-root).length(), model.reach+1e-8)
                        self.assertGreaterEqual(dot(model.head.position-root, model.normal), 6-1e-8)
                        self.assertLess((model.head.position-old).length(), 4)
                        for strand in model.filaments:
                            for p in strand:
                                self.assertTrue(model.bounds.contains(p.position))
                            for a, b in zip(strand, strand[1:]):
                                self.assertLess((a.position-b.position).length(), model.filament_length/4+1)

    def test_rotation_uses_same_local_motion(self):
        models = []
        for edge in Edge:
            model = Overseer(Bounds(0, 0, 500, 500))
            model.show(anchor=Anchor(edge, .5))
            models.append(model)
        for i in range(400):
            local_target = Vec2(160*math.sin(i/30), 120+100*math.cos(i/40))
            poses = []
            for model in models:
                model.step(model.root+model.local_vector(local_target))
                delta = model.head.position-model.root
                poses.append(Vec2(dot(delta, model.tangent), dot(delta, model.normal)))
            for pose in poses[1:]:
                self.assertLess((pose-poses[0]).length(), 1e-8)

    def test_near_eye_gaze_is_continuous_and_small_world_roots_are_safe(self):
        model = Overseer(Bounds(0, 0, 140, 140), OverseerConfig(size=1))
        for edge in Edge:
            for fraction in (0, 1):
                model.show(anchor=Anchor(edge, fraction))
                self.assertTrue(model.bounds.contains(model.root))
                self.assertTrue(model.bounds.contains(model.head.position))
        for dx in (-1e-5, 0, 1e-5):
            model.extended = model.last_extended = 1.
            model.previous_look = model.look_at = model.head.position+Vec2(dx, 0)
            planar, depth = model.gaze()
            self.assertLess(planar.length(), 1e-6)
            self.assertAlmostEqual(depth, 1)


if __name__ == '__main__':
    unittest.main()
