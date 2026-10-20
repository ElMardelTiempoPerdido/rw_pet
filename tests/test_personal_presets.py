"""旧角色缓存补齐新字段时，不继承当前角色的外观或改写已保存的调整"""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from rw_creature_pet.config import AppConfig
from rw_creature_pet.oracle.config import OracleConfig
from rw_creature_pet.presets.personal import PersonalEntry, PersonalState, apply_values, capture
from rw_creature_pet.ui_config import UiConfig


OUTFIT_PREFIX = 'oracle.outfit_settings.'


class PersonalPresetTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.config = AppConfig(ui=UiConfig('en'), oracle=OracleConfig(body_appearance='custom'))

    def old_values(self, kind):
        return {key: value for key, value in capture(self.config, kind, self.directory).items()
                if not key.startswith(OUTFIT_PREFIX)}

    def test_missing_defaults_are_completed_without_inheriting_current_character(self):
        for kind in ('appearance', 'profile'):
            with self.subTest(kind=kind):
                original = {'kind': kind, 'defaults': self.old_values(kind), 'overrides': {
                    'oracle.outfit': 'maid', OUTFIT_PREFIX+'maid.head.offset_x': 3.5}}
                untouched = deepcopy(original)
                entry = PersonalEntry.read(original)
                other = apply_values(self.config, {
                    OUTFIT_PREFIX+'maid.head.offset_x': 8,
                    OUTFIT_PREFIX+'maid.apron.offset_y': 9,
                    OUTFIT_PREFIX+'maid.lace.mirror': False})
                result = apply_values(other, entry.values)
                self.assertEqual(result.oracle.outfit, 'maid')
                self.assertEqual(result.oracle.outfit_settings.maid.head.offset_x, 3.5)
                self.assertEqual(result.oracle.outfit_settings.maid.apron.offset_y, 0)
                self.assertTrue(result.oracle.outfit_settings.maid.lace.mirror)
                self.assertEqual(entry.defaults[OUTFIT_PREFIX+'maid.head.offset_x'], 0)
                self.assertEqual(entry.overrides, original['overrides'])
                self.assertEqual(original, untouched)
                self.assertNotIn('oracle.colors.skin', entry.defaults)
                self.assertNotIn('audio.volume', entry.defaults)
                self.assertEqual('oracle.float_speed' in entry.defaults, kind == 'profile')

    def test_explicit_defaults_overrides_and_inactive_branch_survive_round_trip(self):
        defaults = self.old_values('profile')
        defaults.update({OUTFIT_PREFIX+'maid.head.offset_x': 2,
                         OUTFIT_PREFIX+'maid.head.enabled': False,
                         'oracle.colors.skin': '#123456'})
        overrides = {OUTFIT_PREFIX+'maid.head.offset_x': 0,
                     OUTFIT_PREFIX+'maid.apron.offset_y': 1.5}
        state = PersonalState({'version': 2, 'active': 'role', 'entries': {'role': {
            'kind': 'profile', 'defaults': defaults, 'overrides': overrides}}})
        entry = state.entries['role']
        self.assertEqual(entry.defaults[OUTFIT_PREFIX+'maid.head.offset_x'], 2)
        self.assertFalse(entry.values[OUTFIT_PREFIX+'maid.head.enabled'])
        self.assertEqual(entry.values[OUTFIT_PREFIX+'maid.head.offset_x'], 0)
        self.assertEqual(entry.values['oracle.colors.skin'], '#123456')
        self.assertEqual(entry.overrides, overrides)
        self.assertEqual(PersonalState(state.serialize()).serialize(), state.serialize())

    def test_old_appearance_history_does_not_inherit_current_outfit_parts(self):
        data = {'kind': 'profile', 'defaults': self.old_values('profile'), 'history': [{
            'name': 'Earlier look', 'time': '2026-10-16T00:00:00+00:00',
            'values': self.old_values('appearance'), 'source': None}]}
        untouched = deepcopy(data)
        entry = PersonalEntry.read(data)
        current = apply_values(self.config, {
            'oracle.outfit': 'maid', OUTFIT_PREFIX+'maid.ribbon_down.offset_y': -6.5})
        current = replace(current, oracle=replace(current.oracle, float_speed=1.2))
        restored = entry.restore(0, current, self.directory)
        self.assertEqual(restored.oracle.outfit, 'normal')
        self.assertEqual(restored.oracle.outfit_settings, self.config.oracle.outfit_settings)
        self.assertEqual(restored.oracle.float_speed, 1.2)
        self.assertEqual(data, untouched)

    def test_old_activity_snapshot_defaults_preserve_explicit_adjustments(self):
        prefixes = ('oracle.daily_activity.', 'oracle.reading.', 'oracle.drift.', 'oracle.mouse_avoidance.')
        defaults = {key: value for key, value in capture(self.config, 'profile', self.directory).items()
                    if not key.startswith(prefixes)}
        data = {'kind': 'profile', 'defaults': defaults, 'overrides': {
            'oracle.daily_activity.cross_edge_cooldown_seconds': 0.,
            'oracle.reading.start_probability': .123456,
            'oracle.drift.long_pause_weight': 0., 'oracle.mouse_avoidance.lean_move_probability': 0.}}
        untouched = deepcopy(data)
        entry = PersonalEntry.read(data)
        current = apply_values(self.config, {'oracle.daily_activity.move_weight': 0.,
                                             'oracle.daily_activity.move_lean_degrees': 0.,
                                             'oracle.drift.cooldown_seconds': 0.,
                                             'oracle.mouse_avoidance.lean_sample_power': 5.})
        loaded = apply_values(current, entry.values)
        self.assertEqual(loaded.oracle.daily_activity.move_weight, 35.)
        self.assertEqual(loaded.oracle.daily_activity.move_lean_degrees, 20.)
        self.assertEqual(loaded.oracle.daily_activity.cross_edge_cooldown_seconds, 0.)
        self.assertEqual(loaded.oracle.reading.start_probability, .123456)
        self.assertEqual(entry.defaults['oracle.reading.start_probability'], .25)
        self.assertEqual(loaded.oracle.drift.cooldown_seconds, 120.)
        self.assertEqual(loaded.oracle.drift.long_pause_weight, 0.)
        self.assertEqual(loaded.oracle.mouse_avoidance.lean_sample_power, 2.)
        self.assertEqual(loaded.oracle.mouse_avoidance.lean_move_probability, 0.)
        self.assertEqual(PersonalEntry.read(entry.serialize()).serialize(), entry.serialize())
        self.assertEqual(data, untouched)


if __name__ == '__main__':
    unittest.main()
