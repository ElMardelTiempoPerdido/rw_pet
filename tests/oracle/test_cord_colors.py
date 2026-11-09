"""逐条线缆配色、旧配色兼容和角色间隔离"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from dataclasses import replace
import json
from pathlib import Path
from random import Random
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication

from rw_creature_pet.config import AppConfig
from rw_creature_pet.oracle.config import OracleColors, OracleConfig
from rw_creature_pet.oracle.cord_colors import FINE_CORD_COLORS, legacy_cord_colors, complete_cord_colors
from rw_creature_pet.oracle.graphics.render import OracleRenderer, mixed
from rw_creature_pet.oracle.scene import OracleScene
from rw_creature_pet.oracle.ui.desktop import OracleDesktopWindow
from rw_creature_pet.presets.appearance import apply_appearance, appearance_paths, validate_config
from rw_creature_pet.presets.library import AppearanceLibrary
from rw_creature_pet.presets.personal import PersonalEntry
from rw_creature_pet.presets.profile import apply_profile
from rw_creature_pet.presets.profile_library import ProfileLibrary
from rw_creature_pet.presets.startup import BELL_PROFILE_ID, prepare_character, stage_character_upgrade
from rw_creature_pet.settings_store import SettingsStore
from tests.oracle.character_fixture import geometry_assets


class CordColorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def test_stable_groups_and_legacy_palette_match_original_generation(self):
        rng, expected = Random(10544), []
        for index in range(14):
            short = rng.random() < .5
            value = rng.random()
            length = (50+15*value if short else 50+150*value**1.5)*19/20
            direction = rng.uniform(-1., 1.), rng.uniform(-.6, .6)
            slot = rng.randrange(3)
            if index in (0, 2, 8, 13):
                expected.append((length, direction, slot))
        scene = OracleScene(OracleConfig(physics_backend='python'))
        cords = scene.appearance.cords
        self.assertEqual(len(cords.fine), 4)
        self.assertEqual(sum(len(rope.points) for rope in cords.fine), 80)
        self.assertEqual([name for name, _ in FINE_CORD_COLORS],
                         ['cord_long_2', 'cord_long_1', 'cord_short_2', 'cord_short_1'])
        for i, (length, direction, slot) in enumerate(expected):
            self.assertAlmostEqual(cords.fine_lengths[i], length)
            self.assertEqual((cords.head_dirs[i].x, cords.head_dirs[i].y), direction)
            self.assertEqual(cords.colors[i], slot)
        for joints in ('#424c5d', '#113246', '#abcdef', '#000000', '#ffffff'):
            colors = OracleColors(joints=joints)
            metal = mixed('#000000', joints, .55)
            old = (metal, mixed('#ff0000', metal, .55), mixed('#0000ff', metal, .55))
            for name, slot in FINE_CORD_COLORS:
                self.assertEqual(getattr(colors, name), old[slot].name())
        with self.assertRaises(ValueError):
            OracleColors(cord_short_2='invalid')

    def test_each_field_drives_only_its_own_fine_cord(self):
        for body in ('bell', 'custom'):
            scene = OracleScene(OracleConfig(body_appearance=body, physics_backend='python'))
            renderer = OracleRenderer(colors=scene.config.active_colors)
            colors = {name: f'#{index+100:06x}' for index, (name, _) in enumerate(FINE_CORD_COLORS)}
            renderer.colors = replace(renderer.colors, **colors)
            with patch.object(renderer, 'polyline') as draw, patch.object(renderer, 'sprite'):
                renderer.draw_cords(None, scene, 1.)
                self.assertEqual(len(draw.call_args_list), 5)
                self.assertEqual([c.args[2] for c in draw.call_args_list[1:]], list(colors.values()))
                renderer.colors = replace(renderer.colors, joints='#ffffff')
                draw.reset_mock()
                renderer.draw_cords(None, scene, 1.)
                self.assertEqual([c.args[2] for c in draw.call_args_list[1:]], list(colors.values()))

    def test_legacy_appearance_settings_and_personal_overrides_keep_their_colors(self):
        legacy = {'body_appearance': 'custom', 'custom_colors': {'joints': '#abcdef', 'cord_short_2': '#123456'}}
        restored = validate_config({'oracle': legacy})
        self.assertEqual(restored.custom_colors.cord_long_1, legacy_cord_colors('#abcdef')['cord_long_1'])
        self.assertEqual(restored.custom_colors.cord_short_2, '#123456')
        entry = PersonalEntry.read({'kind': 'profile', 'source': None,
            'defaults': {'oracle.body_appearance': 'custom', 'oracle.custom_colors.joints': '#113246'},
            'overrides': {'oracle.custom_colors.joints': '#abcdef'}})
        self.assertEqual(entry.defaults['oracle.custom_colors.cord_long_1'], '#091c27')
        self.assertEqual(entry.values['oracle.custom_colors.cord_long_1'], restored.custom_colors.cord_long_1)
        with tempfile.TemporaryDirectory() as tmp:
            store = SettingsStore(Path(tmp)/'settings.json')
            store.path.write_text(json.dumps({'version': 1, 'config': {'oracle': legacy}}), encoding='utf-8')
            with patch('rw_creature_pet.settings_store.load_defaults', return_value=AppConfig()):
                loaded = store.load()
                self.assertEqual(loaded.oracle.custom_colors, restored.custom_colors)

    def test_appearance_and_profile_roundtrip_preserve_other_palettes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = AppConfig(oracle=OracleConfig(colors=OracleColors(cord_long_1='#112233'),
                                                  prince_colors=OracleColors(cord_long_1='#334455')))
            config = replace(target, oracle=replace(target.oracle, body_appearance='custom',
                custom_colors=OracleColors(cord_long_1='#abcdef', cord_short_1='#fedcba')))
            for library, apply in ((AppearanceLibrary(root/'looks'), apply_appearance),
                                   (ProfileLibrary(root/'profiles'), apply_profile)):
                result = apply(target, library.export(config, '测试'), root/'assets')
                self.assertEqual(result.oracle.custom_colors, config.oracle.custom_colors)
                self.assertEqual(result.oracle.colors, target.oracle.colors)
                self.assertEqual(result.oracle.prince_colors, target.oracle.prince_colors)
            self.assertFalse(any('.cord_' in p for p in appearance_paths('prince')))

    def test_retained_ropes_follow_the_original_motion(self):
        config = OracleConfig(physics_backend='python')
        current = OracleScene(config)
        with patch('rw_creature_pet.oracle.graphics.cords.FINE_CORD_SOURCE_INDICES', tuple(range(14))):
            original = OracleScene(config)
        for tick in range(200):
            current.step()
            original.step()
            if tick%40 == 0:
                for rope, old_index in zip(current.appearance.cords.fine, (0, 2, 8, 13)):
                    old_rope = original.appearance.cords.fine[old_index]
                    self.assertEqual([p.position for p in rope.points], [p.position for p in old_rope.points])

    def test_fourteen_color_files_and_snapshots_migrate_once(self):
        old = {**{f'cord_long_{i}': f'#{i:06x}' for i in range(1,6)},
               **{f'cord_short_{i}': f'#{i+100:06x}' for i in range(1,10)}}
        expected = {'cord_short_1': old['cord_short_9'], 'cord_short_2': old['cord_long_4'],
                    'cord_long_1': old['cord_long_2'], 'cord_long_2': old['cord_long_1']}
        self.assertEqual(complete_cord_colors(old), expected)
        self.assertEqual(complete_cord_colors(expected), expected)
        config = OracleConfig.from_mapping({palette: old for palette in ('colors','custom_colors','prince_colors')})
        for palette in ('colors','custom_colors','prince_colors'):
            for key,value in expected.items():
                self.assertEqual(getattr(getattr(config,palette),key),value)
        restored = validate_config({'oracle': {'body_appearance': 'custom', 'custom_colors': old}})
        for key,value in expected.items():
            self.assertEqual(getattr(restored.custom_colors,key),value)
        values = {'oracle.body_appearance': 'custom', **{'oracle.custom_colors.'+k:v for k,v in old.items()}}
        entry = PersonalEntry.read({'kind': 'profile', 'source': None, 'defaults': values,
            'overrides': {'oracle.custom_colors.cord_long_1': '#abcdef'},
            'history': [{'time': '2026-11-09T10:00:00', 'source': None, 'name': 'old', 'values': values}]})
        self.assertEqual(entry.defaults['oracle.custom_colors.cord_long_2'], old['cord_long_1'])
        self.assertEqual(entry.values['oracle.custom_colors.cord_long_2'], '#abcdef')
        self.assertEqual(entry.history[0]['values']['oracle.custom_colors.cord_short_1'], old['cord_short_9'])
        self.assertEqual(PersonalEntry.read(entry.serialize()).serialize(), entry.serialize())
        with tempfile.TemporaryDirectory() as tmp:
            store = SettingsStore(Path(tmp)/'settings.json')
            data = {'version': 1, 'config': {'oracle': {'body_appearance': 'custom', 'custom_colors': old}}}
            staged, _ = stage_character_upgrade(data)
            self.assertEqual(staged['preset_state']['directory_migration']['raw_values']['oracle.custom_colors.cord_short_1'],
                             old['cord_short_9'])
            store.path.write_text(json.dumps(data), encoding='utf-8')
            with patch('rw_creature_pet.settings_store.load_defaults', return_value=AppConfig()):
                loaded = store.load()
                self.assertEqual(loaded.oracle.custom_colors, restored.custom_colors)
                store.save(loaded)
                self.assertEqual(store.load(), loaded)

    def test_stationary_frame_is_repainted_after_color_change(self):
        scene = OracleScene(OracleConfig(physics_backend='python', glow_enabled=True))
        renderer = OracleRenderer(colors=scene.config.active_colors)
        def paint():
            image = QImage(700, 500, QImage.Format.Format_ARGB32_Premultiplied)
            image.fill(0)
            painter = QPainter(image)
            try:
                renderer.draw(painter, scene)
            finally:
                painter.end()
            return bytes(image.constBits())
        before = paint()
        renderer.colors = replace(renderer.colors, **{name: '#00ff00' for name, _ in FINE_CORD_COLORS})
        self.assertNotEqual(paint(), before)


class CordColorSettingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def test_live_edit_autosave_switch_and_restart(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch('rw_creature_pet.presets.profile_library.default_profile_directory', return_value=root/'profiles'))
        self.enterContext(patch('rw_creature_pet.presets.library.default_appearance_directory', return_value=root/'looks'))
        self.enterContext(patch('rw_creature_pet.oracle.ui.desktop.QSystemTrayIcon.isSystemTrayAvailable', return_value=True))
        library, store = ProfileLibrary(), SettingsStore(root/'settings.json')
        config = AppConfig(game_dir=root, oracle=OracleConfig(physics_backend='python'))
        bell = library.export(config, 'Bell', preset_id=BELL_PROFILE_ID)
        custom = library.export(replace(config, oracle=replace(config.oracle, body_appearance='custom')), 'Custom')
        initial = prepare_character(config, store)
        with store.preset_state(initial.state.serialize()):
            store.save(initial.config)
        window = OracleDesktopWindow(initial.config, config_store=store, assets=geometry_assets())
        window.timer.stop()
        try:
            dialog = window.ensure_settings_dialog()
            motion = window.motion
            for name, _ in FINE_CORD_COLORS:
                self.assertIn('oracle.colors.'+name, dialog.controls)
                self.assertIn('oracle.custom_colors.'+name, dialog.controls)
                self.assertNotIn('oracle.prince_colors.'+name, dialog.controls)
            dialog.controls['oracle.colors.cord_long_1'].setValue('#123456')
            self.assertTrue(dialog.preset_workflow.flush())
            self.assertIs(window.motion, motion)
            self.assertEqual(window.renderer.colors.cord_long_1, '#123456')
            window.character_menu.choose(custom)
            self.assertNotEqual(window.renderer.colors.cord_long_1, '#123456')
            dialog.controls['oracle.custom_colors.cord_long_1'].setValue('#abcdef')
            self.assertTrue(dialog.preset_workflow.flush())
            window.character_menu.choose(bell)
            self.assertEqual(window.renderer.colors.cord_long_1, '#123456')
            restarted = prepare_character(store.load(), store)
            self.assertEqual(restarted.config.oracle.colors.cord_long_1, '#123456')
        finally:
            window.close()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            self.app.processEvents()
