"""斗篷的起停惯性、姿态限幅、独立缓存和最终休眠"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from copy import deepcopy
from dataclasses import replace
from math import isfinite, pi, sin
import unittest

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QPainterPathStroker

from rw_creature_pet.oracle.cape_config import Cape
from rw_creature_pet.oracle.config import CustomAppearance, OracleConfig
from rw_creature_pet.oracle.graphics.appearance import rotate
from rw_creature_pet.oracle.graphics.cape import cape_geometry
from rw_creature_pet.oracle.graphics.damage import cape_bounds
from rw_creature_pet.oracle.graphics.render import OracleRenderer
from rw_creature_pet.oracle.motion.cape import CapeMotion, CapeOffsets
from rw_creature_pet.oracle.scene import OracleScene
from rw_creature_pet.shared.geometry import Vec2
from tests.oracle.test_cape import paint
from tools.oracle.review_cape import pose_scene


class CapeMotionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_start_lag_stop_rebound_and_longer_cape_sways_more(self):
        amplitudes = []
        for length in (18., 34.):
            shape = CustomAppearance(cape=Cape(enabled=True, length=length))
            direction, upper = Vec2(0, -1), Vec2()
            hands = (Vec2(-5, 14), Vec2(5, 14))
            motion = CapeMotion(shape, upper, direction, hands)
            moving, stopped = [], []
            for tick in range(1, 21):
                upper = Vec2(tick*.8, 0)
                motion.step(upper, direction, tuple(h+upper for h in hands))
                moving.append(motion.current.bottom.x)
            for _ in range(240):
                motion.step(upper, direction, tuple(h+upper for h in hands))
                stopped.append(motion.current.bottom.x)
            self.assertLess(min(moving), -.5)
            self.assertGreater(max(stopped), .5)
            self.assertLess(min(stopped[stopped.index(max(stopped)):]), -.1)
            self.assertTrue(motion.settled)
            self.assertEqual(motion.sample(.5), CapeOffsets())
            amplitudes.append(max(stopped))
        self.assertGreater(amplitudes[1], amplitudes[0])

    def test_constant_speed_returns_to_static_shape_and_teleport_resets(self):
        scene, upper, direction = pose_scene(34.)
        hands = tuple(h.position-upper for h in scene.appearance.hands)
        motion = scene.appearance.cape_motion
        for _ in range(240):
            upper += Vec2(.5, .8)
            motion.step(upper, direction, tuple(upper+h for h in hands))
        self.assertTrue(motion.settled)
        self.assertEqual(motion.current, CapeOffsets())
        upper += Vec2(10, 3)
        motion.step(upper, direction, tuple(upper+h for h in hands))
        self.assertFalse(motion.settled)
        upper += Vec2(600, -250)
        for _ in range(2):
            motion.step(upper, direction, tuple(upper+h for h in hands))
            self.assertTrue(motion.settled)
            self.assertEqual(motion.sample(0), CapeOffsets())
            self.assertEqual(motion.sample(1), CapeOffsets())

    def test_single_arm_keeps_opposite_hem_low_through_lift_and_rebound(self):
        for length in (18., 34., 48.):
            for raised_index in (0, 1):
                with self.subTest(length=length, raised_index=raised_index):
                    scene, upper, direction = pose_scene(length)
                    motion, renderer = scene.appearance.cape_motion, OracleRenderer()
                    hands = tuple(h.position for h in scene.appearance.hands)
                    lower_index = 1-raised_index
                    target = upper+Vec2(-18 if raised_index == 0 else 18, 0)

                    def snapshot():
                        sleeves = tuple(renderer.body_sleeve_edges(scene, 1., upper, direction, i)
                                        for i in range(2))
                        return cape_geometry(upper, direction, tuple(h.position for h in scene.appearance.hands),
                                             sleeves, scene.config.custom_appearance, motion.current)

                    def ends(g):
                        right = g.hem.elementAt(0)
                        return (Vec2(g.hem.currentPosition().x(), g.hem.currentPosition().y()),
                                Vec2(right.x, right.y))

                    initial = ends(snapshot())
                    held = None
                    for tick in range(220):
                        amount = min(1., tick/16)*max(0., min(1., (100-tick)/16))
                        hand = scene.appearance.hands[raised_index]
                        hand.position = hand.previous_position = hands[raised_index].lerp(target, amount)
                        motion.step(upper, direction, tuple(h.position for h in scene.appearance.hands))
                        current = ends(snapshot())
                        # 未抬手侧仍保留大部分垂坠长度，抬起和放下的过渡也不能突然上弹
                        self.assertLess(initial[lower_index].y-current[lower_index].y, length*.2)
                        if tick == 70:
                            held = current
                    self.assertGreater(initial[raised_index].y-held[raised_index].y, length*.5)
                    self.assertGreater(initial[lower_index].y-held[lower_index].y, 0.)
                    self.assertTrue(motion.settled)
                    self.assertAlmostEqual(ends(snapshot())[lower_index].y, initial[lower_index].y)

    def test_turn_and_single_arm_motion_remain_bounded_and_keep_collar_fixed(self):
        edge_tolerance = QPainterPathStroker()
        edge_tolerance.setWidth(.02)
        for length in (8., 18., 48.):
            scene, upper, direction = pose_scene(length)
            motion, renderer = scene.appearance.cape_motion, OracleRenderer()
            maximum = 0.
            for tick in range(120):
                angle = pi*tick/119
                direction = rotate(Vec2(0, -1), angle)
                hands = tuple(upper+rotate(p, angle) for p in (
                    Vec2(-5, 14), Vec2(5, 14).lerp(Vec2(18, 0), .5-.5*sin(tick*.1))))
                motion.step(upper, direction, hands)
                for h, pos in zip(scene.appearance.hands, hands):
                    h.position = h.previous_position = pos
                sleeves = tuple(renderer.body_sleeve_edges(scene, 1., upper, direction, i) for i in range(2))
                still = cape_geometry(upper, direction, hands, sleeves, scene.config.custom_appearance)
                for alpha in (0., .5, 1.):
                    offsets = motion.sample(alpha)
                    for p in offsets.points:
                        self.assertTrue(isfinite(p.x) and isfinite(p.y))
                        self.assertLessEqual(p.length(), motion.limit+1e-8)
                    g = cape_geometry(upper, direction, hands, sleeves, scene.config.custom_appearance, offsets)
                    self.assertEqual(g.opening, still.opening)
                    self.assertEqual(g.outer.elementAt(0), still.outer.elementAt(0))
                    # 旋转后对重合边再次做布尔运算时，Qt 存在浮点分类误差
                    covered = g.fill.united(edge_tolerance.createStroke(g.fill))
                    self.assertTrue(g.trim.subtracted(covered).isEmpty())
                    self.assertTrue(cape_bounds(scene).contains(g.outer.boundingRect()))
                maximum = max(maximum, motion.current.bottom.length())
            self.assertGreater(maximum, .1)
            for _ in range(300):
                motion.step(upper, direction, hands)
            self.assertTrue(motion.settled)

    def test_cape_only_rebound_invalidates_cape_cache_not_gown_and_draw_is_read_only(self):
        scene, upper, direction = pose_scene(34.)
        renderer, motion = OracleRenderer(), scene.appearance.cape_motion
        before = paint(renderer, scene)
        body_frame, cape_frame = renderer._body_frame, renderer._cape_frame
        hands = tuple(h.position for h in scene.appearance.hands)
        motion.step(upper+Vec2(3, 0), direction, tuple(h+Vec2(3, 0) for h in hands))
        scene.appearance.revision += 1
        state = deepcopy(vars(motion))
        after = paint(renderer, scene)
        self.assertNotEqual(before, after)
        self.assertIs(renderer._body_frame, body_frame)
        self.assertIsNot(renderer._cape_frame, cape_frame)
        self.assertEqual(after, paint(renderer, scene, cached=False))
        for shift in (Vec2(2, 3), Vec2(.17, .23)):
            for p in (*scene.body.chunks, *scene.appearance.body_points):
                p.position += shift
                p.previous_position += shift
            scene.appearance.revision += 1
            self.assertEqual(paint(renderer, scene), paint(renderer, scene, cached=False))
        self.assertEqual(vars(motion), state)
        scene.config = replace(scene.config, glow_enabled=True)
        self.assertFalse(paint(renderer, scene, complete=True).isNull())
        self.assertFalse(renderer._body_glow.image.isNull())

    def test_navigation_is_unchanged_and_idle_sleeps_after_rebound(self):
        config = OracleConfig(body_appearance='custom', hide_cords=True, physics_backend='python',
            halo_enabled=False, pearl_matrix_enabled=False, pearl_orbits_enabled=False,
            pearl_fixed_count=0, custom_appearance=CustomAppearance(cape=Cape(enabled=True, length=34.)))
        scene = OracleScene(config)
        baseline = OracleScene(replace(config, custom_appearance=replace(config.custom_appearance, cape=Cape())))
        target = scene.body.chunks[0].position+Vec2(100, 0)
        for s in (scene, baseline):
            s.set_target(target)
        maximum = 0.
        for _ in range(180):
            scene.step(); baseline.step()
            self.assertEqual(scene.body, baseline.body)
            self.assertEqual(scene.arm.joints, baseline.arm.joints)
            maximum = max(maximum, scene.appearance.cape_motion.current.bottom.length())
        self.assertGreater(maximum, .1)
        scene.stop()
        for _ in range(1200):
            scene.step()
        self.assertTrue(scene.appearance.sleeping)
        self.assertTrue(scene.appearance.cape_motion.settled)
        revision = scene.appearance.revision
        for _ in range(100):
            scene.step()
        self.assertEqual(scene.appearance.revision, revision)
        # 颜色不清除运动状态；长度或角色/启用状态变化重新初始化
        app, motion = scene.appearance, scene.appearance.cape_motion
        shape = scene.config.custom_appearance
        scene.config = replace(scene.config, custom_appearance=replace(shape, cape=replace(shape.cape, color='#ffffff')))
        app.sync_cape(scene)
        self.assertIs(app.cape_motion, motion)
        scene.config = replace(scene.config, custom_appearance=replace(shape, cape=replace(shape.cape, length=18.)))
        app.sync_cape(scene)
        self.assertIsNot(app.cape_motion, motion)
        self.assertFalse(app.sleeping)
        self.assertTrue(app.cape_motion.settled)
        scene.config = replace(scene.config, body_appearance='bell')
        app.sync_cape(scene)
        self.assertIsNone(app.cape_motion)
        scene.config = replace(scene.config, body_appearance='custom')
        app.sync_cape(scene)
        self.assertEqual(app.cape_motion.current, CapeOffsets())
        scene.reset()
        self.assertTrue(scene.appearance.cape_motion.settled)


if __name__ == '__main__':
    unittest.main()
