"""统一读珠概率/时钟的安全接续、归位等待与旧配置升级"""
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace as NS
import json
import shutil
import tempfile
import unittest
from unittest.mock import Mock, patch

from rw_creature_pet.config import AppConfig
from rw_creature_pet.oracle.behavior_config import ReadingConfig
from rw_creature_pet.oracle.behavior.controller import OracleBehavior, Activity
from rw_creature_pet.oracle.reading_migration import migrate_reading, migrate_reading_values
from rw_creature_pet.shared.geometry import Vec2
from rw_creature_pet.settings_store import SettingsStore
from rw_creature_pet.presets.personal import PersonalEntry, apply_values
from rw_creature_pet.presets.profile import profile_mapping, validate_config
from rw_creature_pet.presets.profile_library import ProfileLibrary
from rw_creature_pet.presets.behavior_styles import BehaviorStyleLibrary, default_style_directory


class ReadingScheduleTests(unittest.TestCase):
    def fixture(self, **values):
        config = ReadingConfig(**{'attempt_min_seconds': 2, 'attempt_max_seconds': 2, **values})
        b = OracleBehavior(reading=config)
        b.enabled = True
        b.movement_enabled = False
        b.duration = 0
        b.drift_duration = b.drift_next_move = 10000
        scene = NS(config=AppConfig().oracle, pearl_matrix=None, fixed_pearls=NS(roots=(object(),)),
                   mouse_reaction=NS(petting=NS(active=False), avoidance=NS(busy=False, moving=False)),
                   drag=NS(controlling=False), pose=NS(settled=True), observation_pearls_settled=True,
                   arrived=True, navigator=None, target=Vec2(), body=NS(chunks=[NS(position=Vec2())]))
        return b, scene

    def test_initial_wait_and_zero_interval_never_produce_multiple_draws_per_tick(self):
        b, s = self.fixture()
        self.assertEqual(b.reading_wait, 80)
        with patch.object(b.reading_timing_random, 'random', return_value=1) as draw:
            for _ in range(79):
                b.advance_reading(s)
                self.assertFalse(b.attempt_reading(s))
            draw.assert_not_called()
            b.advance_reading(s)
            self.assertFalse(b.attempt_reading(s))
            self.assertEqual(draw.call_count, 1)
            self.assertEqual(b.reading_wait, 80)
            for _ in range(30):
                self.assertFalse(b.attempt_reading(s))
            self.assertEqual(draw.call_count, 1)
        b, s = self.fixture(attempt_min_seconds=0, attempt_max_seconds=0)
        self.assertEqual(b.reading_wait, 1)

    def test_idle_lean_and_drift_share_exactly_one_probability_and_retry(self):
        for mode in ('idle', 'lean', 'drift'):
            for draw, triggered in ((.49, True), (.51, False)):
                b, s = self.fixture(start_probability=.5)
                b.reading_wait = 0
                s.mouse_reaction.avoidance.busy = mode == 'lean'
                if mode == 'drift':
                    b.state = Activity.DRIFT
                    b.drift_active = True
                def notice(*args, **kwargs):
                    b.enter(Activity.NOTICE)
                    return True
                with patch.object(b, 'notice', side_effect=notice) as event, \
                        patch.object(b.reading_timing_random, 'random', return_value=draw) as random, \
                        patch.object(b, 'choose_activity', return_value=Activity.IDLE):
                    b.step(s)
                    self.assertEqual(random.call_count, 1)
                    self.assertEqual(event.called, triggered)
                    if triggered:
                        self.assertEqual(event.call_args.kwargs['stationary'], mode == 'lean')
                    else:
                        self.assertEqual(b.reading_wait, 80)

    def test_reading_and_return_do_not_consume_wait_and_cancel_waits_for_return(self):
        b, s = self.fixture()
        for state in (Activity.NOTICE, Activity.OBSERVE, Activity.RETURN):
            b.enter(state)
            for _ in range(100):
                b.advance_reading(s)
            self.assertEqual(b.reading_wait, 80)
        b.observation_pearl = Mock()
        b.release_observation()
        b.enter(Activity.IDLE)
        s.observation_pearls_settled = False
        b.reading_wait = 0
        for _ in range(100):
            b.advance_reading(s)
            self.assertFalse(b.attempt_reading(s))
        self.assertTrue(b.reading_return_pending)
        s.observation_pearls_settled = True
        b.advance_reading(s)
        self.assertFalse(b.reading_return_pending)
        self.assertEqual(b.reading_wait, 80)

    def test_busy_states_hold_due_attempt_without_interrupt_or_accumulating_retries(self):
        b, s = self.fixture(start_probability=1)
        for blocked in ('petting', 'drag', 'no_pearl'):
            b.reading_wait = 0
            s.mouse_reaction.petting.active = blocked == 'petting'
            s.drag.controlling = blocked == 'drag'
            s.fixed_pearls.roots = () if blocked == 'no_pearl' else (object(),)
            with patch.object(b, 'notice') as notice, patch.object(b.reading_timing_random, 'random') as draw:
                for _ in range(20):
                    b.advance_reading(s)
                    self.assertFalse(b.attempt_reading(s))
                notice.assert_not_called()
                draw.assert_not_called()
        # 跨边与冥想计时可以到期，但其专属状态正常完成后才进入尝试入口
        s.fixed_pearls.roots = (object(),)
        for state in (Activity.CROSS_EDGE, Activity.MEDITATE, Activity.DRIFT_CROSS_EDGE):
            b.enter(state)
            for _ in range(20):
                b.advance_reading(s)
            self.assertEqual(b.reading_wait, 0)
        b.enter(Activity.IDLE)
        with patch.object(b, 'notice', return_value=True) as notice:
            self.assertTrue(b.attempt_reading(s))
            notice.assert_called_once()


class ReadingMigrationTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.old = dict(start_probability=.37, interval_min_seconds=0., interval_max_seconds=0.,
                        drift_probability=.9, avoidance_probability=.1,
                        drift_delay_min_seconds=3., drift_delay_max_seconds=6.,
                        drift_interval_min_seconds=23., drift_interval_max_seconds=41.,
                        observe_min_seconds=12., observe_max_seconds=34.,
                        playback_min_seconds=56., playback_max_seconds=78.)

    def test_priority_new_then_nonzero_old_interval_then_drift_and_preserved_durations(self):
        for extra, expected in (({}, (23, 41)),
                                ({'interval_min_seconds': 0, 'interval_max_seconds': 7}, (0, 7)),
                                ({'interval_min_seconds': 4, 'interval_max_seconds': 7}, (4, 7)),
                                ({'attempt_min_seconds': 2, 'attempt_max_seconds': 3}, (2, 3)),
                                ({'attempt_min_seconds': 2, 'attempt_max_seconds': 3,
                                  'interval_min_seconds': 8, 'interval_max_seconds': 1}, (2, 3))):
            raw = {**self.old, **extra}
            converted = migrate_reading(raw)
            self.assertEqual(converted, migrate_reading(converted))
            reading = ReadingConfig(**converted)
            self.assertEqual((reading.attempt_min_seconds, reading.attempt_max_seconds), expected)
            self.assertEqual(reading.start_probability, .37)
            self.assertEqual((reading.observe_min_seconds, reading.observe_max_seconds,
                              reading.playback_min_seconds, reading.playback_max_seconds), (12, 34, 56, 78))
            self.assertIn('drift_probability', raw)

    def test_old_json_toml_personal_overrides_and_share_roundtrip(self):
        raw = {'oracle': {'reading': self.old}}
        config = validate_config(raw)
        self.assertEqual(config.oracle.reading.attempt_min_seconds, 23)
        store = SettingsStore(self.root/'settings.json')
        store.path.write_text(json.dumps({'version': 1, 'config': raw}), encoding='utf-8')
        self.assertEqual(store.load().oracle.reading, config.oracle.reading)
        toml = self.root/'config.toml'
        toml.write_text('[oracle.reading]\n'+''.join(f'{k} = {v}\n' for k,v in self.old.items()), encoding='utf-8')
        self.assertEqual(AppConfig.load(toml).oracle.reading, config.oracle.reading)
        flat = {'oracle.reading.'+k: v for k,v in self.old.items()}
        entry = PersonalEntry.read({'kind': 'profile', 'source': None, 'defaults': flat,
                                   'overrides': {'oracle.reading.interval_min_seconds': 8,
                                                 'oracle.reading.interval_max_seconds': 11}})
        active = apply_values(AppConfig(), entry.values)
        self.assertEqual((active.oracle.reading.attempt_min_seconds, active.oracle.reading.attempt_max_seconds), (8, 11))
        library = ProfileLibrary(self.root/'profiles')
        preset = library.export(active, '阅读迁移')
        archive = library.export_share(active, self.root/'share.zip', name=preset.name, preset_id=preset.id)
        imported = ProfileLibrary(self.root/'received').import_file(archive)
        self.assertEqual(profile_mapping(imported.config), profile_mapping(active))
        self.assertFalse(any('drift_interval' in key for key in entry.values))

    def test_local_legacy_style_override_is_migrated_before_merging_new_builtins(self):
        shutil.copy2(default_style_directory()/'builtin.toml', self.root/'builtin.toml')
        (self.root/'local.toml').write_text('''format_version = 1
[[styles]]
id = "reading_habits.leisurely"
[styles.values]
"oracle.reading.interval_min_seconds" = 7.0
"oracle.reading.interval_max_seconds" = 13.0
"oracle.reading.start_probability" = 0.63
''', encoding='utf-8')
        library = BehaviorStyleLibrary.load(self.root)
        self.assertFalse(library.errors)
        result = library.find('reading_habits.leisurely', 'reading_habits').apply(AppConfig()).oracle.reading
        self.assertEqual((result.start_probability, result.attempt_min_seconds, result.attempt_max_seconds), (.63,7,13))

