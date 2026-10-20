"""离屏检查斗篷设置的中英文布局，使用临时角色库"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from contextlib import ExitStack
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from PySide6.QtWidgets import QApplication
from rw_creature_pet.config import AppConfig
from rw_creature_pet.i18n import language_manager
from rw_creature_pet.oracle.ui.settings import OracleSettingsDialog
from rw_creature_pet.presets.profile_library import ProfileLibrary
from rw_creature_pet.presets.startup import BELL_PROFILE_ID
from rw_creature_pet.settings_store import SettingsStore
from tools.oracle.review_cape import pose_scene


def main():
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    directory = ROOT/'artifacts/cape'
    directory.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as temporary, ExitStack() as stack:
        root = Path(temporary)
        stack.enter_context(patch('rw_creature_pet.presets.profile_library.default_profile_directory',
                                  return_value=root/'profiles'))
        stack.enter_context(patch('rw_creature_pet.presets.library.default_appearance_directory',
                                  return_value=root/'appearances'))
        game = root/'game'
        (game/'RainWorld_Data').mkdir(parents=True)
        (game/'RainWorld_Data/resources.assets').touch()
        scene, _, _ = pose_scene()
        config = AppConfig(game_dir=game, oracle=scene.config)
        ProfileLibrary().export(config, 'Cape review', preset_id=BELL_PROFILE_ID)
        dialog = OracleSettingsDialog(config, SettingsStore(root/'settings.json'), first_run=True)
        try:
            dialog._migration_notice = False
            dialog.tabs.setCurrentWidget(dialog.pages['appearance'])
            dialog.show()
            for language in ('zh', 'en'):
                language_manager().set_language(language)
                for width in (800, 960):
                    dialog.resize(width, 1000)
                    app.processEvents()
                    page = dialog.pages['appearance']
                    page.ensureWidgetVisible(dialog.cape_group)
                    app.processEvents()
                    assert page.horizontalScrollBar().maximum() == 0
                    assert dialog.grab().save(str(directory/f'settings-{language}-{width}.png'))
                    for field in ('enabled', 'hem_trim_enabled'):
                        control = dialog.controls['oracle.custom_appearance.cape.'+field]
                        control.setChecked(False)
                        app.processEvents()
                        control.setChecked(True)
                    assert not page.horizontalScrollBar().maximum()
            print('Saved:', directory)
        finally:
            dialog.shutdown()
            dialog.close()


if __name__ == '__main__':
    main()
