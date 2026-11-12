"""小角度眼形保真、连续滞回、各像素倍率及大角度回退"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from math import cos, radians, sin
import unittest
from unittest.mock import patch

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

from rw_creature_pet.oracle.config import CustomAppearance
from rw_creature_pet.oracle.eye_config import EyeAppearance
from rw_creature_pet.oracle.graphics.eyes import EyeLidTransition, PixelEye, draw_eye_shape
from rw_creature_pet.oracle.graphics.eye_stability import EyeStability, deformation_amount
from rw_creature_pet.oracle.graphics.render import OracleRenderer
from rw_creature_pet.oracle.scene import OracleScene
from rw_creature_pet.shared.geometry import Vec2
from rw_creature_pet.shared.raster import pixel_density


KINDS = ('normal', 'squeezed', 'slant_in', 'slant_out', 'round',
         'chevron_up', 'chevron_down', 'fixed_open', 'fixed_closed')


class OriginalEye(PixelEye):
    """优化前的眼位、压缩与整头旋转，用来核对大角度回退及正视端点"""
    def replay(self, painter):
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self.color)
        width = self.width-self.foreshortening
        eye = self.eye
        if self.kind != 'normal':
            draw_eye_shape(painter, self.kind, self.sign,
                           QRectF(eye.x-width/2, eye.y-self.height/2, width, self.height))
        elif self.smooth_lid:
            EyeLidTransition(QRectF(eye.x-width/2, eye.y+float(self.lower)-.5, width, 1),
                             QRectF(eye.x-width/2, eye.y-self.height/2, width, self.height),
                             self.opened, self.color).replay(painter)
        else:
            height = 1+(self.height-1)*self.opened
            y = eye.y+float(self.lower)*(1-self.opened)
            painter.drawRect(QRectF(eye.x-width/2, y-height/2, width, height))


class EyeStabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        # 保留上一版整套回归；新方案有独立的保形及半透明采样测试
        mode = patch('rw_creature_pet.oracle.graphics.eye_rendering.EYE_RENDER_MODE', 'stable_pixels')
        mode.start()
        self.addCleanup(mode.stop)

    def render(self, kind='normal', *, scale=1., density=None, angle=0., gx=0., gy=0.,
               closure=0., lower=False, dpr=1., renderer=None, pose=None, height=2.):
        shape = CustomAppearance(
            eye_1=EyeAppearance('#ff0000', default_open=True, height_mode='lower' if lower else 'normal',
                                kind=kind if not kind.startswith('fixed_') else 'normal'),
            eye_2=EyeAppearance('#0000ff', default_open=True,
                                kind=kind if not kind.startswith('fixed_') else 'normal'))
        renderer = renderer or OracleRenderer()
        renderer.OPEN_EYE_HEIGHT = height
        image = QImage(round(64*scale), round(64*scale), QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(0)
        image.setDevicePixelRatio(dpr)
        painter = QPainter(image)
        direction = Vec2(sin(radians(angle)), -cos(radians(angle)))
        look = Vec2(-direction.y, direction.x)*gx+direction*gy
        head = Vec2(32, 32)
        try:
            painter.scale(scale/dpr, scale/dpr)
            renderer.draw_head(painter, head, head-direction*14, direction, look,
                               shape=shape, eye_closure=closure, pixelated=True,
                               eye_expression=kind if kind.startswith('fixed_') else None,
                               raster_scale=scale if density is None else density, eye_stability=pose)
        finally:
            painter.end()
        image.setDevicePixelRatio(1.)
        return image

    def points(self, image, color):
        target = QColor(color).rgba()
        return {(x, y) for y in range(image.height()) for x in range(image.width())
                if image.pixel(x, y) == target}

    def normalized(self, image, color):
        points = self.points(image, color)
        self.assertTrue(points)
        x0, y0 = min(x for x, y in points), min(y for x, y in points)
        return {(x-x0, y-y0) for x, y in points}

    def test_all_shapes_keep_pixel_pattern_during_small_turns_at_each_density(self):
        # 5° + gx=.2 曾使 2×2 和 ^ 眼形多出一个像素；同时覆盖仰俯及左右眼
        for kind in KINDS:
            for scale in (1., 1.5, 2., 3., 4.):
                base = self.render(kind, scale=scale)
                for angle, gx, gy in ((5, .2, 0), (-6, -.3, .2), (8, .3, -.2)):
                    actual = self.render(kind, scale=scale, angle=angle, gx=gx, gy=gy)
                    for color in ('#ff0000', '#0000ff'):
                        with self.subTest(kind=kind, scale=scale, angle=angle, color=color):
                            self.assertEqual(self.normalized(actual, color), self.normalized(base, color))

    def test_eye_positions_still_follow_gaze_and_cardinal_head_rotations(self):
        front = self.render()
        shifted = self.render(gx=.3)
        self.assertNotEqual(self.points(front, '#ff0000'), self.points(shifted, '#ff0000'))
        for axis in (0, 90, 180, 270):
            for kind in ('normal', 'slant_in', 'round', 'chevron_down'):
                base = self.render(kind, angle=axis)
                actual = self.render(kind, angle=axis+5, gx=.2)
                for color in ('#ff0000', '#0000ff'):
                    self.assertEqual(self.normalized(base, color), self.normalized(actual, color), (axis, kind))

    def test_large_turns_and_front_endpoints_match_original_raster(self):
        for kind in KINDS:
            for scale in (1., 1.5, 2.):
                for angle, gx in ((0, 0), (30, .2), (45, -.4), (60, .2), (120, -.2), (0, 1), (5, -1)):
                    with self.subTest(kind=kind, scale=scale, angle=angle, gx=gx):
                        actual = self.render(kind, scale=scale, angle=angle, gx=gx)
                        with patch('rw_creature_pet.oracle.graphics.eye_rendering.make_eye', OriginalEye):
                            original = self.render(kind, scale=scale, angle=angle, gx=gx)
                        self.assertEqual(actual, original)

    def test_petting_is_still_gradual_and_fixed_shapes_ignore_closing(self):
        renderer = OracleRenderer()
        frames = [self.render(angle=5, gx=.2, closure=i/32, renderer=renderer) for i in range(33)]
        self.assertEqual(len({bytes(image.constBits()) for image in frames}), 33)
        for kind in KINDS[1:]:
            opened = self.render(kind, angle=5, gx=.2)
            self.assertEqual(opened, self.render(kind, angle=5, gx=.2, closure=.5))
            self.assertEqual(opened, self.render(kind, angle=5, gx=.2, closure=1.))
        # 自定义眼高继续有效；拖动固定睁眼始终为 2×2
        self.assertEqual(len(self.points(self.render(height=4.), '#ff0000')), 8)
        self.assertEqual(len(self.points(self.render('fixed_open', height=4.), '#ff0000')), 4)

    def test_classic_enlargement_dpi_and_cache_are_consistent(self):
        for kind in ('normal', 'round', 'slant_in'):
            renderer = OracleRenderer()
            for scale, coarse in ((2., True), (3., False), (4., False), (4., True)):
                density = pixel_density('adaptive', scale, coarse)
                base = self.render(kind, scale=density, density=density, angle=5, gx=.2, renderer=renderer)
                cached = renderer._head_image
                actual = self.render(kind, scale=scale, density=density, angle=5, gx=.2, dpr=1.5, renderer=renderer)
                self.assertEqual(actual, base.scaled(actual.size(), Qt.AspectRatioMode.IgnoreAspectRatio,
                                                     Qt.TransformationMode.FastTransformation))
                self.assertIs(renderer._head_image, cached)

    def test_continuous_hysteresis_ignores_jitter_but_slow_turns_release(self):
        state = EyeStability()
        state.step(14., .8)
        held = state.current
        for angle, gx in ((13., .79), (12.5, .78), (14., .8)):
            state.step(angle, gx)
            self.assertEqual(state.current, held)
        state = EyeStability()
        for tick in range(301):
            angle, gx = tick/10., tick/300.
            state.step(angle, gx)
        self.assertEqual(deformation_amount(30., 1., state.sample(1.)), 1.)
        for tick in reversed(range(301)):
            state.step(tick/10., tick/300.)
        self.assertEqual(state.current, (0., 0.))
        self.assertEqual(deformation_amount(0., 0., state.sample(1.)), 0.)

    def test_round_white_center_stays_with_outline_when_moving(self):
        for scale in (1., 1.5, 2.):
            base = self.render('round', scale=scale)
            moved = self.render('round', scale=scale, angle=5, gx=.2)
            for color in ('#ff0000', '#0000ff'):
                for image in (base, moved):
                    outline = self.points(image, color)
                    left, right = min(x for x, y in outline), max(x for x, y in outline)
                    top, bottom = min(y for x, y in outline), max(y for x, y in outline)
                    self.assertEqual(image.pixelColor((left+right)//2, (top+bottom)//2), QColor('#ffffff'))
            self.assertEqual(len(self.points(base, '#ffffff')), len(self.points(moved, '#ffffff')))

    def test_fast_rotation_interpolation_does_not_lock_to_a_stale_axis(self):
        state = EyeStability(0.)
        state.step(90., 0.)
        self.assertEqual(deformation_amount(45., 0., state.sample(.5)), 1.)
        actual = self.render('slant_in', angle=45., pose=state.sample(.5))
        with patch('rw_creature_pet.oracle.graphics.eye_rendering.make_eye', OriginalEye):
            original = self.render('slant_in', angle=45.)
        self.assertEqual(actual, original)

    def test_scene_updates_visual_state_and_rendering_does_not_advance_it(self):
        scene = OracleScene()
        state = scene.appearance.eye_stability
        scene.set_look_target(scene.head.position+Vec2(100, 0))
        for _ in range(60):
            scene.step()
        self.assertGreater(state.current[1], .5)
        before = state.current, state.previous
        renderer = OracleRenderer()
        for alpha in (0., .5, 1., .5):
            self.render(renderer=renderer, angle=12, gx=.7, pose=state.sample(alpha))
        self.assertEqual((state.current, state.previous), before)


if __name__ == '__main__':
    unittest.main()
