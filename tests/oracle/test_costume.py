"""Bell 衣领开口、短链收敛与独立绘制缓存的回归。"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from math import sin
import unittest
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

from rw_creature_pet.shared.geometry import Vec2
from rw_creature_pet.oracle.scene import OracleScene
from rw_creature_pet.oracle.appearance import rotate
from rw_creature_pet.oracle.render import OracleRenderer, PaintCommands


class OracleCostumeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_necklace_follows_anchors_then_settles(self):
        app = OracleScene().appearance
        origin = app.upper
        lag = 0.
        for tick in range(300):
            app.upper = origin+Vec2(18*sin(tick*.025), 5*sin(tick*.04))
            app.direction = rotate(Vec2(0, -1), .4*sin(tick*.02))
            app.step_necklace()
            self.assertEqual([app.necklace[0].position, app.necklace[-1].position], app.necklace_anchors())
            for a, b in zip(app.necklace, app.necklace[1:]):
                self.assertLess(abs((b.position-a.position).length()-app.NECKLACE_LINK_LENGTH), .25)
            self.assertLess(max((p.position-app.upper).length() for p in app.necklace), 16)
            lag = max(lag, max(p.velocity.length() for p in app.necklace))
        self.assertGreater(lag, .3)
        for _ in range(500):
            app.step_necklace()
        self.assertLess(max(p.velocity.length() for p in app.necklace), 1e-6)
        self.assertLess(abs(app.necklace[4].position.x
                            -(app.necklace[0].position.x+app.necklace[-1].position.x)/2), 4.)

    def render(self, renderer, scene, body_only=False):
        image = QImage(960, 600, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        try:
            if body_only:
                a = scene.appearance
                renderer.draw_body(painter, scene, 1., a.upper, a.lower, a.direction,
                                   a.head.position, Vec2())
            else:
                renderer.draw(painter, scene, cords=False)
        finally:
            painter.end()
        return image

    def test_uniform_motion_does_not_pull_necklace_off_chest(self):
        for velocity in (Vec2(0, 1.6), Vec2(0, -1.6), Vec2(1.6, 0), Vec2(-1.6, 0)):
            with self.subTest(velocity=velocity):
                app = OracleScene().appearance
                rest = [p.position-app.upper for p in app.necklace]
                for _ in range(220):
                    app.upper += velocity
                    app.step_necklace()
                for p, reference in zip(app.necklace, rest):
                    self.assertLess((p.position-app.upper-reference).length(), .05)

    def test_v_opening_exposes_inner_garment_through_gown_and_sleeve_roots(self):
        scene, renderer = OracleScene(), OracleRenderer()
        image = self.render(renderer, scene, body_only=True)
        upper = scene.appearance.upper
        # 取开口内部像素，避开 V 边缘抗锯齿的混色。
        for offset in (Vec2(0, -6), Vec2(0, 0), Vec2(2, -3), Vec2(-2, -3)):
            p = upper+offset
            self.assertEqual(image.pixelColor(round(p.x), round(p.y)), QColor(renderer.colors.inner_robe))
        p = upper+Vec2(0, 9)
        self.assertNotEqual(image.pixelColor(round(p.x), round(p.y)), QColor(renderer.colors.inner_robe))

    def test_inner_robe_covers_shoulders_and_collar_follows_actual_neck(self):
        renderer = OracleRenderer()
        upper, lower, direction = Vec2(40, 40), Vec2(40, 49), Vec2(0, -1)
        for offset in (Vec2(0, -10), Vec2(0, -16), Vec2(-3, -13), Vec2(3, -13)):
            with self.subTest(head_offset=offset):
                head = upper+offset
                image = QImage(640, 640, QImage.Format.Format_ARGB32_Premultiplied)
                image.fill(Qt.GlobalColor.transparent)
                painter = QPainter(image)
                painter.scale(8, 8)
                renderer.draw_inner_robe(painter, upper, lower, direction, head)
                painter.end()
                neck = offset*(1/offset.length())
                collar = head-neck*renderer.INNER_NECK_HEAD_GAP
                for sample, color in (
                        (upper+Vec2(-4, -3), renderer.colors.inner_robe),
                        (upper+Vec2(4, -3), renderer.colors.inner_robe),
                        (collar-neck, renderer.colors.inner_robe),
                        (collar+neck, renderer.colors.skin)):
                    self.assertEqual(image.pixelColor(round(sample.x*8), round(sample.y*8)),
                                     QColor(color))

    def test_necklace_has_six_symmetric_beads_and_shorter_raised_chain(self):
        scene, renderer = OracleScene(), OracleRenderer()
        appearance = scene.appearance
        self.assertEqual(len(appearance.necklace), 8)
        self.assertAlmostEqual(appearance.NECKLACE_LINK_LENGTH*7, 18.2)
        for anchor in appearance.necklace_anchors():
            self.assertAlmostEqual(anchor.y-appearance.upper.y, -8.)
        commands = PaintCommands()
        renderer.draw_necklace(commands, scene, 1.)
        sizes = [args[1].width() for name, args in commands.commands if name == 'drawImage']
        self.assertEqual(sizes, [2, 3, 2, 2, 3, 2])
        self.assertEqual([name for name, _ in commands.commands if name.startswith('draw')],
                         ['drawImage']*6, '只绘制六颗珠子，承重细绳隐藏')

    def test_necklace_motion_changes_pixels_without_rebuilding_clothes(self):
        scene, renderer = OracleScene(), OracleRenderer()
        with patch.object(renderer, 'draw_body', wraps=renderer.draw_body) as body:
            before = self.render(renderer, scene)
            scene.appearance.necklace[4].position += Vec2(2, 1)
            scene.appearance.revision += 1
            after = self.render(renderer, scene)
            self.assertEqual(body.call_count, 1)
            self.assertNotEqual(bytes(before.constBits()), bytes(after.constBits()))
        self.assertTrue(all(p in scene.appearance.points for p in scene.appearance.necklace))

    def test_collar_covers_both_sleeve_roots_without_expanding_silhouette(self):
        scene, renderer = OracleScene(), OracleRenderer()
        draw_collar = renderer.draw_collar
        def gown_only(painter, scene, alpha, upper, direction, trim, gown):
            draw_collar(painter, scene, alpha, upper, direction, trim.intersected(gown), gown)
        for tilt in (-25, 0, 25):
            scene.set_tilt(tilt)
            for _ in range(180):
                scene.step()
            with self.subTest(tilt=tilt):
                image = self.render(renderer, scene, body_only=True)
                complete = bytes(image.constBits())
                with patch.object(renderer, 'draw_collar'):
                    image = self.render(renderer, scene, body_only=True)
                    bare = bytes(image.constBits())
                # 有无浅色领边，实际衣袍/袖子外轮廓必须完全一致。
                self.assertEqual(complete[3::4], bare[3::4])
                with patch.object(renderer, 'draw_collar', side_effect=gown_only):
                    image = self.render(renderer, scene, body_only=True)
                    clipped = bytes(image.constBits())
                changes = [i//4 for i in range(0, len(complete), 4)
                           if complete[i:i+4] != clipped[i:i+4]]
                upper = scene.appearance.upper
                self.assertTrue(any(i % 960 < upper.x for i in changes), '左袖根应被领边覆盖')
                self.assertTrue(any(i % 960 > upper.x for i in changes), '右袖根应被领边覆盖')


if __name__ == '__main__':
    unittest.main()
