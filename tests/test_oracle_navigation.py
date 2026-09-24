"""四边滑动验收：轨道连续性、路径安全、支撑可达、反向滞回及绘制范围。"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'

from dataclasses import replace
from math import isfinite
import unittest

from PIL import Image
from PySide6.QtGui import QImage, QPainter
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from rw_creature_pet.atlas import Atlas, extract_atlas
from rw_creature_pet.config import DEFAULT_GAME_DIR
from rw_creature_pet.geometry import Vec2
from rw_creature_pet.oracle import OracleScene, RailSide, dot
from rw_creature_pet.oracle_config import OracleConfig
from rw_creature_pet.oracle_navigation import RoundedRail
from rw_creature_pet.render_oracle import OracleRenderer
from rw_creature_pet.scene import FixedStepper


class OracleNavigationTests(unittest.TestCase):
    def invariants(self, scene, previous_velocity):
        upper, lower = scene.body.chunks
        self.assertAlmostEqual((upper.position - lower.position).length(), 9, places=6)
        self.assertGreater(dot(scene.body.direction, Vec2(0, -1)), .5)
        self.assertTrue(scene.navigator.region.segment_safe(upper.previous_position, upper.position))
        self.assertLessEqual((upper.position - scene.base).length(), scene.arm.maximum_reach + 1e-6)
        self.assertLess(scene.arm.constraint_error, .025)
        self.assertLess(max(j.velocity.length() for j in scene.arm.joints), 12)
        self.assertLess((upper.velocity - previous_velocity).length(), .4)
        self.assertEqual(scene.arm.joints[0].position, scene.base)
        for a, b in zip(scene.arm.joints, scene.arm.joints[1:]):
            self.assertTrue(scene.arm_region.segment_safe(a.position, b.position))
        self.assertTrue(all(isfinite(c.position.x) and isfinite(c.position.y) for c in scene.body.chunks))

    def settle(self, scene, limit=4500):
        previous = scene.body.chunks[0].velocity
        for i in range(limit):
            scene.step()
            self.invariants(scene, previous)
            previous = scene.body.chunks[0].velocity
            if scene.arrived:
                return i
        self.fail(f'未到达：{scene.target}, route={scene.navigator.distance}/{scene.navigator.route.length}')

    def test_round_rail_has_continuous_position_normal_and_uniform_distance(self):
        scene = OracleScene()
        rail = scene.navigator.rail
        for seam in [0., *rail.ends]:
            a, tangent_a = rail.sample(seam - 1e-5)
            b, tangent_b = rail.sample(seam + 1e-5)
            self.assertLess((a - b).length(), 2.1e-5)
            self.assertGreater(dot(tangent_a, tangent_b), .999999)
        for s in range(0, int(rail.length), 3):
            a, _ = rail.sample(s)
            b, tangent = rail.sample(s + 1)
            self.assertAlmostEqual((b - a).length(), 1, delta=.001)
            self.assertAlmostEqual(dot(rail.normal(s + 1), tangent), 0, places=7)
            self.assertLess((rail.sample(s + rail.length)[0] - a).length(), 1e-7)

    def test_clockwise_counterclockwise_all_sides_corners_and_scale_limits(self):
        for side in RailSide:
            for clockwise in (True, False):
                c = OracleConfig(base_side=side.value, base_fraction=0 if clockwise else 1)
                if side in (RailSide.RIGHT, RailSide.BOTTOM):
                    c = replace(c, world_width=640, world_height=480, arm_scale=.35 if side == RailSide.RIGHT else .75)
                with self.subTest(side=side.value, clockwise=clockwise):
                    scene = OracleScene(c)
                    start = scene.body.chunks[0].position
                    scene.start_lap(clockwise)
                    for curve in scene.navigator.route.curves:
                        # 独立密采样，不只依赖规划器自己的凸包验证返回值。
                        for i in range(101):
                            self.assertTrue(scene.body_region.contains(curve.sample(i / 100)))
                    phase = scene.navigator.base.s
                    self.settle(scene)
                    self.assertLess((scene.body.chunks[0].position - start).length(), .3)
                    self.assertEqual(scene.navigator.base.reversals, 0)
                    travel = scene.navigator.base.s - phase
                    self.assertGreater(travel * (1 if clockwise else -1), scene.navigator.rail.length * .85)

    def test_wide_region_short_arm_projects_unreachable_depth_and_waits_for_base(self):
        scene = OracleScene(OracleConfig(world_width=1280, world_height=720, edge_fraction=.35,
                                        arm_scale=.35, float_speed=2., base_speed=1.5, base_side='left'))
        scene.set_target(Vec2(400, 360))
        self.assertLess(scene.target.x, 180)
        self.assertEqual(scene.target.y, 360)
        self.settle(scene)
        scene.start_lap()
        self.settle(scene)
        self.assertEqual(scene.navigator.base.reversals, 0)

    def test_retarget_stop_gaze_and_small_target_jitter(self):
        scene = OracleScene()
        for i in range(360):
            if i % 60 == 0:
                scene.set_target(Vec2(860 if i % 120 == 0 else 100, 70 if i % 180 == 0 else 530))
            previous = scene.body.chunks[0].velocity
            scene.step()
            self.invariants(scene, previous)
        scene.stop()
        self.settle(scene)
        base_before = scene.navigator.base.s
        reversal_count = scene.navigator.base.reversals
        rest = scene.target
        for i in range(480):
            if i % 30 == 0:
                scene.set_target(rest + Vec2(1 if i % 60 else -1, .5))
            scene.set_look_target(Vec2(480 + i % 10, 300))
            scene.step()
        self.settle(scene)
        self.assertLess(abs(scene.navigator.base.s - base_before), 1e-6)
        self.assertEqual(scene.navigator.base.reversals, reversal_count)
        positions = [c.position for c in scene.body.chunks]
        for _ in range(5000):
            scene.step()
        for chunk, position in zip(scene.body.chunks, positions):
            self.assertLess((chunk.position - position).length(), .31)
        self.assertLess(abs(scene.navigator.base.velocity), 1e-8)

    def test_pause_reset_and_fixed_mode(self):
        scene = OracleScene()
        clock = FixedStepper(40)
        scene.start_lap(False)
        for _ in range(100):
            scene.step()
        snapshot = (scene.navigator.base.s, scene.navigator.distance, scene.body.chunks[0].position)
        clock.set_paused(True)
        clock.advance(10, scene.step)
        self.assertEqual(snapshot, (scene.navigator.base.s, scene.navigator.distance, scene.body.chunks[0].position))
        clock.single_step(scene.step)
        self.assertGreater(scene.navigator.distance, snapshot[1])
        scene.reset()
        fresh = OracleScene(scene.config)
        self.assertEqual(scene.body, fresh.body)
        self.assertEqual(scene.arm.joints, fresh.arm.joints)
        scene.set_sliding_base(False)
        base = scene.base
        scene.set_target(Vec2(950, 590))
        for _ in range(500):
            scene.step()
        self.assertEqual(scene.base, base)
        self.assertTrue(scene.world.corridor(scene.anchor.side).contains(scene.body.chunks[0].position))


class OracleRenderedBoundsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)
        # 缺少游戏的机器仍运行几何范围检查；本机则用实际图集进行像素检查。
        atlas = Atlas(extract_atlas(DEFAULT_GAME_DIR)) if DEFAULT_GAME_DIR.is_dir() else None
        cls.renderer = OracleRenderer(atlas)

    def test_rendered_puppet_and_arm_stay_in_band_including_interpolated_frames(self):
        for clockwise in (True, False):
            scene = OracleScene(OracleConfig(world_width=640, world_height=480, arm_scale=.75))
            scene.set_tilt(25 if clockwise else -25)
            scene.start_lap(clockwise)
            for tick in range(1450):
                scene.set_look_target(Vec2(-1000 if tick % 2 else 1800, 900))
                scene.step()
                if tick % 60:
                    continue
                for alpha in (0., .5, 1.):
                    image = QImage(680, 520, QImage.Format.Format_RGBA8888)
                    image.fill(Qt.GlobalColor.transparent)
                    painter = QPainter(image)
                    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
                    painter.translate(20, 20)
                    self.renderer.draw(painter, scene, alpha, cords=False)
                    painter.end()
                    mask = Image.frombytes('RGBA', (680, 520), bytes(image.constBits())).getchannel('A')
                    h = scene.world.inner
                    inner = mask.crop((int(h.left)+20, int(h.top)+20, int(h.right)+20, int(h.bottom)+20))
                    with self.subTest(clockwise=clockwise, tick=tick, alpha=alpha):
                        self.assertIsNone(inner.getbbox(), '可见人偶或机械臂进入中央区域')
                        for rect in ((0, 0, 680, 20), (0, 500, 680, 520), (0, 20, 20, 500), (660, 20, 680, 500)):
                            self.assertIsNone(mask.crop(rect).getbbox(), '可见部分超出工作区')


if __name__ == '__main__':
    unittest.main()
