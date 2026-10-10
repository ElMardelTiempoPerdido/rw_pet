"""召近选位避开完整机械臂外观；复查、有限换位与无空位归队。"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import unittest
from unittest.mock import patch

from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication

from rw_creature_pet.shared.geometry import Bounds
from rw_creature_pet.oracle.behavior.controller import Activity
from rw_creature_pet.oracle.config import OracleConfig
from rw_creature_pet.oracle.effects.projection_placement import ProjectionArmObstacles
from rw_creature_pet.oracle.graphics.render import OracleRenderer
from rw_creature_pet.oracle.scene import OracleScene


class RecallPlacementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def scene(self, **settings):
        scene = OracleScene(OracleConfig(world_width=640, world_height=480, hide_cords=True,
                                        halo_enabled=False, pearl_matrix_enabled=True,
                                        physics_backend='python', **settings))
        scene.appearance.step = lambda _: None
        return scene

    def until(self, scene, condition, limit=2500):
        for _ in range(limit):
            scene.step()
            if condition():
                return
        self.fail(f'未收敛：{scene.behavior.state}')

    def test_reading_does_not_overlap_rendered_arm_at_four_edges_and_three_scales(self):
        renderer = OracleRenderer()
        for side in ('top', 'right', 'bottom', 'left'):
            for arm_scale in (.35, .6, .75):
                with self.subTest(side=side, arm_scale=arm_scale):
                    scene = self.scene(base_side=side, arm_scale=arm_scale,
                                       base_fraction=.88 if side == 'top' else .5,
                                       allowed_edges=(side,))
                    scene.observe_matrix_pearl((2, 0))
                    self.until(scene, lambda: scene.behavior.state == Activity.OBSERVE)
                    pearl = scene.observed_pearl
                    self.assertTrue(pearl.region.contains(pearl.position))
                    self.assertTrue(scene.arm_region.segment_safe(scene.body.chunks[0].position, pearl.position))
                    self.assertLessEqual((pearl.position-scene.body.chunks[0].position).length(), 62.1)
                    # 验证真正绘制的外壳、关节、底座，而非只重复选点函数的判断。
                    for scale in (1., 1.5, 2.):
                        image = QImage(round(scene.world.width*scale), round(scene.world.height*scale),
                                       QImage.Format.Format_ARGB32)
                        image.fill(0)
                        painter = QPainter(image)
                        painter.scale(scale, scale)
                        renderer.draw_arm(painter, scene, 1.)
                        painter.end()
                        p, radius = pearl.position, pearl.radius+1
                        for x in range(int((p.x-radius)*scale), round((p.x+radius)*scale)+1):
                            for y in range(int((p.y-radius)*scale), round((p.y+radius)*scale)+1):
                                self.assertEqual(image.pixelColor(x, y).alpha(), 0, (side, arm_scale, scale, p))

    def test_nearby_occupied_ring_expands_without_using_an_obstructed_home(self):
        scene = self.scene()
        scene.observe_matrix_pearl((2, 0))
        body = scene.body.chunks[0].position
        obstacles = ProjectionArmObstacles()
        obstacles.boxes = (Bounds(body.x-40, body.y-40, body.x+40, body.y+40),)
        with patch.object(scene.behavior.recall_obstacles, 'update', return_value=obstacles):
            point = scene.behavior.recall_point(scene)
        self.assertIsNotNone(point)
        self.assertGreater((point-body).length(), 38.)
        self.assertLessEqual((point-body).length(), 62.)
        self.assertTrue(obstacles.clear(point, 6., 6.))

    def test_no_clear_position_returns_to_original_slot_without_reading(self):
        scene = self.scene()
        matrix = scene.pearl_matrix
        original = matrix.pearls
        scene.observe_matrix_pearl((2, 0))
        selected = scene.observed_pearl
        blocked = ProjectionArmObstacles()
        blocked.boxes = (Bounds(0, 0, scene.world.width, scene.world.height),)
        states = set()
        with patch.object(scene.behavior.recall_obstacles, 'update', return_value=blocked):
            for _ in range(1200):
                scene.step()
                states.add(scene.behavior.state)
                if scene.behavior.completed_cycles == 1:
                    break
        self.assertEqual(scene.behavior.completed_cycles, 1)
        self.assertIn(Activity.RETURN, states)
        self.assertNotIn(Activity.OBSERVE, states)
        self.assertIsNone(matrix.extracted)
        self.assertEqual(matrix.pearls, original)
        self.assertEqual(selected.position, selected.home)

    def test_arm_occludes_arrival_then_pearl_moves_smoothly_to_another_reading_point(self):
        scene = self.scene(base_side='right')
        scene.observe_matrix_pearl((2, 0))
        self.until(scene, lambda: scene.behavior.state == Activity.OBSERVE and scene.arrived)
        selected, behavior = scene.observed_pearl, scene.behavior
        before = selected.position
        # 模拟召近路上机械臂收拢到原目标；保持珠子到位时的正常状态。
        behavior.enter(Activity.RECALL, 300)
        obstacles = ProjectionArmObstacles()
        obstacles.boxes = (Bounds(before.x-8, before.y-8, before.x+8, before.y+8),)
        with patch.object(behavior.recall_obstacles, 'update', return_value=obstacles):
            behavior.step(scene)
            self.assertEqual(selected.position, before)
            self.assertNotEqual(selected.target, before)
            self.assertEqual(behavior.state, Activity.RECALL)
            self.assertEqual(behavior.recall_retries, 1)
            self.until(scene, lambda: behavior.state == Activity.OBSERVE)
        self.assertIs(scene.observed_pearl, selected)
        self.assertTrue(obstacles.clear(selected.position, 6., 6.))
        self.assertTrue(all(curve.certified_safe(selected.region) for curve in selected.route.curves))

    def test_repeated_occlusion_has_retry_limit(self):
        scene = self.scene()
        scene.observe_matrix_pearl((2, 0))
        self.until(scene, lambda: scene.behavior.state == Activity.OBSERVE and scene.arrived)
        pearl, behavior = scene.observed_pearl, scene.behavior
        behavior.enter(Activity.RECALL, 300)
        blocked = ProjectionArmObstacles()
        blocked.boxes = (Bounds(0, 0, scene.world.width, scene.world.height),)
        # 每次选中的位置都在到位复查时被挡住，不允许无限重置移动超时。
        with patch.object(behavior.recall_obstacles, 'update', return_value=blocked), \
                patch.object(behavior, 'recall_point', return_value=pearl.position) as choose:
            for _ in range(behavior.RECALL_RETRIES+1):
                behavior.step(scene)
        self.assertEqual(choose.call_count, behavior.RECALL_RETRIES)
        self.assertEqual(behavior.state, Activity.RETURN)
        self.assertTrue(pearl.returning_home)

    def test_reading_holds_target_without_recalculating_obstacles(self):
        scene = self.scene()
        scene.observe_matrix_pearl((2, 0))
        self.until(scene, lambda: scene.behavior.state == Activity.OBSERVE)
        pearl = scene.observed_pearl
        point = pearl.position
        with patch.object(scene.behavior.recall_obstacles, 'update', wraps=scene.behavior.recall_obstacles.update) as update:
            for _ in range(120):
                scene.step()
            update.assert_not_called()
        self.assertEqual(pearl.position, point)
        self.assertEqual(pearl.target, point)


if __name__ == '__main__':
    unittest.main()
