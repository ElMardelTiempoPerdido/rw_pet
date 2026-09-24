"""袖子明暗、局部金属件、转动状态和圆角底座的外观回归。"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'

from copy import deepcopy
import unittest

from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication

from rw_creature_pet.shared.atlas import Atlas, extract_atlas
from rw_creature_pet.shared.paths import DEFAULT_GAME_DIR
from rw_creature_pet.shared.geometry import Vec2
from rw_creature_pet.oracle.scene import OracleScene
from rw_creature_pet.oracle.arm_graphics import detail_scale
from rw_creature_pet.oracle.config import OracleColors, OracleConfig
from rw_creature_pet.oracle.render import OracleRenderer


class OracleArmGraphicsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_sleeve_shading_is_transverse_mirrored_and_constant_to_cuff(self):
        renderer = OracleRenderer()
        for sign in (-1, 1):
            image = QImage(160, 360, QImage.Format.Format_RGBA8888)
            image.fill(Qt.GlobalColor.transparent)
            p = QPainter(image)
            p.scale(4, 4)
            renderer.ribbon(p, Vec2(20, 10), Vec2(20, 30), Vec2(20, 50), Vec2(20, 80),
                            2, 2, '#202020', '#e0e0e0', across=True, side_sign=sign)
            p.end()
            rows = [(image.pixelColor(75, y).red(), image.pixelColor(85, y).red())
                    for y in (70, 150, 250, 305)]
            self.assertGreater(abs(rows[0][0]-rows[0][1]), 70)
            self.assertGreater((rows[0][0]-rows[0][1])*sign, 0)
            for left, right in rows[1:]:
                self.assertLess(abs(left-rows[0][0]), 2)
                self.assertLess(abs(right-rows[0][1]), 2)
            for y in (70, 150, 250, 305):
                self.assertGreater(image.pixelColor(73, y).alpha(), 200)
                self.assertGreater(image.pixelColor(86, y).alpha(), 200)
                self.assertEqual(image.pixelColor(70, y).alpha(), 0)

    def test_local_metal_does_not_stretch_to_main_span_and_last_joint_attaches_to_hip(self):
        renderer = OracleRenderer()
        for scale in (.35, .6, .75):
            scene = OracleScene(OracleConfig(arm_scale=scale))
            scene.start_lap()
            for tick in range(250):
                scene.step()
                if tick % 25:
                    continue
                frames = renderer.arm_frames(scene, .5)
                for i, frame in enumerate(frames):
                    native = 25*(2 if i == 0 else 1 if i == 1 else .5)*detail_scale(scale)
                    self.assertLessEqual((frame.metal_end-frame.elbow).length(), native+1e-6)
                    self.assertLessEqual((frame.piston-frame.elbow).length(), scene.arm.lengths[i]+1e-6)
                    for strip in frame.strips:
                        widths = [r for _, _, r in strip.sections]
                        self.assertGreater(max(widths)-min(widths), .1)
                lower = scene.body.chunks[1]
                self.assertEqual(frames[-1].end, lower.previous_position.lerp(lower.position, .5))

    def test_native_hand_size_and_cuff_occlusion_on_both_sides(self):
        if not (DEFAULT_GAME_DIR/'RainWorld_Data/resources.assets').is_file():
            self.skipTest('本机没有游戏图集')
        renderer = OracleRenderer(Atlas(extract_atlas(DEFAULT_GAME_DIR)),
                                  OracleColors(skin='#00ff00', robe_top='#ff0000', robe_bottom='#ff0000'))
        scene = OracleScene()
        for hand in scene.appearance.hands:
            # 8 倍原生贴图：真正有色的手应宽/高 32 像素，不能把留白
            # 画布一起缩成 4×4，导致手掌只有原尺寸的 40%。
            image = QImage(120, 120, QImage.Format.Format_RGBA8888)
            image.fill(Qt.GlobalColor.transparent)
            p = QPainter(image)
            p.translate(60, 60)
            p.scale(8, 8)
            p.translate(-hand.position.x, -hand.position.y)
            renderer.draw_hand(p, hand.position)
            p.end()
            mask = Image.frombytes('RGBA', (120, 120), bytes(image.constBits())).getchannel('A')
            x0, y0, x1, y1 = mask.getbbox()
            self.assertEqual((x1-x0, y1-y0), (32, 32))
            image.fill(Qt.GlobalColor.transparent)
            p = QPainter(image)
            p.translate(60, 60)
            p.scale(8, 8)
            p.translate(-hand.position.x, -hand.position.y)
            app = scene.appearance
            renderer.draw_limbs(p, scene, 1., app.upper, app.lower, app.direction, hands=True)
            p.end()
            wrist, fingers = image.pixelColor(60, 52), image.pixelColor(60, 68)
            self.assertGreater(wrist.red(), 240, '袖口应盖住手掌靠手腕的一半')
            self.assertLess(wrist.green(), 10)
            self.assertGreater(fingers.green(), 240, '手掌下半部应露在袖口外')
            self.assertLess(fingers.red(), 10)

    def test_cogs_follow_extension_settle_reset_and_do_not_advance_during_paint(self):
        scene, renderer = OracleScene(), OracleRenderer()
        scene.set_target(Vec2(750, 65))
        for _ in range(100):
            scene.step()
        self.assertGreater(max(abs(t) for t in scene.appearance.cog_turns), .05)
        before = deepcopy(scene.appearance.__dict__)
        image = QImage(960, 600, QImage.Format.Format_ARGB32_Premultiplied)
        for alpha in (0., .5, 1., .5):
            p = QPainter(image)
            renderer.draw(p, scene, alpha)
            p.end()
        self.assertEqual(scene.appearance.__dict__, before)
        scene.stop()
        for _ in range(950):
            scene.step()
        settled = scene.appearance.cog_turns.copy()
        for _ in range(200):
            scene.step()
        self.assertLess(max(abs(a-b) for a, b in zip(settled, scene.appearance.cog_turns)), 1e-7)
        scene.reset()
        self.assertEqual(scene.appearance.cog_turns, [0.]*4)
        self.assertEqual(scene.appearance.previous_cog_turns, [0.]*4)

    def test_base_and_braces_stay_inside_all_corner_angles(self):
        renderer = OracleRenderer()
        scene = OracleScene(OracleConfig(world_width=640, world_height=480, arm_scale=.75))
        rail = scene.navigator.rail
        for index in (1, 3, 5, 7):
            piece = rail.pieces[index]
            for i in range(13):
                base, tangent = piece.sample(piece.length*i/12, rail.radius)
                normal = Vec2(-tangent.y, tangent.x)
                image = QImage(680, 520, QImage.Format.Format_RGBA8888)
                image.fill(Qt.GlobalColor.transparent)
                p = QPainter(image)
                p.setRenderHint(QPainter.RenderHint.Antialiasing)
                p.translate(20, 20)
                for front in (False, True):
                    renderer.draw_arm_base(p, scene, base, normal, base+normal*35, front)
                p.end()
                mask = Image.frombytes('RGBA', (680, 520), bytes(image.constBits())).getchannel('A')
                for rect in ((0, 0, 680, 20), (0, 500, 680, 520), (0, 20, 20, 500), (660, 20, 680, 500)):
                    with self.subTest(corner=index, angle=i):
                        self.assertIsNone(mask.crop(rect).getbbox())


if __name__ == '__main__':
    unittest.main()
