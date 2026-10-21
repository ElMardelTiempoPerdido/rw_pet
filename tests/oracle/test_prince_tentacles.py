"""触手配置预览的独立亮芯、弧长定位、椭圆、像素密度和热重载"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from rw_creature_pet.oracle.prince_tentacles import Bump, Tentacle, load_study, make_path
from rw_creature_pet.oracle.graphics.prince_tentacles import draw_tentacles
from tools.oracle.review_prince_tentacles import (
    DEFAULT_CONFIG, Preview, PreviewWindow, render, save_png,
)


class PrinceTentacleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_authored_layout_is_repeatable_with_three_distinct_lengths(self):
        study = load_study(DEFAULT_CONFIG)
        paths = [make_path(t) for t in study.tentacles]
        self.assertEqual(len(paths), 3)
        self.assertGreater(paths[0].length, paths[1].length)
        self.assertGreater(paths[1].length, paths[2].length)
        self.assertEqual(paths, [make_path(t) for t in study.tentacles])
        for tentacle, path in zip(study.tentacles, paths):
            self.assertEqual(path.sample(0)[0], tentacle.points[0])
            self.assertLess((path.sample(1)[0]-tentacle.points[-1]).length(), 1e-8)

    def test_bumps_use_arc_length_and_local_normal(self):
        tentacle = Tentacle.parse({'points': [[0, 0], [1, 0], [20, 0]], 'smoothness': 0}, 0)
        path = make_path(tentacle)
        center, direction = path.attachment(Bump(.5, 3., 5., 8.))
        self.assertAlmostEqual(center.x, 10.)
        self.assertAlmostEqual(center.y, 3.)
        self.assertAlmostEqual(direction.x, 1.)
        self.assertAlmostEqual(direction.y, 0.)

    def test_separate_core_positions_and_global_core_layer(self):
        a = Tentacle.parse({
            'points': [[2, 12], [28, 12]],
            'colors': [[0, '#110022'], [1, '#110022']],
            'bumps': [{'s': .3, 'width': 8, 'height': 10}],
            'cores': [{'s': .7, 'width': 8, 'height': 4, 'color': '#FF0044'}],
        }, 0)
        b = Tentacle.parse({
            'points': [[20, 3], [20, 21]],
            'bumps': [{'s': .5, 'width': 10, 'height': 10, 'color': '#000000'}],
        }, 1)
        image = QImage(32, 26, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(0)
        painter = QPainter(image)
        draw_tentacles(painter, (a, b))
        painter.end()
        self.assertEqual(image.pixelColor(10, 12).name(), '#110022')
        self.assertEqual(image.pixelColor(20, 12).name(), '#ff0044')
        # 囊肿 width 横跨触手：水平触手上的宽椭圆应沿屏幕竖直方向延伸
        self.assertEqual(image.pixelColor(20, 15).name(), '#ff0044')
        rotated = replace(a, cores=(replace(a.cores[0], angle=90),))
        image.fill(0)
        painter = QPainter(image)
        draw_tentacles(painter, (rotated, b))
        painter.end()
        self.assertEqual(image.pixelColor(20, 15).name(), '#000000')

    def test_gradient_follows_length_through_a_bend(self):
        tentacle = Tentacle.parse({
            'points': [[4, 4], [24, 4], [24, 24]], 'smoothness': 0,
            'colors': [[0, '#000000'], [.5, '#FF0000'], [1, '#FFFFFF']],
        }, 0)
        image = QImage(30, 30, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(0)
        painter = QPainter(image)
        draw_tentacles(painter, (tentacle,))
        painter.end()
        middle = image.pixelColor(23, 4)
        self.assertGreater(middle.red(), 220)
        self.assertLess(middle.green(), 30)
        self.assertEqual(image.pixelColor(24, 24).name(), '#ffffff')
        # 相邻网格之间没有沿中心线的透明裂缝
        path = make_path(tentacle)
        for i in range(101):
            p, _ = path.sample(i/100)
            self.assertEqual(image.pixelColor(round(p.x), round(p.y)).alpha(), 255)

    def test_scale_modes_and_transparent_export(self):
        study = load_study(DEFAULT_CONFIG)
        preview = replace(Preview.parse(study.preview), show_prince=False, background='transparent')
        one = render(study, replace(preview, scale=1))
        two = render(study, replace(preview, scale=2))
        half = render(study, replace(preview, scale=1.5))
        self.assertEqual((half.width(), half.height()), (210, 315))
        self.assertEqual(half.pixelColor(0, 0).alpha(), 0)
        for scale, coarse, base in ((3, False, one), (4, True, one), (4, False, two)):
            result = render(study, replace(preview, scale=scale, coarse_pixels_4x=coarse))
            expected = base.scaled(result.size(), Qt.AspectRatioMode.IgnoreAspectRatio,
                                   Qt.TransformationMode.FastTransformation)
            self.assertEqual(result, expected)
            self.assertEqual(result.pixelColor(0, 0).alpha(), 0)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'中文路径'/'preview.png'
            save_png(two, path)
            self.assertEqual(QImage(str(path)).size(), two.size())

    def test_invalid_fields_and_ranges_are_reported(self):
        for data in (
            {'points': [[0, 0], [0, 0]]},
            {'points': [[0, 0], [20, 0]], 'widths': [[0, 3], [1, -1]]},
            {'points': [[0, 0], [20, 0]], 'colors': [[.1, '#000000'], [1, '#FFFFFF']]},
            {'points': [[0, 0], [20, 0]], 'cores': [{'s': 1.1}]},
            {'points': [[0, 0], [20, 0]], 'cores': [{'colour': '#FFFFFF'}]},
            {'points': [[0, 0], [20, 0]], 'enabled': 'false'},
        ):
            with self.subTest(data=data), self.assertRaises(ValueError):
                Tentacle.parse(data, 0)

    def test_watched_edits_recover_without_replacing_last_valid_picture(self):
        text = '''version = 1
[preview]
show_prince = false
background = "#7044FF"
[[tentacles]]
points = [[0, 0], [20, 0]]
'''
        with tempfile.TemporaryDirectory() as directory:
            config, output = Path(directory)/'触手.toml', Path(directory)/'preview.png'
            config.write_text(text, encoding='utf-8')
            window = PreviewWindow(config, output)
            try:
                window.show()
                self.app.processEvents()
                self.assertTrue(window.valid)
                original = window.image.copy()
                config.write_text('version = [', encoding='utf-8')
                QTest.qWait(550)
                self.assertFalse(window.valid)
                self.assertFalse(window.export_button.isEnabled())
                self.assertEqual(window.image, original)
                self.assertIn('配置未应用', window.status.text())
                config.write_text(text.replace('#7044FF', '#FF0000'), encoding='utf-8')
                QTest.qWait(550)
                self.assertTrue(window.valid)
                self.assertNotEqual(window.image, original)
                window.export()
                self.assertTrue(output.is_file())
            finally:
                window.timer.stop()
                window.close()


if __name__ == '__main__':
    unittest.main()
