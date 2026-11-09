"""跟手程度变化后的次级运动、移动中松手与绘制频率独立性"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'

from math import isfinite, sin
from dataclasses import replace
import unittest

from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication

from rw_creature_pet.interaction.config import InteractionConfig
from rw_creature_pet.oracle.config import CustomAppearance, DragReactionConfig, OracleConfig
from rw_creature_pet.oracle.cape_config import Cape
from rw_creature_pet.oracle.graphics.render import OracleRenderer
from rw_creature_pet.oracle.motion.prince_robe import PIN_LENGTH
from rw_creature_pet.oracle.motion.prince_spine import HEAD
from rw_creature_pet.oracle.scene import OracleScene
from rw_creature_pet.oracle.soft_part_config import SoftPart
from rw_creature_pet.shared.geometry import Vec2
from rw_creature_pet.shared.timing import FixedStepper
from tests.oracle import test_legs, test_prince_drag_limit
from tests.oracle.test_prince_autonomous_support import scene_at


def snapshot(scene):
    points = (*scene.body.chunks, scene.head, *scene.arm.joints,
              *scene.appearance.points)
    if scene.prince_posture is not None:
        points += tuple(scene.prince_posture.points)
    return tuple((p.position, p.previous_position, p.velocity) for p in points)


class DragSecondaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt = QApplication.instance() or QApplication([])

    def scene(self, response, *, prince=False, side='right', cords=True):
        values = dict(drag_reactions=DragReactionConfig(enabled=False))
        if prince:
            scene = scene_at(side, **values)
        else:
            scene = OracleScene(OracleConfig(body_appearance='custom', base_side=side,
                custom_appearance=CustomAppearance(leg_length=20., robe_length=.7),
                physics_backend='auto', hide_cords=not cords, halo_enabled=False,
                pearl_fixed_count=0, **values))
        scene.drag.configure(InteractionConfig(drag_enabled=True, drag_responsiveness=response))
        return scene

    def check_secondary(self, scene):
        app = scene.appearance
        self.assertTrue(all(isfinite(v) for point in snapshot(scene)
                            for vector in point for v in (vector.x, vector.y)))
        for index, hand in enumerate(app.hands):
            shoulder = hand.shoulder(app.upper, app.direction, index)
            anchor, reach = hand.reach_limit(app.upper, shoulder)
            self.assertLessEqual((hand.position-anchor).length(), reach+1e-7)
        test_legs.LegTests.check_segments(self, app)
        if app.cords is not None:
            for alpha in (0., .5, 1.):
                base = scene.arm.joints[0]
                self.assertLess((app.main_cord[0].sample(alpha)-base.previous_position.lerp(base.position, alpha)).length(), 1e-7)
                for cord in app.small_cords:
                    self.assertEqual(cord[0].sample(alpha), app.main_cord[-1].sample(alpha))
                    self.assertEqual(cord[-1].sample(alpha), app.head.sample(alpha))
        self.assertEqual(app.necklace[0].position, app.necklace_anchors()[0])
        self.assertEqual(app.necklace[-1].position, app.necklace_anchors()[1])
        if scene.prince_posture is None:
            for i, (p, goal) in enumerate(zip(app.cloth, app.cloth_goals())):
                depth = (i//app.CLOTH_DIVS)/(app.CLOTH_DIVS-1)
                self.assertLessEqual((p.position-goal).length(), app.CLOTH_SLACK*depth+1e-7)
            self.assertLess(scene.arm.constraint_error, .2)
        else:
            test_prince_drag_limit.PrinceDragLimitTests.check_support(self, scene)
            robe = app.prince_robe
            goals, _ = robe.goals(app)
            for i, uv in enumerate(robe.coords):
                if uv.y <= PIN_LENGTH:
                    self.assertEqual(robe.front.points[i].position, goals[i])
                    for alpha in (0., .5, 1.):
                        self.assertEqual(robe.front.points[i].sample(alpha), robe.back.points[i].sample(alpha))
                for layer in robe.layers:
                    self.assertLessEqual((layer.points[i].position-goals[i]).length(), layer.limit+1e-7)

    def release_and_settle(self, scene, *, cancel):
        before = snapshot(scene)
        scene.drag.release(cancel=cancel)
        self.assertEqual([p[0] for p in snapshot(scene)], [p[0] for p in before])
        self.assertTrue(all(c.velocity.length() <= (0. if cancel else 3.)+1e-8
                            for c in scene.body.chunks))
        for tick in range(1800):
            scene.step()
            if tick < 80 or tick % 40 == 0:
                self.check_secondary(scene)
            if not scene.drag.controlling and scene.appearance.sleeping:
                break
        self.assertFalse(scene.drag.controlling)
        self.assertTrue(scene.appearance.sleeping)
        self.assertEqual(scene.appearance.maximum_speed, 0.)
        still = tuple(p.position for p in scene.appearance.points)
        for _ in range(80):
            scene.step()
        self.assertEqual(still, tuple(p.position for p in scene.appearance.points))

    def test_ordinary_fast_reversal_release_and_cancel_keep_secondary_parts_connected(self):
        for response, side, cancel in ((0., 'top', False), (.5, 'left', True),
                                       (.75, 'bottom', False), (1., 'right', True)):
            with self.subTest(response=response, side=side, cancel=cancel):
                scene = self.scene(response, side=side)
                for _ in range(650):
                    scene.step()
                start = scene.body.chunks[0].position
                self.assertTrue(scene.drag.press(start, lambda _: True))
                peak_hand = peak_cloth = 0.
                for tick in range(72):
                    shift = Vec2(70*sin(tick*.19), 65*sin(tick*.13))
                    scene.drag.move(start+shift)
                    scene.step()
                    self.check_secondary(scene)
                    app = scene.appearance
                    peak_hand = max(peak_hand, max(p.velocity.length() for p in app.hands))
                    peak_cloth = max(peak_cloth, max(p.velocity.length() for p in app.cloth))
                self.assertGreater(peak_hand, .1)
                self.assertGreater(peak_cloth, .1)
                # 不先停稳再松手，覆盖运动中释放残余惯性的路径
                self.release_and_settle(scene, cancel=cancel)

    def test_prince_moving_head_and_tail_release_keep_robe_and_support_stable(self):
        for response, index, cancel in ((0., HEAD, False), (.5, 0, True),
                                       (.75, HEAD, True), (1., 0, False)):
            with self.subTest(response=response, index=index, cancel=cancel):
                scene = self.scene(response, prince=True)
                for _ in range(250):
                    scene.step()
                start = scene.prince_posture.frame(scene.appearance.upper, scene.appearance.direction).points[index]
                self.assertTrue(scene.drag.press(start, lambda _: True))
                self.assertEqual(scene.drag.controller.handle.key, ('prince', index))
                separate = 0.
                for tick in range(90):
                    scene.drag.move(start+Vec2(-80-70*sin(tick*.13), 60*sin(tick*.17)))
                    scene.step()
                    self.check_secondary(scene)
                    robe = scene.appearance.prince_robe
                    separate = max(separate, max((a.position-b.position).length()
                        for a, b in zip(robe.front.points, robe.back.points)))
                self.assertGreater(separate, .1)
                self.release_and_settle(scene, cancel=cancel)
                self.assertTrue(scene.prince_posture.settled)

    def test_draw_cadence_does_not_change_drag_or_release_physics(self):
        # 相同物理时刻注入相同鼠标输入，隔离输入采样延迟与绘制频率
        for prince in (False, True):
            baseline = None
            for hz in (30, 40, 60, 120):
                with self.subTest(prince=prince, hz=hz):
                    scene = self.scene(1., prince=prince, cords=False)
                    start = (scene.prince_posture.frame(scene.appearance.upper, scene.appearance.direction).points[HEAD]
                             if prince else scene.body.chunks[0].position)
                    clock, history = FixedStepper(scene.TICK_RATE), []
                    renderer = OracleRenderer()
                    image = QImage(1200, 900, QImage.Format.Format_ARGB32_Premultiplied)

                    def step():
                        tick = len(history)
                        if tick in (8, 100):
                            pos = scene.head.position if prince else scene.body.chunks[0].position
                            self.assertTrue(scene.drag.press(pos, lambda _: True))
                        if scene.drag.active:
                            scene.drag.move(start+Vec2(-60-30*sin(tick*.17), 35*sin(tick*.13)))
                        if tick in (70, 125):
                            scene.drag.release(cancel=tick == 125)
                        scene.step()
                        history.append(snapshot(scene))

                    for frame in range(4*hz):
                        clock.advance(1/hz, step)
                        self.assertGreaterEqual(clock.alpha, 0.)
                        self.assertLess(clock.alpha, 1.+1e-9)
                        # 实际渲染包含非整帧插值，并确认绘制没有写回物理状态
                        if frame % max(1, hz//6) == 0:
                            before = snapshot(scene)
                            image.fill(0)
                            painter = QPainter(image)
                            try:
                                renderer.draw_geometry(painter, scene, clock.alpha,
                                    cords=False, pearl=False, halo=False, cache_body=True)
                            finally:
                                painter.end()
                            self.assertEqual(before, snapshot(scene))
                    self.assertEqual(len(history), 160)
                    self.assertEqual(clock.dropped_seconds, 0.)
                    if baseline is None:
                        baseline = history
                    else:
                        self.assertEqual(history, baseline)

    def test_accessories_keep_previous_frame_during_fast_drag_and_settle_after_release(self):
        scene = self.scene(1., cords=False)
        scene.config = replace(scene.config, custom_appearance=replace(scene.config.custom_appearance,
            cape=Cape(enabled=True, length=32.),
            soft_part_1=SoftPart(enabled=True, anchor='head', length=28.),
            soft_part_2=SoftPart(enabled=True, anchor='waist', length=36.)))
        for _ in range(400):
            scene.step()
        start = scene.body.chunks[0].position
        self.assertTrue(scene.drag.press(start, lambda _: True))
        for offset in (Vec2(-20, 10), Vec2(-150, -20), Vec2(0, 20)):
            parts = scene.soft_parts.parts
            previous = [[p.position for p in part.points] for part in parts]
            cape_before = scene.appearance.cape_motion.current
            scene.drag.move(start+offset)
            scene.step()
            for part, old in zip(parts, previous):
                self.assertEqual([p.previous_position for p in part.points], old)
                for alpha in (0., .5, 1.):
                    expected = old[0].lerp(part.root, alpha)
                    self.assertEqual(part.points[0].sample(alpha), expected)
                for a, b, rest in zip(part.points, part.points[1:], part.rest):
                    self.assertAlmostEqual((b.position-a.position).length(), rest, places=7)
            self.assertEqual(scene.appearance.cape_motion.previous, cape_before)
        self.release_and_settle(scene, cancel=False)
        for _ in range(1800):
            scene.step()
            if scene.soft_parts.sleeping:
                break
        self.assertTrue(scene.soft_parts.sleeping)
        self.assertTrue(scene.appearance.cape_motion.settled)


if __name__ == '__main__':
    unittest.main()
