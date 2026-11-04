"""离屏检查行为范围输入框，不读取或改写用户角色目录"""
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
from PySide6.QtTest import QSignalSpy, QTest
from rw_creature_pet.config import AppConfig
from rw_creature_pet.i18n import language_manager
from rw_creature_pet.oracle.assets import OracleAssets
from rw_creature_pet.oracle.graphics.render import OracleRenderer
from rw_creature_pet.oracle.ui.number_range import NumberRange
from rw_creature_pet.oracle.ui.form_layout import ContentForm
from rw_creature_pet.oracle.ui.settings import OracleSettingsDialog
from rw_creature_pet.presets.profile_library import ProfileLibrary
from rw_creature_pet.presets.startup import BELL_PROFILE_ID
from rw_creature_pet.settings_store import SettingsStore


def settle(dialog):
    forms = dialog.findChildren(ContentForm)
    spies = [QSignalSpy(form._reflow_timer.timeout) for form in forms]
    previous, quiet = -1, 0
    for _ in range(40):
        QTest.qWait(10)
        count = sum(spy.count() for spy in spies)
        quiet = quiet + 1 if count == previous else 0
        previous = count
        if quiet >= 3 and not any(form._reflow_timer.isActive() for form in forms):
            return
    raise AssertionError('Settings layout did not settle')


def main():
    app = QApplication.instance() or QApplication([])
    scale = os.environ.get('QT_SCALE_FACTOR', '1')
    output = ROOT/'artifacts/behavior-layout'/scale
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
        config = AppConfig(game_dir=game)
        ProfileLibrary().export(config, 'Range review', preset_id=BELL_PROFILE_ID)
        d = OracleSettingsDialog(config, SettingsStore(root/'settings.json'),
                                 assets=OracleAssets(OracleRenderer(), '', {}, ''))
        try:
            d._migration_notice = False
            d.preset_workflow.set_autosave(False)
            page = d.pages['behavior']
            d.tabs.setCurrentWidget(page)
            for group in d.behavior_styles.groups.values():
                group.advanced.setChecked(True)
            d.show()
            for language, width in (('zh', 960), ('en', 800)):
                language_manager().set_language(language)
                d.resize(width, 900)
                settle(d)
                assert page.horizontalScrollBar().maximum() == 0
                page.verticalScrollBar().setValue(0)
                settle(d)
                d.grab().save(str(output/f'page-{language}.png'))
                for dimension, group in d.behavior_styles.groups.items():
                    group.grab().save(str(output/f'{dimension}-{language}.png'))
                control = d.controls['oracle.daily_activity.meditate_min_seconds']
                field = control.parentWidget()
                assert isinstance(field, NumberRange)
                field.grab().save(str(output/f'meditation-{language}.png'))
                d.assets.resources.record('bell_voice', error='missing')
                d.resource_settings.install(d.assets)
                settle(d)
                d.behavior_styles.groups['drag_reactions'].grab().save(str(output/f'disabled-{language}.png'))
        finally:
            d.shutdown()
            d.close()
            language_manager().set_language('zh')
    print(output)


if __name__ == '__main__':
    main()
