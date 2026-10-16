"""柔性槽位：限长、固定点、独立休眠、只读绘制与临时调试"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from copy import deepcopy
from dataclasses import asdict, replace
from math import cos, isfinite, pi, sin
from pathlib import Path
import tempfile
import unittest

from PySide6.QtCore import QCoreApplication, QEvent, QPointF
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication

from rw_creature_pet.config import AppConfig
from rw_creature_pet.oracle.config import CustomAppearance, OracleConfig
from rw_creature_pet.oracle.graphics.damage import visual_bounds
from rw_creature_pet.oracle.graphics.render import OracleRenderer
from rw_creature_pet.oracle.interaction.input import PuppetHitMap
from rw_creature_pet.oracle.motion.soft_parts import SoftStrip, attachment_frame
from rw_creature_pet.oracle.scene import OracleScene
from rw_creature_pet.oracle.soft_part_config import SoftPart
from rw_creature_pet.oracle.ui.debug_window import OracleDebugWindow
from rw_creature_pet.oracle.ui.soft_parts_debug import demo_shape
from rw_creature_pet.presets.library import AppearanceLibrary
from rw_creature_pet.presets.appearance import apply_appearance
from rw_creature_pet.shared.geometry import Vec2


class SoftPartsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def config(self):
        return OracleConfig(hide_cords=True, physics_backend='python', body_appearance='custom',
            halo_enabled=False, pearl_matrix_count=0, pearl_inner_count=0, pearl_outer_count=0,
            pearl_fixed_count=0, pearl_satellite_count=0, custom_appearance=demo_shape(CustomAppearance()))

    def assert_lengths(self, part):
        for a, b, length in zip(part.points, part.points[1:], part.rest):
            self.assertAlmostEqual((b.position-a.position).length(), length, places=8)
            self.assertTrue(isfinite(b.position.x) and isfinite(b.position.y))
        self.assertEqual(part.points[0].position, part.root)
        self.assertLessEqual(len(part.points), 16)

    def settle_strip(self, part, gravity=1.):
        for _ in range(2400):
            part.step(part.root, part.direction, gravity)
            if part.sleeping:
                return
        self.fail('柔性带未收敛')

    def test_turning_and_inverted_strips_keep_lengths_and_settle(self):
        for length in (2., 28., 64.):
            for softness, damping in ((0., 0.), (.7, .5), (1., 1.)):
                with self.subTest(length=length, softness=softness, damping=damping):
                    part = SoftStrip(SoftPart(enabled=True, length=length, softness=softness,
                                              damping=damping), Vec2(), Vec2(0, 1), 1.)
                    for tick in range(180):
                        angle = pi*tick/179
                        part.step(Vec2(30*sin(tick*.04), 0), Vec2(sin(angle), cos(angle)), 1.)
                        self.assert_lengths(part)
                    self.settle_strip(part)
                    self.assert_lengths(part)
                    if softness >= .7:
                        self.assertGreater(part.points[-1].position.y, part.root.y)
                    revision = part.revision
                    for _ in range(60):
                        part.step(part.root, part.direction, 1.)
                    self.assertEqual(part.revision, revision)

    def test_initial_inversion_gravity_transition_and_teleport(self):
        part = SoftStrip(SoftPart(enabled=True, length=40.), Vec2(), Vec2(0, -1), 1.)
        self.settle_strip(part)
        self.assertGreater(part.points[-1].position.y, 20.)
        part.step(part.root, part.direction, 0.)
        self.assertFalse(part.sleeping)
        self.settle_strip(part, gravity=0.)
        part.step(Vec2(1000, 400), Vec2(1, 0), .2)
        self.assert_lengths(part)
        for p in part.points:
            self.assertLessEqual((p.position-part.root).length(), 40.+1e-6)
            self.assertLess((p.position-p.previous_position).length(), 10.)

    def test_each_anchor_uses_its_own_frame_and_bell_keeps_slots_inactive(self):
        scene = OracleScene(self.config())
        app = scene.appearance
        for degrees in (0, 90, 180, 270):
            radians = degrees*pi/180
            app.direction = Vec2(sin(radians), -cos(radians))
            app.upper = Vec2(80, 100)
            app.lower = app.upper-app.direction*9
            app.head.position = app.upper+app.direction*14
            for anchor, expected in (('neck', app.upper+app.direction*3), ('head', app.head.position),
                                     ('waist', app.lower)):
                part = SoftPart(enabled=True, anchor=anchor, offset_x=2, offset_y=1)
                root, forward = attachment_frame(part, app)
                side = Vec2(-app.direction.y, app.direction.x)
                self.assertLess((root-(expected+side*2-app.direction)).length(), 1e-8)
                self.assertLess((forward+app.direction).length(), 1e-8)
        scene.config = replace(scene.config, body_appearance='bell')
        scene.soft_parts.sync(scene)
        self.assertEqual(scene.soft_parts.parts, [None, None])
        scene.config = replace(scene.config, body_appearance='custom')
        scene.soft_parts.sync(scene)
        self.assertTrue(all(scene.soft_parts.parts))

    def test_slot_changes_are_isolated_and_configuration_round_trips(self):
        config = self.config()
        scene = OracleScene(config)
        for _ in range(200):
            scene.step()
        second = scene.soft_parts.parts[1]
        second_points = deepcopy(second.points)
        shape = config.custom_appearance
        shape = replace(shape, soft_part_1=replace(shape.soft_part_1, length=64, anchor='waist'))
        scene.config = replace(config, custom_appearance=shape)
        scene.soft_parts.sync(scene)
        self.assertIs(scene.soft_parts.parts[1], second)
        self.assertEqual(second.points, second_points)
        self.assertEqual(OracleConfig.from_mapping(asdict(scene.config)), scene.config)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            app_config = AppConfig(oracle=scene.config)
            look = AppearanceLibrary(root/'looks').export(app_config, 'Soft scarf')
            restored = apply_appearance(AppConfig(), look, root/'images')
            self.assertEqual(restored.oracle.custom_appearance, shape)
        scene.config = replace(scene.config, custom_appearance=replace(shape,
            soft_part_1=replace(shape.soft_part_1, enabled=False)))
        scene.soft_parts.sync(scene)
        self.assertIsNone(scene.soft_parts.parts[0])
        self.assertIs(scene.soft_parts.parts[1], second)

    def test_drag_and_antigravity_do_not_change_navigation(self):
        config = self.config()
        scene = OracleScene(config)
        baseline = OracleScene(replace(config, custom_appearance=CustomAppearance()))
        for s in (scene, baseline):
            s.drag.set_enabled(True)
            self.assertTrue(s.drag.press(s.body.chunks[0].position, lambda p: True))
        origin = scene.body.chunks[0].position
        for tick in range(120):
            for s in (scene, baseline):
                s.drag.move(origin+Vec2(35*sin(tick*.05), 15*cos(tick*.05)))
                s.step()
            self.assertEqual(scene.body, baseline.body)
            self.assertEqual(scene.arm.joints, baseline.arm.joints)
            for part in scene.soft_parts.parts:
                self.assert_lengths(part)
        for s in (scene, baseline):
            s.drag.release()
        for _ in range(400):
            scene.step(); baseline.step()
        for s in (scene, baseline):
            s.drift()
        saw_weightlessness = False
        for _ in range(450):
            scene.step(); baseline.step()
            self.assertEqual(scene.body, baseline.body)
            saw_weightlessness |= scene.pose.gravity_scale < .5
            for part in scene.soft_parts.parts:
                self.assertEqual(part.gravity, scene.pose.gravity_scale)
                self.assert_lengths(part)
        self.assertTrue(saw_weightlessness)
        scene.stop()
        for _ in range(1800):
            scene.step()
            if scene.arrived and scene.appearance.sleeping and scene.soft_parts.sleeping:
                break
        self.assertTrue(scene.appearance.sleeping and scene.soft_parts.sleeping)

    @staticmethod
    def render(renderer, scene, scale=2.):
        image = QImage(400, 400, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(0)
        painter = QPainter(image)
        try:
            painter.translate(200, 180)
            painter.scale(scale, scale)
            painter.translate(-scene.appearance.upper.x, -scene.appearance.upper.y)
            renderer.draw(painter, scene, .5, raster_scale=scale)
        finally:
            painter.end()
        return image

    def test_render_is_read_only_and_accessory_does_not_rebuild_body_or_hit_map(self):
        scene, renderer, hit = OracleScene(self.config()), OracleRenderer(), PuppetHitMap()
        for _ in range(900):
            scene.step()
        self.assertTrue(scene.appearance.sleeping and scene.soft_parts.sleeping)
        before = self.render(renderer, scene)
        frame, body = renderer._frame, renderer._body_frame
        hit_before = hit.get(renderer, scene)
        part = scene.soft_parts.parts[0]
        part.points[-1].velocity = Vec2(2, 0)
        part.sleeping = False
        part.quiet_ticks = 0
        scene.soft_parts.step(scene)
        state = deepcopy([(p.position, p.previous_position, p.velocity) for p in part.points])
        after = self.render(renderer, scene)
        self.assertIs(renderer._frame, frame)
        self.assertIs(renderer._body_frame, body)
        self.assertIs(hit.get(renderer, scene), hit_before)
        self.assertEqual(state, [(p.position, p.previous_position, p.velocity) for p in part.points])
        self.assertNotEqual(before, after)
        bounds = visual_bounds(scene)
        for part in scene.soft_parts.parts:
            for p in part.points:
                self.assertTrue(bounds.contains(QPointF(p.position.x, p.position.y)))

    def test_debug_controls_are_temporary_and_scene_reset_keeps_them(self):
        config = AppConfig(oracle=self.config())
        window = OracleDebugWindow(config, load_atlas=False)
        window.timer.stop()
        try:
            window.open_soft_parts_debug()
            panel = window.soft_parts_panel
            panel.controls['soft_part_1']['length'].setValue(48.)
            panel.controls['soft_part_2']['enabled'].setChecked(False)
            self.assertEqual(window.scene.config.custom_appearance.soft_part_1.length, 48.)
            self.assertIsNone(window.scene.soft_parts.parts[1])
            window.reset_scene()
            self.assertEqual(window.scene.soft_parts.parts[0].config.length, 48.)
            self.assertEqual(config.oracle.custom_appearance.soft_part_1.length, 34.)
            self.assertTrue(config.oracle.custom_appearance.soft_part_2.enabled)
        finally:
            window.close()
            window.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


if __name__ == '__main__':
    unittest.main()
