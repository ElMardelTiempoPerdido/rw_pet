"""机械臂主动回收：到达时间、合法折叠的保持，以及重新移动。"""
import unittest

from rw_creature_pet.oracle.config import OracleConfig
from rw_creature_pet.oracle.scene import OracleScene
from rw_creature_pet.shared.geometry import Vec2


class OracleArmMotionTests(unittest.TestCase):
    def make_scene(self, **kwargs):
        scene = OracleScene(OracleConfig(physics_backend='python', halo_enabled=False,
                                        pearl_fixed_count=0, **kwargs))
        # 主运动计时不包含衣袍/线缆；完整次级运动另由 test_drag 覆盖。
        scene.appearance.step = lambda _: None
        scene.drag.set_enabled(True)
        return scene

    def test_long_drag_joint_settling_tracks_body_on_every_edge_and_scale(self):
        for scale in (.35, .6, .75):
            for side in ('top', 'right', 'bottom', 'left'):
                with self.subTest(scale=scale, side=side):
                    scene = self.make_scene(arm_scale=scale, base_side=side)
                    scene.drag.press(scene.body.chunks[0].position, lambda _: True)
                    scene.drag.move(scene.base + scene.base_normal() * 3000)
                    for _ in range(220):
                        scene.step()
                    scene.drag.release()
                    last_body = last_arm = last_residual = 0
                    for tick in range(1, 601):
                        scene.step()
                        body = scene.body.chunks[0]
                        arm_speed = max(j.velocity.length() for j in scene.arm.joints[1:3])
                        if (body.position-scene.drag.home).length() >= .3 or body.velocity.length() >= .03:
                            last_body = tick
                        if arm_speed >= .03:
                            last_arm = tick
                        if arm_speed >= .001:
                            last_residual = tick
                        self.assertLess(scene.arm.constraint_error, .02)
                        self.assertLess(arm_speed, 6.)
                    self.assertLess(last_body, 580)
                    self.assertLessEqual(last_arm-last_body, 20)  # 40 Hz，下同：至多半秒。
                    self.assertLessEqual(last_residual-last_body, 20)
                    self.assertFalse(scene.drag.controlling)
                    self.assertTrue(scene.arm.safe_in(scene.arm_region))
                    self.assertTrue(scene.arrived)
                    rest = [j.position for j in scene.arm.joints]
                    for _ in range(120):
                        scene.step()
                    self.assertLess(max((j.position-p).length() for j, p in zip(scene.arm.joints, rest)), 1e-6)
                    # 保持合法姿势不能锁住下一次导航。
                    scene.set_target(body.position + Vec2(50, 50))
                    for _ in range(100):
                        scene.step()
                    self.assertGreater((scene.arm.joints[-1].position-rest[-1]).length(), 5.)

    def test_release_does_not_finish_while_support_joint_is_still_moving(self):
        scene = self.make_scene()
        scene.drag.press(scene.body.chunks[0].position, lambda _: True)
        scene.drag.release()
        scene.arm.joints[1].velocity = Vec2(.5, 0)
        scene.drag.after_step()
        self.assertTrue(scene.drag.recovering)
        self.assertFalse(scene.arrived)
        for _ in range(200):
            scene.step()
        self.assertFalse(scene.drag.controlling)
        self.assertTrue(scene.arm.settled)

    def test_corner_recovery_has_feasible_fold_and_waits_for_the_base(self):
        cases = (
            ({}, Vec2(1800, 900)),
            ({'world_width': 640, 'world_height': 480, 'arm_scale': .75,
              'base_fraction': .95}, Vec2(1200, 800)),
            ({'allowed_edges': ('top',), 'base_fraction': .05}, Vec2(1800, 600)),
        )
        for config, offset in cases:
            with self.subTest(config=config):
                scene = self.make_scene(**config)
                scene.drag.press(scene.body.chunks[1].position, lambda _: True)
                scene.drag.move(scene.base+offset)
                for _ in range(220):
                    scene.step()
                scene.drag.release()
                last_support = last_arm = 0
                for tick in range(1, 601):
                    scene.step()
                    body = scene.body.chunks[0]
                    if ((body.position-scene.drag.home).length() >= .3 or body.velocity.length() >= .03
                            or abs(scene.navigator.base.velocity) >= .01):
                        last_support = tick
                    if max(j.velocity.length() for j in scene.arm.joints[1:3]) >= .03:
                        last_arm = tick
                    self.assertLess(scene.arm.constraint_error, .02)
                    self.assertLess(max(j.velocity.length() for j in scene.arm.joints), 6.)
                self.assertFalse(scene.drag.controlling)
                self.assertTrue(scene.arm.safe_in(scene.arm_region))
                self.assertLessEqual(last_arm-last_support, 20)


if __name__ == '__main__':
    unittest.main()
