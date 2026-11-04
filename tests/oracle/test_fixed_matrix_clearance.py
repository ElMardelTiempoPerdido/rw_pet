"""固定珠避让矩阵：初生、迁移、观察归位、尺寸变化与静止开销"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from rw_creature_pet.shared.geometry import Bounds, Vec2
from rw_creature_pet.oracle.config import OracleConfig
from rw_creature_pet.oracle.motion.navigation import EdgePlanner, EdgeRegion
from rw_creature_pet.oracle.pearls.fixed import FixedPearls
from rw_creature_pet.oracle.pearls.matrix import PearlMatrix
from rw_creature_pet.oracle.pearls.placement import MatrixHomeClearance
from rw_creature_pet.oracle.scene import OracleScene, OracleWorld
from rw_creature_pet.oracle.ui.desktop import OracleDesktopMotion, OracleDesktopViewport


class FixedMatrixClearanceTests(unittest.TestCase):
    def scene(self, **options):
        return OracleScene(OracleConfig(pearl_matrix_enabled=True, **options))

    def assert_clear(self, group, matrix):
        for pearl in group.roots:
            self.assertTrue(pearl.region.contains(pearl.home))
            self.assertGreaterEqual(min((pearl.home-matrix.anchor.home-p.offset).length()
                                        for p in matrix.pearls), MatrixHomeClearance.RADIUS-1e-6)

    def overlapping_slot(self, scene, pearl):
        boxes = pearl._home_boxes(scene.body.chunks[0].position, pearl.region,
                                  scene.config.pearl_follow_width, scene.config.pearl_follow_height)
        points = (scene.pearl_matrix.anchor.home+member.offset for member in scene.pearl_matrix.pearls)
        return next(p for p in points if any(b.contains(p) for b in boxes))

    def test_spawn_on_all_edges_with_different_matrix_sizes(self):
        for size in ((640, 480), (960, 600)):
            for side in ('top', 'right', 'bottom', 'left'):
                for count in (7, 14, 64):
                    with self.subTest(size=size, side=side, count=count):
                        scene = self.scene(world_width=size[0], world_height=size[1], base_side=side,
                                           pearl_matrix_count=count, pearl_fixed_count=3, pearl_satellite_count=1)
                        self.assert_clear(scene.fixed_pearls, scene.pearl_matrix)
                        self.assertTrue(all(p.position == p.home for p in scene.fixed_pearls.roots))

    def test_manual_home_and_extracted_slot_stay_reserved(self):
        scene = self.scene(pearl_fixed_count=1)
        pearl, matrix = scene.pearl, scene.pearl_matrix
        slot = self.overlapping_slot(scene, pearl)
        before = pearl.position
        scene.set_pearl_home(slot)
        self.assertEqual(pearl.position, before, '改悬浮点不能瞬移珠子')
        self.assert_clear(scene.fixed_pearls, matrix)
        selected = pearl.home
        member = min(matrix.pearls, key=lambda p: (matrix.anchor.home+p.offset-slot).length())
        extracted = matrix.extract(member.slot)
        extracted.move_to(scene.body.chunks[0].position)
        extracted.position = extracted.target
        scene.set_pearl_home(slot)
        self.assertEqual(pearl.home, selected, '阅读不释放矩阵槽位')

    def test_live_matrix_enable_and_count_changes_update_placement(self):
        scene = OracleScene(OracleConfig(pearl_fixed_count=1))
        scene.set_pearl_matrix(True)
        pearl = scene.pearl
        pearl.home = self.overlapping_slot(scene, pearl)
        before = pearl.position
        scene.fixed_pearls.step(scene.body.chunks[0].position)
        self.assert_clear(scene.fixed_pearls, scene.pearl_matrix)
        self.assertLess((pearl.position-before).length(), .1)
        scene.set_pearl_counts(matrix=64, fixed=3)
        self.assert_clear(scene.fixed_pearls, scene.pearl_matrix)
        scene.set_pearl_counts(matrix=0)
        self.assertIsNone(scene.fixed_pearls.placement.matrix)
        scene.set_pearl_counts(matrix=7)
        scene.fixed_pearls.step(scene.body.chunks[0].position)
        self.assert_clear(scene.fixed_pearls, scene.pearl_matrix)

    def test_controlled_pearl_keeps_reading_target_and_returns_to_clear_home(self):
        scene = self.scene(pearl_fixed_count=1)
        pearl, center = scene.pearl, scene.body.chunks[0].position
        pearl.home = self.overlapping_slot(scene, pearl)
        pearl.move_to(center)
        target = pearl.target
        for _ in range(24):
            scene.fixed_pearls.step(center, pearl)
        self.assertEqual(pearl.target, target)
        self.assertFalse(pearl.returning_home)
        self.assert_clear(scene.fixed_pearls, scene.pearl_matrix)
        pearl.return_home()
        for _ in range(1000):
            scene.fixed_pearls.step(center)
        self.assertTrue(pearl.settled)
        self.assertEqual(pearl.position, pearl.home)

    def test_follow_both_directions_then_settle_without_repeated_search(self):
        world = OracleWorld(960, 600, .2)
        region = EdgeRegion(world)
        for clockwise in (True, False):
            center = Vec2(480, 60)
            matrix = PearlMatrix(world, region, center, Vec2(0, 1), 360, 280, 14)
            group = FixedPearls(world, region, center, Vec2(0, 1), 360, 280, 3, 1, matrix=matrix)
            route = EdgePlanner(world, region).lap(center, clockwise)
            for tick in range(int(route.length/2)+800):
                center = route.sample(min(route.length, tick*2))
                matrix.step(center)
                group.step(center)
                for pearl in group.roots:
                    self.assertTrue(pearl.region.segment_safe(pearl.previous_position, pearl.position))
            self.assertTrue(group.roots_settled)
            self.assert_clear(group, matrix)
            before = group.revision
            with patch.object(group.placement, 'choose', wraps=group.placement.choose) as choose:
                for _ in range(200):
                    matrix.step(center)
                    group.step(center)
                self.assertEqual(choose.call_count, 0)
            # 卫星仍在转动，母珠自身已休眠
            self.assertEqual(group.revision-before, 200)

    def test_work_area_rebuild_rechecks_transformed_homes(self):
        scene = self.scene(pearl_fixed_count=3, pearl_satellite_count=1)
        for viewport in (OracleDesktopViewport(0, 0, 640, 480),
                         OracleDesktopViewport(-1080, 0, 1080, 1920)):
            restored = OracleDesktopMotion(scene.config, viewport, scene).scene
            self.assert_clear(restored.fixed_pearls, restored.pearl_matrix)
            self.assertTrue(all(p.position == p.home for p in restored.fixed_pearls.roots))

    def test_no_room_chooses_largest_available_gap_and_stays_legal(self):
        matrix = SimpleNamespace(anchor=SimpleNamespace(home=Vec2(5, 5)),
                                 pearls=(SimpleNamespace(offset=Vec2()),))
        placement = MatrixHomeClearance(matrix)
        box = Bounds(0, 0, 10, 10)
        home = placement.choose(Vec2(5, 5), (box,))
        self.assertTrue(box.contains(home))
        self.assertAlmostEqual((home-Vec2(5, 5)).length(), 50**.5)
        self.assertEqual(placement.choose(home, (box,)), home)


if __name__ == '__main__':
    unittest.main()
