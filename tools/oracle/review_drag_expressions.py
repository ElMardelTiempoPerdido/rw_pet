"""离屏复核中英文拖动表情面板；所有配置写入临时目录"""
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
from rw_creature_pet.oracle.assets import OracleAssets
from rw_creature_pet.oracle.config import OracleConfig
from rw_creature_pet.oracle.drag_expression_config import DragExpressionConfig, ExpressionChoice
from rw_creature_pet.oracle.graphics.render import OracleRenderer
from rw_creature_pet.oracle.ui.sections import CollapsibleSection
from rw_creature_pet.oracle.ui.settings import OracleSettingsDialog
from rw_creature_pet.presets.profile_library import ProfileLibrary
from rw_creature_pet.presets.startup import BELL_PROFILE_ID
from rw_creature_pet.settings_store import SettingsStore


def main():
    app = QApplication.instance() or QApplication([])
    output = ROOT/'artifacts/drag-expressions'
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as temporary, ExitStack() as stack:
        root = Path(temporary)
        stack.enter_context(patch('rw_creature_pet.presets.profile_library.default_profile_directory',
                                  return_value=root/'profiles'))
        stack.enter_context(patch('rw_creature_pet.presets.library.default_appearance_directory',
                                  return_value=root/'appearances'))
        game = root/'game'
        (game/'RainWorld_Data').mkdir(parents=True)
        (game/'RainWorld_Data/resources.assets').touch()
        config = AppConfig(game_dir=game, oracle=OracleConfig(drag_expressions=DragExpressionConfig(
            squeezed=ExpressionChoice(True, 3), slant_out=ExpressionChoice(True, 1, True),
            round=ExpressionChoice(True, 2))))
        ProfileLibrary().export(config, 'Expression review', preset_id=BELL_PROFILE_ID)
        d = OracleSettingsDialog(config, SettingsStore(root/'settings.json'),
                                 assets=OracleAssets(OracleRenderer(), '', {}, ''))
        try:
            d._migration_notice = False
            d.preset_workflow.set_autosave(False)
            page = d.pages['behavior']
            d.tabs.setCurrentWidget(page)
            sections = page.findChildren(CollapsibleSection)
            drag = next(s for s in sections if s.heading.text() == '拖动反应')
            for section in sections:
                section.set_expanded(section is drag)
            d.show()
            for language, width in (('zh', 960), ('en', 800)):
                language_manager().set_language(language)
                d.resize(width, 900)
                for _ in range(4):
                    app.processEvents()
                assert page.horizontalScrollBar().maximum() == 0
                d.grab().save(str(output/f'settings-{language}.png'))
                drag.grab().save(str(output/f'group-{language}.png'))
        finally:
            d.shutdown()
            d.close()
            language_manager().set_language('zh')
    print(output)


if __name__ == '__main__':
    main()
