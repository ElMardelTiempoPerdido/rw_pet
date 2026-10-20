"""服装 PNG 的原尺寸采样、网格跟随、裁剪、透明度和绘图缓存"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

import numpy as np
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath
from PySide6.QtWidgets import QApplication

from rw_creature_pet.oracle.clothing_config import ClothingDecal
from rw_creature_pet.oracle.graphics.clothing_decals import clothing_mesh, draw_texture_mesh
from rw_creature_pet.oracle.graphics.face_assets import face_image, import_face_png
from rw_creature_pet.oracle.graphics.render import OracleRenderer, PaintCommands
from rw_creature_pet.shared.geometry import Vec2
from tests.oracle.test_cape import paint
from tools.oracle.review_cape import pose_scene


def pixels(image):
    rgba = image.convertToFormat(QImage.Format.Format_RGBA8888)
    return np.frombuffer(rgba.constBits(), dtype=np.uint8).reshape(rgba.height(), rgba.width(), 4).copy()


class ClothingDecalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        face_image.cache_clear()
        self.texture = QImage(12, 24, QImage.Format.Format_ARGB32_Premultiplied)
        self.texture.fill(QColor('#12fe45'))
        painter = QPainter(self.texture)
        painter.fillRect(0, 0, 5, 24, QColor('#472aff'))
        painter.fillRect(0, 8, 12, 2, QColor('#ffffff'))
        painter.end()
        self.path = self.root/'texture.png'
        self.texture.save(str(self.path))

    def scene(self, pose='rest', angle=0):
        scene, upper, direction = pose_scene(pose=pose, angle=angle)
        decal = ClothingDecal(enabled=True, image_path=str(self.path), offset_y=3.)
        shape = replace(scene.config.custom_appearance, cape=replace(scene.config.custom_appearance.cape, enabled=False),
                        clothing_decal_1=decal,
                        clothing_decal_2=replace(decal, part='left_sleeve'),
                        clothing_decal_3=replace(decal, part='right_sleeve'))
        scene.config = replace(scene.config, custom_appearance=shape)
        return scene, upper, direction

    def test_native_pixels_alpha_clip_and_parent_transform(self):
        source = QImage(8, 12, QImage.Format.Format_ARGB32_Premultiplied)
        source.fill(QColor(255, 0, 0, 128))
        coords = (Vec2(0, 0), Vec2(40, 0), Vec2(40, 40), Vec2(0, 40))
        triangles = ((0, 1, 2), (0, 2, 3))
        rect = QRectF(6, 9, source.width(), source.height())
        for density in (1., 1.5, 2.):
            for cached in (False, True):
                image = QImage(120, 120, QImage.Format.Format_ARGB32_Premultiplied)
                image.fill(0)
                painter = QPainter(image)
                painter.translate(10, 10)
                painter.scale(density, density)
                commands = PaintCommands() if cached else painter
                clip = QPainterPath()
                clip.addRect(QRectF(0, 0, 40, 40))
                hole = QPainterPath()
                hole.addRect(QRectF(8, 10, 2, 2))
                commands.setClipPath(clip.subtracted(hole), Qt.ClipOperation.IntersectClip)
                draw_texture_mesh(commands, source, rect, coords, coords, triangles)
                if cached:
                    commands.replay(painter)
                painter.end()
                alpha = pixels(image)[:, :, 3]
                self.assertEqual(set(np.unique(alpha)), {0, 128})  # 无接缝处重复合成
                self.assertEqual(np.count_nonzero(alpha), int((8*12-4)*density*density))

    def test_reference_sleeve_pixels_are_not_fitted_to_width(self):
        scene, upper, direction = self.scene()
        renderer = OracleRenderer()
        for index, part in enumerate(('left_sleeve', 'right_sleeve')):
            edges = renderer.body_sleeve_edges(scene, 1., upper, direction, index)
            coords, vertices, triangles = clothing_mesh(renderer, scene.appearance,
                scene.config.custom_appearance, part, edges)
            offsets = [a-b for a, b in zip(vertices, coords)]
            for offset in offsets:
                self.assertLess((offset-offsets[0]).length(), 1e-8)
            self.assertEqual(len(triangles), (len(edges)-1)*2)

    def test_pose_changes_and_cached_rendering_keep_clipped_texture(self):
        for pose, angle in (('rest', 0), ('both', 0), ('single', 0), ('single', 160)):
            scene, _, _ = self.scene(pose, angle)
            shape = scene.config.custom_appearance
            renderer = OracleRenderer()
            with_texture = paint(renderer, scene, cached=True)
            self.assertEqual(with_texture, paint(renderer, scene, cached=False))
            scene.config = replace(scene.config, custom_appearance=replace(shape,
                **{f'clothing_decal_{i}': ClothingDecal() for i in (1, 2, 3)}))
            without = paint(OracleRenderer(), scene)
            self.assertNotEqual(with_texture, without)
            self.assertTrue(np.array_equal(pixels(with_texture)[:, :, 3], pixels(without)[:, :, 3]))
        scene.config = replace(scene.config, body_appearance='bell', custom_appearance=shape)
        bell = paint(OracleRenderer(), scene)
        scene.config = replace(scene.config, custom_appearance=replace(shape,
            **{f'clothing_decal_{i}': ClothingDecal() for i in (1, 2, 3)}))
        self.assertEqual(bell, paint(OracleRenderer(), scene))

    def test_translation_cache_and_large_pixel_scales(self):
        scene, _, _ = self.scene('single')
        renderer = OracleRenderer()
        for scale in (1., 1.5, 2.):
            paint(renderer, scene, scale=scale)
            frame = renderer._body_frame
            for delta in (Vec2(2, 3), Vec2(.17, .23)):
                for p in (*scene.body.chunks, *scene.appearance.body_points):
                    p.position += delta
                    p.previous_position += delta
                scene.appearance.revision += 1
                cached = paint(renderer, scene, scale=scale)
                self.assertIs(frame, renderer._body_frame)
                self.assertEqual(cached, paint(renderer, scene, scale=scale, cached=False))
        scene, _, _ = self.scene('both')
        for scale, source, coarse in ((3., 1., False), (4., 2., False), (4., 1., True)):
            scene.config = replace(scene.config, coarse_pixels_4x=coarse)
            small = paint(renderer, scene, scale=source, complete=True)
            large = paint(renderer, scene, scale=scale, complete=True)
            self.assertEqual(large, small.scaled(large.size()))

    def test_garment_and_neckline_clip_and_slot_order(self):
        scene, _, _ = self.scene('both')
        cover = QImage(128, 128, QImage.Format.Format_ARGB32_Premultiplied)
        cover.fill(QColor('#00ff00'))
        path = self.root/'cover.png'
        cover.save(str(path))
        shape = scene.config.custom_appearance
        decal = ClothingDecal(enabled=True, image_path=str(path), offset_y=-32)
        shape = replace(shape, clothing_decal_1=decal, clothing_decal_2=decal,
                        clothing_decal_3=replace(decal, image_path=str(self.path), offset_y=6.))
        scene.config = replace(scene.config, custom_appearance=shape)
        renderer = OracleRenderer()
        def gown():
            image = QImage(80, 80, QImage.Format.Format_ARGB32_Premultiplied)
            image.fill(0)
            painter = QPainter(image)
            painter.translate(40-400, 20-300)
            renderer.draw_gown(painter, scene, 1.)
            painter.end()
            return pixels(image)
        colored = gown()
        # 最后一个槽位原色出现在整片绿色覆盖之上
        self.assertTrue(np.any(np.all(colored[:, :, :3] == (18, 254, 69), axis=2)))
        scene.config = replace(scene.config, custom_appearance=replace(shape,
            **{f'clothing_decal_{i}': ClothingDecal() for i in (1, 2, 3)}))
        plain = gown()
        self.assertTrue(np.array_equal(colored[:, :, 3], plain[:, :, 3]))
        self.assertEqual(colored[20, 40, 3], 0)  # 领口内部仍为真孔洞

    def test_restored_png_invalidates_recorded_body_and_pixel_layers(self):
        scene, _, _ = self.scene()
        shape = scene.config.custom_appearance
        managed = import_face_png(self.path, self.root/'managed', shape.clothing_decal_1)
        target = Path(managed.image_path)
        target.unlink()
        scene.config = replace(scene.config, custom_appearance=replace(shape, clothing_decal_1=managed,
            clothing_decal_2=ClothingDecal(), clothing_decal_3=ClothingDecal()))
        renderer = OracleRenderer()
        before = paint(renderer, scene, complete=True)
        key = renderer._body_key
        import_face_png(self.path, self.root/'managed', managed)
        after = paint(renderer, scene, complete=True)
        self.assertNotEqual(key, renderer._body_key)
        self.assertNotEqual(before, after)


if __name__ == '__main__':
    unittest.main()
