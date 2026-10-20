"""离屏检查衣袍长度、下摆张开与底边弧度，不读取或修改本机角色"""
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
from PySide6.QtCore import QPoint, QRectF
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication
from rw_creature_pet.config import AppConfig
from rw_creature_pet.i18n import language_manager
from rw_creature_pet.oracle.config import CustomAppearance, OracleConfig
from rw_creature_pet.oracle.graphics.render import OracleRenderer
from rw_creature_pet.oracle.scene import OracleScene
from rw_creature_pet.oracle.ui.sections import CollapsibleSection
from rw_creature_pet.oracle.ui.settings import OracleSettingsDialog
from rw_creature_pet.oracle.ui.settings_style import settings_font
from rw_creature_pet.presets.profile_library import ProfileLibrary
from rw_creature_pet.presets.startup import BELL_PROFILE_ID
from rw_creature_pet.settings_store import SettingsStore


def main():
    app = QApplication.instance() or QApplication([])
    directory = ROOT/'artifacts/robe-shape'
    directory.mkdir(parents=True, exist_ok=True)
    base = OracleConfig(body_appearance='custom', hide_cords=True, physics_backend='python')
    sheet = QImage(840, 930, QImage.Format.Format_ARGB32_Premultiplied)
    sheet.fill(QColor('#26333c'))
    canvas = QPainter(sheet)
    canvas.setFont(settings_font())
    cases = [('Length', dict(robe_length=v), str(v)) for v in (.7, 1., 1.5)]
    cases += [('Flare', dict(robe_flare=v), f'{v*100:g}%') for v in (0., 1., 2.)]
    cases += [('Curve', dict(robe_hem_curve=v), f'{v*100:g}%') for v in (0., 1., 2.)]
    try:
        for i, (name, values, label) in enumerate(cases):
            scene = OracleScene(replace(base, custom_appearance=CustomAppearance(**values)))
            renderer = OracleRenderer()
            tile = QImage(140, 140, QImage.Format.Format_ARGB32_Premultiplied)
            tile.fill(0)
            painter = QPainter(tile)
            try:
                upper = scene.body.chunks[0].position
                painter.scale(2., 2.)
                painter.translate(35-upper.x, 25-upper.y)
                renderer.draw_geometry(painter, scene, arm=False, cords=False, pearl=False,
                                       halo=False, cache_body=True, raster_scale=2.)
            finally:
                painter.end()
            x, y = i%3*280, i//3*310
            canvas.drawImage(QRectF(x, y+30, 280, 280), tile)
            canvas.setPen(QColor('#e0e8ef'))
            canvas.drawText(x+16, y+25, f'{name}: {label}')
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
        config = AppConfig(game_dir=game, oracle=base)
        ProfileLibrary().export(config, 'Robe review', preset_id=BELL_PROFILE_ID)
        dialog = OracleSettingsDialog(config, SettingsStore(root/'settings.json'), first_run=True)
        try:
            dialog._migration_notice = False
            page = dialog.pages['appearance']
            dialog.tabs.setCurrentWidget(page)
            section = next(s for s in page.findChildren(CollapsibleSection) if s.heading.text() == '基础体型')
            section.set_expanded(True)
            dialog.show()
            for language, width in (('zh', 960), ('en', 800)):
                language_manager().set_language(language)
                dialog.resize(width, 1000)
                for _ in range(3):
                    app.processEvents()
                page.verticalScrollBar().setValue(section.mapTo(page.widget(), QPoint()).y()-12)
                app.processEvents()
                assert page.horizontalScrollBar().maximum() == 0
                section.grab().save(str(directory/f'settings-{language}.png'))
        finally:
            dialog.shutdown()
            dialog.close()
    print(directory)


if __name__ == '__main__':
    main()
