"""矩阵队形、四角整体迁移、滞回休眠及单珠行为隔离。"""
from dataclasses import replace
import unittest
from unittest.mock import patch

from rw_creature_pet.shared.geometry import Vec2
from rw_creature_pet.oracle.config import OracleConfig
from rw_creature_pet.oracle.navigation import EdgePlanner, EdgeRegion
from rw_creature_pet.oracle.pearl_matrix import PearlMatrix
from rw_creature_pet.oracle.scene import OracleScene, OracleWorld


class PearlMatrixTests(unittest.TestCase):
    def matrix(self, width=960, height=600, follow=360):
        world = OracleWorld(width, height, .2)
        region = EdgeRegion(world)
        center = region.boxes[0].clamp(Vec2(width/2, 70))
        return world, region, center, PearlMatrix(world, region, center, Vec2(0, 1), follow, max(160, follow*.78))

    def assert_safe(self, matrix, world):
        anchor = matrix.anchor
        self.assertTrue(matrix.region.segment_safe(anchor.previous_position, anchor.position))
        self.assertLessEqual(anchor.velocity.length(), anchor.FOLLOW_SPEED+1e-7)
        self.assertTrue(matrix.region.contains(anchor.home))
        for p in (anchor.home- matrix.half_size, anchor.home+matrix.half_size):
            self.assertTrue(matrix.follow_bounds.contains(p))
        # 珠体及字形完整包围框，不只检查珠心；包含绘制插值的中间帧。
        for alpha in (0., .5, 1.):
            for pos, _, _ in matrix.samples(alpha):
                l, r, t, b = pos.x-4, pos.x+15, pos.y-15, pos.y+4
                self.assertGreaterEqual(min(l, t), -1e-6)
                self.assertLessEqual(r, world.width+1e-6)
                self.assertLessEqual(b, world.height+1e-6)
                inner = world.inner
                self.assertTrue(r <= inner.left+1e-6 or l >= inner.right-1e-6
                                or b <= inner.top+1e-6 or t >= inner.bottom-1e-6)

    def test_layout_config_and_repeatable_glyphs(self):
        self.assertFalse(OracleConfig().pearl_matrix_enabled)
        for value in (1, 'true', None):
            with self.assertRaises(ValueError):
                OracleConfig.from_mapping({'pearl_matrix_enabled': value})
        world, _, _, matrix = self.matrix()
        pearls = {p.slot: p for p in matrix.pearls}
        self.assertEqual(len(pearls), 14)
        self.assertNotIn((2, 2), pearls)
        self.assertEqual(matrix.layout_scale, 1.)
        self.assertAlmostEqual((pearls[0, 1].offset-pearls[0, 0].offset).length(), 17.)
        self.assertAlmostEqual((pearls[1, 0].offset-pearls[0, 0].offset).length(), 17.)
        self.assertEqual(matrix.pearls, self.matrix()[3].pearls)
        self.assert_safe(matrix, world)

    def test_both_directions_four_corners_and_compact_follow_rectangle(self):
        for size, follow in (((960, 600), 360), ((640, 480), 160), ((1920, 1040), 360)):
            for clockwise in (True, False):
                with self.subTest(size=size, clockwise=clockwise):
                    world, region, center, matrix = self.matrix(*size, follow)
                    route = EdgePlanner(world, region).lap(center, clockwise)
                    original = matrix.pearls
                    replans, seen = 0, set()
                    previous = matrix.anchor.route
                    for tick in range(int(route.length/2)+1100):
                        center = route.sample(min(route.length, tick*2.))
                        matrix.step(center)
                        if matrix.anchor.route is not previous:
                            replans += 1
                            previous = matrix.anchor.route
                        seen.update(i for i, box in enumerate(matrix.region.boxes) if box.contains(matrix.anchor.position))
                        if tick % 12 == 0:
                            self.assert_safe(matrix, world)
                        self.assertLess(abs(center.x-matrix.anchor.position.x), 300)
                        self.assertLess(abs(center.y-matrix.anchor.position.y), 270)
                    self.assertEqual(seen, {0, 1, 2, 3})
                    self.assertTrue(matrix.settled)
                    self.assertEqual(matrix.anchor.position, matrix.anchor.home)
                    self.assertEqual(original, matrix.pearls)
                    self.assertLess(replans, route.length/12)
                    self.assertTrue(all(c.certified_safe(matrix.region) for c in matrix.anchor.route.curves))

    def test_small_moves_and_settled_matrix_do_not_replan(self):
        world, _, center, matrix = self.matrix()
        before = (matrix.anchor.position, matrix.anchor.home, matrix.revision)
        with patch.object(matrix.anchor.planner, 'plan', wraps=matrix.anchor.planner.plan) as plan:
            for _ in range(2000):
                matrix.step(center+Vec2(8, 0))
            self.assertEqual(plan.call_count, 0)
        self.assertEqual(before, (matrix.anchor.position, matrix.anchor.home, matrix.revision))
        self.assert_safe(matrix, world)

    def test_scene_toggle_reset_and_existing_observation_are_independent(self):
        plain = OracleScene()
        matrix_scene = OracleScene(replace(OracleConfig(), pearl_matrix_enabled=True))
        for scene in (plain, matrix_scene):
            scene.appearance.step = lambda s: None
            scene.observe_pearl('recall')
        for tick in range(520):
            if tick == 40:
                matrix_scene.set_pearl_matrix(False)
            if tick == 100:
                matrix_scene.set_pearl_matrix(True)
            plain.step()
            matrix_scene.step()
            self.assertEqual(plain.pearl.position, matrix_scene.pearl.position)
            self.assertEqual(plain.body.chunks[0].position, matrix_scene.body.chunks[0].position)
            self.assertEqual(plain.behavior.state, matrix_scene.behavior.state)
        self.assertEqual(plain.behavior.random.getstate(), matrix_scene.behavior.random.getstate())
        matrix_scene.reset()
        self.assertTrue(matrix_scene.pearl_matrix_enabled)
        self.assertTrue(matrix_scene.pearl_matrix.settled)
        matrix_scene.set_pearl_matrix(False)
        matrix_scene.reset()
        self.assertIsNone(matrix_scene.pearl_matrix)


if __name__ == '__main__':
    unittest.main()
