"""通用肩线、袖根搭接和手部参考点在不同尺寸、姿态下保持一致"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from dataclasses import replace
from math import cos, radians, isfinite
import unittest
from unittest.mock import patch

from PySide6.QtGui import QColor, QImage, QPainter

from rw_creature_pet.oracle.config import CustomAppearance, OracleConfig
from rw_creature_pet.oracle.graphics.appearance import perpendicular, rotate
from rw_creature_pet.oracle.graphics import shoulders
from rw_creature_pet.oracle.graphics.render import OracleRenderer, point
from rw_creature_pet.oracle.scene import OracleScene
from rw_creature_pet.shared.geometry import Vec2


class CustomShoulderTests(unittest.TestCase):
    def test_width_opens_upper_shoulder_and_keeps_lower_root_and_cuff(self):
        renderer = OracleRenderer()
        up, origin = Vec2(0, -1), Vec2()
        original_profile = shoulders._upper_shoulder

        def chest_height_profile(*args):
            a, b, _ = original_profile(*args)
            return a, b, 0.

        upper_widths, lifts = [], []
        for width in (6., 8., 10., 12., 16., 18.):
            shape = CustomAppearance(chest_width=14., chest_height=6.5, shoulder_width=width,
                                     sleeve_root_width=12., sleeve_cuff_width=8.5)
            shoulder = renderer.sleeve_shoulder(origin, up, 1, shape)
            end = Vec2(5.26685, 14.04494)
            edges = renderer.sleeve_edges(shoulder, end, up, 1, shape)
            with patch.object(shoulders, '_upper_shoulder', side_effect=chest_height_profile):
                before = renderer.sleeve_edges(shoulder, end, up, 1, shape)
            self.assertEqual([e[0] for e in edges], [e[0] for e in before])
            self.assertEqual(edges[0], before[0])
            self.assertEqual(edges[-4:], before[-4:])
            # 在胸部中心上方五像素测量可见横向轮廓，而非只比较控制点
            path = renderer.sleeve_path(edges, shape).united(renderer.torso_path(origin, Vec2(0, 9), up, shape=shape))
            old_path = renderer.sleeve_path(before, shape).united(renderer.torso_path(origin, Vec2(0, 9), up, shape=shape))
            def cross_section(outline):
                return max(x/20 for x in range(401) if outline.contains(point(Vec2(x/20, -5))))
            upper_widths.append(cross_section(path))
            if width <= 8.:
                self.assertEqual(edges, before, '较窄时保留圆滑肩线，不直接变成平肩')
            elif width >= 12.:
                self.assertGreater(cross_section(path), cross_section(old_path))
            lifts.append(max(b[1].y-e[1].y for b, e in zip(before, edges)))
            # 举过头顶时完全回到原有抬臂轮廓
            raised = Vec2(15, -15)
            arm = renderer.sleeve_edges(shoulder, raised, up, 1, shape)
            with patch.object(shoulders, '_upper_shoulder', side_effect=chest_height_profile):
                self.assertEqual(renderer.sleeve_edges(shoulder, raised, up, 1, shape), arm)
        self.assertEqual(upper_widths, sorted(upper_widths))
        self.assertEqual(lifts[:2], [0., 0.])
        self.assertEqual(lifts[1:], sorted(set(lifts[1:])), '方肩提升量随肩宽逐渐增强')
        self.assertLess(lifts[2], lifts[-1]*.25, '较低肩宽不能已经接近完整方肩')

    def test_shoulder_width_spreads_sleeves_without_resizing_torso_or_teleporting_hands(self):
        scene = OracleScene(OracleConfig(body_appearance='custom', hide_cords=True, physics_backend='python'))
        app, renderer = scene.appearance, OracleRenderer()
        original = scene.config.custom_appearance
        cloth = app.cloth_goals()
        hands = tuple(hand.position for hand in app.hands)
        torso = renderer.torso_path(app.upper, app.lower, app.direction, shape=original)
        previous_edges = None
        widths = []
        for width in (4., 8., 12., 18.):
            shape = replace(original, shoulder_width=width)
            scene.config = replace(scene.config, custom_appearance=shape)
            app.sleeping = True
            app.sync_shape(scene)
            self.assertFalse(app.sleeping)
            self.assertEqual(app.cloth_goals(), cloth)
            self.assertEqual(tuple(hand.position for hand in app.hands), hands)
            self.assertEqual(renderer.torso_path(app.upper, app.lower, app.direction, shape=shape), torso)
            roots = [hand.shoulder(app.upper, app.direction, i) for i, hand in enumerate(app.hands)]
            self.assertAlmostEqual((roots[0]-roots[1]).length(), width)
            for i in range(2):
                self.assertEqual(roots[i], renderer.sleeve_shoulder(app.upper, app.direction, 2*i-1, shape))
            edges = renderer.body_sleeve_edges(scene, 1., app.upper, app.direction, 1)
            self.assertIsNot(edges, previous_edges)
            previous_edges = edges
            up = Vec2(0, -1)
            edges = renderer.sleeve_edges(renderer.sleeve_shoulder(Vec2(), up, 1, shape),
                                          Vec2(5.26685, 14.04494), up, 1, shape)
            widths.append(renderer.sleeve_path(edges, shape).boundingRect().right())
        self.assertEqual(widths, sorted(set(widths)), '增加肩宽必须实际展开袖子外轮廓')

    def test_custom_removes_bell_offsets_and_keeps_the_original_torso_lower_edge(self):
        renderer = OracleRenderer()
        up, origin = Vec2(0, -1), Vec2()
        shape = CustomAppearance()
        bell = renderer.torso_path(origin, Vec2(0, 9), up)
        custom = renderer.torso_path(origin, Vec2(0, 9), up, shape=shape)
        self.assertEqual(bell.boundingRect().top(), -7.)
        self.assertEqual(custom.boundingRect().top(), -8.)
        self.assertEqual(bell.boundingRect().bottom(), custom.boundingRect().bottom())
        for sign in (-1, 1):
            self.assertEqual(renderer.sleeve_shoulder(origin, up, sign), Vec2(sign*4., -2.))
            self.assertEqual(renderer.sleeve_shoulder(origin, up, sign, shape), Vec2(sign*4., 0.))

    def test_root_keeps_overlap_across_widths_poses_and_bent_torsos_without_moving_cuff(self):
        renderer = OracleRenderer()
        changed = 0
        for width in (2., 4., 8., 10., 12.):
            shape = CustomAppearance(sleeve_root_width=width, sleeve_cuff_width=16.)
            for degrees in (0, 37, 90, 180, 270):
                direction = rotate(Vec2(0, -1), radians(degrees))
                for waist_angle in (-.35, 0., .35):
                    waist = rotate(direction, waist_angle)
                    upper = Vec2(901.13, 237.96)
                    torso = renderer.torso_path(upper, upper-waist*9, direction, waist, shape=shape)
                    for sign in (-1, 1):
                        outward = perpendicular(direction)*sign
                        shoulder = renderer.sleeve_shoulder(upper, direction, sign, shape)
                        for across, rise in ((5., -14.), (15., 3.), (1., 15.)):
                            end = upper+outward*across+direction*rise
                            edges = renderer.sleeve_edges(shoulder, end, direction, sign, shape, torso=torso)
                            with patch('rw_creature_pet.oracle.graphics.render.attach_sleeve_root',
                                       side_effect=lambda edges, *args: edges):
                                original = renderer.sleeve_edges(shoulder, end, direction, sign, shape, torso=torso)
                            self.assertEqual(edges[-4:], original[-4:], '肩部修形不能改变袖口与手腕遮挡')
                            self.assertAlmostEqual((edges[0][0]-edges[0][1]).length(), width)
                            self.assertAlmostEqual((edges[-1][0]-edges[-1][1]).length(), 16.)
                            for t in (0., .25, .5, .75, 1.):
                                p = edges[0][0].lerp(edges[0][1], t)+outward*.99
                                self.assertTrue(torso.contains(point(p)), (width, degrees, waist_angle, sign, t))
                            changed += edges[0] != original[0]
        self.assertGreater(changed, 0, '最宽的袖根确实需要额外搭接')

    def test_chest_dimensions_and_shoulder_tangent_across_custom_proportions(self):
        renderer = OracleRenderer()
        up, origin = Vec2(0, -1), Vec2()
        for width in (8., 12., 18.):
            for height in (4., 6., 8., 10.):
                for sleeve in (2., 8., 12.):
                    shape = CustomAppearance(chest_width=width, chest_height=height,
                                             sleeve_root_width=sleeve, sleeve_cuff_width=8.5)
                    torso = renderer.torso_path(origin, Vec2(0, 9), up, shape=shape)
                    self.assertEqual(torso.boundingRect().top(), -height)
                    self.assertEqual(torso.boundingRect().bottom(), 13.)
                    self.assertTrue(torso.contains(point(Vec2(width*.5-.01, 0))))
                    self.assertFalse(torso.contains(point(Vec2(width*.5+.01, 0))))
                    edges = renderer.sleeve_edges(renderer.sleeve_shoulder(origin, up, 1, shape),
                                                   Vec2(5.26685, 14.04494), up, 1, shape)
                    start = edges[1][1]
                    # 独立用椭圆方程验证交接点和切向，不重用修形函数的控制点
                    self.assertAlmostEqual((start.x/(width*.5))**2+(start.y/height)**2, 1., delta=.001)
                    tangent = Vec2(-width*width*.25*start.y, height*height*start.x)
                    segment = edges[2][1]-start
                    agreement = (segment.x*tangent.x+segment.y*tangent.y)/(segment.length()*tangent.length())
                    self.assertGreater(agreement, cos(radians(12)), (width, height, sleeve))
                    for t in (0., .25, .5, .75, 1.):
                        self.assertTrue(torso.contains(point(edges[0][0].lerp(edges[0][1], t)+Vec2(.99, 0))))

    def test_arm_sweep_keeps_shoulder_continuous_and_cuff_unchanged(self):
        renderer = OracleRenderer()
        from math import sin
        for width, height, shoulder_width in ((8., 4., 8.), (12., 8., 8.), (18., 10., 8.),
                                              (8., 4., 18.), (18., 10., 4.)):
            for sleeve in (2., 8., 12.):
                shape = CustomAppearance(chest_width=width, chest_height=height, sleeve_root_width=sleeve,
                                         shoulder_width=shoulder_width)
                # 加高的肩线在收臂时需要回收更多距离，用细角度检查连续性与跳变
                step, limit = .1, .12
                torso = renderer.torso_path(Vec2(), Vec2(0, 9), Vec2(0, -1), shape=shape)
                previous = None
                for tick in range(round(240/step)+1):
                    angle = -75+tick*step
                    end = Vec2(15*cos(radians(angle)), 15*sin(radians(angle)))
                    shoulder = renderer.sleeve_shoulder(Vec2(), Vec2(0, -1), 1, shape)
                    edges = renderer.sleeve_edges(shoulder, end, Vec2(0, -1), 1, shape)
                    with patch('rw_creature_pet.oracle.graphics.render.attach_sleeve_root',
                               side_effect=lambda edges, *args: edges):
                        original = renderer.sleeve_edges(shoulder, end, Vec2(0, -1), 1, shape)
                    self.assertEqual(edges[-4:], original[-4:])
                    self.assertTrue(all(isfinite(p.x) and isfinite(p.y) for edge in edges for p in edge))
                    for t in (0., .5, 1.):
                        # 裁短的截面跨过胸腰曲线时，中部覆盖略少于端点的一像素
                        self.assertTrue(torso.contains(point(edges[0][0].lerp(edges[0][1], t)+Vec2(.5, 0))),
                                        (width, height, shoulder_width, sleeve, angle, t))
                    if previous is not None:
                        self.assertEqual(len(edges), len(previous), (width, height, sleeve, angle))
                        self.assertLess(max((a-b).length() for e, old in zip(edges, previous)
                                            for a, b in zip(e, old)), limit,
                                        (width, height, shoulder_width, sleeve, angle))
                    previous = edges

    def test_cloth_shoulders_follow_chest_but_center_collar_and_hem_remain_independent(self):
        scene = OracleScene(OracleConfig(body_appearance='custom', hide_cords=True, physics_backend='python'))
        app = scene.appearance
        before = app.cloth_goals()
        body = tuple(c.position for c in scene.body.chunks)
        head, hands = app.head.position, tuple(p.position for p in app.hands)
        n = app.CLOTH_DIVS
        for width, height in ((8., 4.), (12., 6.), (18., 10.)):
            scene.config = replace(scene.config, custom_appearance=CustomAppearance(chest_width=width, chest_height=height))
            app.sync_shape(scene)
            goals = app.cloth_goals()
            self.assertEqual(goals[n//2], before[n//2])
            self.assertEqual(goals[5*n:], before[5*n:])
            self.assertAlmostEqual((goals[0]-goals[n-1]).length(), 10*width/12)
            self.assertNotEqual(goals[0], before[0])
            for i, neighbors in enumerate(app._cloth_neighbors):
                for j, rest in neighbors:
                    self.assertAlmostEqual((goals[i]-goals[j]).length(), rest)
            self.assertEqual(tuple(c.position for c in scene.body.chunks), body)
            self.assertEqual(app.head.position, head)
            self.assertEqual(tuple(p.position for p in app.hands), hands)
            for i, hand in enumerate(app.hands):
                self.assertEqual(hand.shoulder(app.upper, app.direction, i),
                                 OracleRenderer().sleeve_shoulder(app.upper, app.direction, 2*i-1,
                                                                 scene.config.active_custom_appearance))
        scene.config = replace(scene.config, body_appearance='bell')
        app.sync_shape(scene)
        self.assertEqual(app.cloth_goals(), before)

    def test_shared_sleeve_geometry_refreshes_for_pose_and_dimensions(self):
        scene = OracleScene(OracleConfig(body_appearance='custom', hide_cords=True, physics_backend='python'))
        renderer = OracleRenderer()
        app = scene.appearance
        first = renderer.body_sleeve_edges(scene, 1., app.upper, app.direction, 0)
        self.assertIs(renderer.body_sleeve_edges(scene, 1., app.upper, app.direction, 0), first)
        scene.config = replace(scene.config, custom_appearance=CustomAppearance(chest_width=16., chest_height=6.))
        second = renderer.body_sleeve_edges(scene, 1., app.upper, app.direction, 0)
        self.assertIsNot(second, first)
        app.hands[0].position += Vec2(1, 0)
        self.assertIsNot(renderer.body_sleeve_edges(scene, 1., app.upper, app.direction, 0), second)

    def test_extreme_chests_move_and_settle(self):
        for width, height, shoulder_width in ((8., 4., 18.), (18., 10., 4.)):
            scene = OracleScene(OracleConfig(body_appearance='custom', hide_cords=True, physics_backend='python',
                                            custom_appearance=CustomAppearance(chest_width=width, chest_height=height,
                                                                               shoulder_width=shoulder_width)))
            scene.set_autonomous(False)
            scene.set_target(scene.body.chunks[0].position+Vec2(55, 0))
            for tick in range(2400):
                if tick == 80:
                    scene.stop()
                scene.step()
            self.assertTrue(scene.appearance.sleeping, (width, height))
            self.assertTrue(all(isfinite(p.position.x) and isfinite(p.position.y) for p in scene.appearance.cloth))

    def test_front_shoulder_outline_does_not_dip_between_torso_and_sleeve(self):
        renderer = OracleRenderer()
        origin, up = Vec2(), Vec2(0, -1)
        for width in (2., 8., 12.):
            shape = CustomAppearance(sleeve_root_width=width, sleeve_cuff_width=8.5)
            for density in (1., 1.5, 2.):
                for phase in (0., .25, .5):
                    image = QImage(96, 96, QImage.Format.Format_ARGB32_Premultiplied)
                    image.fill(0)
                    painter = QPainter(image)
                    try:
                        painter.translate(48+phase, 48+phase)
                        painter.scale(density, density)
                        painter.fillPath(renderer.torso_path(origin, Vec2(0, 9), up, shape=shape), QColor('white'))
                        for sign in (-1, 1):
                            shoulder = renderer.sleeve_shoulder(origin, up, sign, shape)
                            edges = renderer.sleeve_edges(shoulder, Vec2(sign*5.26685, 14.04494), up, sign, shape)
                            painter.fillPath(renderer.sleeve_path(edges, shape), QColor('white'))
                    finally:
                        painter.end()
                    for sign in (-1, 1):
                        heights = []
                        for distance in range(round(4*density)+1):
                            x = 48+sign*distance
                            heights.append(next(y for y in range(96) if image.pixelColor(x, y).alpha()))
                        self.assertEqual(heights, sorted(heights), (width, density, phase, sign))

    def test_simulation_shoulders_follow_style_and_switch_without_teleporting_hands(self):
        renderer = OracleRenderer()
        for initial in ('bell', 'custom'):
            scene = OracleScene(OracleConfig(body_appearance=initial, hide_cords=True, physics_backend='python'))
            app = scene.appearance
            for style in (initial, 'custom', 'bell'):
                before = tuple(hand.position for hand in app.hands)
                scene.config = replace(scene.config, body_appearance=style)
                app.sleeping = True
                changed = app.hands[0].shoulder_rise != (0. if style == 'custom' else 2.)
                app.sync_shape(scene)
                self.assertEqual(tuple(hand.position for hand in app.hands), before)
                if changed:
                    self.assertFalse(app.sleeping)
                for i, hand in enumerate(app.hands):
                    actual = hand.shoulder(app.upper, app.direction, i)
                    expected = renderer.sleeve_shoulder(app.upper, app.direction, 2*i-1,
                                                        scene.config.active_custom_appearance)
                    self.assertEqual(actual, expected)
