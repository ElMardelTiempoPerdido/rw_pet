"""离屏检查角色分享入口与导入冲突对话框，角色库和 settings 全部隔离"""
from contextlib import ExitStack
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication
from rw_creature_pet.config import AppConfig
from rw_creature_pet.i18n import language_manager
from rw_creature_pet.oracle.ui.settings import OracleSettingsDialog
from rw_creature_pet.oracle.ui.preset_dialogs import ProfileConflictDialog
from rw_creature_pet.presets.profile_library import ProfileLibrary
from rw_creature_pet.settings_store import SettingsStore
from rw_creature_pet.ui_config import UiConfig


def main():
    app = QApplication.instance() or QApplication([])
    app.setFont(QFont('Microsoft YaHei UI', 10))
    app.setStyle('Fusion')
    output = ROOT/'artifacts/profile-sharing-ui'
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as temporary, ExitStack() as stack:
        root = Path(temporary)
        stack.enter_context(patch('rw_creature_pet.presets.profile_library.default_profile_directory',
                                  return_value=root/'profiles'))
        stack.enter_context(patch('rw_creature_pet.presets.library.default_appearance_directory',
                                  return_value=root/'appearances'))
        config = AppConfig(ui=UiConfig('zh'))
        ProfileLibrary().export(config, '分享预览角色')
        dialog = OracleSettingsDialog(config, SettingsStore(root/'settings.json'), assets=object())
        dialog.tabs.setCurrentIndex(next(i for i in range(dialog.tabs.count())
                                        if dialog.tabs.tabText(i) == '角色设置'))
        for language in ('zh', 'en'):
            language_manager().set_language(language)
            for width in (800, 1100):
                dialog.resize(width, 750)
                dialog.show()
                app.processEvents()
                panel = dialog.profile_presets
                assert panel.share_hint.width() > 250, '分享说明横向空间不足'
                assert panel.export_button.width() >= panel.export_button.sizeHint().width()
                dialog.grab().save(str(output/f'settings-{language}-{width}.png'))
            conflict = ProfileConflictDialog(dialog, '分享预览角色')
            conflict.show()
            app.processEvents()
            assert conflict.selection == 'keep'
            conflict.grab().save(str(output/f'conflict-{language}.png'))
            conflict.close()
        dialog.preset_workflow.state.autosave = False
        dialog.shutdown()
        dialog.close()
    print(output)


if __name__ == '__main__':
    main()
