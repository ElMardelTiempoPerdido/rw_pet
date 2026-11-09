"""腿长、拖动跟随、旋转一致性、静置休眠及绘制范围"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'

from dataclasses import replace
from math import atan2, pi
import unittest

from PySide6.QtCore import QPointF
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication

from rw_creature_pet.oracle.config import CustomAppearance, OracleConfig, LEG_LENGTH_DEFAULT
from rw_creature_pet.oracle.graphics.appearance import rotate
from rw_creature_pet.oracle.graphics.damage import body_bounds
from rw_creature_pet.oracle.graphics.legs import LegShape
from rw_creature_pet.oracle.graphics.render import OracleRenderer
from rw_creature_pet.oracle.interaction.input import PuppetHitMap
from rw_creature_pet.oracle.motion.legs import LegMotion
from rw_creature_pet.oracle.scene import OracleScene
from rw_creature_pet.shared.geometry import Vec2


class LegTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt = QApplication.instance() or QApplication([])

    def scene(self, length=20.):
        return OracleScene(OracleConfig(body_appearance='custom', hide_cords=True,
            physics_backend='python', custom_appearance=CustomAppearance(leg_length=length, robe_length=.7)))

    def test_long_legs_have_small_bends_and_fit_body_margin_in_all_orientations(self):
        scene = self.scene()
        for length in (4., LEG_LENGTH_DEFAULT, 20.):
            legs = LegShape(length)
            for angle in (0., pi/4, pi/2, pi, -pi/2):
                up = rotate(Vec2(0, -1), angle)
                lower = up*(-9)
                for sign in (-1, 1):
                    root = legs.root(lower, up, sign)
                    goal = legs.goal(lower, up, sign)
                    self.assertAlmostEqual(-(goal-root).x*up.x-(goal-root).y*up.y, length)
                    knee = legs.rest_knee(lower, up, sign)
                    self.assertLess((knee-root.lerp(goal, .5)).length(), .81)
                    first, second = legs.curves(lower, up, sign, knee, goal)
                    self.assertEqual(first[0], root)
                    self.assertEqual(first[-1], second[0])
                    self.assertEqual(second[-1], goal)
                    self.assertLess(((first[-1]-first[-2])-(second[1]-second[0])).length(), 1e-8)
                    self.assertLess((goal-root).length(), legs.reach)
                    # 根部、最远脚部及曲线宽度都在现有 36px 身体留白内
                    self.assertLess(root.length()+legs.reach+3., scene.world.body_margin)

    def test_resize_updates_paused_and_sleeping_pose_without_touching_robe_or_navigation(self):
        scene = self.scene(8.5)
        app = scene.appearance
        cloth = tuple(p.position for p in app.cloth)
        body = tuple(p.position for p in scene.body.chunks)
        app.sleeping = True
        revision = app.revision
        for length in (20., 4., 8.5):
            scene.config = replace(scene.config, custom_appearance=replace(scene.config.custom_appearance,
                                                                          leg_length=length))
            app.sync_shape(scene)
            for p, goal in zip(app.feet, app.foot_goals()):
                self.assertLess((p.position-goal).length(), 1e-8)
                self.assertEqual(p.position, p.previous_position)
                self.assertEqual(p.velocity, Vec2())
            self.assertEqual(tuple(p.position for p in app.cloth), cloth)
            self.assertEqual(tuple(p.position for p in scene.body.chunks), body)
        self.assertFalse(app.sleeping)
        self.assertGreater(app.revision, revision)
        scene.config = replace(scene.config, body_appearance='bell',
                               custom_appearance=CustomAppearance(leg_length=20.))
        app.sync_shape(scene)
        self.assertEqual(app.legs.length, LEG_LENGTH_DEFAULT)

    def test_motion_lags_softly_remains_bounded_and_settles(self):
        for length in (4., 8.5, 20.):
            app = self.scene(length).appearance
            initial = app.lower
            largest_lag = 0.
            for tick in range(100):
                app.direction = rotate(Vec2(0, -1), tick*.025)
                app.lower = initial+Vec2(tick*.65, tick*.2)
                app.step_feet()
                for sign, p, goal in zip((-1, 1), app.feet, app.foot_goals()):
                    root = app.legs.root(app.lower, app.direction, sign)
                    largest_lag = max(largest_lag, (p.position-goal).length())
                    self.assertLessEqual((p.position-root).length(), app.legs.reach+1e-8)
                    self.assertLess(p.velocity.length(), 4.)
                self.check_segments(app)
            self.assertGreater(largest_lag, .1)
            for _ in range(500):
                app.step_feet()
            self.check_segments(app)
            for p in (*app.knees, *app.feet):
                self.assertLess(p.velocity.length(), .002)
        scene = self.scene()
        for _ in range(700):
            scene.step()
        self.assertTrue(scene.appearance.sleeping)

    def test_long_legs_render_and_hit_test_at_each_scale_after_live_resize(self):
        scene = self.scene(8.5)
        renderer, hit = OracleRenderer(), PuppetHitMap()
        for scale in (1., 1.5, 2., 4.):
            frames = []
            for length in (8.5, 20., 4., 20.):
                scene.config = replace(scene.config, custom_appearance=replace(scene.config.custom_appearance,
                                                                              leg_length=length))
                scene.appearance.sync_shape(scene)
                image = QImage(240, 300, QImage.Format.Format_ARGB32_Premultiplied)
                image.fill(0)
                painter = QPainter(image)
                try:
                    painter.translate(120, 100)
                    painter.scale(scale, scale)
                    upper = scene.body.chunks[0].position
                    painter.translate(-upper.x, -upper.y)
                    renderer.draw_geometry(painter, scene, cords=False, pearl=False, halo=False,
                                           arm=False, cache_body=True, raster_scale=scale)
                finally:
                    painter.end()
                frames.append(bytes(image.constBits()))
                if length == 20.:
                    for foot in scene.appearance.feet:
                        self.assertTrue(hit.contains(renderer, scene, foot.position, raster_scale=scale))
                        self.assertTrue(body_bounds(scene).contains(QPointF(foot.position.x, foot.position.y)))
            self.assertNotEqual(frames[0], frames[1])
            self.assertEqual(frames[1], frames[3])

    def check_segments(self, app):
        direction = app.waist_direction(app.direction)
        for sign, motion in zip((-1, 1), app.leg_motion):
            root = app.legs.root(app.lower, direction, sign)
            upper = motion.knee.position-root
            lower = motion.foot.position-motion.knee.position
            self.assertAlmostEqual(upper.length(), motion.upper_length, places=7)
            self.assertAlmostEqual(lower.length(), motion.lower_length, places=7)
            angle = abs(atan2(upper.x*lower.y-upper.y*lower.x, upper.x*lower.x+upper.y*lower.y))
            self.assertLessEqual(angle, LegMotion.KNEE_LIMIT+1e-8)

    def test_knee_is_independent_and_gravity_follows_antigravity(self):
        result = []
        for gravity in (0., 1.):
            app = self.scene().appearance
            app.direction = Vec2(1, 0)
            app.gravity_scale = gravity
            for _ in range(600):
                app.step_feet()
            self.check_segments(app)
            result.append(sum(p.position.y for p in app.feet)/2)
        self.assertGreater(result[1]-result[0], 1.)
        app = self.scene().appearance
        knee = app.knees[0]
        self.assertIn(knee, app.body_points)
        before = app.feet[0].position
        knee.velocity = Vec2(-3, 1)
        app.step_feet()
        self.assertGreater((app.feet[0].position-before).length(), .01)
        self.check_segments(app)

    def test_knee_motion_invalidates_cached_geometry_and_render_is_read_only(self):
        scene, renderer = self.scene(), OracleRenderer()
        image = QImage(960, 600, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(0)
        painter = QPainter(image)
        try:
            renderer.draw_geometry(painter, scene, cache_body=True, cords=False, halo=False, pearl=False)
            frame = renderer._body_frame
            scene.appearance.knees[0].position += Vec2(-1, 0)
            before = [(p.position, p.previous_position, p.velocity) for p in scene.appearance.points]
            renderer.draw_geometry(painter, scene, cache_body=True, cords=False, halo=False, pearl=False)
            self.assertIsNot(renderer._body_frame, frame)
            self.assertEqual(before, [(p.position, p.previous_position, p.velocity) for p in scene.appearance.points])
        finally:
            painter.end()

    def test_long_legs_follow_real_drag_and_recover_to_sleep(self):
        scene = self.scene()
        scene.drag.set_enabled(True)
        self.assertTrue(scene.drag.press(scene.body.chunks[0].position, lambda _: True))
        for offset in (Vec2(40, 20), Vec2(-55, 60), Vec2(30, -40)):
            scene.drag.move(scene.body.chunks[0].position+offset)
            for _ in range(45):
                scene.step()
                app = scene.appearance
                up = app.waist_direction(app.direction)
                for sign, p in zip((-1, 1), app.feet):
                    root = app.legs.root(app.lower, up, sign)
                    self.assertLessEqual((p.position-root).length(), app.legs.reach+1e-8)
                self.check_segments(app)
                self.assertLess(scene.arm.constraint_error, .2)
        scene.drag.release()
        for _ in range(1800):
            scene.step()
            if not scene.drag.controlling and scene.appearance.sleeping:
                break
        self.assertFalse(scene.drag.controlling)
        self.assertTrue(scene.appearance.sleeping)


if __name__ == '__main__':
    unittest.main()
