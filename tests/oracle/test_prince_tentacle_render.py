"""触手绘制降细分后的曲线、配置转折和缓存更新回归"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from dataclasses import replace
import unittest
from unittest.mock import patch

from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication

from rw_creature_pet.oracle.graphics import prince_tentacles as drawing
from rw_creature_pet.oracle.graphics.render import PaintCommands
from rw_creature_pet.oracle.prince_tentacles import Tentacle, TubePath
from rw_creature_pet.shared.geometry import Vec2


def polyline(*coords):
    points = tuple(Vec2(*p) for p in coords)
    distances = [0.]
    for a, b in zip(points, points[1:]):
        distances.append(distances[-1]+(b-a).length())
    return TubePath(points, tuple(distances))


class PrinceTentacleRenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def tentacle(self, **values):
        return Tentacle.parse({'points': [[10, 20], [351, 20]], **values}, 0)

    def render(self, tentacle, path):
        image = QImage(740, 100, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(0)
        painter = QPainter(image)
        try:
            painter.scale(2, 2)
            drawing.draw_tentacles(painter, (), paths=((tentacle, path),))
        finally:
            painter.end()
        return image

    def test_gentle_tube_uses_far_fewer_draw_commands(self):
        tentacle = self.tentacle()
        path = polyline((10, 20), (180, 20), (351, 20))
        commands = PaintCommands()
        drawing.draw_tentacles(commands, (), paths=((tentacle, path),))
        quads = sum(name == 'drawPolygon' for name, _ in commands.commands)
        self.assertLess(quads, 100)  # 原实现 682 片；不依赖机器速度的开销回归检查
        self.assertGreater(quads, 0)

    def test_narrow_color_and_width_features_are_not_skipped(self):
        tentacle = self.tentacle(widths=[[0, 2], [.48, 2], [.5, 8], [.52, 2], [1, 2]],
            colors=[[0, '#000000'], [.48, '#000000'], [.5, '#FF0000'],
                    [.52, '#000000'], [1, '#000000']])
        image = self.render(tentacle, polyline((10, 20), (210, 20)))
        self.assertGreater(image.pixelColor(220, 40).red(), 220)
        self.assertEqual(image.pixelColor(220, 46).alpha(), 255)
        self.assertEqual(image.pixelColor(190, 46).alpha(), 0)

    def test_folded_and_s_bent_centerlines_remain_filled(self):
        tentacle = self.tentacle(widths=[[0, 2], [1, 2]])
        for path in (polyline((10, 20), (60, 20), (60, 38), (12, 38)),
                     polyline((10, 20), (15, 22), (20, 20), (25, 18), (30, 20), (60, 20))):
            with self.subTest(path=path):
                image = self.render(tentacle, path)
                for i in range(301):
                    p, _ = path.sample(i/300)
                    self.assertEqual(image.pixelColor(round(p.x*2), round(p.y*2)).alpha(), 255)

    def test_small_motion_reuses_profile_and_config_edits_refresh_it(self):
        tentacle = self.tentacle(widths=[[0, 2], [1, 2]],
                                colors=[[0, '#220044'], [1, '#220044']])
        self.render(tentacle, polyline((10, 20), (351, 20)))
        # 长度由 341 变为 342，几何更新但静态颜色和宽度无需重新插值
        with patch.object(drawing, 'stop_interval', side_effect=AssertionError('unexpected resampling')):
            image = self.render(tentacle, polyline((10, 21), (352, 21)))
        self.assertEqual(image.pixelColor(100, 42).name(), '#220044')
        changed = replace(tentacle, widths=((0., 8.), (1., 8.)),
                          colors=((0., '#00FF00'), (1., '#00FF00')))
        image = self.render(changed, polyline((10, 20), (351, 20)))
        self.assertEqual(image.pixelColor(100, 46).name(), '#00ff00')


if __name__ == '__main__':
    unittest.main()
