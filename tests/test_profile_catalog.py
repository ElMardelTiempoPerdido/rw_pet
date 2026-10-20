"""目录索引缓存必须及时发现包和贴图的变化"""
from datetime import datetime, timezone
from dataclasses import replace
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from rw_creature_pet.presets.catalog import cached_scan


class ProfileCatalogTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))/'profiles'
        self.root.mkdir()
        self.manifest = self.root/'profile.json'
        self.manifest.write_text('one', encoding='utf-8')
        self.texture = self.root/'image.png'
        self.texture.write_bytes(b'good')
        def load(path):
            if self.texture.read_bytes() != b'good':
                raise ValueError('invalid image')
            return SimpleNamespace(id='one', name=path.read_text(encoding='utf-8'), path=path,
                                   timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc))
        self.loader = Mock(side_effect=load)

    def scan(self):
        return cached_scan(self.root, 'profile.json', self.loader)

    def test_warm_reads_reuse_validation_but_manifest_and_image_changes_invalidate(self):
        first = self.scan()
        self.assertIs(self.scan(), first)
        self.loader.assert_called_once()
        self.manifest.write_text('renamed', encoding='utf-8')
        self.assertEqual(self.scan().presets[0].name, 'renamed')
        self.texture.write_bytes(b'broken')
        report = self.scan()
        self.assertFalse(report.presets)
        self.assertEqual(len(report.errors), 1)
        self.texture.write_bytes(b'good')
        self.assertEqual(len(self.scan().presets), 1)
        self.texture.unlink()
        self.assertEqual(len(self.scan().errors), 1)
        self.texture.write_bytes(b'good')
        self.assertEqual(len(self.scan().presets), 1)

    def test_removing_and_recreating_directory_does_not_reuse_old_results(self):
        self.scan()
        self.manifest.unlink()
        self.texture.unlink()
        self.root.rmdir()
        self.assertFalse(self.scan().presets)
        self.root.mkdir()
        self.manifest.write_text('new', encoding='utf-8')
        self.texture.write_bytes(b'good')
        self.assertEqual(self.scan().presets[0].name, 'new')

    def test_cached_real_png_error_does_not_lock_replacement_or_deletion(self):
        from PIL import Image
        from rw_creature_pet.config import AppConfig
        from rw_creature_pet.oracle.config import CustomAppearance
        from rw_creature_pet.oracle.face_config import FaceDecal
        from rw_creature_pet.presets.profile_library import ProfileLibrary
        source = self.root/'source.png'
        Image.new('RGBA', (4, 4), 'white').save(source)
        config = AppConfig()
        config = replace(config, oracle=replace(config.oracle, body_appearance='custom',
            custom_appearance=CustomAppearance(forehead=FaceDecal(True, str(source), 'source.png'))))
        library = ProfileLibrary(self.root/'real')
        preset = library.export(config, 'PNG')
        image = preset.appearance.image(preset.appearance.oracle.custom_appearance.forehead.image_path)
        original = image.read_bytes()
        Image.new('RGBA', (129, 1), 'white').save(image)
        report = library.scan()
        self.assertEqual(len(report.errors), 1)
        error = report.errors[0][1]
        self.assertIsNone(error.__traceback__)
        self.assertIsNone(error.__context__)
        self.assertIsNone(error.__cause__)
        replacement = self.root/'replacement.png'
        replacement.write_bytes(original)
        replacement.replace(image)
        self.assertEqual(len(library.scan().presets), 1)
        Image.new('RGBA', (129, 1), 'white').save(image)
        self.assertEqual(len(library.scan().errors), 1)
        image.unlink()
