from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from rw_creature_pet.config import AppConfig
from rw_creature_pet.overseer.config import OverseerConfig, OverseerSlot
from rw_creature_pet.settings_store import SettingsStore


class OverseerConfigTests(unittest.TestCase):
    def test_slot_shape_defaults_legacy_size_and_roundtrip(self):
        legacy = AppConfig.from_mapping({'overseer': {'size': .83, 'slots': [
            {'id': 1, 'color': '#ffffff'}, {'id': 2, 'appearance': 'friend'}]}})
        self.assertEqual([s.size for s in legacy.overseer.slots], [.83, .83])
        self.assertEqual([s.filament_count for s in legacy.overseer.slots], [4, 4])
        self.assertEqual(OverseerConfig(size=.9).slots[0].size, .9)
        self.assertEqual(OverseerSlot().size, .6)
        slots = (OverseerSlot(1, size=.5, filament_count=3),
                 OverseerSlot(2, appearance='friend', size=1., filament_count=5))
        config = replace(legacy, overseer=replace(legacy.overseer, slots=slots))
        with tempfile.TemporaryDirectory() as temp:
            store = SettingsStore(Path(temp)/'settings.json')
            store.save(config)
            self.assertEqual(store.load().overseer.slots, slots)
            path = Path(temp)/'slots.toml'
            path.write_text('[overseer]\nsize=0.9\nslots=[{id=1,size=0.5,filament_count=3},'
                            '{id=2,appearance="friend",size=1.0,filament_count=5}]\n', encoding='utf-8')
            self.assertEqual(AppConfig.load(path).overseer.slots, slots)

    def test_slot_and_single_model_reject_invalid_shapes(self):
        for cls in (OverseerSlot, OverseerConfig):
            for size in (.49, 1.01, True, None, '0.6', float('nan'), float('inf')):
                with self.subTest(cls=cls, size=size), self.assertRaises(ValueError):
                    cls(size=size)
            for count in (-1, 0, 2, 6, 8, True, 2.5, '4', None):
                with self.subTest(cls=cls, count=count), self.assertRaises(ValueError):
                    cls(filament_count=count)

    def test_toml_and_user_settings_roundtrip(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'test.toml'
            path.write_text("[overseer]\ncolor='#ffcc99'\nsafe_delay=0.7\nenabled=true\n"
                            "check_interval=2.5\nappearance_probability=0.8\nduration_min=8.0\n"
                            "duration_max=9.0\ncooldown_min=3.0\ncooldown_max=4.0\n"
                            "relocation_probability=0.7\npuppet_withdraw_distance=110\n"
                            "puppet_reemerge_distance=170\nobservation_probability=0.8\n"
                            "observation_interval=15\n", encoding='utf-8')
            config = AppConfig.load(path)
            self.assertEqual(config.overseer.color, '#ffcc99')
            self.assertEqual(config.overseer.safe_delay, .7)
            self.assertTrue(config.overseer.enabled)
            self.assertEqual(config.overseer.check_interval, 2.5)
            self.assertEqual(config.overseer.appearance_probability, .8)
            self.assertEqual(config.overseer.relocation_probability, .7)
            self.assertEqual(config.overseer.puppet_withdraw_distance, 110)
            self.assertEqual(config.overseer.puppet_reemerge_distance, 170)
            self.assertEqual(config.overseer.observation_probability, .8)
            self.assertEqual(config.overseer.observation_interval, 15)
            self.assertEqual(AppConfig.from_mapping({}).overseer, OverseerConfig())
            store = SettingsStore(Path(temp)/'settings.json')
            store.save(config)
            self.assertEqual(store.load().overseer, config.overseer)

    def test_invalid_ranges_and_colors_fail_early(self):
        for value in ('red', '#12345', None, 12):
            with self.subTest(color=value), self.assertRaises(ValueError):
                replace(OverseerConfig(), color=value)
        for key in ('withdraw_distance', 'reemerge_distance', 'emerge_seconds', 'withdraw_seconds',
                    'puppet_withdraw_distance', 'puppet_reemerge_distance', 'observation_interval'):
            for value in (-1, 0, True, float('nan'), float('inf')):
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    replace(OverseerConfig(), **{key: value})
        with self.assertRaises(ValueError):
            replace(OverseerConfig(), reemerge_distance=60)
        with self.assertRaises(ValueError):
            replace(OverseerConfig(), safe_delay=-1)
        with self.assertRaises(ValueError):
            replace(OverseerConfig(), puppet_reemerge_distance=100)

    def test_invalid_event_parameters(self):
        for key in ('check_interval', 'duration_min', 'duration_max', 'cooldown_min', 'cooldown_max',
                    'appearance_probability', 'relocation_probability', 'observation_probability'):
            for value in (-1, True, float('nan'), float('inf'), '1'):
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    replace(OverseerConfig(), **{key: value})
        for values in (dict(enabled=1), dict(check_interval=0), dict(appearance_probability=1.01),
                       dict(duration_min=50), dict(cooldown_min=121), dict(duration_min=0),
                       dict(relocation_probability=1.01), dict(observation_probability=1.01)):
            with self.subTest(values=values), self.assertRaises(ValueError):
                replace(OverseerConfig(), **values)


if __name__ == '__main__':
    unittest.main()
