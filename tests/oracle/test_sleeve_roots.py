"""宽袖折叠覆盖及抬臂腋下与衣袍的连续连接"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from math import radians, sin, cos
import unittest

from PySide6.QtGui import QImage, QPainter, QPainterPath, QPolygonF
from rw_creature_pet.oracle.config import CustomAppearance, OracleColors, OracleConfig
from rw_creature_pet.oracle.graphics.appearance import perpendicular, rotate
from rw_creature_pet.oracle.graphics.render import OracleRenderer, point
from rw_creature_pet.oracle.scene import OracleScene
from rw_creature_pet.shared.geometry import Vec2


def projection(v, axis):
    return v.x*axis.x+v.y*axis.y


def distance_to_segment(p, a, b):
    delta = b-a
    t = max(0., min(1., projection(p-a, delta)/max(projection(delta, delta), 1e-12)))
    return (p-a.lerp(b, t)).length()


class SleeveRootTests(unittest.TestCase):
    def test_folded_sleeves_cover_their_mesh_instead_of_cutting_a_hole(self):
        renderer = OracleRenderer(colors=OracleColors(robe_top='#ff0000', robe_bottom='#ff0000'))
        shape = CustomAppearance(sleeve_root_width=12., sleeve_cuff_width=12., sleeve_cuff_radius=0.)
        holes = 0
        for turn in (0, 35, 90, 180):
            up = rotate(Vec2(0, -1), radians(turn))
            for sign in (-1, 1):
                side = perpendicular(up)*sign
                edges = renderer.sleeve_edges(side*4, side*5-up*14, up, sign, shape)
                outline = QPainterPath()
                outline.addPolygon(QPolygonF([point(a) for a, _ in edges]
                                              + [point(b) for _, b in reversed(edges)]))
                outline.closeSubpath()
                coverage = renderer.sleeve_path(edges, shape)
                # 取真实网格三角形内部，折叠区同样属于不透明袖子
                for (a, b), (d, c) in zip(edges, edges[1:]):
                    for p, q, r in ((a, b, d), (b, d, c)):
                        for weights in ((.2, .3, .5), (.6, .2, .2), (.1, .8, .1)):
                            sample = point(p*weights[0]+q*weights[1]+r*weights[2])
                            self.assertTrue(coverage.contains(sample))
                            holes += not outline.contains(sample)
                # 在多倍率下，原孔洞中的像素不能透出下层的绿色围裙
                for scale in (1., 1.5, 2., 4.):
                    image = QImage(round(64*scale), round(64*scale), QImage.Format.Format_ARGB32)
                    image.fill(0xff00ff00)
                    painter = QPainter(image)
                    painter.scale(scale, scale)
                    painter.translate(32, 32)
                    renderer.draw_sleeve(painter, edges, shape)
                    painter.end()
                    for y in range(image.height()):
                        for x in range(image.width()):
                            p = point(Vec2((x+.5)/scale-32, (y+.5)/scale-32))
                            if coverage.contains(p) and not outline.contains(p):
                                self.assertEqual(image.pixel(x, y), 0xffff0000, (turn, sign, scale, x, y))
        self.assertGreater(holes, 0, '测试姿态确实覆盖旧路径的折叠空洞')

    def scene(self, shape, degrees=0):
        appearance = {'body_appearance': 'custom', 'custom_appearance': shape} if shape else {}
        scene = OracleScene(OracleConfig(**appearance, physics_backend='python', hide_cords=True))
        app, origin = scene.appearance, scene.appearance.upper
        for p, goal in zip(app.cloth, app.cloth_goals()):
            p.pin(goal)
        turn = radians(degrees)
        for node in [*scene.body.chunks, *app.body_points]:
            node.position = origin+rotate(node.position-origin, turn)
            node.previous_position = node.position
        app.direction = rotate(app.direction, turn)
        app.lower = origin+rotate(app.lower-origin, turn)
        return scene

    def test_raised_root_follows_cloth_edge_out_and_up_without_changing_the_cuff(self):
        renderer = OracleRenderer()
        shape = CustomAppearance(sleeve_root_width=12., sleeve_cuff_width=12.)
        for degrees in (0, 40, 90, 180, 270):
            scene = self.scene(shape, degrees)
            app, up, origin = scene.appearance, scene.appearance.direction, scene.appearance.upper
            for index, sign in enumerate((-1, 1)):
                side = perpendicular(up)*sign
                app.hands[index].pin(origin+side*16+up*2)
                shoulder = renderer.sleeve_shoulder(origin, up, sign, shape)
                raw = renderer.sleeve_edges(shoulder, app.hands[index].position, up, sign, shape)
                result = renderer.body_sleeve_edges(scene, 1., origin, up, index)
                change = result[1][0]-raw[1][0]
                self.assertGreater(projection(change, side), 1.)
                self.assertGreater(projection(change, up), 1.)
                self.assertEqual(result[-4:], raw[-4:])
                side_edge = [p.position for p in app.cloth[(0 if sign < 0 else app.CLOTH_DIVS-1)::app.CLOTH_DIVS]]
                for p in (result[0][0], result[1][0]):
                    distance = min(distance_to_segment(p, a, b) for a, b in zip(side_edge, side_edge[1:]))
                    self.assertLessEqual(distance, 1.01, (degrees, sign, p))
                # 跟随布料变化也必须刷新缓存，不能只按手的位置缓存
                cached = renderer.body_sleeve_edges(scene, 1., origin, up, index)
                self.assertIs(cached, result)
                for p in app.cloth[(0 if sign < 0 else app.CLOTH_DIVS-1)::app.CLOTH_DIVS]:
                    p.pin(p.position+side)
                moved = renderer.body_sleeve_edges(scene, 1., origin, up, index)
                self.assertAlmostEqual(projection(moved[1][0]-result[1][0], side), 1.)

    def test_relaxed_root_narrows_only_inside_and_keeps_outer_silhouette_and_cuff(self):
        renderer = OracleRenderer()
        shapes = [None, *(CustomAppearance(chest_width=width, chest_height=height,
                                           shoulder_width=shoulder, sleeve_root_width=sleeve)
                         for width, height, shoulder in ((8., 4., 18.), (12., 8., 8.), (18., 10., 4.))
                         for sleeve in (2., 6., 12.))]
        changes = 0
        for shape in shapes:
            for degrees in (0, 40, 90, 180):
                scene = self.scene(shape, degrees)
                app, up, origin = scene.appearance, scene.appearance.direction, scene.appearance.upper
                for index, sign in enumerate((-1, 1)):
                    side = perpendicular(up)*sign
                    hand = origin+side*5-up*14
                    app.hands[index].pin(hand)
                    root = renderer.sleeve_shoulder(origin, up, sign, shape)
                    raw = renderer.sleeve_edges(root, hand, up, sign, shape)
                    result = renderer.body_sleeve_edges(scene, 1., origin, up, index)
                    self.assertEqual([e[1] for e in result], [e[1] for e in raw])
                    self.assertEqual(result[-4:], raw[-4:])
                    for e, old in zip(result, raw):
                        delta = e[0]-old[0]
                        self.assertAlmostEqual(projection(delta, up), 0., delta=1e-10)
                        self.assertGreaterEqual(projection(delta, side), -1e-10)
                    old_path, path = renderer.sleeve_path(raw, shape), renderer.sleeve_path(result, shape)
                    self.assertTrue(path.subtracted(old_path).isEmpty(), (shape, degrees, sign))
                    if shape is None or shape.shoulder_width == 8.:
                        self.assertGreater(projection(result[1][0]-raw[1][0], side), 1.)
                        self.assertFalse(old_path.subtracted(path).isEmpty(), '内缘应实际收窄而非只移动隐藏点')
                        changes += 1
        self.assertGreater(changes, 0)

    def test_root_sweep_is_continuous_and_crossed_arms_keep_their_shape(self):
        renderer = OracleRenderer()
        for width, height, shoulder in ((8., 4., 18.), (12., 8., 8.), (18., 10., 4.)):
            shape = CustomAppearance(chest_width=width, chest_height=height, shoulder_width=shoulder,
                                     sleeve_root_width=12.)
            scene = self.scene(shape)
            app, up, origin = scene.appearance, scene.appearance.direction, scene.appearance.upper
            for index, sign in enumerate((-1, 1)):
                side = perpendicular(up)*sign
                root = renderer.sleeve_shoulder(origin, up, sign, shape)
                for across, rise in ((-1., -6.),):
                    hand = origin+side*across+up*rise
                    app.hands[index].pin(hand)
                    self.assertEqual(renderer.body_sleeve_edges(scene, 1., origin, up, index),
                                     renderer.sleeve_edges(root, hand, up, sign, shape))
                previous = None
                for step in range(481):
                    angle = radians(-75+step*.5)
                    hand = origin+side*(15*cos(angle))-up*(15*sin(angle))
                    app.hands[index].pin(hand)
                    result = renderer.body_sleeve_edges(scene, 1., origin, up, index)
                    if previous is not None:
                        self.assertLess(max((p-q).length() for e, old in zip(result, previous)
                                            for p, q in zip(e, old)), .6, (width, height, shoulder, step))
                    previous = result


if __name__ == '__main__':
    unittest.main()
