"""领口尺寸、间隔、布料跟随及 Bell 隔离"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from dataclasses import replace
from math import cos, sin, radians, floor
import unittest
from unittest.mock import patch

from PySide6.QtCore import QPointF
from PySide6.QtGui import QColor, QImage, QPainter

from rw_creature_pet.oracle.config import CustomAppearance, OracleColors, OracleConfig
from rw_creature_pet.oracle.graphics.appearance import OracleAppearance, rotate
from rw_creature_pet.oracle.graphics.neckline import neckline_paths, reference_paths, sleeve_neckline_path, _bound_paths
from rw_creature_pet.oracle.graphics.render import OracleRenderer, point
from rw_creature_pet.oracle.scene import OracleScene
from rw_creature_pet.shared.geometry import Vec2


class NecklineTests(unittest.TestCase):
    def test_deformed_overlapping_neckline_cutouts_do_not_leave_sleeve_pixels_on_skin(self):
        # moondown 的宽弧领口与露肩裁剪重叠；记录轻微衣料形变后的前两行
        # 对合并路径做一次 subtracted，Qt 会把本应移除的区域重新留在袖子上
        top = ((-4.1425974390986084, -4.74550518277556), (-3.3699033575942394, -4.171142859616452),
               (-2.540862531592211, -3.8045906382253634), (-1.6764801219972014, -3.5369955376904727),
               (-.7350515435473426, -3.427226749410579), (.025867052250305278, -3.2919520207809683),
               (.7881436760783345, -3.2411336372700816), (1.557089172617907, -3.5282982788831987),
               (2.5658851930893434, -3.925540200702926), (3.3954514056677, -4.204618768564615),
               (4.274460624964831, -4.802521351262158), (-4.893961169188515, -1.5308342500674144),
               (-3.9153131197913353, -1.2786825662714136), (-2.857277979493574, -1.178143624995414),
               (-1.9001350564512904, -1.0654778921909838), (-.9792095989282643, -1.174447597037556),
               (.11042510884976764, -.930813215959688), (.9187791635877147, -.9527076020677896),
               (1.8490931182989243, -1.1301024536340947), (2.957199171937418, -1.2332300301286523),
               (3.8037832551224255, -1.424944902769198), (4.911837785187117, -1.4582242028665178))
        shape = CustomAppearance(chest_width=10., chest_height=7.5, shoulder_width=6.,
                                 sleeve_root_width=8., sleeve_cuff_width=9.5, sleeve_cuff_radius=1.5,
                                 neckline_shape='arc', neckline_width=13., neckline_height=5.5,
                                 neckline_depth=3., neckline_roundness=.55, neckline_trim_enabled=False,
                                 inner_robe_enabled=False, robe_length=1.0182889391108962)
        colors = OracleColors(skin='#00ff00', robe_top='#ff0000', robe_bottom='#ff0000')
        origin = Vec2(1838., 610.36)
        for angle in (0., 35., 145.):
            up = rotate(Vec2(0, -1), radians(angle))
            scene = OracleScene(OracleConfig(body_appearance='custom', custom_appearance=shape,
                                             hide_cords=True, physics_backend='python'))
            for part, pos in zip((*scene.body.chunks, scene.head), (origin, origin-up*9, origin+up*14)):
                part.position = part.previous_position = pos
            scene.appearance = OracleAppearance(scene)
            app = scene.appearance
            for node, (x, y) in zip(app.cloth, top):
                node.pin(origin+rotate(Vec2(x, y), radians(angle)))
            cloth = [p.position for p in app.cloth]
            opening, _ = neckline_paths(cloth, app._cloth_local, app.CLOTH_DIVS, shape)
            cutouts = sleeve_neckline_path(cloth, app._cloth_local, app.CLOTH_DIVS, shape, opening)
            renderer = OracleRenderer(colors=colors)
            for density in (1., 1.5, 2., 4.):
                for cached in (False, True):
                    with self.subTest(angle=angle, density=density, cached=cached):
                        image = QImage(round(80*density), round(80*density), QImage.Format.Format_ARGB32_Premultiplied)
                        image.fill(0)
                        painter = QPainter(image)
                        painter.scale(density, density)
                        painter.translate(40-floor(origin.x), 40-floor(origin.y))
                        renderer.draw_geometry(painter, scene, include_head=False, arm=False, cords=False,
                                               pearl=False, halo=False, include_front_outfit=False,
                                               cache_body=cached, raster_scale=density)
                        painter.end()
                        # 两肩内三个曾露出袖色的采样点，旋转与缩放后仍在开口内部
                        for local in (Vec2(-3.5, -4.86), Vec2(-2.5, -3.86), Vec2(3.5, -4.86)):
                            q = origin+rotate(local, radians(angle))
                            x = floor((q.x-floor(origin.x)+40)*density)
                            y = floor((q.y-floor(origin.y)+40)*density)
                            actual = Vec2((x+.5)/density+floor(origin.x)-40,
                                          (y+.5)/density+floor(origin.y)-40)
                            self.assertTrue(cutouts.contains(point(actual)))
                            self.assertEqual(image.pixelColor(x, y), QColor(colors.skin))

    def test_high_neckline_cuts_sleeve_caps_above_the_gown_edge(self):
        colors = OracleColors(skin='#f8c7d7', inner_robe='#a48fd4', robe_top='#2a1f19', robe_bottom='#ff7045')
        shape = CustomAppearance(chest_width=11., chest_height=7.5, shoulder_width=11.,
                                 sleeve_root_width=12., sleeve_cuff_width=8.5,
                                 neckline_shape='arc', neckline_width=10., neckline_height=8.,
                                 neckline_depth=0., neckline_trim_enabled=False, inner_collar_enabled=False)
        origin = Vec2(400, 300)
        for angle in (0., 145.):
            up = rotate(Vec2(0, -1), radians(angle))
            for inner in (False, True):
                config = OracleConfig(body_appearance='custom', custom_appearance=replace(shape, inner_robe_enabled=inner),
                                      hide_cords=True, physics_backend='python')
                scene = OracleScene(config)
                for part, pos in zip((*scene.body.chunks, scene.head), (origin, origin-up*9, origin+up*14)):
                    part.position = part.previous_position = pos
                scene.appearance = OracleAppearance(scene)
                app = scene.appearance
                cloth = [p.position for p in app.cloth]
                opening, _ = neckline_paths(cloth, app._cloth_local, app.CLOTH_DIVS, shape)
                sleeve_opening = sleeve_neckline_path(cloth, app._cloth_local, app.CLOTH_DIVS, shape, opening)
                renderer = OracleRenderer(colors=colors)

                def paint(original=False):
                    image = QImage(192, 192, QImage.Format.Format_ARGB32_Premultiplied)
                    image.fill(0)
                    painter = QPainter(image)
                    try:
                        painter.translate(96, 96)
                        painter.scale(4, 4)
                        painter.translate(-origin.x, -origin.y)
                        with patch('rw_creature_pet.oracle.graphics.render.sleeve_neckline_path',
                                   return_value=opening if original else sleeve_opening):
                            renderer.draw_geometry(painter, scene, include_head=False, arm=False, cords=False,
                                                   pearl=False, halo=False, include_front_outfit=False,
                                                   cache_body=False, raster_scale=2.)
                    finally:
                        painter.end()
                    return image

                before, after = paint(True), paint()
                expected = QColor(colors.inner_robe if inner else colors.skin)
                for sign in (-1, 1):
                    with self.subTest(angle=angle, inner=inner, side=sign):
                        # 高领口本身在肩部以上，这里是图中仍被袖色覆盖的小三角
                        p = origin+rotate(Vec2(sign*3., -6.), radians(angle))
                        self.assertFalse(opening.contains(point(p)))
                        x, y = round(96+4*(p.x-origin.x)), round(96+4*(p.y-origin.y))
                        self.assertNotEqual(before.pixelColor(x, y), expected)
                        self.assertEqual(after.pixelColor(x, y), expected)
                # 只替换已有衣料的颜色，不向外扩大人偶轮廓
                for y in range(192):
                    for x in range(192):
                        self.assertEqual(before.pixelColor(x, y).alpha(), after.pixelColor(x, y).alpha())

    def test_wide_opening_exposes_skin_or_inner_robe_over_both_sleeve_roots(self):
        colors = OracleColors(skin='#20b870', inner_robe='#b580e0', robe_top='#e15030', robe_bottom='#e15030')
        origin = Vec2(878.13, 237.96)
        renderer = OracleRenderer(colors=colors)

        def paint(scene, density, cached):
            image = QImage(96, 96, QImage.Format.Format_ARGB32_Premultiplied)
            image.fill(0)
            painter = QPainter(image)
            try:
                painter.translate(48, 48)
                painter.scale(density, density)
                painter.translate(-origin.x, -origin.y)
                renderer.draw_geometry(painter, scene, include_head=False, arm=False, cords=False,
                                       pearl=False, halo=False, include_front_outfit=False,
                                       cache_body=cached, raster_scale=density)
            finally:
                painter.end()
            return image

        for angle in (0., 35., 145.):
            shape = CustomAppearance(chest_width=11., chest_height=7.5, shoulder_width=11.,
                                     sleeve_root_width=12., sleeve_cuff_width=8.5,
                                     neckline_shape='arc', neckline_width=18., neckline_height=3.,
                                     neckline_depth=4., neckline_roundness=1., neckline_trim_enabled=False,
                                     inner_collar_enabled=False)
            scene = OracleScene(OracleConfig(body_appearance='custom', custom_appearance=shape,
                                             hide_cords=True, physics_backend='python'))
            up = rotate(Vec2(0, -1), radians(angle))
            for part, pos in zip((*scene.body.chunks, scene.head),
                                 (origin, origin-up*9, origin+up*14)):
                part.position = part.previous_position = pos
            scene.appearance = OracleAppearance(scene)
            app = scene.appearance
            opening, _ = neckline_paths([p.position for p in app.cloth], app._cloth_local, app.CLOTH_DIVS, shape)
            torso = renderer.torso_path(origin, origin-up*9, up, shape=shape)
            sleeves = [renderer.sleeve_path(renderer.body_sleeve_edges(scene, 1., origin, up, i), shape)
                       for i in range(2)]
            # 重用同一个渲染器切换内搭，检查静态身体缓存也会更新
            for inner in (False, True):
                scene.config = replace(scene.config, custom_appearance=replace(shape, inner_robe_enabled=inner))
                expected = QColor(colors.inner_robe if inner else colors.skin)
                for density in (1., 1.5, 2.):
                    with self.subTest(angle=angle, inner=inner, density=density):
                        image = paint(scene, density, True)
                        self.assertEqual(image, paint(scene, density, False))
                        with patch.object(renderer, 'draw_neckline_shoulders'):
                            before = paint(scene, density, False)
                        counts = [0, 0]
                        for y in range(24, 72):
                            for x in range(24, 72):
                                p = origin+Vec2((x+.5-48)/density, (y+.5-48)/density)
                                if torso.contains(point(p)):
                                    continue
                                probes = [point(p+offset) for offset in (Vec2(), Vec2(.1, 0), Vec2(-.1, 0),
                                                                       Vec2(0, .1), Vec2(0, -.1))]
                                for side, sleeve in enumerate(sleeves):
                                    if all(opening.contains(q) and sleeve.contains(q) for q in probes):
                                        self.assertEqual(image.pixelColor(x, y), expected)
                                        if before.pixelColor(x, y).alpha() == 0:
                                            counts[side] += 1
                        self.assertTrue(all(count > 0 for count in counts), (angle, inner, density, counts))

    def test_width_height_and_depth_are_independent(self):
        shape = CustomAppearance(neckline_width=8., neckline_height=3., neckline_depth=6.)
        for width in (2., 8., 18.):
            for kind in ('v', 'arc'):
                path, _ = reference_paths(replace(shape, neckline_width=width, neckline_shape=kind))
                self.assertAlmostEqual(path.boundingRect().width(), width)
                self.assertAlmostEqual(path.boundingRect().bottom(), 3.)
                self.assertTrue(path.contains(QPointF(width*.49, -3.1)))
                self.assertFalse(path.contains(QPointF(width*.51, -3.1)))
        for height in (-6., 8.):
            path, _ = reference_paths(replace(shape, neckline_height=height))
            self.assertAlmostEqual(path.boundingRect().bottom(), 6-height)

    def test_arc_roundness_and_v_rounding_change_the_opening(self):
        shape = CustomAppearance(neckline_width=8., neckline_height=3., neckline_depth=6.)
        v, _ = reference_paths(shape)
        arc, _ = reference_paths(replace(shape, neckline_shape='arc', neckline_roundness=.8))
        rounded, _ = reference_paths(replace(shape, neckline_tip_radius=2.))
        self.assertFalse(v.contains(QPointF(2., 1.)))
        self.assertTrue(arc.contains(QPointF(2., 1.)))
        self.assertTrue(v.contains(QPointF(0., 2.9)))
        self.assertFalse(rounded.contains(QPointF(0., 2.9)))
        self.assertEqual(rounded.boundingRect().width(), v.boundingRect().width())

    def test_trim_distance_is_a_real_gap_and_zero_width_or_disabled_is_empty(self):
        shape = CustomAppearance(neckline_depth=0., neckline_height=0., neckline_trim_width=2.)
        for gap in (0., 1., 4.):
            opening, trim = reference_paths(replace(shape, neckline_trim_gap=gap))
            self.assertFalse(trim.contains(QPointF(0., -.1)))
            self.assertTrue(trim.contains(QPointF(0., gap+.1)))
            self.assertTrue(trim.contains(QPointF(0., gap+1.9)))
            self.assertFalse(trim.contains(QPointF(0., gap+2.1)))
            if gap:
                self.assertFalse(trim.contains(QPointF(0., gap*.5)))
            self.assertFalse(opening.contains(QPointF(0., gap+.1)))
        self.assertTrue(reference_paths(replace(shape, neckline_trim_enabled=False))[1].isEmpty())
        self.assertTrue(reference_paths(replace(shape, neckline_trim_width=0.))[1].isEmpty())

    def test_binding_follows_rotation_and_local_cloth_deformation(self):
        scene = OracleScene(OracleConfig(hide_cords=True, physics_backend='python'))
        app = scene.appearance
        shape = CustomAppearance(neckline_shape='arc', neckline_trim_gap=2.)
        rest = app._cloth_local
        cloth = [Vec2(x, -y) for x, y in rest]
        original = neckline_paths(cloth, rest, app.CLOTH_DIVS, shape)
        bindings = _bound_paths.cache_info()
        for angle in (0., .8, 1.57, 3.14):
            changed = [Vec2(300+v.x*cos(angle)-v.y*sin(angle),
                            200+v.x*sin(angle)+v.y*cos(angle)) for v in cloth]
            paths = neckline_paths(changed, rest, app.CLOTH_DIVS, shape)
            for path, before in zip(paths, original):
                self.assertEqual(path.elementCount(), before.elementCount())
                for i in range(path.elementCount()):
                    a, b = before.elementAt(i), path.elementAt(i)
                    self.assertAlmostEqual(b.x, 300+a.x*cos(angle)-a.y*sin(angle))
                    self.assertAlmostEqual(b.y, 200+a.x*sin(angle)+a.y*cos(angle))
        self.assertEqual(_bound_paths.cache_info().misses, bindings.misses)
        cloth[3*app.CLOTH_DIVS+5] += Vec2(1., 2.)
        self.assertTrue(neckline_paths(cloth, rest, app.CLOTH_DIVS, shape) != original)

    def test_bell_ignores_custom_neckline_and_custom_caches_refresh(self):
        scene = OracleScene(OracleConfig(hide_cords=True, physics_backend='python'))
        renderer = OracleRenderer()

        def paint():
            image = QImage(360, 400, QImage.Format.Format_ARGB32_Premultiplied)
            image.fill(0)
            painter = QPainter(image)
            try:
                painter.translate(180, 140)
                painter.scale(4, 4)
                upper = scene.body.chunks[0].position
                painter.translate(-upper.x, -upper.y)
                renderer.colors = scene.config.active_colors
                renderer.draw_geometry(painter, scene, cords=False, pearl=False, halo=False, arm=False,
                                       cache_body=True, raster_scale=2.)
            finally:
                painter.end()
            return bytes(image.constBits())

        bell = paint()
        shape = CustomAppearance(neckline_shape='arc', neckline_width=12., neckline_depth=9.,
                                 neckline_height=2., neckline_trim_gap=1., neckline_trim_width=1.5)
        scene.config = replace(scene.config, custom_appearance=shape)
        self.assertEqual(paint(), bell)
        scene.config = replace(scene.config, body_appearance='custom')
        custom = paint()
        scene.config = replace(scene.config, custom_appearance=replace(shape, neckline_trim_enabled=False))
        self.assertNotEqual(paint(), custom)
        scene.config = replace(scene.config, custom_appearance=shape)
        self.assertEqual(paint(), custom)
        scene.config = replace(scene.config, body_appearance='bell')
        self.assertEqual(paint(), bell)
