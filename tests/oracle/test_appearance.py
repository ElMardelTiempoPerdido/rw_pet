"""次级运动验收：拖尾、收敛、连接点、导航隔离及绘制只读。"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'

from copy import deepcopy
import unittest

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication

from rw_creature_pet.shared.geometry import Vec2
from rw_creature_pet.oracle.scene import OracleScene
from rw_creature_pet.oracle.config import OracleConfig
from rw_creature_pet.oracle.render import OracleRenderer


class OracleAppearanceTests(unittest.TestCase):
    def test_gown_falls_from_ideal_outline_with_fixed_collar(self):
        for tilt in (0, -25, 25):
            with self.subTest(tilt=tilt):
                scene = OracleScene()
                scene.set_tilt(tilt)
                scene.reset()
                app = scene.appearance
                # 从未下垂的旧轮廓释放，验证实际受力，而非初始化拉长贴图。
                for p, goal in zip(app.cloth, app.cloth_goals()):
                    p.position = p.previous_position = goal
                for _ in range(500):
                    scene.step()
                n = app.CLOTH_DIVS
                goals = app.cloth_goals()
                for i, (p, goal) in enumerate(zip(app.cloth, goals)):
                    self.assertLessEqual((p.position-goal).length(), 9*(i//n)/(n-1)+1e-8)
                    self.assertLess((p.position-app.upper).length(), 34.)
                    if i < n:
                        self.assertEqual(p.position, goal)
                hem = (n-1)*n+n//2
                sag = app.cloth[hem].position-goals[hem]
                self.assertGreater(sag.y, 8.5, '下摆要沿画面向下垂坠')
                self.assertLess(abs(sag.x), 1.)
                self.assertLess(max(p.velocity.length() for p in app.cloth), 1e-6)
                if tilt == 0:
                    self.assertAlmostEqual((app.cloth[hem].position-app.upper).y, 33.3, delta=.1)
                    width = app.cloth[-1].position.x-app.cloth[-n].position.x
                    self.assertAlmostEqual(width, 22., delta=.5, msg='保留原版宽度，靠下垂改善比例')

    def test_gown_midline_stops_shimmering_after_movement(self):
        scene = OracleScene()
        scene.set_target(Vec2(760, 65))
        for _ in range(100):
            scene.step()
        scene.stop()
        for _ in range(500):
            scene.step()
        app = scene.appearance
        old = [p.position for p in app.cloth]
        # 旧的不稳定反向插值会在身体已停稳后反复激发中线的细小摆动。
        for _ in range(200):
            scene.step()
            self.assertLess(max(p.velocity.length() for p in app.cloth), 1e-6)
            self.assertLess(max((p.position-before).length() for p, before in zip(app.cloth, old)), 1e-6)
        self.assertTrue(app.sleeping)

    def test_relaxed_hands_drop_in_front_and_keep_world_down_bias(self):
        for tilt in (0, -25, 25):
            with self.subTest(tilt=tilt):
                scene = OracleScene()
                scene.set_tilt(tilt)
                scene.reset()
                upper = scene.body.chunks[0].position
                # 从缩回胸前的位置释放，必须由受力自然垂下，不能只验证初始化。
                for sign, hand in zip((-1, 1), scene.appearance.hands):
                    hand.position = hand.previous_position = upper+Vec2(sign*2, 4)
                # 长线在倾斜姿态下多摆动约一秒；这里同时等待全部次级运动休眠。
                for _ in range(700):
                    scene.step()
                offsets = [p.position-scene.appearance.upper for p in scene.appearance.hands]
                for p in offsets:
                    self.assertAlmostEqual(p.length(), 15., places=5)
                    self.assertGreater(p.y, 12.)
                    self.assertLess(abs(p.x), 8.)
                if tilt == 0:
                    for sign, p in zip((-1, 1), offsets):
                        self.assertAlmostEqual(p.x, sign*5.26685, places=3)
                        self.assertAlmostEqual(p.y, 14.04494, places=3)
                else:
                    center = offsets[0].lerp(offsets[1], .5)
                    axis = scene.appearance.direction
                    # 固定向画面下方的力让手比身体更接近竖直；不能把固定
                    # 放手姿势整体随身体旋转，也不能随底座法线翻转。
                    self.assertLess(abs(center.x/center.y), abs(axis.x/axis.y))
                    self.assertLess(center.x*axis.x, 0)
                self.assertTrue(scene.appearance.sleeping)
                # 仅观察变化唤醒外观时，垂手不应重新掉落或弹跳。
                scene.set_look_target(upper+Vec2(100, -40))
                scene.step()
                self.assertFalse(scene.appearance.sleeping)
                for p, before in zip(scene.appearance.hands, offsets):
                    self.assertLess((p.position-scene.appearance.upper-before).length(), 1e-6)

    def test_follow_lag_fixed_endpoints_and_settling_on_four_sides(self):
        for side in ('top', 'right', 'bottom', 'left'):
            scene = OracleScene(OracleConfig(base_side=side))
            start = scene.body.chunks[0].position
            scene.set_target(start + (Vec2(150, 0) if side in ('top', 'bottom') else Vec2(0, 150)))
            lag = 0.
            for tick in range(180):
                if tick == 100:
                    scene.stop()
                scene.step()
                app = scene.appearance
                upper = scene.body.chunks[0]
                for hand in app.hands:
                    for alpha in (0., .5, 1.):
                        origin = upper.previous_position.lerp(upper.position, alpha)
                        self.assertLessEqual((hand.sample(alpha)-origin).length(), 15.+1e-8)
                goals = app.cloth_goals()
                # 下垂本身不是移动滞后；与初始垂坠轮廓比较，检测起停形变。
                n = app.CLOTH_DIVS
                lag = max(lag, max((p.position-g-Vec2(0, 9*(i//n)/(n-1))).length()
                                  for i, (p, g) in enumerate(zip(app.cloth, goals))))
                for a, b in app.cloth_links:
                    length = (app.cloth[b].position-app.cloth[a].position).length()
                    rest = (goals[b]-goals[a]).length()
                    self.assertLess(abs(length-rest), 2.5)
                self.assertEqual(app.main_cord[0].position, scene.base)
                self.assertLess((app.main_cord[-1].position-app.upper).length(), 112.)
                self.assertEqual(app.main_cord[60].position, app.cords.guide)
                for cord in app.small_cords:
                    self.assertEqual(cord[0].position, app.main_cord[-1].position)
                    self.assertEqual(cord[-1].position, app.head.position)
            self.assertGreater(lag, 1., '下摆应有可见的惯性跟随')
            for _ in range(850):
                scene.step()
            self.assertLess(scene.appearance.maximum_speed, 1e-6)
            old = [p.position for p in scene.appearance.points]
            for _ in range(1500):
                scene.step()
            self.assertLess(max((a-p.position).length() for a, p in zip(old, scene.appearance.points)), 1e-6)
            self.assertTrue(scene.appearance.sleeping)
            scene.set_look_target(start+Vec2(120, -80))
            scene.step()
            self.assertFalse(scene.appearance.sleeping, '观察变化需唤醒头部线束')

    def test_appearance_cannot_change_navigation_and_reset_is_deterministic(self):
        scene, baseline = OracleScene(), OracleScene()
        baseline.appearance.step = lambda _: None
        for s in (scene, baseline):
            s.start_lap()
        for tick in range(450):
            if tick == 240:
                for s in (scene, baseline):
                    s.set_target(Vec2(800, 570))
            scene.step()
            baseline.step()
            self.assertEqual(scene.body, baseline.body)
            self.assertEqual(scene.head, baseline.head)
            self.assertEqual(scene.arm.joints, baseline.arm.joints)
            self.assertEqual(scene.navigator.base.s, baseline.navigator.base.s)
        scene.reset()
        fresh = OracleScene()
        self.assertEqual(scene.appearance.points, fresh.appearance.points)
        for _ in range(120):
            scene.step()
            fresh.step()
        self.assertEqual(scene.appearance.points, fresh.appearance.points)

    def test_paint_is_read_only_and_interpolation_keeps_connections(self):
        app = QApplication.instance() or QApplication([])
        scene = OracleScene()
        scene.set_target(Vec2(760, 65))
        for _ in range(80):
            scene.step()
        before = deepcopy(scene.appearance.points)
        renderer = OracleRenderer()
        for alpha in (0., .25, .5, .75, 1.):
            image = QImage(960, 600, QImage.Format.Format_ARGB32_Premultiplied)
            image.fill(Qt.GlobalColor.transparent)
            painter = QPainter(image)
            renderer.draw(painter, scene, alpha, skeleton=True)
            painter.end()
            for cord in scene.appearance.small_cords:
                self.assertEqual(cord[0].sample(alpha), scene.appearance.main_cord[-1].sample(alpha))
                self.assertEqual(cord[-1].sample(alpha), scene.appearance.head.sample(alpha))
        self.assertEqual(scene.appearance.points, before)
        self.assertIsNotNone(app)


if __name__ == '__main__':
    unittest.main()
