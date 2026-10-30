"""风格选择、显隐、手动编辑与角色会话；全部使用临时角色目录"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from rw_creature_pet.config import AppConfig
from rw_creature_pet.i18n import language_manager
from rw_creature_pet.oracle.style_config import DIMENSIONS
from rw_creature_pet.oracle.ui.settings import OracleSettingsDialog
from rw_creature_pet.presets.behavior_styles import BehaviorStyleLibrary, DIMENSION_PATHS
from rw_creature_pet.presets.profile import profile_mapping
from rw_creature_pet.presets.profile_library import ProfileLibrary
from rw_creature_pet.settings_store import SettingsStore
from tests.oracle.character_fixture import geometry_assets, isolate_characters


class BehaviorStyleSettingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        isolate_characters(self, self.root)
        self.enterContext(patch('rw_creature_pet.presets.library.default_appearance_directory',
                                return_value=self.root/'appearances'))
        game = self.root/'game'
        (game/'RainWorld_Data').mkdir(parents=True)
        (game/'RainWorld_Data/resources.assets').touch()
        self.config = AppConfig(game_dir=game)
        self.store = SettingsStore(self.root/'settings.json')
        self.dialogs = []
        self.d = self.open(self.config)
        self.d.preset_workflow.set_autosave(False)
        self.enterContext(patch.object(self.d, 'space_assessment', return_value=None))

    def open(self, config):
        d = OracleSettingsDialog(config, self.store, assets=geometry_assets())
        self.dialogs.append(d)
        return d

    def tearDown(self):
        for d in self.dialogs:
            d.shutdown()
            d.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()
        language_manager().set_language('zh')

    def choose(self, dimension, identifier):
        combo = self.d.behavior_styles.groups[dimension].selector
        combo.setCurrentIndex(combo.findData(identifier))
        combo.activated.emit(combo.currentIndex())

    def test_legacy_is_custom_and_all_140_controls_remain_owned_by_their_dimension(self):
        d = self.d
        before = d.candidate()
        for dimension, group in d.behavior_styles.groups.items():
            self.assertEqual(group.selector.currentData(), '')
            self.assertTrue(group.content.isHidden())
            for path in DIMENSION_PATHS[dimension]:
                self.assertTrue(group.content.isAncestorOf(d.controls[path]), path)
            group.advanced.setChecked(True)
            group.advanced.setChecked(False)
        self.assertEqual(d.candidate(), before)
        self.assertFalse(d.preset_workflow.dirty)

    def test_apply_only_own_dimension_and_manual_edit_never_rematches(self):
        d = self.d
        self.choose('drift', 'drift.continuous')
        before = profile_mapping(d.candidate())
        self.choose('mouse_attention', 'mouse_attention.curious')
        selected = d.candidate().oracle.behavior_styles
        self.assertEqual(selected.drift.id, 'drift.continuous')
        self.assertEqual(selected.mouse_attention.id, 'mouse_attention.curious')
        self.assertTrue(selected.mouse_attention.version.startswith('v1:'))
        self.assertEqual(profile_mapping(d.candidate())['oracle']['drift'], before['oracle']['drift'])
        control = d.controls['interaction.hover_radius']
        control.setValue(219)
        control.setValue(220)
        self.assertFalse(d.candidate().oracle.behavior_styles.mouse_attention.id)
        self.assertEqual(d.behavior_styles.groups['mouse_attention'].selector.currentData(), '')
        self.assertEqual(d.candidate().oracle.behavior_styles.drift.id, 'drift.continuous')
        self.choose('mouse_attention', 'mouse_attention.curious')
        self.assertEqual(d.candidate().oracle.behavior_styles.mouse_attention.id, 'mouse_attention.curious')
        d.controls['oracle.voice'].setCurrentIndex(d.controls['oracle.voice'].findData('none'))
        self.assertEqual(d.candidate().oracle.behavior_styles.mouse_attention.id, 'mouse_attention.curious')

    def test_programmatic_load_autosave_and_character_switch_preserve_markers(self):
        d = self.d
        style = d.behavior_styles.library.find('daily_activity.active', 'daily_activity')
        other = ProfileLibrary(self.root/'others').export(style.apply(self.config), 'Other')
        d.preset_workflow.activate('profile', other)
        self.assertEqual(d.behavior_styles.groups['daily_activity'].selector.currentData(), style.id)
        self.choose('mouse_attention', 'mouse_attention.curious')
        self.assertTrue(d.preset_workflow.flush())
        saved = self.store.load()
        self.assertEqual(saved.oracle.behavior_styles.mouse_attention.id, 'mouse_attention.curious')
        reopened = self.open(saved)
        self.assertEqual(reopened.behavior_styles.groups['daily_activity'].selector.currentData(), style.id)
        self.assertEqual(reopened.behavior_styles.groups['mouse_attention'].selector.currentData(), 'mouse_attention.curious')
        d.preset_workflow.set_autosave(True)
        self.choose('mouse_attention', 'mouse_attention.reserved')
        self.assertTrue(d.preset_workflow.timer.isActive())
        self.assertTrue(d.preset_workflow.flush())
        self.assertEqual(self.store.load().oracle.behavior_styles.mouse_attention.id, 'mouse_attention.reserved')

    def test_missing_definition_and_updated_version_do_not_overwrite_snapshot(self):
        d = self.d
        self.choose('drift', 'drift.continuous')
        before = d.candidate()
        library = d.behavior_styles.library
        style = library.find('drift.continuous', 'drift')
        changed = replace(style, values={**style.values, 'oracle.drift_speed': .9})
        d.behavior_styles.library = BehaviorStyleLibrary(tuple(changed if s.id == style.id else s for s in library.styles))
        d.behavior_styles.refresh()
        self.assertEqual(d.candidate(), before)
        self.assertEqual(d.behavior_styles.groups['drift'].selector.currentData(), style.id)
        self.choose('drift', style.id)  # 再次激活同一项也可应用新版
        self.assertEqual(d.candidate().oracle.drift_speed, .9)
        self.assertNotEqual(d.candidate().oracle.behavior_styles.drift.version, before.oracle.behavior_styles.drift.version)
        current = d.candidate()
        d.behavior_styles.library = BehaviorStyleLibrary(())
        d.behavior_styles.refresh()
        self.assertEqual(d.behavior_styles.groups['drift'].selector.currentData(), '')
        self.assertEqual(d.candidate(), current)

    def test_language_folding_and_resource_disable_do_not_change_values_or_markers(self):
        d = self.d
        for dimension in DIMENSIONS:
            self.choose(dimension, d.behavior_styles.library.for_dimension(dimension)[-1].id)
        before = d.candidate()
        for resource in ('bell_voice', 'scan_images', 'pearl_playback_curve'):
            d.assets.resources.record(resource, error='missing')
        d.resource_settings.install(d.assets)
        for language in ('zh', 'en', 'zh'):
            language_manager().set_language(language)
            for group in d.behavior_styles.groups.values():
                group.advanced.setChecked(True)
                group.advanced.setChecked(False)
            self.assertEqual(d.candidate().oracle.behavior_styles, before.oracle.behavior_styles)
            self.assertEqual(profile_mapping(d.candidate()), profile_mapping(before))
        self.assertFalse(d.controls['oracle.drag_reactions.voice_delay_min_seconds'].isEnabled())

    def test_single_reset_is_custom_and_full_profile_reset_restores_original_marker(self):
        d = self.d
        self.choose('mouse_attention', 'mouse_attention.curious')
        d.preset_workflow.reset_parameter('interaction.hover_radius')
        self.assertFalse(d.candidate().oracle.behavior_styles.mouse_attention.id)
        style = d.behavior_styles.library.find('mouse_attention.curious', 'mouse_attention')
        other = ProfileLibrary(self.root/'others').export(style.apply(self.config), 'Styled')
        d.preset_workflow.activate('profile', other)
        self.choose('mouse_attention', 'mouse_attention.reserved')
        d.preset_workflow.restore_defaults('profile')
        self.assertEqual(d.candidate().oracle.behavior_styles.mouse_attention.id, style.id)

    def test_long_local_style_name_does_not_widen_the_page(self):
        d = self.d
        library = d.behavior_styles.library
        style = library.for_dimension('mouse_attention')[0]
        long_style = replace(style, name_en='Gentle mouse attention with longer pauses and a stable natural resting rhythm')
        d.behavior_styles.library = replace(library, styles=tuple(long_style if s.id == style.id else s for s in library.styles))
        language_manager().set_language('en')
        d.behavior_styles.refresh()
        d.resize(800, 760)
        d.show()
        d.tabs.setCurrentWidget(d.pages['behavior'])
        QTest.qWait(150)
        self.assertEqual(d.pages['behavior'].horizontalScrollBar().maximum(), 0)

    def test_cancel_does_not_save_style_selection(self):
        before = self.store.path.read_bytes()
        self.choose('mouse_attention', 'mouse_attention.curious')
        self.assertTrue(self.d.preset_workflow.dirty)
        self.d.reject()
        self.assertEqual(self.store.path.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
