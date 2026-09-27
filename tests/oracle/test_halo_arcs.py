"""电弧局部几何、稀疏时序、渲染透明度与工作区重建回归。"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from dataclasses import replace
from math import ceil
import unittest
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication
from rw_creature_pet.shared.geometry import Vec2
from rw_creature_pet.oracle.scene import OracleScene, OracleWorld
from rw_creature_pet.oracle.config import OracleConfig
from rw_creature_pet.oracle.halo import OracleHalo
from rw_creature_pet.oracle.halo_arcs import HaloArcs
from rw_creature_pet.oracle.desktop import OracleDesktopMotion, OracleDesktopViewport
from rw_creature_pet.oracle.render import OracleRenderer, bezier
from rw_creature_pet.oracle.damage import visual_bounds


class HaloArcTests(unittest.TestCase):
    def test_long_arcs_have_visible_bows_and_radial_tangents_on_all_edges(self):
        world = OracleWorld(960, 960, .2)
        for edge in range(4):
            def turn(v):
                for _ in range(edge):
                    v = Vec2(960-v.y, v.x)
                return v
            halo = OracleHalo(world, turn(Vec2(480, 90)))
            for endpoint, target in ((Vec2(899, 1), edge), (Vec2(959, 90), (edge+1) % 4)):
                for seed in range(10):
                    arcs = HaloArcs(world)
                    arcs.MAX_DISTANCE = 480.  # 固定本测试几何尺度，独立于用户调节的默认距离
                    arcs.random.seed(seed)
                    band = arcs.edge_regions()[edge]
                    arc = arcs.make_arc(halo, band, target, edge, turn(endpoint))
                    self.assertIsNotNone(arc)
                    controls = arc.controls(halo, 1., arcs.MAX_DISTANCE)
                    start, a, b, end = controls
                    chord, radial = end-start, a-start
                    self.assertAlmostEqual(chord.x*radial.y-chord.y*radial.x, 0.)
                    points = [bezier(*controls, i/100) for i in range(101)]
                    offsets = [(chord.x*(p.y-start.y)-chord.y*(p.x-start.x))/chord.length()
                               for p in points]
                    bow = max(abs(v) for v in offsets)
                    self.assertGreaterEqual(bow, 15.)
                    self.assertLessEqual(bow, 40.+1e-6)
                    self.assertTrue(all(v >= -1e-6 for v in offsets)
                                    or all(v <= 1e-6 for v in offsets), '不再强制反向 S 形')
                    self.assertTrue(all(band.contains(p) for p in controls))
                    self.assertTrue(all(arc.region.contains(p) for p in controls))

    def test_bow_yields_to_narrow_band_and_length_budget(self):
        bows = []
        for height in (960, 180):
            world = OracleWorld(960, height, .2)
            halo = OracleHalo(world, Vec2(480, 20))
            halo.center = halo.previous_center = Vec2(480, 20)
            arcs = HaloArcs(world)
            arcs.MAX_DISTANCE = 480.
            arcs.random.seed(4)
            band = arcs.edge_regions()[0]
            arc = arcs.make_arc(halo, band, 0, 0, Vec2(899, 1))
            self.assertIsNotNone(arc)
            controls = arc.controls(halo, 1., arcs.MAX_DISTANCE)
            start, _, _, end = controls
            chord = end-start
            samples = [bezier(*controls, i/100) for i in range(101)]
            bows.append(max(abs(chord.x*(p.y-start.y)-chord.y*(p.x-start.x))/chord.length()
                            for p in samples))
            self.assertTrue(all(band.contains(p) for p in samples))
            self.assertLessEqual(sum((b-a).length() for a, b in zip(controls, controls[1:])), arcs.MAX_DISTANCE)
        self.assertGreater(bows[0], 20.)
        self.assertLess(bows[1], bows[0]*.5)

        world = OracleWorld(1920, 1080, .2)
        halo = OracleHalo(world, Vec2(960, 105))
        arcs = HaloArcs(world)
        arcs.MAX_DISTANCE = 480.
        # 端点弦长接近上限时必须减小弧度，不能生成超长曲线。
        arc = arcs.make_arc(halo, arcs.edge_regions()[0], 0, 0, Vec2(1460, 1))
        self.assertIsNotNone(arc)
        controls = arc.controls(halo, 1., arcs.MAX_DISTANCE)
        self.assertLessEqual(sum((b-a).length() for a, b in zip(controls, controls[1:])), arcs.MAX_DISTANCE)

    def test_wall_handle_stays_fixed_while_halo_moves(self):
        world = OracleWorld(960, 600, .2)
        halo, arcs = OracleHalo(world, Vec2(480, 65)), HaloArcs(world)
        arcs.MAX_DISTANCE = 480.
        arc = arcs.make_arc(halo, arcs.edge_regions()[0], 1, 0, Vec2(959, 65))
        self.assertIsNotNone(arc)
        state = arcs.random.getstate()
        halo.previous_center = halo.center
        halo.center += Vec2(-2, 1)
        previous = None
        for i in range(11):
            points = arc.controls(halo, i/10, arcs.MAX_DISTANCE)
            self.assertIsNotNone(points)
            self.assertEqual(points[2], arc.wall_handle)
            self.assertEqual(points[-1], arc.endpoint)
            if previous:
                self.assertLess(max((b-a).length() for a, b in zip(previous, points)), .3)
            previous = points
        self.assertEqual(arcs.random.getstate(), state)

    def test_four_edges_and_corners_keep_entire_curves_in_one_band(self):
        w = OracleWorld(1920, 1080, .2)
        cases = ((Vec2(960, 105), 0), (Vec2(1815, 540), 1),
                 (Vec2(960, 975), 2), (Vec2(105, 540), 3),
                 (Vec2(105, 105), 0), (Vec2(1815, 105), 0),
                 (Vec2(1815, 975), 1), (Vec2(105, 975), 2))
        for center, primary in cases:
            with self.subTest(center=center):
                h, arcs = OracleHalo(w, center), HaloArcs(w)
                h.center = h.previous_center = center
                with patch.object(arcs, 'sample_count', return_value=arcs.max_count):
                    self.assertEqual(arcs.trigger(h, manual=True), arcs.max_count)
                self.assertEqual(arcs.trigger(h, manual=True), 0, '不能叠加超过三条')
                self.assertLessEqual(sum(a.edge != primary for a in arcs.arcs), arcs.max_count//2)
                for arc in arcs.arcs:
                    self.assertNotEqual(arc.edge, (primary+2) % 4)
                    self.assertEqual(arc.source_edge, primary)
                    for alpha in (0., .5, 1.):
                        points = arc.controls(h, alpha, arcs.MAX_DISTANCE)
                        self.assertIsNotNone(points)
                        self.assertTrue(all(arc.region.contains(p) for p in points))
                        self.assertLessEqual(sum((b-a).length() for a, b in zip(points, points[1:])), arcs.MAX_DISTANCE)
                        for i in range(101):
                            p = bezier(*points, i/100)
                            self.assertTrue(arcs.edge_regions()[primary].contains(p))
                            self.assertFalse(w.inner.contains(p))

    def test_adjacent_edges_are_available_outside_corners_with_shared_half_quota(self):
        w = OracleWorld(960, 600, .2)
        center = Vec2(480, 65)
        h = OracleHalo(w, center)
        for maximum in range(1, 11):
            seen = set()
            for seed in range(20):
                arcs = HaloArcs(w, maximum)
                arcs.MAX_DISTANCE = 480.
                arcs.random.seed(seed)
                self.assertFalse(arcs.edge_regions()[1].contains(h.center))
                self.assertFalse(arcs.edge_regions()[3].contains(h.center))
                with patch.object(arcs, 'sample_count', return_value=maximum):
                    self.assertEqual(arcs.trigger(h, manual=True), maximum)
                adjacent = [a for a in arcs.arcs if a.edge != 0]
                self.assertLessEqual(len(adjacent), maximum//2)
                self.assertTrue(all(a.edge in (1, 3) for a in adjacent))
                seen.update(a.edge for a in adjacent)
            self.assertEqual(seen, set() if maximum == 1 else {1, 3})

    def test_max_distance_also_expands_same_edge_endpoint_search(self):
        w = OracleWorld(1920, 1080, .2)
        h = OracleHalo(w, Vec2(960, 105))
        longest = []
        for maximum in (160., 480.):
            arcs = HaloArcs(w)
            arcs.MAX_DISTANCE = maximum
            lengths = []
            for _ in range(80):
                arcs.clear()
                self.assertGreater(arcs.trigger(h, manual=True), 0)
                for curve in arcs.curves(h):
                    lengths.append((curve[-1]-curve[0]).length())
                    self.assertLessEqual(sum((b-a).length() for a, b in zip(curve, curve[1:])), maximum)
            longest.append(max(lengths))
        self.assertGreater(longest[0], 120.)
        self.assertGreater(longest[1], 400.)
        self.assertGreater(longest[1], longest[0]*2.)

    def test_manual_and_automatic_counts_are_random_over_complete_configured_range(self):
        w = OracleWorld(1920, 1080, .2)
        h = OracleHalo(w, Vec2(960, 105))
        for maximum in (1, 3, 5, 10):
            for manual in (False, True):
                arcs = HaloArcs(w, maximum)
                counts = set()
                for _ in range(400):
                    arcs.clear()
                    arcs.wait = 0
                    counts.add(arcs.trigger(h, manual=manual))
                self.assertEqual(counts, set(range(1, maximum+1)), (maximum, manual))

    def test_far_boundary_or_center_drag_has_no_endpoint(self):
        w = OracleWorld(5000, 5000, .2)
        h, arcs = OracleHalo(w, Vec2(2500, 800)), HaloArcs(w)
        for center in (Vec2(2500, 800), Vec2(2500, 2500)):
            h.center = h.previous_center = center
            wait = arcs.wait
            self.assertEqual(arcs.trigger(h, manual=True), 0)
            self.assertEqual(arcs.wait, wait)

    def test_cooldown_mean_width_decay_cutoff_and_manual_bypass(self):
        w = OracleWorld(960, 600, .2)
        h, arcs = OracleHalo(w, Vec2(480, 60)), HaloArcs(w)
        waits = [arcs.next_wait()/40 for _ in range(20000)]
        self.assertGreaterEqual(min(waits), 60.)
        self.assertAlmostEqual(sum(waits)/len(waits), 180., delta=4.)
        arcs.wait = 2400
        for _ in range(2399):
            arcs.step(h)
            self.assertFalse(arcs.arcs)
        arcs.step(h)
        self.assertTrue(1 <= len(arcs.arcs) <= 3)
        self.assertGreaterEqual(arcs.wait, 2400)
        widths = [arcs.width_at()]
        self.assertEqual(widths[0], arcs.LINE_WIDTH)
        for _ in range(arcs.DURATION_TICKS):
            arcs.step(h)
            widths.append(arcs.width_at())
            self.assertAlmostEqual(arcs.width_at(0.), widths[-2])
            if arcs.age < arcs.DURATION_TICKS:
                self.assertAlmostEqual(widths[-1], arcs.LINE_WIDTH*.9**arcs.age)
                self.assertAlmostEqual(arcs.width_at(.5), (widths[-2]+widths[-1])*.5)
        self.assertEqual(widths[-1], 0.)
        self.assertGreater(widths[-2], 0.)
        self.assertEqual(widths, sorted(widths, reverse=True))
        arcs.step(h)
        self.assertFalse(arcs.arcs)
        self.assertEqual(arcs.trigger(h), 0)
        self.assertGreater(arcs.trigger(h, manual=True), 0)
        self.assertGreaterEqual(arcs.wait, 2400)

    def test_moving_halo_stays_attached_and_disable_resize_clear_old_endpoints(self):
        s = OracleScene()
        self.assertGreater(s.trigger_halo_arcs(), 0)
        s.halo.previous_center = s.halo.center
        s.halo.center += Vec2(2, 0)
        for alpha in (0., .5, 1.):
            for curve in s.halo_arcs.curves(s.halo, alpha):
                self.assertAlmostEqual((curve[0]-s.halo.center_at(alpha)).length(), s.halo.radius_at(2.5, alpha))
        new = OracleDesktopMotion(s.config, OracleDesktopViewport(-800, 0, 800, 600), s).scene
        self.assertFalse(new.halo_arcs.arcs)
        self.assertEqual(new.halo_arcs.wait, s.halo_arcs.wait)
        self.assertEqual(new.halo_arcs.random.getstate(), s.halo_arcs.random.getstate())
        s.set_halo_enabled(False)
        self.assertFalse(s.halo_arcs.arcs)
        self.assertEqual(s.trigger_halo_arcs(), 0)

    def test_arc_random_stream_is_independent_and_config_validated(self):
        a = OracleScene()
        b = OracleScene(replace(a.config, halo_arcs_enabled=False))
        for scene in (a, b):
            scene.appearance.step = lambda _: None
        for i in range(100):
            if i % 20 == 0:
                a.trigger_halo_arcs()
            a.step(); b.step()
        self.assertEqual(a.halo.random.getstate(), b.halo.random.getstate())
        self.assertEqual(a.behavior.random.getstate(), b.behavior.random.getstate())
        self.assertEqual(a.body, b.body)
        for count in (1, 2, 3, 5, 10):
            s = OracleScene(OracleConfig(halo_arc_max_count=count))
            self.assertTrue(1 <= s.trigger_halo_arcs() <= count)
        for settings in ({'halo_arcs_enabled': 1}, {'halo_arc_max_count': True},
                         {'halo_arc_max_count': 0}, {'halo_arc_max_count': 11}):
            with self.assertRaises(ValueError):
                OracleConfig(**settings)


class HaloArcRenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_pixels_opacity_bounds_and_read_only_drawing(self):
        s, renderer = OracleScene(), OracleRenderer()
        self.assertGreater(s.trigger_halo_arcs(), 0)
        before = s.halo_arcs.revision, s.halo_arcs.random.getstate(), s.halo_arcs.age
        for scale in (1., 1.5, 2.):
            image = QImage(round(980*scale), round(620*scale), QImage.Format.Format_RGBA8888)
            image.fill(0)
            p = QPainter(image)
            p.scale(scale, scale)
            p.translate(10, 10)
            renderer.draw_halo_arcs(p, s, 1., scale)
            p.end()
            from PIL import Image
            mask = Image.frombytes('RGBA', (image.width(), image.height()), bytes(image.constBits())).getchannel('A')
            self.assertGreater(mask.getextrema()[1], 0)
            self.assertLessEqual(mask.getextrema()[1], ceil(255*s.config.projection_opacity*s.halo_arcs.OPACITY))
            inner = s.world.inner
            self.assertIsNone(mask.crop(tuple(round(v*scale) for v in
                (inner.left+10, inner.top+10, inner.right+10, inner.bottom+10))).getbbox())
            self.assertIsNone(mask.crop((0, 0, image.width(), round(10*scale))).getbbox())
            bounds = visual_bounds(s)
            for curve in s.halo_arcs.curves(s.halo):
                self.assertTrue(all(bounds.contains(v.x, v.y) for v in curve))
        self.assertEqual(before, (s.halo_arcs.revision, s.halo_arcs.random.getstate(), s.halo_arcs.age))

    def test_arc_shrinks_without_rebuilding_sleeping_body_or_leaving_pixels(self):
        s, renderer = OracleScene(), OracleRenderer()
        for _ in range(700):
            s.step()
        self.assertTrue(s.appearance.sleeping)
        def paint():
            image = QImage(960, 600, QImage.Format.Format_RGBA8888)
            image.fill(0)
            p = QPainter(image)
            renderer.draw(p, s, 1.)
            p.end()
            return bytes(image.constBits())
        before = paint()
        body = renderer._raster_image
        self.assertGreater(s.trigger_halo_arcs(), 0)
        self.assertNotEqual(paint(), before)
        self.assertIs(renderer._raster_image, body)
        wide = renderer._arc_image
        for _ in range(8):
            s.halo_arcs.step(s.halo)
        self.assertNotEqual(paint(), before)
        self.assertIsNot(renderer._arc_image, wide)
        self.assertIs(renderer._raster_image, body)
        narrow = renderer._arc_image
        paint()
        self.assertIs(renderer._arc_image, narrow)
        for _ in range(s.halo_arcs.DURATION_TICKS+1):
            s.halo_arcs.step(s.halo)
        self.assertEqual(paint(), before)
        self.assertIs(renderer._raster_image, body)

    def test_subpixel_strokes_lose_pixels_without_losing_opacity_at_all_scales(self):
        from PIL import Image
        s, renderer = OracleScene(), OracleRenderer()
        self.assertGreater(s.trigger_halo_arcs(), 0)
        for scale in (1., 1.5, 2.):
            counts, peak = [], None
            for age in (0, 4, 12, 24, s.halo_arcs.DURATION_TICKS-1, s.halo_arcs.DURATION_TICKS):
                s.halo_arcs.age = age
                image = QImage(round(980*scale), round(620*scale), QImage.Format.Format_RGBA8888)
                image.fill(0)
                p = QPainter(image)
                p.scale(scale, scale)
                p.translate(10, 10)
                renderer.draw_halo_arcs(p, s, 1., scale)
                p.end()
                mask = Image.frombytes('RGBA', (image.width(), image.height()), bytes(image.constBits())).getchannel('A')
                histogram = mask.histogram()
                counts.append(sum(histogram[1:]))
                levels = {i for i in range(1, 256) if histogram[i]}
                if peak is None:
                    peak = levels
                    self.assertEqual(len(peak), 1)
                if age < s.halo_arcs.DURATION_TICKS:
                    self.assertGreater(counts[-1], 0)
                    self.assertEqual(levels, peak, (scale, age, '可见像素不能透明度淡出'))
            self.assertGreater(counts[0], counts[2]*2)
            self.assertLess(counts[-2], counts[0]*.15)
            self.assertEqual(counts[-1], 0, '到期直接清空，不能留下最小线宽')


if __name__ == '__main__':
    unittest.main()
