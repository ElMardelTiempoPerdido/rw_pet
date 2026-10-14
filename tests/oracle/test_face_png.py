"""面部 PNG 的导入、配置升级、裁剪遮挡与绘制缓存"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

from rw_creature_pet.config import AppConfig
from rw_creature_pet.oracle.config import CustomAppearance
from rw_creature_pet.oracle.face_config import FaceDecal
from rw_creature_pet.oracle.graphics.face_assets import face_image, import_face_png
from rw_creature_pet.oracle.graphics.render import OracleRenderer
from rw_creature_pet.settings_store import SettingsStore, load_defaults
from rw_creature_pet.shared.geometry import Vec2


class FacePngTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        face_image.cache_clear()

    def png(self, name='标记.png', size=5, color='#ff0000'):
        image = QImage(size, size, QImage.Format.Format_ARGB32)
        image.fill(QColor(color))
        path = self.root/name
        self.assertTrue(image.save(str(path)))
        return path

    def paint(self, shape, *, gaze=Vec2(), openness=0., renderer=None, density=2., turn=False):
        renderer = renderer or OracleRenderer()
        image = QImage(128, 128, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(0)
        painter = QPainter(image)
        try:
            painter.translate(64, 64)
            painter.scale(4, 4)
            direction = Vec2(1, 0) if turn else Vec2(0, -1)
            renderer.draw_head(painter, Vec2(), direction*-10, direction, gaze, openness,
                               shape=shape, raster_scale=density, pixelated=True)
        finally:
            painter.end()
        return image

    def test_import_retains_padding_color_alpha_and_survives_source_removal(self):
        source = self.png(size=8, color='#00000000')
        image = QImage(str(source))
        image.setPixelColor(3, 2, QColor(80, 160, 240, 128))
        image.save(str(source))
        original = source.read_bytes()
        decal = import_face_png(source, self.root/'managed', FaceDecal(offset_x=1.23456))
        self.assertEqual(source.read_bytes(), original)
        self.assertEqual(decal.offset_x, 1.23456)
        self.assertTrue(decal.enabled)
        again = import_face_png(source, self.root/'managed', decal)
        self.assertEqual(again, decal)
        self.assertEqual(len(list((self.root/'managed').glob('*.png'))), 1)
        source.unlink()
        managed = face_image(decal.image_path)
        self.assertEqual(managed.size(), image.size())
        self.assertEqual(managed.pixelColor(0, 0).alpha(), 0)
        self.assertEqual(managed.pixelColor(3, 2).alpha(), 128)
        for actual, expected in zip(managed.pixelColor(3, 2).getRgb()[:3], (80, 160, 240)):
            self.assertLessEqual(abs(actual-expected), 1)

    def test_invalid_imports_never_create_managed_files(self):
        large = self.png('large.png', 33)
        corrupt = self.root/'corrupt.png'
        corrupt.write_bytes(b'not a PNG')
        wrong = self.root/'wrong.png'
        QImage(str(large)).save(str(wrong), 'JPEG')
        huge = self.root/'huge.png'
        huge.write_bytes(b'0'*(1024*1024+1))
        for path in (large, corrupt, wrong, huge, self.root/'missing.png'):
            with self.subTest(path=path.name), self.assertRaises((ValueError, OSError)):
                import_face_png(path, self.root/'managed', FaceDecal())
        self.assertFalse((self.root/'managed').exists())

    def test_nested_profiles_upgrade_and_relative_paths_resolve_from_their_file(self):
        template = self.root/'config.toml'
        template.write_text("[oracle.custom_appearance.forehead]\nimage_path='mark.png'\n", encoding='utf-8')
        defaults = load_defaults(template)
        self.assertEqual(AppConfig.load(template).oracle.custom_appearance, defaults.oracle.custom_appearance)
        self.assertEqual(defaults.oracle.custom_appearance.forehead.image_path, str(self.root/'mark.png'))
        self.assertEqual(defaults.oracle.custom_appearance.forehead.offset_y, -3.)
        store = SettingsStore(self.root/'user/settings.json')
        store.path.parent.mkdir()
        old = {'version': 1, 'config': {'oracle': {'body_appearance': 'custom',
               'custom_appearance': {'head_length': 1.25, 'face': {'offset_x': 2.125}}}}}
        store.path.write_text(json.dumps(old), encoding='utf-8')
        with patch('rw_creature_pet.settings_store.default_template_path', return_value=None):
            config, first, message = store.startup()
            self.assertEqual((first, message), (False, ''))
            shape = config.oracle.custom_appearance
            self.assertEqual(shape.head_length, 1.25)
            self.assertEqual(shape.face, FaceDecal(offset_x=2.125))
            self.assertEqual(shape.forehead, FaceDecal(offset_y=-3.))
            decal = replace(shape.face, image_path='local.png', image_name='原图.png', enabled=True)
            config = replace(config, oracle=replace(config.oracle, custom_appearance=replace(shape, face=decal)))
            store.save(config)
            loaded = store.load().oracle.custom_appearance.face
            self.assertEqual(loaded, replace(decal, image_path=str(store.path.parent/'local.png')))
            self.assertEqual(json.loads(store.path.with_suffix('.json.bak').read_text(encoding='utf-8'))
                             ['config']['oracle']['custom_appearance']['head_length'], 1.25)

    def test_decals_clip_to_skin_and_eyes_remain_above_them_at_all_views(self):
        path = self.png(size=32)
        shape = CustomAppearance(face=FaceDecal(True, str(path)))
        renderer = OracleRenderer()
        eyes = QColor(renderer.colors.eyes).rgba()
        for density in (1., 1.5, 2.):
            for gaze in (Vec2(), Vec2(.8, 0), Vec2(0, -.65), Vec2(0, .65)):
                for turn in (False, True):
                    with self.subTest(density=density, gaze=gaze, turn=turn):
                        base = self.paint(CustomAppearance(), gaze=gaze, openness=1., density=density, turn=turn)
                        actual = self.paint(shape, gaze=gaze, openness=1., density=density, turn=turn)
                        self.assertNotEqual(base, actual)
                        self.assertEqual(bytes(base.constBits())[3::4], bytes(actual.constBits())[3::4])
                        for y in range(actual.height()):
                            for x in range(actual.width()):
                                if base.pixel(x, y) == eyes:
                                    self.assertEqual(actual.pixel(x, y), eyes)
                                if actual.pixelColor(x, y) == QColor('#ff0000'):
                                    self.assertEqual(base.pixelColor(x, y), QColor(renderer.colors.skin))

    def test_layer_order_offsets_and_cached_bell_custom_switch(self):
        red, green = self.png('red.png'), self.png('green.png', color='#00ff00')
        renderer = OracleRenderer()
        shape = CustomAppearance(face=FaceDecal(True, str(green)), forehead=FaceDecal(True, str(red)))
        bell = self.paint(None, renderer=renderer)
        actual = self.paint(shape, renderer=renderer)
        self.assertEqual(actual.pixelColor(64, 64), QColor('#ff0000'))
        disabled = replace(shape, forehead=replace(shape.forehead, enabled=False))
        self.assertEqual(self.paint(disabled, renderer=renderer).pixelColor(64, 64), QColor('#00ff00'))
        shifted = replace(shape, forehead=replace(shape.forehead, offset_x=3.))
        self.assertNotEqual(self.paint(shifted, renderer=renderer), actual)
        self.assertEqual(self.paint(None, renderer=renderer), bell)
        with patch('rw_creature_pet.oracle.graphics.face_assets.read_face_png', side_effect=AssertionError('disk read')):
            for gaze in (Vec2(), Vec2(.3, -.2), Vec2(-.8, .3)):
                self.paint(shape, renderer=renderer, gaze=gaze)
        self.paint(shape, renderer=renderer)
        cached = renderer._head_image
        self.paint(shape, renderer=renderer)
        self.assertIs(renderer._head_image, cached)

    def test_missing_png_is_skipped_and_cached_in_runtime(self):
        decal = FaceDecal(True, str(self.root/'missing.png'))
        with self.assertLogs('rw_creature_pet.oracle.graphics.face_assets', level='WARNING') as logged:
            first = self.paint(CustomAppearance(face=decal))
            second = self.paint(CustomAppearance(face=decal))
        self.assertEqual(len(logged.records), 1)
        self.assertEqual(first, second)
        self.assertEqual(first, self.paint(CustomAppearance()))

    def test_near_front_pitch_does_not_shift_png_sampling_by_a_whole_row(self):
        from rw_creature_pet.oracle.graphics.face_decals import draw_face_decals

        source = QImage(32, 32, QImage.Format.Format_ARGB32_Premultiplied)
        for row in range(32):
            for col in range(32):
                source.setPixelColor(col, row, QColor(row*7, col*7, 180, 128))
        path = self.root/'gradient.png'
        source.save(str(path))
        shape = CustomAppearance(face=FaceDecal(True, str(path)))

        def flat(renderer, painter, shape, gx, gy):
            draw_face_decals(renderer, painter, shape, gx, 0.)

        for density in (1., 1.5, 2.):
            kwargs = dict(gaze=Vec2(0, -.000001), density=density)
            actual = self.paint(shape, **kwargs)
            # 眼睛和耳机保持同一视线，仅比较贴图是否因为切换采样方式而跳行
            with patch('rw_creature_pet.oracle.graphics.render.draw_face_decals', flat):
                self.assertEqual(actual, self.paint(shape, **kwargs))
