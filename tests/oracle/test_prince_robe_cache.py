"""双层下摆共享栅格图，保持显示、插值和鼠标透明区域一致"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from dataclasses import replace
from math import pi, sin
import unittest
from unittest.mock import patch

import numpy as np
from PySide6.QtCore import QRectF
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication

from rw_creature_pet.oracle.config import OracleConfig
from rw_creature_pet.oracle.graphics import prince_robe as drawing, styles
from rw_creature_pet.oracle.graphics.appearance import rotate
from rw_creature_pet.oracle.graphics.clothing_decals import draw_texture_mesh
from rw_creature_pet.oracle.graphics.render import OracleRenderer
from rw_creature_pet.oracle.interaction.input import PuppetHitMap
from rw_creature_pet.oracle.prince_assets import ROBE_BACK, ROBE_FRONT
from rw_creature_pet.oracle.scene import OracleScene
from rw_creature_pet.shared.geometry import Vec2


def direct_lower_robe(renderer, painter, scene, alpha, **kwargs):
    """优化前的直接网格路径，独立于新增缓存，作为像素回归参考"""
    robe = scene.appearance.prince_robe
    rect = QRectF(0., 0., robe.art.width, robe.art.height)
    for path, layer in zip((ROBE_BACK, ROBE_FRONT), robe.layers):
        vertices = tuple(p.sample(alpha) for p in layer.points)
        draw_texture_mesh(painter, drawing.robe_image(path), rect, robe.coords, vertices, robe.triangles)


def alpha_pixels(image):
    image = image.convertToFormat(QImage.Format.Format_RGBA8888)
    return np.frombuffer(image.constBits(), np.uint8).reshape(image.height(), image.width(), 4)[:, :, 3].copy()


class PrinceRobeCacheTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def scene(self):
        return OracleScene(OracleConfig(body_appearance='prince', physics_backend='python',
            world_width=640, world_height=480, hide_cords=True, halo_enabled=False,
            pearl_matrix_enabled=False, pearl_orbits_enabled=False, pearl_fixed_count=0))

    def render(self, renderer, scene, alpha=.5, scale=2.):
        image = QImage(round(640*scale), round(480*scale), QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(0)
        painter = QPainter(image)
        try:
            painter.scale(scale, scale)
            renderer.draw(painter, scene, alpha, raster_scale=scale)
        finally:
            painter.end()
        return image

    def pose(self, scene, angle):
        direction = rotate(Vec2(0., -1.), angle)
        origin = Vec2(320., 240.)
        for i in range(30):
            upper = origin+Vec2(3*sin(i/5), 0.)
            for p, goal in zip(scene.body.chunks, (upper, upper-direction*9)):
                p.previous_position, p.velocity, p.position = p.position, goal-p.position, goal
            scene.prince_posture.step(scene.head, upper, direction, Vec2())
            scene.appearance.step(scene)

    def test_display_and_hit_map_share_mesh_in_both_call_orders(self):
        scene = self.scene()
        for first in ('display', 'hit'):
            for scale in (1., 1.5, 2., 3., 4.):
                with self.subTest(first=first, scale=scale):
                    renderer = OracleRenderer(colors=scene.config.active_colors)
                    with patch.object(drawing, 'draw_texture_mesh', wraps=draw_texture_mesh) as mesh:
                        if first == 'hit':
                            PuppetHitMap().get(renderer, scene, .5, raster_scale=scale)
                        self.render(renderer, scene, scale=scale)
                        # 用新的命中对象，证明没有借助命中图自己的缓存绕过网格绘制
                        PuppetHitMap().get(renderer, scene, .5, raster_scale=scale)
                        self.assertEqual(mesh.call_count, 2)  # 前后两层各一次

    def test_old_and_cached_pixels_match_for_rotation_interpolation_and_scales(self):
        scene = self.scene()
        for angle in (0., pi/2, pi, -pi/2):
            self.pose(scene, angle)
            for scale, coarse in ((1., False), (1.5, False), (2., False), (3., False),
                                  (4., False), (4., True)):
                scene.config = replace(scene.config, coarse_pixels_4x=coarse)
                for alpha in (0., .5, 1.):
                    with self.subTest(angle=angle, scale=scale, coarse=coarse, alpha=alpha):
                        old = OracleRenderer(colors=scene.config.active_colors)
                        new = OracleRenderer(colors=scene.config.active_colors)
                        with patch.object(styles, 'draw_lower_robe', direct_lower_robe):
                            expected = self.render(old, scene, alpha, scale)
                            hit_before = PuppetHitMap().get(old, scene, alpha, raster_scale=scale)
                        self.assertEqual(expected, self.render(new, scene, alpha, scale))
                        hit_after = PuppetHitMap().get(new, scene, alpha, raster_scale=scale)
                        self.assertEqual(hit_before.origin, hit_after.origin)
                        self.assertEqual(hit_before.density, hit_after.density)
                        self.assertEqual(hit_before.image, hit_after.image)

    def test_tail_motion_density_interpolation_and_scene_switch_refresh_cache(self):
        scene = self.scene()
        self.pose(scene, .3)
        renderer = OracleRenderer(colors=scene.config.active_colors)
        with patch.object(drawing, 'draw_texture_mesh', wraps=draw_texture_mesh) as mesh:
            self.render(renderer, scene, .5, 2.)
            self.assertEqual(mesh.call_count, 2)
            # 只改变尾端，不推进上身，也不改变 appearance.revision
            point = scene.appearance.prince_robe.back.points[-1]
            point.position += Vec2(2., 1.)
            PuppetHitMap().get(renderer, scene, .5, raster_scale=2.)
            self.assertEqual(mesh.call_count, 4)
            PuppetHitMap().get(renderer, scene, .8, raster_scale=2.)
            self.assertEqual(mesh.call_count, 6)
            # 同一 renderer、同一物理帧改变显示精度，外层帧缓存也必须更新
            self.render(renderer, scene, .8, 1.5)
            self.assertEqual(mesh.call_count, 8)
            self.render(renderer, scene, .8, 2.)
            self.assertEqual(mesh.call_count, 10)
            other = self.scene()
            self.render(renderer, other, .8, 2.)
            PuppetHitMap().get(renderer, other, .8, raster_scale=2.)
            self.assertEqual(mesh.call_count, 12)

    def test_glow_and_tentacles_remain_mouse_through(self):
        scene = self.scene()
        renderer = OracleRenderer(colors=scene.config.active_colors)
        self.render(renderer, scene)
        plain = PuppetHitMap().get(renderer, scene, .5, raster_scale=2.)
        scene.config = replace(scene.config, glow_enabled=True)
        with patch.object(drawing, 'draw_texture_mesh', wraps=draw_texture_mesh) as mesh:
            self.render(renderer, scene)
            glow_hit = PuppetHitMap().get(renderer, scene, .5, raster_scale=2.)
            self.assertEqual(mesh.call_count, 0)
        self.assertIsNotNone(renderer._body_glow.image)
        self.assertEqual(plain.image, glow_hit.image)
        self.assertTrue(np.any(alpha_pixels(plain.image) >= 128))
        self.assertTrue(np.any(alpha_pixels(plain.image) == 0))
        for part in scene.prince_tentacles.parts:
            self.assertFalse(glow_hit.contains(part.nodes[-1].position))


if __name__ == '__main__':
    unittest.main()
