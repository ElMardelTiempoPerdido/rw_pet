"""Oracle 运动验收：四边、角落、独立观察、长时间停留与重置。"""
from dataclasses import replace
import math
from pathlib import Path
import tempfile
import unittest

from rw_creature_pet.config import AppConfig
from rw_creature_pet.shared.geometry import Vec2
from rw_creature_pet.oracle.scene import OracleScene, RailSide, dot
from rw_creature_pet.oracle.config import OracleColors, OracleConfig
from rw_creature_pet.shared.timing import FixedStepper


class OraclePhysicsTests(unittest.TestCase):
    def make_scene(self, config=OracleConfig()):
        # 首批固定底座的验收继续保留；滑动模式另有跨边路径测试。
        return OracleScene(replace(config, sliding_base=False))

    def assert_invariants(self, scene):
        upper, lower = scene.body.chunks
        self.assertAlmostEqual((upper.position - lower.position).length(), 9, places=7)
        # 改变倾角指令后允许平滑过渡；整个过渡都必须保持头在躯干上方。
        self.assertGreater(dot(scene.body.direction, Vec2(0, -1)), .5)
        self.assertTrue(scene.world.corridor(scene.anchor.side).contains(upper.position))
        self.assertEqual(scene.arm.joints[0].position, scene.base)
        self.assertAlmostEqual((scene.arm.joints[-1].position - upper.position).length(), scene.arm.lengths[3], places=7)
        for joint in scene.arm.joints:
            self.assertTrue(scene.world.corridor(scene.anchor.side, False).contains(joint.position))
            self.assertTrue(math.isfinite(joint.position.x) and math.isfinite(joint.position.y))
        self.assertLess(scene.arm.constraint_error, .2)

    def test_four_sides_corners_reverse_and_unreachable_targets(self):
        for width, height in ((960, 600), (640, 480)):
            for side in RailSide:
                for fraction in (0., .5, 1.):
                    with self.subTest(size=(width, height), side=side, fraction=fraction):
                        scene = self.make_scene(OracleConfig(world_width=width, world_height=height,
                                                        base_side=side.value, base_fraction=fraction))
                        for goal in (Vec2(-100, -100), Vec2(3000, 2000), scene.base):
                            scene.set_target(goal)
                            self.assertLessEqual((scene.target - scene.base).length(), scene.arm.maximum_reach + 1e-6)
                            for _ in range(360):
                                scene.step()
                                self.assert_invariants(scene)
                                self.assertLess(max(j.velocity.length() for j in scene.arm.joints), 12)
                            self.assertTrue(scene.arrived)

    def test_long_rest_and_independent_look(self):
        scene = self.make_scene()
        for _ in range(800):
            scene.step()
        positions = [c.position for c in scene.body.chunks]
        for goal in (Vec2(960, 0), Vec2(0, 600), Vec2(480, 600), None):
            scene.set_look_target(goal)
            for _ in range(500):
                scene.step()
            for chunk, position in zip(scene.body.chunks, positions):
                self.assertLess((chunk.position - position).length(), 1e-7)
            self.assertTrue(scene.arrived)
            self.assert_invariants(scene)
        self.assertLess(scene.look_direction.length(), 1e-8)
        initial = [j.position for j in scene.arm.joints]
        for _ in range(12000):  # 五分钟仿真；检查漂移而不是仅检查无异常。
            scene.step()
        for joint, position in zip(scene.arm.joints, initial):
            self.assertLess((joint.position - position).length(), 1e-6)
            self.assertLess(joint.velocity.length(), 1e-6)

    def test_tilt_and_stop_without_exchanging_body_chunks(self):
        for side in RailSide:
            scene = self.make_scene(OracleConfig(base_side=side.value))
            for tilt in (-25, 25, 0):
                scene.set_tilt(tilt)
                scene.set_target(scene.base + Vec2(-250, 250))
                for _ in range(80):
                    old = scene.body.direction
                    scene.step()
                    self.assertGreater(dot(old, scene.body.direction), .998)
                    self.assert_invariants(scene)
                scene.stop()
                for _ in range(600):
                    scene.step()
                self.assertTrue(scene.arrived)
                self.assertGreater(dot(scene.body.direction, scene.desired_direction), .999)

    def test_scale_extremes_and_reset_are_deterministic(self):
        for scale in (.35, .75):
            for side in RailSide:
                for fraction in (0., 1.):
                    scene = self.make_scene(OracleConfig(world_width=640, world_height=480, arm_scale=scale,
                                                    base_side=side.value, base_fraction=fraction))
                    scene.set_target(Vec2(320, 240))
                    for _ in range(500):
                        scene.step()
                        self.assert_invariants(scene)
                    scene.reset()
                    fresh = self.make_scene(scene.config)
                    self.assertEqual(scene.body, fresh.body)
                    self.assertEqual(scene.arm.joints, fresh.arm.joints)
                    self.assertEqual(scene.head, fresh.head)
                    self.assertEqual(scene.ticks, 0)

    def test_pause_single_step_and_frame_partition(self):
        a, b = self.make_scene(), self.make_scene()
        ca, cb = FixedStepper(40), FixedStepper(40)
        for scene in (a, b):
            scene.set_target(Vec2(700, 70))
            scene.set_look_target(Vec2(0, 300))
        for _ in range(100):
            ca.advance(.01, a.step)
        for _ in range(40):
            cb.advance(.025, b.step)
        self.assertEqual(a.body, b.body)
        self.assertEqual(a.arm.joints, b.arm.joints)
        ca.set_paused(True)
        ca.advance(5, a.step)
        self.assertEqual(a.ticks, 40)
        ca.single_step(a.step)
        self.assertEqual(a.ticks, 41)

    def test_config_colors_and_invalid_input(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'oracle.toml'
            path.write_text("[oracle]\nbase_side='left'\n[oracle.colors]\nskin='#ad7744'\n", encoding='utf-8')
            config = AppConfig.load(path)
            self.assertEqual(config.oracle.colors.skin, '#ad7744')
            self.assertEqual(config.oracle.colors.eyes, OracleColors().eyes)
            self.assertEqual(config.oracle.base_side, 'left')
        for kwargs in ({'skin': 'red'}, {'eyes': '#fff'}, {'arm': 12}):
            with self.assertRaises(ValueError):
                OracleColors(**kwargs)
        for kwargs in ({'base_fraction': math.nan}, {'arm_scale': 0}, {'base_side': 'floor'},
                       {'edge_fraction': .05}, {'world_width': True}):
            with self.assertRaises(ValueError):
                OracleConfig(**kwargs)
        scene = OracleScene()
        for setter in (scene.set_target, scene.set_look_target):
            with self.assertRaises(ValueError):
                setter(Vec2(math.nan, 2))


if __name__ == '__main__':
    unittest.main()
