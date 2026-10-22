"""Prince 两层衣料的连接、惯性隔离、透明镂空、角色切换与实体绘制范围"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from dataclasses import replace
from math import sin, pi
import unittest
from unittest.mock import patch

import numpy as np
from PySide6.QtCore import QRectF
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication
from rw_creature_pet.oracle.config import OracleConfig
from rw_creature_pet.oracle.graphics import prince
from rw_creature_pet.oracle.graphics.appearance import rotate
from rw_creature_pet.oracle.graphics.damage import body_bounds
from rw_creature_pet.oracle.graphics.prince_robe import draw_lower_robe, robe_image
from rw_creature_pet.oracle.graphics.raster import local_canvas
from rw_creature_pet.oracle.graphics.render import OracleRenderer
from rw_creature_pet.oracle.interaction.input import PuppetHitMap
from rw_creature_pet.oracle.motion.prince_robe import COLUMNS, PIN_LENGTH
from rw_creature_pet.oracle.prince_assets import ROBE_FRONT, ROBE_BACK, robe_layout
from rw_creature_pet.oracle.scene import OracleScene
from rw_creature_pet.shared.geometry import Vec2


def pixels(image):
    image = image.convertToFormat(QImage.Format.Format_RGBA8888)
    return np.frombuffer(image.constBits(), dtype=np.uint8).reshape(image.height(), image.width(), 4).copy()


class PrinceRobeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def scene(self, name='prince'):
        return OracleScene(OracleConfig(body_appearance=name, hide_cords=True, physics_backend='python',
                                       pearl_fixed_count=0, halo_enabled=False))

    def advance(self, scene, origin, angle):
        direction = rotate(Vec2(0., -1.), angle)
        for point, goal in zip(scene.body.chunks, (origin, origin-direction*9)):
            point.previous_position = point.position
            point.velocity = goal-point.position
            point.position = goal
        scene.prince_posture.step(scene.head, origin, direction, Vec2())
        scene.appearance.step(scene)

    def test_real_assets_and_layer_order_keep_native_colors_and_transparency(self):
        art = robe_layout()
        self.assertEqual((art.width, art.height), (22, 46))
        self.assertEqual(art.color, '#030408')
        scene = self.scene()
        robe = scene.appearance.prince_robe
        # 将网格放回原图坐标，隔离物理，验证层序及三角形边缘没有透明裂缝
        for layer in robe.layers:
            for p, uv in zip(layer.points, robe.coords):
                p.position = p.previous_position = uv
        image = QImage(art.width, art.height, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(0)
        painter = QPainter(image)
        draw_lower_robe(OracleRenderer(), painter, scene, 1.)
        painter.end()
        expected = QImage(image.size(), image.format())
        expected.fill(0)
        painter = QPainter(expected)
        painter.drawImage(QRectF(0, 0, art.width, art.height), robe_image(ROBE_BACK))
        painter.drawImage(QRectF(0, 0, art.width, art.height), robe_image(ROBE_FRONT))
        painter.end()
        np.testing.assert_array_equal(pixels(image), pixels(expected))

    def test_seam_is_shared_but_lower_meshes_move_independently_and_settle(self):
        scene = self.scene()
        origin = scene.body.chunks[0].position
        robe = scene.appearance.prince_robe
        peak = 0.
        for tick in range(220):
            phase = tick/35
            self.advance(scene, origin+Vec2(8*sin(phase), 0.), .5*sin(phase))
            goals, _ = robe.goals(scene.appearance)
            for i, uv in enumerate(robe.coords):
                a, b = robe.front.points[i].position, robe.back.points[i].position
                if uv.y <= PIN_LENGTH:
                    self.assertEqual(a, b)
                    self.assertEqual(a, goals[i])
                peak = max(peak, (a-b).length())
                for layer in robe.layers:
                    self.assertLessEqual((layer.points[i].position-goals[i]).length(), layer.limit+1e-8)
        self.assertGreater(peak, .4)
        for _ in range(700):
            self.advance(scene, origin, 0.)
        self.assertTrue(scene.appearance.sleeping)
        self.assertTrue(robe.settled)
        self.assertEqual(scene.appearance.maximum_speed, 0.)
        old = tuple(p.position for p in robe.points)
        for _ in range(40):
            self.advance(scene, origin, 0.)
        self.assertEqual(old, tuple(p.position for p in robe.points))

    def test_idle_png_keeps_native_width_below_join_at_different_shoulder_widths(self):
        for half in (2.5, 3.7, 5.):
            with self.subTest(shoulder_half=half), patch(
                    'rw_creature_pet.oracle.motion.prince_robe.SHOULDER_HALF', half):
                scene = self.scene()
                origin = scene.body.chunks[0].position
                for _ in range(600):
                    self.advance(scene, origin, 0.)
                robe = scene.appearance.prince_robe
                self.assertTrue(robe.settled)
                for row in range(len(robe.coords)//COLUMNS):
                    i = row*COLUMNS
                    if robe.coords[i].y < PIN_LENGTH:
                        continue
                    for layer in robe.layers:
                        # 不只检查接缝宽度：尾端也必须保留素材尺寸，不能累计向外扩展
                        span = layer.points[i+COLUMNS-1].position-layer.points[i].position
                        self.assertAlmostEqual(span.length(), robe.art.width, places=3)

    def test_switching_clears_meshes_restores_bell_width_and_paused_join(self):
        scene = self.scene('bell')
        app = scene.appearance
        local = tuple(app._cloth_local)
        self.assertIsNone(app.prince_robe)
        scene.config = replace(scene.config, body_appearance='prince')
        scene.sync_character()
        app.sync_shape(scene)
        robe = app.prince_robe
        self.assertLess(max(x for x, _ in app._cloth_local), max(x for x, _ in local))
        self.assertTrue(all(p in app.body_points for p in robe.points))
        goals, _ = robe.goals(app)
        self.assertEqual(tuple(p.position for p in robe.front.points), goals)
        scene.config = replace(scene.config, body_appearance='bell')
        scene.sync_character()
        app.sync_shape(scene)
        self.assertIsNone(app.prince_robe)
        self.assertEqual(tuple(app._cloth_local), local)
        self.assertEqual(app.CLOTH_SLACK, 9.)
        self.assertTrue(all(p not in app.body_points for p in robe.points))

    def test_rotated_bounds_cache_and_glow_include_actual_lower_pixels(self):
        scene = self.scene()
        renderer = OracleRenderer(colors=scene.config.active_colors)
        origin = scene.body.chunks[0].position
        for angle in (0., pi/2, pi, -pi/2):
            for _ in range(70):
                self.advance(scene, origin, angle)
            for alpha in (0., .5, 1.):
                bounds = body_bounds(scene)
                for p in scene.appearance.prince_robe.points:
                    v = p.sample(alpha)
                    self.assertTrue(bounds.contains(v.x, v.y))
                images = []
                for cached in (False, True):
                    image, rect = local_canvas(bounds, 1.5)
                    painter = QPainter(image)
                    painter.scale(1.5, 1.5)
                    painter.translate(-rect.x(), -rect.y())
                    renderer.draw_geometry(painter, scene, alpha, cache_body=cached, arm=False,
                                           cords=False, pearl=False, halo=False, raster_scale=1.5)
                    painter.end()
                    images.append(image)
                self.assertEqual(*images)
        scene.config = replace(scene.config, glow_enabled=True)
        image, rect = local_canvas(body_bounds(scene).adjusted(-12, -12, 12, 12), 1.)
        painter = QPainter(image)
        painter.translate(-rect.x(), -rect.y())
        renderer.draw(painter, scene)
        painter.end()
        self.assertIsNotNone(renderer._body_glow.image)
        self.assertTrue(PuppetHitMap().get(renderer, scene) is not None)

    def test_tail_motion_does_not_rebuild_upper_body_or_clip_at_display_scales(self):
        scene = self.scene()
        renderer = OracleRenderer(colors=scene.config.active_colors)
        with patch.object(prince, 'draw_body', wraps=prince.draw_body) as body:
            for scale in (1., 1.5, 2., 3., 4.):
                image = QImage(480, 560, QImage.Format.Format_ARGB32_Premultiplied)
                image.fill(0)
                painter = QPainter(image)
                painter.translate(240, 180)
                painter.scale(scale, scale)
                origin = scene.body.chunks[0].position
                painter.translate(-origin.x, -origin.y)
                renderer.draw_geometry(painter, scene, cache_body=True, arm=False, cords=False,
                                       pearl=False, halo=False, raster_scale=scale)
                painter.end()
                rgba = pixels(image)
                self.assertFalse(np.any(rgba[[0, -1], :, 3]))
                self.assertFalse(np.any(rgba[:, [0, -1], 3]))
                scene.appearance.prince_robe.front.points[-1].position += Vec2(1., 0.)
            self.assertEqual(body.call_count, 1)


if __name__ == '__main__':
    unittest.main()
