"""本体路径自动检测：配置优先、多库、安装记录与缺失回退"""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from rw_creature_pet.shared.game_installation import find_game_directory, is_game_directory
from rw_creature_pet.shared.game_mods import steam_libraries


class GameInstallationTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(TemporaryDirectory()))
        self.steam = self.root/'Steam'
        (self.steam/'steamapps').mkdir(parents=True)
        self.enterContext(patch('rw_creature_pet.shared.game_mods._system_steam_roots',
                               return_value=[self.steam]))

    def game(self, root):
        (root/'RainWorld_Data').mkdir(parents=True)
        (root/'RainWorld_Data/resources.assets').write_bytes(b'base game fixture')
        return root.resolve()

    def test_valid_preference_wins_without_steam_lookup_or_dlc(self):
        chosen = self.game(self.root/'自选目录')
        self.game(self.steam/'steamapps/common/Rain World')
        with patch('rw_creature_pet.shared.game_installation.steam_libraries') as libraries:
            self.assertEqual(find_game_directory(chosen), chosen)
            libraries.assert_not_called()

    def test_secondary_library_both_vdf_formats_and_nonstandard_install_name(self):
        secondary = self.root/'其他游戏库'
        game = self.game(secondary/'steamapps/common/雨世界')
        (secondary/'steamapps/appmanifest_312520.acf').write_text(
            '\ufeff"AppState"\n{\n "appid" "312520"\n "installdir" "雨世界"\n}', encoding='utf-8')
        for field in ('"path"', '"1"'):
            value = str(secondary).replace('\\', '\\\\')
            (self.steam/'steamapps/libraryfolders.vdf').write_text(
                f'"libraryfolders"\n{{\n {field} "{value}"\n}}', encoding='utf-8')
            self.assertEqual(find_game_directory(self.root/'missing'), game)

    def test_default_directory_works_without_manifest_or_registry(self):
        game = self.game(self.steam/'steamapps/common/Rain World')
        self.assertEqual(find_game_directory(steam_roots=[self.steam]), game)
        # 无注册表时也能从已经配置的 Steam 路径推导原库
        self.assertEqual(find_game_directory(self.steam/'steamapps/common/old', steam_roots=[]), game)

    def test_bad_library_or_manifest_is_skipped_and_duplicates_are_removed(self):
        missing = self.root/'offline'
        game = self.game(self.steam/'steamapps/common/Rain World')
        (self.steam/'steamapps/libraryfolders.vdf').write_bytes(b'\xffbroken')
        (self.steam/'steamapps/appmanifest_312520.acf').write_bytes(b'\xffbroken')
        self.assertEqual(find_game_directory(steam_roots=[missing, self.steam, self.steam]), game)
        self.assertEqual(steam_libraries(steam_roots=[self.steam, self.steam]), (self.steam,))

    def test_manifest_cannot_escape_common_and_invalid_installs_do_not_count(self):
        self.game(self.root/'elsewhere')
        manifest = self.steam/'steamapps/appmanifest_312520.acf'
        for name in ('../../../elsewhere', '..\\..\\..\\elsewhere', str(self.root/'elsewhere'), 'Missing Game'):
            manifest.write_text(f'"installdir" "{name}"', encoding='utf-8')
            self.assertIsNone(find_game_directory(steam_roots=[self.steam]))
        self.assertFalse(is_game_directory(self.root/'elsewhere/RainWorld_Data'))

    def test_unreadable_manifests_and_empty_library_list_fall_back_cleanly(self):
        game = self.game(self.steam/'steamapps/common/Rain World')
        with patch.object(Path, 'read_text', side_effect=PermissionError('fixture')):
            self.assertEqual(find_game_directory(steam_roots=[self.steam]), game)
        self.assertIsNone(find_game_directory(steam_roots=[]))
        self.assertIsNone(find_game_directory('bad\0path', steam_roots=[]))


if __name__ == '__main__':
    unittest.main()
