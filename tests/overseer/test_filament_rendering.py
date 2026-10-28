"""五节点触须的局部圆滑路径、配色与纯绘制边界"""
import math
import unittest

from PySide6.QtCore import QPointF
from PySide6.QtGui import QImage, QPainter

from rw_creature_pet.overseer.graphics.filaments import rounded_paths
from rw_creature_pet.overseer.graphics.render import OverseerRenderer
from rw_creature_pet.overseer.model import Point
from rw_creature_pet.shared.geometry import Vec2
from tests.overseer.test_filament_observation import make_model


class FilamentRenderingTests(unittest.TestCase):
    def test_curved_joins_keep_endpoints_and_continuous_tangents_inside_node_bounds(self):
        points = [Vec2(0, 0), Vec2(10, 0), Vec2(10, 10), Vec2(20, 10), Vec2(20, 20)]
        paths = rounded_paths(points)
        self.assertEqual(len(paths), 4)
        self.assertEqual(paths[0][2].pointAtPercent(0), QPointF(0, 0))
        self.assertEqual(paths[-1][2].currentPosition(), QPointF(20, 20))
        for start, end, path in paths:
            self.assertEqual(path.pointAtPercent(0), start)
            self.assertEqual(path.currentPosition(), end)
            for t in range(101):
                point = path.pointAtPercent(t/100)
                self.assertTrue(-1e-8 <= point.x() <= 20+1e-8 and -1e-8 <= point.y() <= 20+1e-8)
        for (_, end, previous), (start, _, following) in zip(paths, paths[1:]):
            self.assertEqual(end, start)
            a, b = previous.elementAt(previous.elementCount()-2), following.elementAt(1)
            incoming = Vec2(end.x()-a.x, end.y()-a.y)
            outgoing = Vec2(b.x-start.x(), b.y-start.y())
            self.assertLess((incoming-outgoing).length(), 1e-8)
        # 原折点的锐角顶点已让出，转换为局部圆弧，不把整根触须拉成新的大曲线
        self.assertNotEqual(paths[0][1], QPointF(10, 0))
        self.assertLess((paths[0][1]-QPointF(10, 0)).manhattanLength(), 2.)

    def test_straight_collapsed_and_short_segments_remain_finite_and_bounded(self):
        for points in ([Vec2(i*4, 2) for i in range(5)], [Vec2(3, 4)]*5,
                       [Vec2(), Vec2(), Vec2(1e-8, 0), Vec2(), Vec2(2, 3)]):
            paths = rounded_paths(points)
            self.assertEqual(len(paths), len(points)-1)
            for _, _, path in paths:
                for t in range(21):
                    p = path.pointAtPercent(t/20)
                    self.assertTrue(math.isfinite(p.x()) and math.isfinite(p.y()))
                    self.assertTrue(min(v.x for v in points)-1e-8 <= p.x() <= max(v.x for v in points)+1e-8)
                    self.assertTrue(min(v.y for v in points)-1e-8 <= p.y() <= max(v.y for v in points)+1e-8)
            self.assertEqual(paths[-1][2].currentPosition(), QPointF(points[-1].x, points[-1].y))

    def test_drawing_keeps_five_physics_nodes_blue_tips_and_pixel_edges_at_all_densities(self):
        for appearance in ('standard', 'friend'):
            model = make_model(appearance)
            points = [Vec2(10, 30), Vec2(20, 25), Vec2(25, 30), Vec2(30, 35), Vec2(40, 30)]
            model.filaments[0] = [Point.at(p) for p in points]
            before = [(p.position, p.previous, p.velocity) for p in model.filaments[0]]
            rng = model.random.getstate(), model.filament_motion.random.getstate()
            for scale in (1., 1.5, 2., 4.):
                image = QImage(round(64*scale), round(64*scale), QImage.Format.Format_ARGB32_Premultiplied)
                image.fill(0)
                painter = QPainter(image)
                painter.scale(scale, scale)
                try:
                    OverseerRenderer()._filaments(painter, model, 1., (0,), '#ffaa66')
                    self.assertFalse(painter.testRenderHint(QPainter.RenderHint.Antialiasing))
                finally:
                    painter.end()
                colors = [image.pixelColor(x, y) for y in range(image.height()) for x in range(image.width())]
                self.assertTrue(any(c.alpha() and c.blue() > 200 and c.red() < 30 for c in colors))
                # Qt 在 1x 下把 .85 像素细笔统一降透明度；接头叠加另有一档，但没有抗锯齿灰阶边
                self.assertLessEqual(len({c.alpha() for c in colors if c.alpha()}), 2)
                self.assertEqual(len(model.filaments[0]), 5)
                self.assertEqual(before, [(p.position, p.previous, p.velocity) for p in model.filaments[0]])
                self.assertEqual(rng, (model.random.getstate(), model.filament_motion.random.getstate()))


if __name__ == '__main__':
    unittest.main()
