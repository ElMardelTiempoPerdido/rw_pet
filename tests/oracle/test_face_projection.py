"""抬头时面部曲面投影的连续性、透明度和留白一致性"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath
from PySide6.QtWidgets import QApplication

from rw_creature_pet.oracle.config import CustomAppearance
from rw_creature_pet.oracle.face_config import FaceDecal
from rw_creature_pet.oracle.graphics.face_assets import face_image
from rw_creature_pet.oracle.graphics.face_decals import UPWARD_EXTRA_LIFT, draw_face_decals, project_face_y
from rw_creature_pet.oracle.graphics.render import OracleRenderer


class FaceProjectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.renderer = OracleRenderer()

    def mask(self, shape, yaw):
        path = QPainterPath()
        path.addEllipse(self.renderer.head_rect(shape.head_length))
        path.addEllipse(QRectF(yaw*2-10/3, 1.8-10/3, 20/3, 20/3))
        path.setFillRule(Qt.FillRule.WindingFill)
        return path

    def paint(self, shape, *, pitch, yaw=0., density=2., angle=0., reference=False, dpr=1.):
        image = QImage(96, 96, QImage.Format.Format_ARGB32_Premultiplied)
        image.setDevicePixelRatio(dpr)
        image.fill(0)
        painter = QPainter(image)
        try:
            painter.translate(48/dpr, 48/dpr)
            painter.scale(density, density)
            painter.rotate(angle)
            if not reference:
                draw_face_decals(self.renderer, painter, shape, yaw, pitch)
            else:
                # 纯色整图经曲面变形后的包围矩形，用来检测逐行绘制的裂缝或重复叠色
                mask = self.mask(shape, yaw)
                painter.setClipPath(mask)
                bounds = mask.boundingRect()
                for decal in (shape.face, shape.forehead):
                    if not decal.enabled:
                        continue
                    source = face_image(decal.image_path)
                    scale_x = 1-abs(yaw)*.25
                    left = yaw*2.5+(decal.offset_x-source.width()/2)*scale_x
                    top, bottom = [project_face_y(decal.offset_y+sign*source.height()/2,
                                   pitch, bounds.top(), bounds.bottom()) for sign in (-1, 1)]
                    painter.drawImage(QRectF(left, top, source.width()*scale_x, bottom-top), source)
        finally:
            painter.end()
        return image

    def save_image(self, name, image):
        path = self.root/name
        self.assertTrue(image.save(str(path)))
        return str(path)

    def test_upper_face_compresses_more_and_projection_never_folds(self):
        for length in (.7, 1., 1.5):
            bounds = self.mask(CustomAppearance(head_length=length), 0.).boundingRect()
            top, bottom = bounds.top(), bounds.bottom()
            for pitch in (0., .000001, .3, .7, 1.):
                values = [project_face_y(row/4, pitch, top, bottom) for row in range(-192, 193)]
                self.assertTrue(all(a < b for a, b in zip(values, values[1:])))
                self.assertAlmostEqual(project_face_y(0., pitch, top, bottom),
                                       -pitch*1.5-UPWARD_EXTRA_LIFT*pitch*pitch)
            upper = project_face_y(top, 1., top, bottom)-project_face_y(top-1, 1., top, bottom)
            lower = project_face_y(bottom+1, 1., top, bottom)-project_face_y(bottom, 1., top, bottom)
            self.assertAlmostEqual(upper, .25)
            self.assertAlmostEqual(lower, .9)
            self.assertGreater(project_face_y(bottom, 1., top, bottom)
                               -project_face_y(top, 1., top, bottom), (bottom-top)*.5)

    def test_translucent_rows_have_no_gaps_or_double_alpha_after_rotation(self):
        source = QImage(32, 32, QImage.Format.Format_ARGB32_Premultiplied)
        source.fill(QColor(60, 180, 230, 128))
        path = self.save_image('solid.png', source)
        shape = CustomAppearance(face=FaceDecal(True, path))
        for density in (1., 1.5, 2.):
            for angle in (0., 22., 73., 155.):
                for pitch in (.000001, .3, .7, 1.):
                    with self.subTest(density=density, angle=angle, pitch=pitch):
                        kwargs = dict(pitch=pitch, yaw=.3, density=density, angle=angle)
                        self.assertEqual(self.paint(shape, **kwargs), self.paint(shape, reference=True, **kwargs))
        for dpr in (1.5, 2.):
            kwargs = dict(pitch=.7, yaw=.3, density=1.5, angle=22., dpr=dpr)
            self.assertEqual(self.paint(shape, **kwargs), self.paint(shape, reference=True, **kwargs))

    def test_transparent_padding_does_not_change_surface_projection(self):
        small = QImage(8, 10, QImage.Format.Format_ARGB32_Premultiplied)
        small.fill(0)
        for row in range(1, 9):
            for col in range(2, 7):
                small.setPixelColor(col, row, QColor(row*20, col*30, 180, 128))
        padded = QImage(32, 30, small.format())
        padded.fill(0)
        painter = QPainter(padded)
        painter.drawImage(6, 8, small)
        painter.end()
        path = self.save_image('small.png', small)
        large = self.save_image('padded.png', padded)
        for slot in ('face', 'forehead'):
            shape = replace(CustomAppearance(), **{slot: FaceDecal(True, path)})
            padded_shape = replace(shape, **{slot: FaceDecal(True, large, offset_x=6., offset_y=2.)})
            for density in (1., 1.5, 2.):
                for pitch in (-.8, 0., .000001, .7, 1.):
                    with self.subTest(slot=slot, density=density, pitch=pitch):
                        kwargs = dict(pitch=pitch, density=density, yaw=.5, angle=23.)
                        self.assertEqual(self.paint(shape, **kwargs), self.paint(padded_shape, **kwargs))

    def test_front_and_down_keep_the_original_uniform_projection(self):
        source = QImage(12, 12, QImage.Format.Format_ARGB32_Premultiplied)
        for row in range(12):
            for col in range(12):
                source.setPixelColor(col, row, QColor(row*20, col*20, 180, 128))
        path = self.save_image('pattern.png', source)
        shape = CustomAppearance(face=FaceDecal(True, path, offset_x=-.75, offset_y=1.25))
        for density in (1., 1.5, 2.):
            for pitch in (0., -.3, -1.):
                kwargs = dict(pitch=pitch, yaw=-.6, density=density, angle=31.)
                self.assertEqual(self.paint(shape, **kwargs), self.paint(shape, reference=True, **kwargs))
