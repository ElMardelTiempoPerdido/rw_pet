"""自定义尺寸的独立存储、布料约束、绘制缓存和 Bell 固定比例回归"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from dataclasses import fields, replace
from math import isfinite, radians
from pathlib import Path
import tempfile
import unittest

from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath
from PySide6.QtWidgets import QApplication

from rw_creature_pet.config import AppConfig
from rw_creature_pet.oracle.config import CustomAppearance, OracleConfig
from rw_creature_pet.oracle.graphics.appearance import rotate
from rw_creature_pet.oracle.graphics.render import OracleRenderer, point
from rw_creature_pet.oracle.interaction.input import PuppetHitMap
from rw_creature_pet.oracle.scene import OracleScene
from rw_creature_pet.settings_store import SettingsStore
from rw_creature_pet.shared.geometry import Vec2


class CustomAppearanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def scene(self, **kwargs):
        return OracleScene(OracleConfig(hide_cords=True, physics_backend='python', **kwargs))

    def paint(self, renderer, scene, *, cached=True, density=2.):
        image = QImage(320, 400, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(0)
        painter = QPainter(image)
        try:
            painter.translate(160, 145)
            painter.scale(4, 4)
            upper = scene.body.chunks[0].position
            painter.translate(-upper.x, -upper.y)
            renderer.draw_geometry(painter, scene, cords=False, pearl=False, halo=False, arm=False,
                                   cache_body=cached, raster_scale=density)
        finally:
            painter.end()
        return bytes(image.constBits())

    def test_validation_and_independent_saved_values(self):
        for field in fields(CustomAppearance):
            for bad in (float('nan'), float('inf'), 1 if isinstance(field.default, bool) else True, '1', -1000, 1000):
                with self.subTest(field=field.name, bad=bad), self.assertRaises(ValueError):
                    CustomAppearance(**{field.name: bad})
        shape = CustomAppearance(1.35, 4., 13., 1.25, sleeve_cuff_radius=0., neck_width=5.,
                                 chest_width=15., chest_height=5.5, shoulder_width=12.5)
        config = AppConfig(oracle=OracleConfig(body_appearance='custom', custom_appearance=shape))
        with tempfile.TemporaryDirectory() as temp:
            store = SettingsStore(Path(temp)/'settings.json')
            store.save(config)
            self.assertEqual(store.load().oracle.active_custom_appearance, shape)
            store.save(replace(config, oracle=replace(config.oracle, body_appearance='bell')))
            bell = store.load().oracle
            self.assertIsNone(bell.active_custom_appearance)
            self.assertEqual(bell.custom_appearance, shape)
        self.assertEqual(OracleConfig.from_mapping({}).custom_appearance, CustomAppearance())

    def test_head_keeps_neck_and_changes_crown_and_face_clip(self):
        renderer = OracleRenderer()
        original = renderer.head_rect()
        for length in (.7, 1.5):
            rect = renderer.head_rect(length)
            self.assertAlmostEqual(rect.bottom(), original.bottom())
            self.assertEqual(rect.width(), original.width())
            self.assertAlmostEqual(rect.height(), original.height()*length)
            scene = self.scene(body_appearance='custom', custom_appearance=CustomAppearance(head_length=length))
            self.paint(renderer, scene)
            self.assertNotEqual(self.paint(renderer, scene), self.paint(OracleRenderer(), self.scene()))

    def test_sleeve_widths_apply_to_both_sides_in_every_orientation(self):
        renderer = OracleRenderer()
        shape = CustomAppearance(sleeve_root_width=4., sleeve_cuff_width=14.)
        for angle in (0, 45, 90, 180):
            up = rotate(Vec2(0, -1), radians(angle))
            for sign in (-1, 1):
                edges = renderer.sleeve_edges(Vec2(), up*(-14), up, sign, shape)
                self.assertAlmostEqual((edges[0][1]-edges[0][0]).length(), 4.)
                self.assertAlmostEqual((edges[-1][1]-edges[-1][0]).length(), 14.)
        self.assertEqual(renderer.SLEEVE_ROOT_HALF_WIDTH, 3.)
        self.assertEqual(renderer.SLEEVE_CUFF_HALF_WIDTH, 5.)

    def test_custom_cuff_zero_is_square_and_large_radius_preserves_narrow_opening(self):
        renderer = OracleRenderer()
        for angle in (0, 45, 90, 180):
            up = rotate(Vec2(0, -1), radians(angle))
            for sign in (-1, 1):
                shape = CustomAppearance(sleeve_cuff_width=2., sleeve_cuff_radius=0.)
                edges = renderer.sleeve_edges(Vec2(), up*(-14), up, sign, shape)
                self.assertEqual(renderer.sleeve_path(edges, shape), renderer.strip_path(edges))
                rounded = renderer.sleeve_path(edges, replace(shape, sleeve_cuff_radius=4.))
                self.assertEqual(rounded, renderer.sleeve_path(edges, replace(shape, sleeve_cuff_radius=.5)))
                self.assertNotEqual(rounded, renderer.strip_path(edges))
                self.assertTrue(rounded.contains(point(edges[-1][0].lerp(edges[-1][1], .5)+up*.1)))

    def test_custom_neck_width_and_collar_have_independent_widths_and_apron_mask(self):
        renderer = OracleRenderer()
        upper, lower, up, head = Vec2(), Vec2(0, 10), Vec2(0, -1), Vec2(0, -20)
        for width in (1., 3., 8.):
            shape = CustomAppearance(neck_width=width, inner_collar_height=8.,
                                     inner_collar_top_width=6., inner_collar_bottom_width=6.)
            scene = self.scene(body_appearance='custom', custom_appearance=shape)
            image = QImage(200, 200, QImage.Format.Format_ARGB32_Premultiplied)
            image.fill(0)
            painter = QPainter(image)
            painter.translate(100, 120)
            painter.scale(4, 4)
            renderer.draw_inner_robe(painter, upper, lower, up, head, shape=shape)
            painter.end()
            mask, _, _ = renderer.apron_geometry(scene, 1., upper, lower, up, head,
                                                 QPainterPath(), QPainterPath(), Vec2())
            # 拉长测试颈部以隔离胸肩/头部遮挡，分别检查内搭与露出的皮肤
            for y, color, expected_width in ((-10., renderer.colors.inner_robe, 6.),
                                               (-16., renderer.colors.skin, width)):
                pixels = [image.pixelColor(x, round(120+y*4)) for x in range(200)]
                self.assertEqual(sum(p == QColor(color) for p in pixels), round(expected_width*4))
            self.assertTrue(mask.contains(point(Vec2(2.8, -10))))
            self.assertFalse(mask.contains(point(Vec2(3.2, -10))))
            self.assertFalse(mask.contains(point(Vec2(0, -16))), '围裙不能覆盖领口以上的皮肤')

    def test_robe_changes_lower_cloth_and_rest_lengths_without_moving_collar_or_body(self):
        scene = self.scene()
        app = scene.appearance
        before = app.cloth_goals()
        body = tuple(c.position for c in scene.body.chunks)
        head, hands = app.head.position, tuple(p.position for p in app.hands)
        for length in (.7, 1.5):
            scene.config = replace(scene.config, body_appearance='custom',
                                   custom_appearance=CustomAppearance(robe_length=length))
            app.sync_shape(scene)
            goals = app.cloth_goals()
            self.assertEqual(before[:5*app.CLOTH_DIVS], goals[:5*app.CLOTH_DIVS])
            hem = len(goals)-app.CLOTH_DIVS//2-1
            self.assertEqual(goals[hem].y > before[hem].y, length > 1)
            for i, neighbors in enumerate(app._cloth_neighbors):
                for j, rest in neighbors:
                    self.assertAlmostEqual((goals[i]-goals[j]).length(), rest)
            self.assertEqual(tuple(c.position for c in scene.body.chunks), body)
            self.assertEqual(app.head.position, head)
            self.assertEqual(tuple(p.position for p in app.hands), hands)
            self.assertTrue(all(p.previous_position == p.position for p in app.cloth))
        scene.config = replace(scene.config, body_appearance='bell')
        app.sync_shape(scene)
        self.assertEqual(app.cloth_goals(), before)
        self.assertEqual(scene.config.custom_appearance.robe_length, 1.5)

    def test_active_shapes_refresh_render_and_hit_cache_and_return_to_bell(self):
        for outfit in ('normal', 'maid'):
            scene = self.scene(outfit=outfit)
            renderer, hit = OracleRenderer(), PuppetHitMap()
            original = self.paint(renderer, scene)
            original_hit = hit.get(renderer, scene, raster_scale=2.)
            for shape in (CustomAppearance(head_length=1.5),
                          CustomAppearance(sleeve_root_width=10.),
                          CustomAppearance(sleeve_cuff_width=14.),
                          CustomAppearance(sleeve_cuff_radius=0.),
                          CustomAppearance(neck_width=8.),
                          CustomAppearance(chest_width=18., chest_height=4.),
                          CustomAppearance(inner_robe_enabled=False),
                          CustomAppearance(inner_collar_enabled=False),
                          CustomAppearance(inner_collar_height=7., inner_collar_top_width=6.),
                          CustomAppearance(robe_length=1.4)):
                # Bell 忽略已经保存的自定义数据，不污染常量或复用错缓存
                scene.config = replace(scene.config, body_appearance='bell', custom_appearance=shape)
                scene.appearance.sync_shape(scene)
                self.assertEqual(self.paint(renderer, scene), original)
                scene.config = replace(scene.config, body_appearance='custom')
                scene.appearance.sync_shape(scene)
                actual = self.paint(renderer, scene)
                self.assertNotEqual(actual, original)
                self.assertEqual(actual, self.paint(OracleRenderer(), scene))
                self.assertIsNot(hit.get(renderer, scene, raster_scale=2.), original_hit)
            scene.config = replace(scene.config, body_appearance='bell')
            scene.appearance.sync_shape(scene)
            self.assertEqual(self.paint(renderer, scene), original)

    def test_extreme_robe_lengths_move_and_settle_without_nonfinite_points(self):
        for length in (.7, 1.5):
            scene = self.scene(body_appearance='custom', custom_appearance=CustomAppearance(robe_length=length))
            scene.set_target(scene.body.chunks[0].position+Vec2(55, 0))
            for tick in range(2400):
                if tick == 80:
                    scene.stop()
                scene.step()
            self.assertTrue(scene.appearance.sleeping)
            self.assertTrue(all(isfinite(p.position.x) and isfinite(p.position.y)
                                for p in scene.appearance.cloth))


if __name__ == '__main__':
    unittest.main()
