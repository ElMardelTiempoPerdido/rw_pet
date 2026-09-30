from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from rw_creature_pet.config import AppConfig
from rw_creature_pet.overseer.config import OverseerConfig
from rw_creature_pet.settings_store import SettingsStore


class OverseerConfigTests(unittest.TestCase):
    def test_toml_and_user_settings_roundtrip(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'test.toml'
            path.write_text("[overseer]\ncolor='#ffcc99'\nsafe_delay=0.7\n", encoding='utf-8')
            config = AppConfig.load(path)
            self.assertEqual(config.overseer.color, '#ffcc99')
            self.assertEqual(config.overseer.safe_delay, .7)
            self.assertEqual(AppConfig.from_mapping({}).overseer, OverseerConfig())
            store = SettingsStore(Path(temp)/'settings.json')
            store.save(config)
            self.assertEqual(store.load().overseer, config.overseer)

    def test_invalid_ranges_and_colors_fail_early(self):
        for value in ('red', '#12345', None, 12):
            with self.subTest(color=value), self.assertRaises(ValueError):
                replace(OverseerConfig(), color=value)
        for key in ('withdraw_distance', 'reemerge_distance', 'emerge_seconds', 'withdraw_seconds'):
            for value in (-1, 0, True, float('nan'), float('inf')):
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    replace(OverseerConfig(), **{key: value})
        with self.assertRaises(ValueError):
            replace(OverseerConfig(), reemerge_distance=60)
        with self.assertRaises(ValueError):
            replace(OverseerConfig(), safe_delay=-1)


if __name__ == '__main__':
    unittest.main()
