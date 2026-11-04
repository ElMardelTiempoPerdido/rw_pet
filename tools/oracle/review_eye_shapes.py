"""离屏检查六种眼形和中英文编辑器，不读取或改写本机角色"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from contextlib import ExitStack
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QPoint, QRectF
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication
from rw_creature_pet.config import AppConfig
from rw_creature_pet.i18n import language_manager
from rw_creature_pet.oracle.assets import OracleAssets
from rw_creature_pet.oracle.config import CustomAppearance, OracleConfig, OracleColors
from rw_creature_pet.oracle.eye_config import EYE_KINDS, EyeAppearance
from rw_creature_pet.oracle.graphics.render import OracleRenderer
from rw_creature_pet.oracle.ui.sections import CollapsibleSection
from rw_creature_pet.oracle.ui.settings import OracleSettingsDialog
from rw_creature_pet.oracle.ui.settings_style import settings_font
from rw_creature_pet.presets.profile_library import ProfileLibrary
from rw_creature_pet.presets.startup import BELL_PROFILE_ID
from rw_creature_pet.settings_store import SettingsStore
from rw_creature_pet.shared.geometry import Vec2


def main():
    app = QApplication.instance() or QApplication([])
    directory = ROOT/'artifacts/eye-shapes'
    directory.mkdir(parents=True, exist_ok=True)
    sheet = QImage(720, 510, QImage.Format.Format_ARGB32_Premultiplied)
    sheet.fill(QColor('#e8edf2'))
    canvas = QPainter(sheet)
    font = settings_font()
    font.setPixelSize(20)
    canvas.setFont(font)
    renderer = OracleRenderer(colors=OracleColors(skin='#a2f39e'))
    try:
        for i, (kind, label) in enumerate(EYE_KINDS[1:]):
            shape = CustomAppearance(eye_1=EyeAppearance('#000000', kind=kind),
                                     eye_2=EyeAppearance('#000000', kind=kind))
            image = QImage(48, 48, QImage.Format.Format_ARGB32_Premultiplied)
            image.fill(0)
            painter = QPainter(image)
            renderer.draw_head(painter, Vec2(24, 24), Vec2(24, 38), Vec2(0, -1), Vec2(),
                               shape=shape, pixelated=True)
            painter.end()
            x, y = i%3*240, i//3*255
            canvas.setPen(QColor('#203040'))
            canvas.drawText(x+100, y+28, label)
            strip = QRectF(x+36, y+50, 168, 60)
            canvas.fillRect(strip, QColor(renderer.colors.skin))
            canvas.drawImage(strip, image.copy(18, 25, 14, 5))
            canvas.drawImage(QRectF(x+72, y+130, 96, 96), image.copy(12, 12, 24, 24))
    finally:
        canvas.end()
    sheet.save(str(directory/'shapes.png'))

    with tempfile.TemporaryDirectory() as temporary, ExitStack() as stack:
        root = Path(temporary)
        stack.enter_context(patch('rw_creature_pet.presets.profile_library.default_profile_directory',
                                  return_value=root/'profiles'))
        stack.enter_context(patch('rw_creature_pet.presets.library.default_appearance_directory',
                                  return_value=root/'appearances'))
        game = root/'game'
        (game/'RainWorld_Data').mkdir(parents=True)
        (game/'RainWorld_Data/resources.assets').touch()
        config = AppConfig(game_dir=game, oracle=OracleConfig(body_appearance='custom',
            custom_appearance=CustomAppearance(eye_1=EyeAppearance(kind='round'),
                                               eye_2=EyeAppearance(default_open=True))))
        ProfileLibrary().export(config, 'Eye review', preset_id=BELL_PROFILE_ID)
        dialog = OracleSettingsDialog(config, SettingsStore(root/'settings.json'),
                                      assets=OracleAssets(OracleRenderer(), '', {}, ''))
        try:
            dialog._migration_notice = False
            page = dialog.pages['appearance']
            dialog.tabs.setCurrentWidget(page)
            section = next(s for s in page.findChildren(CollapsibleSection) if s.heading.text() == '眼睛')
            section.set_expanded(True)
            dialog.show()
            dialog.open_face_preview()
            for language, width in (('zh', 960), ('en', 800)):
                language_manager().set_language(language)
                dialog.resize(width, 900)
                dialog.face_preview.resize(1000, 780)
                for _ in range(3):
                    app.processEvents()
                page.verticalScrollBar().setValue(section.mapTo(page.widget(), QPoint()).y()-12)
                app.processEvents()
                assert page.horizontalScrollBar().maximum() == 0
                section.grab().save(str(directory/f'settings-{language}.png'))
                dialog.face_preview.grab().save(str(directory/f'preview-{language}.png'))
        finally:
            dialog.shutdown()
            dialog.close()
            language_manager().set_language('zh')
    print(directory)


if __name__ == '__main__':
    main()
