"""扫描投影的调度、指向、冷却、资源与透明桌面绘制。"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from dataclasses import replace
from math import isfinite
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

from PySide6.QtCore import QPointF
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

from rw_creature_pet.oracle.config import DragReactionConfig, OracleConfig
from rw_creature_pet.oracle.graphics.damage import visual_bounds
from rw_creature_pet.oracle.ui.desktop import OracleDesktopMotion, OracleDesktopViewport
from rw_creature_pet.oracle.interaction.input import PuppetHitMap
from rw_creature_pet.oracle.effects.projection_assets import load_projection_images, prepare_projection
from rw_creature_pet.oracle.effects.projection_placement import ProjectionArmObstacles
from rw_creature_pet.oracle.graphics.render import OracleRenderer
from rw_creature_pet.oracle.scene import OracleScene
from rw_creature_pet.shared.geometry import Bounds, Vec2


def make_scene(**options):
    config = OracleConfig(hide_cords=True, halo_enabled=False, pearl_fixed_count=0,
                          physics_backend='python', drag_projection_probability=1.,
                          drag_reactions=DragReactionConfig(gesture_probability=0, voice_probability=0))
    scene = OracleScene(replace(config, **options))
    scene.projection.available = True
    scene.drag.set_enabled(True)
    scene.drag.press(scene.head.position, lambda _: True)
    return scene


class ProjectionTests(unittest.TestCase):
    def test_config_rejects_invalid_values_and_old_mapping_gets_defaults(self):
        self.assertEqual(OracleConfig.from_mapping({}).drag_projection_cooldown_seconds, 45.)
        for key, values in (('drag_projection_probability', (-.1, 1.1, True, float('nan'))),
                            ('drag_projection_cooldown_seconds', (-1, 3601, '10', float('inf')))):
            for value in values:
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    OracleConfig(**{key: value})

    def test_waits_for_gesture_and_reach_release_then_blocks_new_gestures(self):
        scene = make_scene()
        r, p = scene.drag_reactions, scene.projection
        r.start_gesture('alternating', scene)
        for _ in range(12):
            scene.step()
            self.assertFalse(p.busy)
        r.gesture, r.weight = None, 0.
        self.assertFalse(p.try_start(scene), '袖根物理连接还在收势时不能开始投影')
        for _ in range(15):
            scene.step()
        r.gesture_wait = 0
        scene.step()
        self.assertTrue(p.busy)
        self.assertIsNone(r.gesture)
        r.start_gesture('flutter', scene)
        self.assertIsNone(r.gesture)

    def test_images_precede_one_hand_and_switch_every_fifteen_ticks(self):
        scene = make_scene()
        p, r = scene.projection, scene.drag_reactions
        self.assertTrue(p.try_start(scene))
        nearest = p.nearest_hand(scene)
        for tick in range(1, 61):
            scene.step()
            self.assertEqual(p.frame_index, (tick//15) % 2)
            if tick <= 13:
                self.assertEqual(p.weight, 0.)
            self.assertEqual(r.hand_weight(1-nearest), 0.)
            self.assertEqual(scene.look_target, scene.drag.controller.pointer)
        self.assertEqual(p.hand_index, nearest)
        self.assertGreater(r.hand_weight(nearest), .99)
        hand = scene.appearance.hands[nearest]
        shoulder = hand.shoulder(scene.appearance.upper, scene.appearance.direction, nearest)
        arm, ray = hand.position-shoulder, p.position-shoulder
        alignment = (arm.x*ray.x+arm.y*ray.y)/(arm.length()*ray.length())
        self.assertGreater(alignment, .9)
        self.assertGreater(arm.length(), 13.)

    def test_relocations_vary_stay_onscreen_and_do_not_toggle_hands_for_jitter(self):
        scene = make_scene()
        p = scene.projection
        points = set()
        for _ in range(12):
            p.cooldown = 0
            self.assertTrue(p.try_start(scene))
            points.add(p.position)
            self.assertGreaterEqual(p.clearance(p.position, scene.body.chunks[0].position), 28)
            p.stop(cancel=True)
        self.assertGreater(len(points), 4)
        p.cooldown = 0
        p.try_start(scene)
        initial, hand = p.position, p.hand_index
        for _ in range(260):
            scene.step()
            self.assertTrue(p.region(scene).contains(p.position))
            self.assertEqual(p.hand_index, hand)
        self.assertGreater((p.position-initial).length(), 1.)

    def test_release_cancels_pending_start_and_hides_existing_projection_immediately(self):
        scene = make_scene()
        scene.drag.release()
        for _ in range(80):
            scene.drag_reactions.step(scene)
        self.assertEqual(scene.projection.starts, 0)
        for cancel in (False, True):
            scene = make_scene()
            p = scene.projection
            p.try_start(scene)
            for _ in range(50):
                scene.step()
            scene.drag.release(cancel=cancel)
            self.assertFalse(p.visible)
            self.assertEqual((p.alpha, p.previous_alpha), (0., 0.))
            if not cancel:
                self.assertGreater(p.weight, 0., '正常松手仍平滑放下手臂')
            for _ in range(30):
                scene.step()
            self.assertFalse(p.busy)
            self.assertFalse(p.visible)
            self.assertEqual(p.weight, 0.)
            self.assertTrue(all(h.reach_weight == 0 for h in scene.appearance.hands))

    def test_cooldown_survives_regrab_reset_resize_and_idle_does_not_repaint(self):
        scene = make_scene()
        p = scene.projection
        p.try_start(scene)
        scene.drag.release(cancel=True)
        cooldown = p.cooldown
        scene.drag.press(scene.head.position, lambda _: True)
        self.assertEqual(p.cooldown, cooldown)
        self.assertFalse(p.try_start(scene))
        for _ in range(20):
            p.step(scene)
        self.assertAlmostEqual(p.cooldown, cooldown-.5)
        revision = p.revision
        for _ in range(20):
            p.step(scene)
        self.assertEqual(p.revision, revision)
        scene.reset()
        self.assertAlmostEqual(scene.projection.cooldown, cooldown-1.)
        viewport = OracleDesktopViewport(0, 0, 1280, 800, 1., 1.5)
        moved = OracleDesktopMotion(scene.config, viewport, scene).scene
        self.assertEqual(moved.projection.cooldown, scene.projection.cooldown)
        self.assertFalse(moved.projection.busy)
        self.assertTrue(moved.projection.available)

    def test_probability_and_missing_assets_gate_start_and_cooldown_expires(self):
        scene = make_scene(drag_projection_probability=0.)
        self.assertFalse(scene.projection.try_start(scene))
        scene.config = replace(scene.config, drag_projection_probability=1.)
        scene.projection.available = False
        self.assertFalse(scene.projection.try_start(scene))
        scene.projection.available = True
        scene.projection.cooldown = .1
        for _ in range(5):
            scene.projection.step(scene)
        self.assertTrue(scene.projection.try_start(scene))
        for _ in range(350):
            scene.projection.step(scene)
        self.assertFalse(scene.projection.busy)
        self.assertFalse(scene.projection.try_start(scene))

    def test_timeout_hides_image_without_interpolation_and_lowers_hand_then_stops_repainting(self):
        scene = make_scene()
        p = scene.projection
        p.try_start(scene)
        for _ in range(round(p.DURATION/p.DT)-1):
            p.step(scene)
        self.assertEqual((p.alpha, p.previous_alpha), (1., 1.))
        revision = p.revision
        p.step(scene)
        self.assertEqual((p.alpha, p.previous_alpha), (0., 0.))
        self.assertFalse(p.visible)
        self.assertGreater(p.revision, revision)
        self.assertGreater(p.weight, 0., '画面已消失，手臂继续收势')
        while p.busy:
            p.step(scene)
        settled_revision = p.revision
        for _ in range(20):
            p.step(scene)
        self.assertEqual(p.revision, settled_revision)

    def test_fast_drag_keeps_projection_finite_and_secondary_physics_running(self):
        scene = make_scene()
        p = scene.projection
        p.try_start(scene)
        for point in (Vec2(50, 70), Vec2(920, 500), Vec2(480, 300), Vec2(900, 70)):
            scene.drag.move(point)
            for _ in range(65):
                scene.step()
                self.assertTrue(p.region(scene).contains(p.position))
                for hand in scene.appearance.hands:
                    self.assertTrue(isfinite(hand.position.x+hand.position.y))
                    self.assertLess((hand.position-scene.appearance.upper).length(), 24)
                self.assertLessEqual(sum(scene.drag_reactions.hand_weight(i) > 0 for i in range(2)), 1)

    def test_full_projection_rectangle_and_movement_path_avoid_arm(self):
        obstacles = ProjectionArmObstacles()
        obstacles.boxes = (Bounds(450, 100, 470, 500),)
        # 中心未碰到机械臂，但投影右缘已经压到杆件。
        self.assertFalse(obstacles.clear(Vec2(420, 300), 80, 120))
        self.assertTrue(obstacles.clear(Vec2(200, 300), 80, 120))
        self.assertTrue(obstacles.clear(Vec2(700, 300), 80, 120))
        self.assertFalse(obstacles.clear_path(Vec2(200, 300), Vec2(700, 300), 80, 120))
        scene = make_scene()
        p = scene.projection
        self.assertTrue(p.try_start(scene))
        p.previous_position = p.position = Vec2(200, 300)
        p.target = Vec2(700, 300)
        with patch.object(p.arm_obstacles, 'update', return_value=obstacles), \
                patch.object(p.arm_obstacles, 'broadly_clear', return_value=False):
            p.avoid_arm(scene)
        self.assertEqual(p.position, p.target)
        self.assertEqual(p.previous_position, p.target, '跨杆换位不能经过绘制插值穿过机械臂')

    def test_no_safe_position_skips_start_without_cooldown_or_ends_existing_event(self):
        scene = make_scene()
        p, blocked = scene.projection, ProjectionArmObstacles()
        blocked.boxes = (Bounds(0, 0, scene.world.width, scene.world.height),)
        with patch.object(p.arm_obstacles, 'update', return_value=blocked):
            self.assertFalse(p.try_start(scene))
        self.assertEqual((p.starts, p.cooldown), (0, 0.))
        self.assertTrue(p.try_start(scene))
        for _ in range(40):
            p.step(scene)
        cooldown = p.cooldown
        with patch.object(p.arm_obstacles, 'update', return_value=blocked), \
                patch.object(p.arm_obstacles, 'broadly_clear', return_value=False):
            p.avoid_arm(scene)
        self.assertFalse(p.visible)
        self.assertGreater(p.weight, 0., '结束画面后仍需收势')
        self.assertEqual(p.cooldown, cooldown)


class ProjectionRenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def assets(self, root):
        directory = root/'RainWorld_Data/StreamingAssets/illustrations'
        directory.mkdir(parents=True)
        for name, color in (('aiimg3a.png', 0xff10ee60), ('aiimg3b.png', 0xffee1060)):
            image = QImage(250, 350, QImage.Format.Format_ARGB32)
            image.fill(0)
            painter = QPainter(image)
            painter.fillRect(25, 25, 200, 300, QColor.fromRgba(color))
            painter.end()
            image.save(str(directory/name))
        return directory

    def test_assets_load_atomically_crop_padding_and_report_missing_frame(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            directory = self.assets(root)
            renderer = OracleRenderer()
            self.assertEqual(prepare_projection(root, renderer), '')
            self.assertEqual([(im.width(), im.height()) for im in renderer.projection_images], [(200, 300)]*2)
            (directory/'aiimg3b.png').unlink()
            self.assertTrue(prepare_projection(root, renderer))
            self.assertFalse(renderer.projection_images)

    def test_projection_is_separate_from_hit_map_and_body_cache_at_all_scales(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.assets(root)
            renderer = OracleRenderer()
            renderer.projection_images = load_projection_images(root)
            scene = make_scene()
            scene.projection.try_start(scene)
            p = scene.projection
            p.alpha = p.previous_alpha = 1.
            for scale in (1., 1.5, 2.):
                image = QImage(round(960*scale), round(600*scale), QImage.Format.Format_ARGB32)
                image.fill(0)
                painter = QPainter(image)
                painter.scale(scale, scale)
                renderer.draw(painter, scene)
                cache = renderer._body_frame
                color = image.pixelColor(round(p.position.x*scale), round(p.position.y*scale))
                self.assertGreater(color.green(), color.red())
                self.assertAlmostEqual(color.alphaF(), scene.config.projection_opacity, delta=.01)
                p.frame_index = 1
                renderer.draw(painter, scene)
                painter.end()
                self.assertIs(renderer._body_frame, cache)
                self.assertFalse(PuppetHitMap().get(renderer, scene, raster_scale=scale).contains(p.position))
                self.assertTrue(visual_bounds(scene).contains(QPointF(p.position.x+39, p.position.y+59)))
                p.frame_index = 0

    def test_thin_frame_survives_scaling_and_fractional_movement_with_cached_images(self):
        texture = QImage(200, 300, QImage.Format.Format_ARGB32_Premultiplied)
        texture.fill(0)
        painter = QPainter(texture)
        for rect in ((0, 0, 200, 2), (0, 298, 200, 2), (0, 0, 2, 300), (198, 0, 2, 300)):
            painter.fillRect(*rect, QColor('white'))
        painter.end()
        renderer, scene = OracleRenderer(), make_scene()
        renderer.projection_images = (texture, texture.copy())
        p = scene.projection
        p.alpha = p.previous_alpha = 1.
        for mode in ('classic', 'adaptive'):
            scene.config = replace(scene.config, pixel_mode=mode)
            for scale in (1., 1.5, 2.):
                cached = None
                for offset in (0., .27, .65):
                    with self.subTest(mode=mode, scale=scale, offset=offset):
                        p.position = p.previous_position = Vec2(150+offset, 150+offset)
                        p.frame_index = int(offset > 0)
                        image = QImage(600, 600, QImage.Format.Format_ARGB32)
                        image.fill(0)
                        painter = QPainter(image)
                        painter.translate(.37, .19)
                        painter.scale(scale, scale)
                        renderer.draw_projection(painter, scene)
                        painter.end()
                        if cached is not None:
                            self.assertIs(renderer._projection_frames, cached)
                        cached = renderer._projection_frames
                        x, y = round(p.position.x*scale+.37), round(p.position.y*scale+.19)
                        for sign in (-1, 1):
                            edge_x = round((p.position.x+sign*p.WIDTH/2)*scale+.37)
                            edge_y = round((p.position.y+sign*p.HEIGHT/2)*scale+.19)
                            self.assertTrue(any(image.pixelColor(edge_x+d, y).alpha() for d in range(-2, 3)))
                            self.assertTrue(any(image.pixelColor(x, edge_y+d).alpha() for d in range(-2, 3)))

    def assert_arm_clear(self, renderer, scene, scale=1., alpha=1.):
        p = scene.projection
        center = p.previous_position.lerp(p.position, alpha)
        width, height = round(scene.world.width*scale), round(scene.world.height*scale)
        image = QImage(width, height, QImage.Format.Format_RGBA8888)
        image.fill(0)
        painter = QPainter(image)
        painter.scale(scale, scale)
        renderer.draw_arm(painter, scene, alpha)
        painter.end()
        mask = Image.frombytes('RGBA', (width, height), bytes(image.constBits())).getchannel('A')
        box = (int((center.x-p.WIDTH/2-1)*scale), int((center.y-p.HEIGHT/2-1)*scale),
               round((center.x+p.WIDTH/2+1)*scale), round((center.y+p.HEIGHT/2+1)*scale))
        self.assertIsNone(mask.crop(box).getbbox(), (scene.config.base_side, center, scale, alpha))

    def test_placement_avoids_rendered_shell_joints_and_base_on_four_edges(self):
        renderer = OracleRenderer()
        for side in ('top', 'right', 'bottom', 'left'):
            for arm_scale in (.35, .6, .75):
                for fraction in (.1, .5, .9):
                    with self.subTest(side=side, arm_scale=arm_scale, fraction=fraction):
                        scene = make_scene(base_side=side, arm_scale=arm_scale, base_fraction=fraction)
                        self.assertTrue(scene.projection.try_start(scene))
                        for scale in (1., 1.5, 2.):
                            self.assert_arm_clear(renderer, scene, scale)

    def test_dragging_and_jitter_do_not_move_projection_across_rendered_arm(self):
        scene, renderer = make_scene(), OracleRenderer()
        p = scene.projection
        self.assertTrue(p.try_start(scene))
        checks = 0
        for pointer in (Vec2(700, 180), Vec2(300, 230), Vec2(100, 80), Vec2(800, 90)):
            scene.drag.move(pointer)
            for tick in range(65):
                scene.step()
                if p.visible and tick % 8 == 0:
                    checks += 1
                    for alpha in (0., .5, 1.):
                        self.assert_arm_clear(renderer, scene, alpha=alpha)
        self.assertGreater(checks, 16)


if __name__ == '__main__':
    unittest.main()
