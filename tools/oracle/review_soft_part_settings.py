"""离屏检查柔性部件设置，仅使用临时角色库和配置"""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from contextlib import ExitStack
from dataclasses import replace
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from PySide6.QtCore import QPoint
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from rw_creature_pet.config import AppConfig
from rw_creature_pet.i18n import language_manager
from rw_creature_pet.oracle.soft_part_config import SoftPart
from rw_creature_pet.oracle.ui.settings import OracleSettingsDialog
from rw_creature_pet.presets.profile_library import ProfileLibrary
from rw_creature_pet.presets.startup import BELL_PROFILE_ID
from rw_creature_pet.settings_store import SettingsStore


def main():
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    output = ROOT/'artifacts/soft-parts/settings'
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as temporary, ExitStack() as stack:
        root = Path(temporary)
        stack.enter_context(patch('rw_creature_pet.presets.profile_library.default_profile_directory',
                                  return_value=root/'profiles'))
        stack.enter_context(patch('rw_creature_pet.presets.library.default_appearance_directory',
                                  return_value=root/'appearances'))
        image = QImage(12, 64, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(QColor('#e4cda9'))
        painter = QPainter(image)
        for y in range(8, 64, 12):
            painter.fillRect(0, y, 12, 3, QColor('#b45c6e'))
        painter.end()
        source = root/'scarf.png'
        image.save(str(source))
        config = AppConfig.load(ROOT/'config.toml')
        shape = replace(config.oracle.custom_appearance,
            soft_part_1=SoftPart(enabled=True),
            soft_part_2=SoftPart(enabled=True, kind='trapezoid', layer='back', width=8, length=40))
        config = replace(config, oracle=replace(config.oracle, body_appearance='custom', custom_appearance=shape))
        ProfileLibrary().export(config, 'Soft accessories', preset_id=BELL_PROFILE_ID)
        dialog = OracleSettingsDialog(config, SettingsStore(root/'settings.json'), first_run=True)
        try:
            dialog._migration_notice = False
            dialog.tabs.setCurrentWidget(dialog.pages['appearance'])
            dialog.show()
            page = dialog.pages['appearance']
            editor = dialog.soft_part_editors['soft_part_1']
            for language in ('zh', 'en'):
                language_manager().set_language(language)
                for width in (960, 720):
                    dialog.resize(width, 1040)
                    editor.setValue(replace(editor.value(), kind='rectangle', image_path='', image_name=''))
                    for state in ('geometry', 'png-empty', 'png-imported'):
                        if state == 'png-empty':
                            control = editor.parameter_controls['kind']
                            control.setCurrentIndex(control.findData('png'))
                        elif state == 'png-imported':
                            assert editor.import_file(source)
                        QTest.qWait(120)
                        page.verticalScrollBar().setValue(editor.mapTo(page.widget(), QPoint()).y()-12)
                        app.processEvents()
                        assert page.horizontalScrollBar().maximum() == 0
                        for group in dialog.soft_part_editors.values():
                            assert group.width() <= page.viewport().width()
                            assert group.height() >= group.heightForWidth(group.width())
                        second = dialog.soft_part_editors['soft_part_2']
                        assert editor.geometry().bottom() < second.geometry().top()
                        assert dialog.grab().save(str(output/f'{language}-{width}-{state}.png'))
            print(output)
        finally:
            dialog.shutdown()
            dialog.close()


if __name__ == '__main__':
    main()
