"""光环动画与交互的独立性、安全范围、像素缓存和窗口唤醒。"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from dataclasses import replace
from random import Random
from statistics import mean, median
import unittest
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication

from rw_creature_pet.config import AppConfig
from rw_creature_pet.shared.geometry import Bounds, Vec2
from rw_creature_pet.oracle.config import OracleConfig
from rw_creature_pet.oracle.halo import HaloBit, HaloRing, OracleHalo
from rw_creature_pet.oracle.scene import OracleScene, OracleWorld
from rw_creature_pet.oracle.render import OracleRenderer
from rw_creature_pet.oracle.debug_window import OracleDebugWindow
from rw_creature_pet.oracle.desktop import OracleDesktopMotion, OracleDesktopViewport


class HaloTests(unittest.TestCase):
    def test_interaction_is_smooth_bounded_and_returns_without_accumulation(self):
        h = OracleHalo(OracleWorld(1920, 1080, .2), Vec2(400, 65))
        # 单测交互意愿的恢复，不让新的常驻随机半径同时改变测量值。
        h.random.random = lambda: 1.
        base = h.scale_at()
        h.pulse(1.25, 1.)
        self.assertEqual(h.scale_at(), base)
        values = []
        for _ in range(180):
            h.step(Vec2(400, 65))
            values.append(h.scale_at())
        self.assertGreater(max(values), base*1.20)
        self.assertAlmostEqual(values[-1], base, places=4)
        self.assertLess(max(abs(a-b) for a,b in zip([base]+values, values)), .021)
        h.set_scale(.7)
        for _ in range(100):
            h.step(h.center)
        self.assertAlmostEqual(h.interaction, .7, places=4)
        for _ in range(20):
            h.pulse(1.4, .25)
            h.step(h.center)
        self.assertLessEqual(h.interaction, 1.4)
        for _ in range(140):
            h.step(h.center)
        self.assertAlmostEqual(h.interaction, .7, places=4)
        for value in (float('nan'), 0, 2, True, 'large'):
            with self.assertRaises(ValueError):
                h.set_scale(value)

    def test_full_footprint_and_interpolation_stay_in_band_through_four_corners(self):
        for size in ((640, 480), (960, 600), (2560, 1540)):
            world = OracleWorld(*size, .2)
            w, h, inner = *size, world.inner
            boxes = (Bounds(0, 0, w, inner.top), Bounds(inner.right, 0, w, h),
                     Bounds(0, inner.bottom, w, h), Bounds(0, 0, inner.left, h))
            halo = OracleHalo(world, Vec2(w/2, 0), 1.5)
            halo.set_scale(1.4)
            for target in (Vec2(w-5, 4), Vec2(w+30, h-4), Vec2(2, h+30), Vec2(-30, 1), Vec2(w/2, 1)):
                halo.target_expand, halo.target_push = 2., 3.
                for _ in range(160):
                    halo.step(target)
                    for alpha in (0., .5, 1.):
                        center = halo.center_at(alpha)
                        extent = halo.radius_at(2.5, alpha)+5*halo.geometry_at(alpha)[2]+1
                        self.assertLessEqual(extent, halo.extent)
                        corners = [center+Vec2(x*extent, y*extent) for x in (-1,1) for y in (-1,1)]
                        self.assertTrue(any(all(box.contains(p) for p in corners) for box in boxes),
                                        (size, target, center, extent))
                self.assertLess((halo.center-halo.region.clamp(target)).length(), .1)

    def test_ring_flash_fills_then_hides_for_two_of_four_ticks(self):
        h = OracleHalo(OracleWorld(1920, 1080, .2), Vec2(400, 65))
        h.flash_ring(2)
        self.assertTrue(all(b.blink_counter == 20 for b in h.bits[2]))
        self.assertTrue(all(b.blink_counter == 0 for row in h.bits[:2] for b in row))
        bit = HaloBit(.2, .2, .2, 0.)
        bit.set_to_max()
        while bit.fill < 1:
            self.assertEqual(bit.blink_counter, 20)
            bit.step(h.random)
        visibility = []
        for _ in range(20):
            bit.step(h.random)
            visibility.append(bit.fill_at(.5) > 0)
        self.assertEqual(visibility, [False, False, True, True]*5)
        self.assertEqual(bit.fill_at(.5), 1.)
        self.assertEqual(bit.blink_counter, 0)

    def test_settled_bits_have_memoryless_waits_and_a_broad_speed_distribution(self):
        bit, random = HaloBit(.5, .5, .5, 0.), Random(4821)
        waits, speeds, targets, waiting = [], [], [], 0
        for _ in range(60000):
            settled, target = bit.fill == bit.target, bit.target
            bit.step(random)
            if settled:
                waiting += 1
                if bit.target != target:
                    waits.append(waiting)
                    speeds.append(bit.speed)
                    targets.append(bit.target)
                    waiting = 0
            self.assertEqual(bit.blink_counter, 0, '单根重选长度不应自行触发闪烁')
        self.assertGreater(len(waits), 500)
        self.assertTrue(50 < mean(waits) < 70, mean(waits))
        self.assertLess(min(waits), 3)
        self.assertGreater(max(waits), 180)
        self.assertLess(min(targets), .02)
        self.assertGreater(max(targets), .98)
        self.assertLess(min(speeds), .014)
        self.assertGreater(max(speeds), .4)
        self.assertTrue(.02 < median(speeds) < .03, median(speeds))

    def test_fill_button_uses_natural_exit_without_a_fixed_timeout(self):
        h = OracleHalo(OracleWorld(1920, 1080, .2), Vec2(400, 65))
        h.random.random = lambda: 1.
        h.pulse_fill()
        values = []
        for _ in range(160):
            h.step(h.center)
            values.append(h.white_at())
        self.assertEqual(max(values), 1.)
        self.assertEqual(values[-1], 1., '没有随机退出时，四秒后仍应保持实心')
        self.assertLess(max(abs(a-b) for a,b in zip([0.]+values, values)), .1)
        # 隔离短条及旋转随机流，注入一次自然退出判定；按钮没有锁定实心状态。
        with patch.object(HaloRing, 'step'), patch.object(HaloBit, 'step'), \
                patch.object(h.random, 'random', side_effect=(1., 0., .5, 1., 1.)):
            h.step(h.center)
        self.assertEqual(h.target_white, 0.)
        self.assertEqual(h.white, 1., '随机判定设置目标，不在同帧跳变可见填充')
        previous = h.white
        for _ in range(40):
            h.step(h.center)
            self.assertLessEqual(h.white, previous)
            previous = h.white
        self.assertEqual(h.white, 0.)

    def test_natural_fill_and_flash_events_still_occur(self):
        h = OracleHalo(OracleWorld(1920, 1080, .2), Vec2(400, 65))
        saw_fill, flashed, radii = False, set(), []
        for _ in range(12000):
            h.step(h.center)
            saw_fill |= h.white == 1.
            flashed.update(i for i, row in enumerate(h.bits) if any(b.blink_counter for b in row))
            radii.append(h.radius_at(2.5))
        self.assertTrue(saw_fill)
        self.assertEqual(flashed, {0, 1, 2})
        self.assertGreater(max(radii), min(radii)*2)

    def test_separate_push_expansion_and_fixed_bar_size(self):
        h = OracleHalo(OracleWorld(5000, 5000, .2), Vec2(400, 300), 1.)
        self.assertEqual((h.radius_at(0), h.radius_at(2.5)), (30., 55.))
        detail = h.geometry_at()[2]
        h.expand = h.previous_expand = 2.
        h.push = h.previous_push = 3.
        self.assertEqual((h.radius_at(0), h.radius_at(2.5)), (120., 170.))
        self.assertEqual(h.geometry_at()[2], detail)
        h = OracleHalo(OracleWorld(640, 480, .2), Vec2(300, 65), 1.5)
        h.expand, h.previous_expand = 2., .8
        h.push, h.previous_push = 3., -1.
        h.interaction, h.previous_interaction = 1.4, .6
        for step in range(101):
            alpha = step/100
            self.assertGreater(h.radius_at(0, alpha), 0)
            self.assertLessEqual(h.radius_at(2.5, alpha)+5*h.geometry_at(alpha)[2]+2,
                                 h.extent+1e-9)

    def test_enabled_and_hidden_halo_do_not_change_simulation_or_behavior_randomness(self):
        on, off = OracleScene(), OracleScene(OracleConfig(halo_enabled=False))
        for scene in (on, off):
            scene.set_autonomous(True)
            scene.start_lap()
        for tick in range(240):
            if tick == 80:
                on.pulse_halo()
            if tick == 120:
                on.set_autonomous(True)
                off.set_autonomous(True)
            on.step(); off.step()
            self.assertEqual([p.position for p in on.appearance.points], [p.position for p in off.appearance.points])
            self.assertEqual(on.behavior.random.getstate(), off.behavior.random.getstate())
            self.assertEqual(on.eyes.random.getstate(), off.eyes.random.getstate())
        self.assertEqual(off.halo.revision, 0)
        self.assertEqual(on.halo.revision, 240)
        on.reset()
        self.assertEqual(on.halo.random.getstate(), OracleScene().halo.random.getstate())
        self.assertEqual(on.halo.interaction, 1.)

    def test_resize_and_reenable_reanchor_without_cross_screen_interpolation(self):
        scene = OracleScene()
        scene.set_halo_enabled(False)
        scene.halo.center = scene.halo.previous_center = Vec2(2000, 2000)
        scene.set_halo_enabled(True)
        self.assertEqual(scene.halo.center, scene.halo.previous_center)
        self.assertTrue(scene.halo.region.contains(scene.halo.center))
        scene.pulse_halo()
        resized = OracleDesktopMotion(scene.config, OracleDesktopViewport(0, 0, 800, 600), scene).scene
        self.assertEqual(resized.halo.center, resized.halo.previous_center)
        self.assertTrue(resized.halo.region.contains(resized.halo.center))
        self.assertEqual(resized.halo.interaction, 1.)
        self.assertEqual(resized.halo.random.getstate(), scene.halo.random.getstate())
        for kwargs in ({'halo_enabled': 1}, {'halo_scale': 0}, {'halo_scale': float('inf')}):
            with self.assertRaises(ValueError):
                OracleConfig(**kwargs)


class HaloRenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def paint(self, renderer, scene, only_halo=False):
        image = QImage(960, 600, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(0)
        p = QPainter(image)
        try:
            if only_halo:
                renderer.draw_halo(p, scene, .5)
            else:
                renderer.draw(p, scene, .5)
        finally:
            p.end()
        return image

    def test_opacity_color_and_animation_keep_body_cached_and_render_read_only(self):
        scene, renderer = OracleScene(), OracleRenderer()
        for _ in range(700):
            scene.step()
        self.assertTrue(scene.appearance.sleeping)
        self.paint(renderer, scene)
        body = renderer._raster_image
        before_image = self.paint(renderer, scene, True)
        before = bytes(before_image.constBits())
        random_state = scene.halo.random.getstate()
        halo_image = renderer._halo_image
        self.paint(renderer, scene)
        self.assertIs(renderer._halo_image, halo_image)
        self.assertEqual(scene.halo.random.getstate(), random_state)
        for _ in range(20):
            scene.step()
            self.paint(renderer, scene)
        self.assertIs(renderer._raster_image, body)
        after_image = self.paint(renderer, scene, True)
        self.assertNotEqual(before, bytes(after_image.constBits()))
        self.assertEqual(max(bytes(after_image.constBits())[3::4]), 127)
        scene.config = replace(scene.config, projection_opacity=0)
        hidden = self.paint(renderer, scene, True)
        self.assertFalse(any(bytes(hidden.constBits())))
        revision = scene.halo.revision
        scene.step()
        self.assertEqual(scene.halo.revision, revision)
        scene.config = replace(scene.config, projection_opacity=1)
        opaque = self.paint(renderer, scene, True)
        self.assertEqual(max(bytes(opaque.constBits())[3::4]), 255)
        renderer.colors = replace(renderer.colors, pearl_glyph='#ff00cc')
        changed = self.paint(renderer, scene, True)
        self.assertNotEqual(bytes(opaque.constBits()), bytes(changed.constBits()))

    def test_filled_disc_opens_a_transparent_hole_without_fading_or_residue(self):
        scene, renderer = OracleScene(), OracleRenderer()
        h = scene.halo
        # 单独观察两个圆环，防止短条与取样像素偶然重合。
        for row in h.bits:
            for bit in row:
                bit.fill = bit.previous = 0.
        cx, cy = round(h.center.x), round(h.center.y)
        for white, inside, outside in ((1., True, True), (.5, False, True), (0., False, False)):
            h.white = h.previous_white = white
            h.revision += 1
            im = self.paint(renderer, scene, True)
            self.assertEqual(im.pixelColor(cx, cy).alpha() > 0, white == 1.)
            self.assertEqual(im.pixelColor(cx+5, cy).alpha() > 0, inside)
            self.assertEqual(im.pixelColor(cx+16, cy).alpha() > 0, outside)
            self.assertEqual(max(bytes(im.constBits())[3::4]), 127)
        # 完全消失的短条不能被 QPainter 当作零面积多边形画出残线。
        h.bits[2][0].fill = h.bits[2][0].previous = h.bits[2][0].target = 1.
        h.bits[2][0].blink_counter = 18
        h.revision += 1
        hidden = self.paint(renderer, scene, True)
        self.assertEqual(bytes(im.constBits()), bytes(hidden.constBits()))

    def test_debug_controls_pause_reset_and_halo_only_refresh(self):
        window = OracleDebugWindow(AppConfig(), load_atlas=False)
        window.timer.stop()
        try:
            for _ in range(700):
                window.scene.step()
            window.refresh()
            window.scene.step()
            window._next_render_time = 0
            with patch.object(window.canvas, 'update') as update:
                window.refresh(force=False)
                update.assert_called_once()
            self.assertTrue(window.scene.appearance.sleeping)
            window.halo_box.setChecked(False)
            window.scene.step()
            window._next_render_time = 0
            with patch.object(window.canvas, 'update') as update:
                window.refresh(force=False)
                update.assert_not_called()
            window.halo_box.setChecked(True)
            window.set_paused(True)
            window.set_autonomous(True)
            before = window.scene.halo.scale_at()
            window.halo_pulse_button.click()
            self.assertEqual(window.scene.halo.scale_at(), before)
            self.assertTrue(window.scene.behavior.enabled)
            window.single_step()
            self.assertGreater(window.scene.halo.scale_at(), before)
            self.assertTrue(window.clock.paused)
            window.halo_flash_button.click()
            self.assertTrue(all(b.blink_counter == 20 for b in window.scene.halo.bits[2]))
            window.reset_scene()
            window.halo_fill_button.click()
            self.assertEqual(window.scene.halo.target_white, 1.)
            self.assertEqual(window.scene.halo.white, 0.)
            window.single_step()
            self.assertGreater(window.scene.halo.white, 0.)
            self.assertTrue(window.clock.paused)
            window.reset_scene()
            self.assertEqual(window.scene.halo.interaction, 1.)
            self.assertEqual(window.scene.halo.white, 0.)
        finally:
            window.close()


if __name__ == '__main__':
    unittest.main()
