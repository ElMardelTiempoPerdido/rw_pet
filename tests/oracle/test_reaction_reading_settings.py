"""新行为字段的界面、资源禁用、保存和范围重置边界"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from dataclasses import fields
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication

from rw_creature_pet.config import AppConfig
from rw_creature_pet.oracle.behavior_config import ReadingConfig
from rw_creature_pet.oracle.config import DragReactionConfig
from rw_creature_pet.oracle.ui.settings import OracleSettingsDialog, PERCENTAGES
from rw_creature_pet.presets.profile import profile_mapping
from rw_creature_pet.presets.profile_library import ProfileLibrary
from rw_creature_pet.settings_store import SettingsStore
from tests.oracle.character_fixture import geometry_assets, isolate_characters


class ReactionReadingSettingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        isolate_characters(self, self.root)
        self.enterContext(patch('rw_creature_pet.presets.library.default_appearance_directory',
                                return_value=self.root/'appearances'))
        self.config = AppConfig()
        self.store = SettingsStore(self.root/'settings.json')
        self.d = OracleSettingsDialog(self.config, self.store, assets=geometry_assets())
        self.d.preset_workflow.set_autosave(False)

    def tearDown(self):
        self.d.shutdown()
        self.d.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()

    def test_all_fields_roundtrip_and_percent_display_is_not_stored_as_percent(self):
        d = self.d
        for group, cls in (('drag_reactions', DragReactionConfig), ('reading', ReadingConfig)):
            for field in fields(cls):
                path = 'oracle.'+group+'.'+field.name
                self.assertIn(path, d.controls)
                value = d.value(d.controls[path])
                expected = getattr(getattr(d.original.oracle, group), field.name)
                self.assertAlmostEqual(value, expected*100 if path in PERCENTAGES else expected)
        d.controls['oracle.drag_reactions.flutter_sync_probability'].setValue(77.7)
        d.controls['oracle.drag_reactions.projection_frame_seconds'].setValue(.125)
        d.controls['oracle.reading.matrix_probability'].setValue(62.5)
        d.controls['oracle.reading.recall_distance'].setValue(64)
        candidate = d.candidate()
        self.assertAlmostEqual(candidate.oracle.drag_reactions.flutter_sync_probability, .777)
        self.assertEqual(candidate.oracle.drag_reactions.projection_frame_seconds, .125)
        self.assertEqual(candidate.oracle.reading.matrix_probability, .625)
        self.assertEqual(candidate.oracle.reading.recall_distance, 64)
        library = ProfileLibrary(self.root/'export')
        archive = library.export_share(candidate, self.root/'shared.zip', name='Timing',
                                       preset_id=d.profile_presets.loaded.id)
        imported = ProfileLibrary(self.root/'import').import_file(archive)
        self.assertEqual(profile_mapping(imported.config), profile_mapping(candidate))

    def test_resource_and_capability_states_preserve_values(self):
        d = self.d
        before = d.candidate().oracle
        for resource in ('bell_voice', 'scan_images', 'pearl_playback_curve'):
            d.assets.resources.record(resource, error='missing')
        d.resource_settings.install(d.assets)
        for key in ('drag_reactions.voice_delay_min_seconds', 'drag_reactions.projection_frame_seconds',
                    'reading.playback_min_seconds'):
            self.assertFalse(d.controls['oracle.'+key].isEnabled())
        self.assertTrue(d.controls['oracle.reading.observe_min_seconds'].isEnabled())
        self.assertEqual(d.candidate().oracle, before)
        d.resource_settings.install(geometry_assets())
        d.controls['oracle.body_appearance'].setValue('prince')
        d.sync_dependencies()
        self.assertFalse(d.controls['oracle.drag_reactions.gesture_speed'].isEnabled())
        self.assertFalse(d.controls['oracle.reading.eye_open_probability'].isEnabled())
        self.assertTrue(d.controls['oracle.reading.observe_min_seconds'].isEnabled())

    def test_zero_probabilities_and_no_pearls_disable_only_relevant_settings(self):
        d = self.d
        d.controls['oracle.reading.drift_probability'].setValue(0)
        self.assertFalse(d.controls['oracle.reading.drift_interval_min_seconds'].isEnabled())
        self.assertTrue(d.controls['oracle.reading.observe_min_seconds'].isEnabled())
        d.controls['interaction.hover_avoidance_enabled'].setChecked(False)
        self.assertFalse(d.controls['oracle.reading.avoidance_probability'].isEnabled())
        d.controls['oracle.drag_reactions.gesture_probability'].setValue(0)
        self.assertFalse(d.controls['oracle.drag_reactions.gesture_speed'].isEnabled())
        self.assertTrue(d.controls['oracle.drag_reactions.voice_delay_min_seconds'].isEnabled())
        d.controls['oracle.pearl_matrix_enabled'].setChecked(False)
        d.controls['oracle.pearl_fixed_count'].setValue(0)
        for path, control in d.controls.items():
            if path.startswith('oracle.reading.'):
                self.assertFalse(control.isEnabled(), path)

    def test_invalid_single_default_reset_reports_conflict_and_preserves_draft(self):
        d = self.d
        d.controls['oracle.reading.interval_max_seconds'].setValue(10)
        d.controls['oracle.reading.interval_min_seconds'].setValue(5)
        before = d.candidate()
        d.preset_workflow.reset_parameter('oracle.reading.interval_max_seconds')
        self.assertEqual(d.candidate(), before)
        self.assertIn('无法恢复此项默认值', d.status.text())
        d.preset_workflow.reset_parameter('oracle.reading.interval_min_seconds')
        d.preset_workflow.reset_parameter('oracle.reading.interval_max_seconds')
        self.assertEqual(d.candidate().oracle.reading.interval_min_seconds, 0)
        self.assertEqual(d.candidate().oracle.reading.interval_max_seconds, 0)


if __name__ == '__main__':
    unittest.main()
