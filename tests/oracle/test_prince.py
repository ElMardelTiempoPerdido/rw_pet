"""固定特殊角色的配色隔离、无眼睛/双臂能力、共用渲染和角色切换"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication

from rw_creature_pet.config import AppConfig
from rw_creature_pet.oracle.assets import OracleAssets
from rw_creature_pet.oracle.characters import PRINCE_COLOR_NAMES
from rw_creature_pet.oracle.config import CustomAppearance, OracleConfig
from rw_creature_pet.oracle.face_config import FaceDecal
from rw_creature_pet.oracle.graphics.render import OracleRenderer
from rw_creature_pet.oracle.scene import MotionPoint, OracleHead, OracleScene, dot
from rw_creature_pet.oracle.graphics.appearance import rotate
from rw_creature_pet.oracle.motion.prince import CHEST_DROP
from rw_creature_pet.oracle.ui.desktop import OracleDesktopWindow
from rw_creature_pet.presets.appearance import apply_appearance, appearance_paths
from rw_creature_pet.presets.library import AppearanceLibrary
from rw_creature_pet.presets.profile import apply_profile, load_profile
from rw_creature_pet.presets.profile_library import ProfileLibrary
from rw_creature_pet.presets.startup import (BELL_PROFILE_ID, PRINCE_PROFILE_ID,
                                           default_custom, default_prince, prepare_character)
from rw_creature_pet.settings_store import SettingsStore
from rw_creature_pet.shared.geometry import Vec2


class PrinceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def scene(self, body='prince', **values):
        values.setdefault('voice', 'bell' if body == 'bell' else 'none')
        return OracleScene(OracleConfig(body_appearance=body, hide_cords=True, physics_backend='python', **values))

    def paint(self, scene, renderer=None, scale=2.):
        renderer = renderer or OracleRenderer(colors=scene.config.active_colors)
        image = QImage(400, 400, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(0)
        painter = QPainter(image)
        try:
            painter.translate(200, 150)
            painter.scale(scale, scale)
            p = scene.body.chunks[0].position
            painter.translate(-p.x, -p.y)
            renderer.draw_geometry(painter, scene, cords=False, pearl=False, halo=False, arm=False,
                                   cache_body=True, raster_scale=scale)
        finally:
            painter.end()
        return bytes(image.constBits())

    def test_bundled_profile_and_default_new_custom_are_separate(self):
        root = Path(__file__).resolve().parents[2]/'presets/profiles'
        princes = [p for p in root.glob('profile-prince-*/profile.json')]
        self.assertEqual(len(princes), 1)
        profile = load_profile(princes[0])
        self.assertEqual((profile.id, profile.name, profile.appearance.oracle.body_appearance),
                         (PRINCE_PROFILE_ID, 'prince', 'prince'))
        self.assertEqual(default_custom(default_prince(AppConfig())).oracle.body_appearance, 'custom')

    def test_neck_length_applies_when_switching_paused_and_restores_other_characters(self):
        scene = self.scene('bell')
        before = scene.head.position
        body = tuple(p.position for p in scene.body.chunks)
        scene.config = replace(scene.config, body_appearance='prince')
        scene.sync_character()
        scene.appearance.sync_shape(scene)
        extension = scene.config.character.neck_extension
        expected = before+scene.body.direction*(extension-CHEST_DROP)
        self.assertLess((scene.head.position-expected).length(), 1e-10)
        self.assertEqual(scene.appearance.head.position, scene.head.position)
        self.assertEqual(scene.appearance.head.previous_position, scene.head.position)
        self.assertEqual(tuple(p.position for p in scene.body.chunks), body)
        for name in ('custom', 'bell'):
            scene.config = replace(scene.config, body_appearance=name)
            scene.sync_character()
            scene.appearance.sync_shape(scene)
            self.assertEqual(scene.head.position, before)
            self.assertEqual(scene.appearance.head.position, before)
        prince = self.scene()
        upper = prince.body.chunks[0].position
        rest_height = OracleHead.NECK_BASE_OFFSET+extension+OracleHead.CONNECTION_LENGTH-CHEST_DROP
        self.assertAlmostEqual(dot(prince.head.position-upper, prince.body.direction), rest_height)
        prince.reset()
        self.assertAlmostEqual(dot(prince.head.position-prince.body.chunks[0].position, prince.body.direction), rest_height)

    def test_extended_neck_keeps_short_fixed_swing_connection_while_moving_and_turning(self):
        upper = MotionPoint.at(Vec2(100., 100.))
        head = OracleHead.at(upper.position+Vec2(0., -23.))
        head.neck_extension = self.scene().config.character.neck_extension
        for tick in range(900):
            direction = rotate(Vec2(0., -1.), min(tick, 600)*.01)
            upper.velocity = Vec2(1., .3) if tick < 600 else Vec2()
            upper.position += upper.velocity
            head.step(upper, direction, direction)
            root = upper.position+direction*(head.NECK_BASE_OFFSET+head.neck_extension)
            self.assertAlmostEqual((head.position-root).length(), 8., places=8)
        self.assertLess(head.velocity.length(), 1e-7)
        self.assertAlmostEqual(dot(head.position-upper.position, direction),
                               head.NECK_BASE_OFFSET+head.neck_extension+head.CONNECTION_LENGTH, places=7)

    def test_appearance_and_profile_roundtrip_preserve_inactive_palettes(self):
        prince = default_prince(AppConfig())
        prince = replace(prince, oracle=replace(prince.oracle,
            prince_colors=replace(prince.oracle.prince_colors, skin='#123456'), float_speed=1.3))
        target = replace(AppConfig(), oracle=replace(OracleConfig(),
            custom_appearance=CustomAppearance(head_length=1.4), outfit='maid'))
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for library, apply in ((AppearanceLibrary(root/'appearances'), apply_appearance),
                                   (ProfileLibrary(root/'profiles'), apply_profile)):
                preset = library.export(prince, 'prince')
                loaded = apply(target, preset, root/'images')
                self.assertEqual(loaded.oracle.active_colors.skin, '#123456')
                self.assertEqual(loaded.oracle.colors, target.oracle.colors)
                self.assertEqual(loaded.oracle.custom_colors, target.oracle.custom_colors)
                self.assertEqual(loaded.oracle.custom_appearance, target.oracle.custom_appearance)
                self.assertEqual(loaded.oracle.outfit, 'maid')
                self.assertEqual(loaded.oracle.active_outfit, 'normal')
            store = SettingsStore(root/'settings.json')
            store.save(loaded)
            self.assertEqual(store.load(), loaded)
        self.assertFalse(any('custom_' in p or '.outfit' in p or p.startswith('oracle.colors.')
                             for p in appearance_paths('prince')))

    def test_inactive_custom_geometry_and_outfit_cannot_appear_on_prince(self):
        scene = self.scene()
        renderer = OracleRenderer(colors=scene.config.active_colors)
        with (patch.object(renderer, 'draw_head_parts', side_effect=AssertionError('Bell head')),
             patch.object(renderer, 'draw_face', side_effect=AssertionError('eyes')),
             patch.object(renderer, 'draw_hand', side_effect=AssertionError('hands')),
              patch.object(renderer, 'draw_necklace', side_effect=AssertionError('Bell beads'))):
            before = self.paint(scene, renderer)
            self.assertTrue(any(before))
            scene.config = replace(scene.config, outfit='maid', custom_appearance=CustomAppearance(
                head_length=1.5, robe_flare=2., forehead=FaceDecal(True, 'missing.png')))
            scene.appearance.sync_shape(scene)
            self.assertEqual(self.paint(scene, renderer), before)
            for scale in (1., 1.5, 2., 3., 4.):
                self.assertTrue(any(self.paint(scene, renderer, scale)))

    def test_switch_in_place_clears_actions_and_restores_hands_and_eyes(self):
        scene = self.scene('bell')
        renderer = OracleRenderer(colors=scene.config.colors)
        before = self.paint(scene, renderer)
        scene.eyes.begin_reaction(True)
        scene.eyes.step()
        scene.drag_reactions.start_gesture('flutter', scene)
        scene.projection.state = 'showing'
        old_hands = tuple(scene.appearance.hands)
        scene.config = replace(scene.config, body_appearance='prince')
        scene.sync_character()
        scene.appearance.sync_shape(scene)
        self.assertEqual(scene.appearance.hands, [])
        self.assertTrue(all(p not in scene.appearance.points for p in old_hands))
        self.assertEqual(scene.eyes.sample(.5), 0.)
        self.assertFalse(scene.eyes.moving)
        self.assertFalse(scene.drag_reactions.gesturing)
        self.assertFalse(scene.projection.busy)
        # 用同一份配色测试缓存，不能仅靠配色变化间接刷新绘制类型
        self.assertNotEqual(self.paint(scene, renderer), before)
        scene.config = replace(scene.config, body_appearance='bell')
        scene.sync_character()
        scene.appearance.sync_shape(scene)
        self.assertEqual(len(scene.appearance.hands), 2)
        scene.eyes.begin_reaction(True)
        scene.eyes.step()
        self.assertGreater(scene.eyes.openness, 0.)
        scene.drag_reactions.start_gesture('flutter', scene)
        self.assertTrue(scene.drag_reactions.gesturing)

    def test_common_movement_and_pearls_work_without_eyes_or_gestures(self):
        scene = self.scene(pearl_matrix_enabled=True, pearl_matrix_count=4)
        eye_rng = scene.eyes.random.getstate()
        scene.eyes.begin_observation(restart=True)
        scene.eyes.begin_reaction(True)
        scene.drag_reactions.begin(scene)
        scene.drag_reactions.start_gesture('protest', scene)
        scene.projection.available = True
        self.assertFalse(scene.projection.try_start(scene))
        start = scene.body.chunks[0].position
        scene.set_target(start+Vec2(40, 0))
        for _ in range(120):
            scene.step()
        self.assertGreater((scene.body.chunks[0].position-start).length(), 5.)
        self.assertTrue(scene.behavior.notice(scene, 'recall', matrix=True))
        for _ in range(80):
            scene.step()
        self.assertIsNotNone(scene.behavior.observation_pearl)
        self.assertEqual(scene.eyes.random.getstate(), eye_rng)
        self.assertEqual(scene.eyes.openness, 0.)
        self.assertFalse(scene.drag_reactions.gesturing)
        self.assertFalse(scene.drag_reactions.active)


class PrinceSettingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch('rw_creature_pet.presets.profile_library.default_profile_directory',
                                return_value=self.root/'profiles'))
        self.enterContext(patch('rw_creature_pet.presets.library.default_appearance_directory',
                                return_value=self.root/'appearances'))
        self.enterContext(patch('rw_creature_pet.oracle.ui.desktop.QSystemTrayIcon.isSystemTrayAvailable', return_value=True))
        self.library = ProfileLibrary()
        self.store = SettingsStore(self.root/'settings.json')
        config = AppConfig(game_dir=self.root)
        self.bell = self.library.export(config, 'Bell', preset_id=BELL_PROFILE_ID)
        self.prince = self.library.export(default_prince(config), 'prince', preset_id=PRINCE_PROFILE_ID)
        initial = prepare_character(config, self.store)
        with self.store.preset_state(initial.state.serialize()):
            self.store.save(initial.config)
        self.window = OracleDesktopWindow(initial.config, config_store=self.store,
                                           assets=OracleAssets(OracleRenderer(), '', {}, ''))
        self.window.timer.stop()

    def tearDown(self):
        self.window.close()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()

    def test_menu_switch_palette_autosave_and_restart(self):
        original = self.prince.path.read_bytes(), self.prince.appearance.path.read_bytes()
        menu = self.window.character_menu
        menu.refresh()
        self.assertIn('prince', [a.text() for a in menu.actions()])
        menu.choose(self.prince)
        self.assertEqual(self.window.motion.scene.config.body_appearance, 'prince')
        self.assertEqual(self.window.motion.scene.appearance.hands, [])
        dialog = self.window.ensure_settings_dialog()
        self.assertFalse(dialog.prince_parameters.isHidden())
        self.assertTrue(dialog.bell_parameters.isHidden())
        self.assertTrue(dialog.custom_parameters.isHidden())
        self.assertTrue(dialog.outfit_section.isHidden())
        self.assertEqual({key.rsplit('.', 1)[1] for key in dialog.controls if key.startswith('oracle.prince_colors.')},
                         set(PRINCE_COLOR_NAMES))
        self.assertFalse(dialog.controls['oracle.drag_reactions.gesture_probability'].isEnabled())
        voice = dialog.controls['oracle.voice']
        self.assertEqual(voice.currentData(), 'none')
        voice.setCurrentIndex(voice.findData('bell'))
        self.assertTrue(dialog.controls['oracle.drag_reactions.voice_probability'].isEnabled())
        dialog.controls['oracle.prince_colors.skin'].setValue('#654321')
        dialog.projection_colors['oracle.prince_colors.pearl_glyph'].setValue('#fedcba')
        self.assertTrue(dialog.preset_workflow.flush())
        self.assertEqual(self.window.renderer.colors.skin, '#654321')
        self.assertEqual(self.window.renderer.colors.pearl_glyph, '#fedcba')
        self.assertEqual(self.window.motion.scene.config.voice, 'bell')
        self.assertEqual(original, (self.prince.path.read_bytes(), self.prince.appearance.path.read_bytes()))
        menu.choose(self.bell)
        voice.setCurrentIndex(voice.findData('none'))
        self.assertTrue(dialog.preset_workflow.flush())
        self.assertEqual(self.window.motion.scene.config.voice, 'none')
        self.assertEqual(len(self.window.motion.scene.appearance.hands), 2)
        self.assertNotEqual(self.window.renderer.colors.skin, '#654321')
        menu.choose(self.prince)
        self.assertEqual(voice.currentData(), 'bell')
        self.assertEqual(self.window.motion.scene.config.voice, 'bell')
        self.assertEqual(self.window.renderer.colors.skin, '#654321')
        restarted = prepare_character(self.store.load(), self.store)
        self.assertEqual(restarted.config.oracle.body_appearance, 'prince')
        self.assertEqual(restarted.config.oracle.prince_colors.skin, '#654321')
        self.assertEqual(restarted.config.oracle.voice, 'bell')


if __name__ == '__main__':
    unittest.main()
