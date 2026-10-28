"""极限拖拽持续长按、重新移动和归位时的反馈振荡回归"""
import unittest

from rw_creature_pet.shared.geometry import Vec2
from tests.oracle.test_prince_autonomous_support import scene_at


class PrinceDragLimitTests(unittest.TestCase):
    def prepare(self, side='right', index=4):
        scene = scene_at(side)
        for _ in range(250):
            scene.step()
        start = scene.prince_posture.points[index].position
        scene.drag.set_enabled(True)
        self.assertTrue(scene.drag.press(start, lambda _: True))
        self.assertEqual(scene.drag.controller.handle.key, ('prince', index))
        return scene, start

    def check_support(self, scene):
        support = scene.prince_tentacles
        self.assertTrue(support.guard.attached)
        self.assertGreaterEqual(sum(p.attached for p in support.parts), 1)
        self.assertLessEqual(sum(not p.attached for p in support.parts), 2)
        self.assertTrue(scene.drag.outer.contains(scene.body.chunks[0].position, .001))
        for part in support.parts:
            limit = part.reference_length*support.MAX_DRAG_STRETCH
            self.assertLessEqual(part.path(1).length, limit+1e-6)
            if part.attached:
                self.assertLessEqual((support.part_root(part.definition)-part.grip).length(), limit)

    def test_fixed_pointer_at_limit_settles_for_head_and_tail_on_all_edges(self):
        for side in ('right', 'left', 'top', 'bottom'):
            for index in (4, 0):
                with self.subTest(side=side, index=index):
                    scene, start = self.prepare(side, index)
                    direction = scene.base_normal()
                    # 沿边缘法线拖远，避免跨角重新抓附后不再处于牵拉极限
                    history = []
                    for tick in range(1200):
                        scene.drag.move(start+direction*min(900., tick*6.))
                        scene.step()
                        self.check_support(scene)
                        if tick >= 1000:
                            history.append(tuple(p.position for p in scene.prince_posture.points))
                    for points in history:
                        for a, b in zip(points, history[0]):
                            self.assertLess((a-b).length(), .05)
                    self.assertLess(scene.body.chunks[0].velocity.length(), .01)
                    # 稳定不能靠缩短可拖距离实现，最长触手仍能拉直
                    support = scene.prince_tentacles
                    guard = support.guard
                    self.assertIs(guard, max(support.parts, key=lambda p: p.reference_length))
                    self.assertGreater((guard.grip-support.part_root(guard.definition)).length(),
                                       guard.reference_length*1.05)

    def test_limit_reacts_to_new_pointer_and_releases_without_sticking(self):
        scene, start = self.prepare()
        far = start+Vec2(-900., 0.)
        scene.drag.move(far)
        for _ in range(900):
            scene.step()
        before = scene.head.position
        scene.drag.move(far+Vec2(0., 120.))
        for _ in range(200):
            scene.step()
            self.check_support(scene)
        self.assertGreater((scene.head.position-before).length(), 20.)
        # 返回可达区时恢复通常的柔性抓取，不能锁死在极限位置
        near = start+Vec2(-70., 0.)
        scene.drag.move(near)
        for _ in range(500):
            scene.step()
            self.check_support(scene)
        self.assertLess((scene.head.position-near).length(), .5)
        scene.drag.release()
        for _ in range(1400):
            scene.step()
            if not scene.drag.controlling and scene.appearance.sleeping:
                break
        self.assertFalse(scene.drag.controlling)
        self.assertTrue(scene.appearance.sleeping)

    def test_projection_does_not_move_its_boundary_during_body_integration(self):
        scene, start = self.prepare()
        support = scene.prince_tentacles
        point = start+Vec2(-900., 0.)
        expected = support.project_drag(scene, point, choose=True)
        # 本帧导航积分还没有更新可见胸部，此时重复限位必须保持同一个边界
        scene.body.chunks[0].position += Vec2(5., -2.)
        actual = support.project_drag(scene, point)
        self.assertLess((actual-expected).length(), 1e-8)


if __name__ == '__main__':
    unittest.main()
