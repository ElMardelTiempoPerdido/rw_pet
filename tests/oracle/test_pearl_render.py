"""字形遮罩缓存、原版素材入口、珠子独立绘制和暂停/单步集成。"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from rw_creature_pet.shared.atlas import Atlas, extract_atlas
from rw_creature_pet.config import AppConfig
from rw_creature_pet.shared.paths import DEFAULT_GAME_DIR
from rw_creature_pet.shared.geometry import Vec2
from rw_creature_pet.oracle.scene import OracleScene
from rw_creature_pet.oracle.glyphs import PearlGlyphs, load_pearl_glyphs
from rw_creature_pet.oracle.debug_window import OracleDebugWindow
from rw_creature_pet.oracle.render import OracleRenderer


class OraclePearlRenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def test_mask_tint_keeps_transparency_and_bounded_cache(self):
        with TemporaryDirectory() as temp:
            image = QImage(750, 15, QImage.Format.Format_ARGB32_Premultiplied)
            image.fill(Qt.GlobalColor.transparent)
            for i in range(14):
                image.setPixelColor(i*15+2, 3, QColor('#ffffff'))
            path = Path(temp)/'glyphs.png'
            image.save(str(path))
            glyphs = PearlGlyphs(path)
            a = glyphs.sprite(3, '#123456')
            self.assertEqual(a.pixelColor(2, 3), QColor('#123456'))
            self.assertEqual(a.pixelColor(0, 0).alpha(), 0)
            self.assertIs(a, glyphs.sprite(3, '#123456'))
            for i in range(100):
                glyphs.sprite(3, f'#{i:06x}')
            self.assertLessEqual(len(glyphs.cache), 64)

    @unittest.skipUnless((DEFAULT_GAME_DIR/'RainWorld_Data/resources.assets').exists(), '需要本机游戏')
    def test_real_glyphs_extract_once_and_match_shader_threshold(self):
        import UnityPy
        atlas = Atlas(extract_atlas(DEFAULT_GAME_DIR))
        for name in ('JetFishEyeA', 'tinyStar'):
            self.assertFalse(atlas.sprite(name).isNull())
        glyphs = load_pearl_glyphs(DEFAULT_GAME_DIR, atlas.root)
        with patch.object(UnityPy, 'load', side_effect=AssertionError('缓存命中仍加载 Unity 资源')):
            cached = load_pearl_glyphs(DEFAULT_GAME_DIR, atlas.root)
        env = UnityPy.load(str(DEFAULT_GAME_DIR/'RainWorld_Data/resources.assets'))
        texture = None
        for obj in env.objects:
            if obj.type.name == 'Texture2D':
                data = obj.read()
                if data.m_Name == 'glyphs':
                    texture = data.image.convert('RGB')
                    break
        self.assertIsNotNone(texture)
        for i in range(14):
            a, b = glyphs.sprite(i, '#abcdef'), cached.sprite(i, '#abcdef')
            self.assertEqual(bytes(a.constBits()), bytes(b.constBits()))
            for y in range(15):
                for x in range(15):
                    self.assertEqual(a.pixelColor(x, y).alpha(),
                                     255 if texture.getpixel((i*15+x, y))[0] < 128 else 0)

    def test_pearl_moves_without_rebuilding_sleeping_puppet(self):
        scene, renderer = OracleScene(), OracleRenderer()
        for _ in range(650):
            scene.step()
        self.assertTrue(scene.appearance.sleeping)
        image = QImage(960, 600, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        try:
            renderer.draw(painter, scene)
            frame, revision = renderer._frame, scene.appearance.revision
            scene.set_pearl_home(scene.pearl.home+Vec2(70, 0))
            before = scene.pearl.position
            for _ in range(12):
                scene.step()
                renderer.draw(painter, scene, .5)
                self.assertIs(renderer._frame, frame)
            self.assertGreater((scene.pearl.position-before).length(), 0)
            self.assertEqual(revision, scene.appearance.revision)
            pos, velocity, tick = scene.pearl.position, scene.pearl.velocity, scene.ticks
            renderer.draw(painter, scene, 0)
            renderer.draw(painter, scene, 1)
            self.assertEqual((pos, velocity, tick), (scene.pearl.position, scene.pearl.velocity, scene.ticks))
        finally:
            painter.end()

    def test_window_controls_pause_step_takeover_and_reset(self):
        window = OracleDebugWindow(AppConfig(), load_atlas=False)
        window.timer.stop()
        try:
            window.show()
            self.app.processEvents()
            window.pause_button.setChecked(True)
            window.autonomous_box.setChecked(True)
            window.recall_pearl_button.click()
            self.assertFalse(window.autonomous_box.isChecked(), '单次观察应关闭重复循环')
            state_tick = window.scene.behavior.state_ticks
            window.clock.advance(2., window.scene.step)
            self.assertEqual(window.scene.behavior.state_ticks, state_tick)
            window.single_step()
            self.assertEqual(window.scene.behavior.state_ticks, state_tick+1)
            window.autonomous_box.setChecked(True)
            window.pick_target(640, 65)
            self.assertFalse(window.autonomous_box.isChecked())
            self.assertFalse(window.scene.behavior.active)
            target = Vec2(610, 65)
            p = window.canvas.world_to_view(target)
            QTest.mouseClick(window.canvas, Qt.MouseButton.LeftButton,
                             Qt.KeyboardModifier.ShiftModifier, QPoint(round(p.x), round(p.y)))
            self.assertLess((window.scene.pearl.home-target).length(), 1.5)
            window.reset_scene()
            self.assertEqual(window.scene.ticks, 0)
            self.assertTrue(window.scene.pearl.settled)
            self.assertTrue(window.clock.paused)
        finally:
            window.close()
