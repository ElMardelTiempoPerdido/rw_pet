"""柔性几何、透明 PNG 分段采样、层级与携图往返"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from dataclasses import replace
from math import cos, sin
from pathlib import Path
import tempfile
import unittest

import numpy as np
from PySide6.QtCore import QCoreApplication, QEvent, QRectF
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

from rw_creature_pet.config import AppConfig
from rw_creature_pet.oracle.config import CustomAppearance, OracleConfig
from rw_creature_pet.oracle.face_config import FaceDecal
from rw_creature_pet.oracle.graphics.face_assets import read_face_png
from rw_creature_pet.oracle.graphics.render import OracleRenderer
from rw_creature_pet.oracle.graphics.soft_mesh import rasterize_strip
from rw_creature_pet.oracle.graphics.damage import soft_part_bounds
from rw_creature_pet.oracle.graphics.soft_parts import SoftPartsRenderer
from rw_creature_pet.oracle.motion.soft_parts import SoftStrip
from rw_creature_pet.oracle.scene import OracleScene
from rw_creature_pet.oracle.soft_part_config import SoftPart, SOFT_SHAPES
from rw_creature_pet.oracle.ui.debug_window import OracleDebugWindow
from rw_creature_pet.presets.appearance import apply_appearance, load_appearance
from rw_creature_pet.presets.editing import preset_snapshot, snapshot
from rw_creature_pet.presets.library import AppearanceLibrary
from rw_creature_pet.presets.profile_library import ProfileLibrary
from rw_creature_pet.presets.profile import apply_profile
from rw_creature_pet.presets.personal import capture
from rw_creature_pet.shared.geometry import Vec2
from tests.oracle import test_soft_parts as base_tests


def pixels(image):
    image = image.convertToFormat(QImage.Format.Format_RGBA8888)
    return np.frombuffer(image.constBits(), np.uint8).reshape(image.height(), image.width(), 4).copy()


def straight(config, direction=Vec2(0, 1), root=Vec2()):
    part = SoftStrip(config, root, direction, 1.)
    distance = 0.
    for i, p in enumerate(part.points):
        if i:
            distance += part.rest[i-1]
        p.position = p.previous_position = root+direction*distance
    return part


class SoftPartRenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def test_png_uses_native_pixels_for_mesh_physics_and_bounds(self):
        with tempfile.TemporaryDirectory() as folder:
            for width, height in ((12, 64), (40, 96), (1, 128), (128, 1)):
                with self.subTest(size=(width, height)):
                    source = Path(folder)/f'{width}x{height}.png'
                    texture = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
                    texture.fill(QColor('#abcdef'))
                    texture.setPixelColor(0, 0, QColor(0, 0, 0, 0))
                    texture.save(str(source))
                    config = SoftPart(enabled=True, kind='png', image_path=str(source), width=.5, length=2.)
                    part = straight(config, root=Vec2(width/2, 0))
                    self.assertEqual((part.width, part.length), (width, height))
                    self.assertAlmostEqual(sum(part.rest), height)
                    self.assertLessEqual(len(part.points), 16)
                    renderer = SoftPartsRenderer()
                    _, image, target = renderer.prepare(0, part, 1., 1.)
                    x, y = round(-target.x()), round(-target.y())
                    self.assertTrue(np.array_equal(pixels(image)[y:y+height, x:x+width], pixels(texture)))
                    self.assertTrue(soft_part_bounds(part).contains(QRectF(0, 0, width, height)))
                    # 几何尺寸完全不同，也不能拉伸 PNG 或改变其物理长度
                    other = straight(replace(config, width=24., length=64.), root=part.root)
                    _, changed, changed_target = renderer.prepare(0, other, 1., 1.)
                    self.assertEqual(changed, image)
                    self.assertEqual(changed_target, target)

    def test_png_size_changes_rebuild_only_when_actual_length_changes(self):
        with tempfile.TemporaryDirectory() as folder:
            def picture(name, width, height):
                source = Path(folder)/name
                image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
                image.fill(QColor('#abcdef'))
                image.save(str(source))
                return str(source)
            config = SoftPart(enabled=True, kind='png', image_path=picture('first.png', 40, 96))
            scene = OracleScene(OracleConfig(body_appearance='custom', hide_cords=True,
                custom_appearance=CustomAppearance(soft_part_1=config)))
            def change(**fields):
                value = replace(scene.config.custom_appearance.soft_part_1, **fields)
                scene.config = replace(scene.config, custom_appearance=replace(
                    scene.config.custom_appearance, soft_part_1=value))
                scene.soft_parts.sync(scene)
                return scene.soft_parts.parts[0]
            part = scene.soft_parts.parts[0]
            before = [(p.position, p.velocity) for p in part.points]
            self.assertIs(change(width=24., length=64.), part)
            self.assertEqual(before, [(p.position, p.velocity) for p in part.points])
            self.assertIs(change(image_path=picture('wider.png', 80, 96)), part)
            self.assertEqual(part.width, 80)
            taller = change(image_path=picture('taller.png', 80, 128))
            self.assertIsNot(taller, part)
            self.assertAlmostEqual(sum(taller.rest), 128)
            geometry = change(kind='rectangle')
            self.assertEqual((geometry.width, geometry.length), (24., 64.))

    def test_geometry_profiles_and_all_sampling_densities(self):
        counts = {}
        for kind in SOFT_SHAPES[:-1]:
            config = SoftPart(enabled=True, kind=kind, width=12., length=32.)
            for density in (1., 1.5, 2.):
                image, target = rasterize_strip(straight(config), 1., density)
                alpha = pixels(image)[:, :, 3]
                self.assertTrue(np.isin(alpha, (0, 255)).all())
                rows = np.count_nonzero(alpha, axis=1)
                first = int(-target.y()*density)
                self.assertGreater(rows[first+int(16*density)], 0)
                counts[kind, density] = rows[first:first+int(32*density)]
        for density in (1., 1.5, 2.):
            rectangle = counts['rectangle', density]
            self.assertTrue((rectangle == int(12*density)).all())
            for kind in ('ellipse', 'line'):
                rows = counts[kind, density]
                self.assertLess(rows[0], rows[len(rows)//2])
                self.assertEqual(rows[0], rows[-1])
            self.assertGreater(counts['triangle', density][0], counts['triangle', density][-1])
            self.assertAlmostEqual(counts['trapezoid', density][-1], 6*density, delta=1)

    def test_transparent_triangle_edges_have_no_holes_or_double_alpha(self):
        texture = QImage(16, 64, QImage.Format.Format_ARGB32_Premultiplied)
        texture.fill(QColor(80, 120, 200, 128))
        config = SoftPart(enabled=True, kind='rectangle', width=12., length=48.)
        for density in (1., 1.5, 2.):
            for angle in (0., .3, .7853981633974483, 1.5707963267948966, 3.141592653589793):
                direction = Vec2(sin(angle), cos(angle))
                part = straight(config, direction, Vec2(.25, .5))
                opaque, _ = rasterize_strip(part, 1., density)
                image, _ = rasterize_strip(part, 1., density, texture)
                alpha = pixels(image)[:, :, 3]
                self.assertTrue(np.isin(alpha, (0, 128)).all(), (density, angle, np.unique(alpha)))
                self.assertTrue(np.array_equal(alpha > 0, pixels(opaque)[:, :, 3] > 0))
        # 缓弯的相邻段也不能因三角形拼接重复叠加半透明度
        part = straight(replace(config, width=4.))
        for i, p in enumerate(part.points):
            direction = Vec2(sin(i*.10), cos(i*.10))
            if i:
                p.position = part.points[i-1].position+direction*part.rest[i-1]
                p.previous_position = p.position
        for density in (1., 1.5, 2.):
            image, _ = rasterize_strip(part, 1., density, texture)
            self.assertTrue(np.isin(pixels(image)[:, :, 3], (0, 128)).all())

    def test_png_orientation_holes_and_bent_continuity(self):
        texture = QImage(8, 64, QImage.Format.Format_ARGB32_Premultiplied)
        texture.fill(0)
        for y in range(64):
            for x in range(8):
                if not (24 <= y < 40 and 2 <= x < 6):
                    texture.setPixelColor(x, y, QColor(255 if x < 4 else 0, 255 if x >= 4 else 0, y*4))
        folder = self.enterContext(tempfile.TemporaryDirectory())
        source = Path(folder)/'orientation.png'
        texture.save(str(source))
        part = straight(SoftPart(enabled=True, kind='png', image_path=str(source)))
        image, bounds = rasterize_strip(part, 1., 2., texture)
        def color(x, y):
            return image.pixelColor(int((x-bounds.x())*2), int((y-bounds.y())*2))
        self.assertEqual(color(-3, 2).red(), 255)
        self.assertEqual(color(3, 2).green(), 255)
        self.assertGreater(color(-3, 58).blue(), color(-3, 2).blue())
        self.assertEqual(color(0, 32).alpha(), 0)
        for tick in range(80):
            part.step(Vec2(12*sin(tick*.04), 0), Vec2(0, 1), 1.)
        bent, _ = rasterize_strip(part, 1., 2., texture)
        self.assertNotEqual(bent, image)
        colors = pixels(bent)
        opaque = colors[colors[:, :, 3] > 0]
        self.assertTrue(((opaque[:, 0] == 255) | (opaque[:, 1] == 255)).all())

    def test_front_back_layer_and_visual_changes_preserve_physics(self):
        part = SoftPart(enabled=True, width=10, length=48, color='#01fd02')
        config = OracleConfig(body_appearance='custom', hide_cords=True, halo_enabled=False,
            pearl_fixed_count=0, pearl_satellite_count=0, custom_appearance=CustomAppearance(soft_part_1=part))
        scene = OracleScene(config)
        renderer = OracleRenderer()
        for _ in range(900):
            scene.step()
        self.assertTrue(scene.soft_parts.sleeping)
        before = [(p.position, p.velocity) for p in scene.soft_parts.parts[0].points]
        front = base_tests.SoftPartsTests.render(renderer, scene)
        scene.config = replace(config, custom_appearance=replace(config.custom_appearance,
            soft_part_1=replace(part, layer='back')))
        scene.soft_parts.sync(scene)
        self.assertTrue(scene.soft_parts.sleeping)
        self.assertEqual(before, [(p.position, p.velocity) for p in scene.soft_parts.parts[0].points])
        back = base_tests.SoftPartsTests.render(renderer, scene)
        def green(image):
            return np.all(pixels(image)[:, :, :3] == (1, 253, 2), axis=2)
        self.assertGreater(green(front).sum(), green(back).sum())
        self.assertGreater(green(back).sum(), 0)

    def test_png_appearance_profile_and_personal_copies_survive_source_removal(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root/'scarf.png'
            image = QImage(24, 128, QImage.Format.Format_ARGB32_Premultiplied)
            image.fill(QColor('#abcdee'))
            image.save(str(source))
            part = SoftPart(enabled=True, kind='png', layer='back', image_path=str(source), image_name=source.name)
            config = AppConfig(oracle=OracleConfig(body_appearance='custom',
                custom_appearance=CustomAppearance(soft_part_1=part)))
            looks = AppearanceLibrary(root/'looks')
            profiles = ProfileLibrary(root/'profiles')
            look = looks.export(config, 'Scarf')
            profile = profiles.export(config, 'Scarf character')
            captured = capture(config, 'profile', root/'history')
            path = 'oracle.custom_appearance.soft_part_1.image_path'
            self.assertEqual(snapshot(config, [path])[path], preset_snapshot(look, 'appearance')[path])
            self.assertTrue(Path(captured[path]).is_file())
            relative = replace(config.oracle.custom_appearance, soft_part_1=replace(part, image_path='scarf.png'))
            self.assertEqual(relative.resolve_image_paths(root).soft_part_1.image_path, str(source.resolve()))
            source.unlink()
            loaded = apply_appearance(AppConfig(), load_appearance(look.path), root/'cache')
            loaded_profile = apply_profile(AppConfig(), profile, root/'cache')
            self.assertEqual(loaded.oracle.custom_appearance, loaded_profile.oracle.custom_appearance)
            self.assertEqual(read_face_png(loaded.oracle.custom_appearance.soft_part_1.image_path, 128).height(), 128)
            restored_part = OracleScene(loaded_profile.oracle).soft_parts.parts[0]
            self.assertEqual((restored_part.width, restored_part.length), (24., 128.))
            # 原有面部限制保持 32px，不因新增柔性贴图而放宽
            with self.assertRaises(ValueError):
                read_face_png(loaded.oracle.custom_appearance.soft_part_1.image_path)
            bad = replace(config, oracle=replace(config.oracle, custom_appearance=replace(
                config.oracle.custom_appearance, forehead=FaceDecal(enabled=True,
                    image_path=loaded.oracle.custom_appearance.soft_part_1.image_path))))
            with self.assertRaises(ValueError):
                looks.export(bad, 'Oversized face')

    def test_debug_png_import_validation_layers_and_missing_file(self):
        window = OracleDebugWindow(AppConfig(oracle=OracleConfig(body_appearance='custom')), load_atlas=False)
        window.timer.stop()
        try:
            window.open_soft_parts_debug()
            panel = window.soft_parts_panel
            with tempfile.TemporaryDirectory() as folder:
                source = Path(folder)/'scarf.png'
                image = QImage(12, 64, QImage.Format.Format_ARGB32_Premultiplied)
                image.fill(QColor('#ab7788'))
                image.save(str(source))
                self.assertTrue(panel.import_file('soft_part_1', source))
                value = window.scene.config.custom_appearance.soft_part_1
                self.assertNotEqual(value.image_path, str(source))
                self.assertEqual(value.kind, 'png')
                self.assertEqual(panel.controls['soft_part_1']['kind'].currentData(), 'png')
                self.assertFalse(panel.controls['soft_part_1']['color'].isEnabled())
                for key in ('width', 'length'):
                    self.assertTrue(panel.controls['soft_part_1'][key].isHidden())
                self.assertEqual((window.scene.soft_parts.parts[0].width, window.scene.soft_parts.parts[0].length), (12., 64.))
                image = QImage(129, 1, QImage.Format.Format_ARGB32_Premultiplied)
                image.fill(0)
                image.save(str(source))
                self.assertFalse(panel.import_file('soft_part_1', source))
                self.assertEqual(window.scene.config.custom_appearance.soft_part_1, value)
                panel.controls['soft_part_1']['layer'].setCurrentIndex(0)
                self.assertEqual(window.scene.config.custom_appearance.soft_part_1.layer, 'back')
                panel.clear_file('soft_part_1')
                base_tests.SoftPartsTests.render(OracleRenderer(), window.scene)
                self.assertEqual(window.scene.config.custom_appearance.soft_part_1.image_path, '')
        finally:
            window.close()
            window.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


if __name__ == '__main__':
    unittest.main()
