"""离屏检查附加外观表单，不访问用户的配置或角色库"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from contextlib import ExitStack
from dataclasses import replace
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


def main():
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    output = ROOT/'artifacts/outfit-settings'
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as temporary, ExitStack() as stack:
        root = Path(temporary)
        stack.enter_context(patch('rw_creature_pet.presets.profile_library.default_profile_directory',
                                  return_value=root/'profiles'))
        stack.enter_context(patch('rw_creature_pet.presets.library.default_appearance_directory',
                                  return_value=root/'appearances'))
        config = AppConfig.load(ROOT/'config.toml')
        config = replace(config, oracle=replace(config.oracle, outfit='maid'))
        ProfileLibrary().export(config, 'Outfit settings', preset_id=BELL_PROFILE_ID)
        dialog = OracleSettingsDialog(config, SettingsStore(root/'settings.json'), first_run=True)
        try:
            dialog._migration_notice = False
            dialog.tabs.setCurrentWidget(dialog.pages['appearance'])
            dialog.show()
            for language in ('zh', 'en'):
                language_manager().set_language(language)
                for width in (960, 720):
                    dialog.resize(width, 850)
                    app.processEvents()
                    page = dialog.pages['appearance']
                    page.verticalScrollBar().setValue(0)
                    app.processEvents()
                    assert dialog.grab().save(str(output/f'{language}-{width}.png'))
                    assert page.horizontalScrollBar().maximum() == 0
                    for group in dialog.outfit_part_groups.values():
                        assert group.width() <= page.viewport().width()
                    prefix = 'oracle.outfit_settings.maid.lace.'
                    layer = dialog.controls[prefix+'layer']
                    layer.setCurrentIndex(layer.findData('after_cape'))
                    page.ensureWidgetVisible(dialog.outfit_part_groups[prefix])
                    app.processEvents()
                    assert dialog.grab().save(str(output/f'{language}-{width}-layers.png'))
                    assert page.horizontalScrollBar().maximum() == 0
                    layer.showPopup()
                    app.processEvents()
                    assert layer.view().grab().save(str(output/f'{language}-{width}-choices.png'))
                    layer.hidePopup()
            print('Saved:', output)
        finally:
            dialog.shutdown()
            dialog.close()


if __name__ == '__main__':
    main()
