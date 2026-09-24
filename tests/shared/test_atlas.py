"""共享图集还原、着色及缓存测试。"""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from PySide6.QtGui import QColor, QImage
from rw_creature_pet.shared.atlas import Atlas, AtlasError, extract_atlas


class AtlasTests(unittest.TestCase):
    def test_atlas_trim_tint_cache_and_missing_frame(self):
        with TemporaryDirectory() as folder:
            folder = Path(folder)
            image = QImage(4, 4, QImage.Format.Format_ARGB32)
            image.fill(QColor('white'))
            image.save(str(folder / 'rainWorld.png'))
            entry = {'frame': {'x': 1, 'y': 1, 'w': 2, 'h': 2}, 'trimmed': True,
                     'sourceSize': {'w': 8, 'h': 8}, 'spriteSourceSize': {'x': 3, 'y': 2}}
            (folder / 'rainWorld.json').write_text(json.dumps({'frames': {'test.png': entry}}), encoding='utf-8')
            atlas = Atlas(folder)
            sprite = atlas.sprite('test', '#141414')
            self.assertEqual((sprite.width(), sprite.height()), (8, 8))
            self.assertEqual(sprite.pixelColor(0, 0).alpha(), 0)
            self.assertEqual(sprite.pixelColor(3, 2), QColor('#141414'))
            self.assertIs(sprite, atlas.sprite('test', '#141414'))
            self.assertEqual(atlas.sprite('test').pixelColor(3, 2), QColor('white'))
            with self.assertRaises(AtlasError):
                atlas.sprite('missing')
            with self.assertRaises(AtlasError):
                extract_atlas(folder)

