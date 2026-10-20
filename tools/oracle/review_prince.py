"""离屏检查 Prince 固定绘制入口和配色面板，不使用本机用户配置"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from contextlib import ExitStack
from dataclasses import replace
from math import sqrt
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication
from rw_creature_pet.config import AppConfig
from rw_creature_pet.oracle.graphics.render import OracleRenderer
from rw_creature_pet.oracle.graphics import prince
from rw_creature_pet.oracle.scene import OracleScene
from rw_creature_pet.oracle.ui.settings import OracleSettingsDialog
from rw_creature_pet.oracle.ui.settings_style import settings_font
from rw_creature_pet.presets.profile_library import ProfileLibrary
from rw_creature_pet.presets.startup import PRINCE_PROFILE_ID, default_prince
from rw_creature_pet.settings_store import SettingsStore
from rw_creature_pet.shared.geometry import Vec2
from rw_creature_pet.shared import petal_head


def turn_range_preview(directory):
    """使用同一素材和注视输入对比旧映射与当前响应，不改变场景或用户配置"""
    sheet = QImage(1000, 460, QImage.Format.Format_ARGB32_Premultiplied)
    sheet.fill(QColor('#c5c1bc'))
    painter = QPainter(sheet)
    painter.setFont(settings_font())
    painter.setPen(QColor('#34313f'))
    cases = (('Side .5', .5, 0.), ('Side .8', .8, 0.), ('Side 1', 1., 0.),
             ('Up 1', 0., 1.), ('Diagonal', 1/sqrt(2), 1/sqrt(2)))
    try:
        for row in range(2):
            for col, (label, gx, gy) in enumerate(cases):
                if row == 0:
                    matrix = petal_head.view_matrix(Vec2(gx, -gy), sqrt(max(0., 1.-gx*gx-gy*gy)), Vec2(0., -1.))
                    image, half = petal_head.project(prince._surface(), matrix, 2., prince.DISC_RADIUS, prince.DISC_COLOR)
                else:
                    image, half = prince.head_image(gx, gy, 2.)
                x, y = col*200, row*230
                painter.drawText(x+12, y+24, f'{"Before" if row == 0 else "After"}: {label}')
                painter.drawImage(QRectF(x+100-half*5, y+130-half*5, half*10, half*10), image)
    finally:
        painter.end()
    sheet.save(str(directory/'prince-head-turn-range.png'))


def main():
    app = QApplication.instance() or QApplication([])
    directory = ROOT/'artifacts/prince'
    directory.mkdir(parents=True, exist_ok=True)
    config = default_prince(AppConfig())
    oracle = replace(config.oracle, hide_cords=True, physics_backend='python')
    scene = OracleScene(oracle)
    renderer = OracleRenderer(colors=oracle.active_colors)
    sheet = QImage(960, 440, QImage.Format.Format_ARGB32_Premultiplied)
    sheet.fill(QColor('#e8e5df'))
    painter = QPainter(sheet)
    painter.setFont(settings_font())
    try:
        for i, scale in enumerate((1., 1.5, 2., 3., 4.)):
            x = 96+i*192
            painter.setPen(QColor('#34313f'))
            painter.drawText(x-40, 28, f'prince {scale:g}x')
            painter.save()
            try:
                painter.translate(x, 190)
                painter.scale(scale, scale)
                upper = scene.body.chunks[0].position
                painter.translate(-upper.x, -upper.y)
                renderer.draw_geometry(painter, scene, arm=False, cords=False, pearl=False,
                                       halo=False, cache_body=True, raster_scale=scale)
            finally:
                painter.restore()
    finally:
        painter.end()
    sheet.save(str(directory/'prince-scales.png'))

    sheet = QImage(800, 690, QImage.Format.Format_ARGB32_Premultiplied)
    sheet.fill(QColor('#c5c1bc'))
    painter = QPainter(sheet)
    painter.setFont(settings_font())
    painter.setPen(QColor('#34313f'))
    try:
        for row, density in enumerate((1., 1.5, 2.)):
            for col, (label, gaze) in enumerate((('Front', Vec2()), ('Left', Vec2(-.7, 0)),
                                                ('Right', Vec2(.7, 0)), ('Up', Vec2(0, -.7)))):
                tile = QImage(round(40*density), round(40*density), QImage.Format.Format_ARGB32_Premultiplied)
                tile.fill(0)
                local = QPainter(tile)
                try:
                    local.scale(density, density)
                    renderer.draw_head(local, Vec2(20, 20), Vec2(20, 30), Vec2(0, -1), gaze,
                                       body_appearance='prince', raster_scale=density)
                finally:
                    local.end()
                x, y = col*200, row*230
                painter.drawText(x+16, y+24, f'{label} / {density:g}x')
                painter.drawImage(QRectF(x, y+30, 200, 200), tile)
    finally:
        painter.end()
    sheet.save(str(directory/'prince-head-views.png'))
    turn_range_preview(directory)

    with tempfile.TemporaryDirectory() as temporary, ExitStack() as stack:
        root = Path(temporary)
        stack.enter_context(patch('rw_creature_pet.presets.profile_library.default_profile_directory',
                                  return_value=root/'profiles'))
        stack.enter_context(patch('rw_creature_pet.presets.library.default_appearance_directory',
                                  return_value=root/'appearances'))
        game = root/'game'
        (game/'RainWorld_Data').mkdir(parents=True)
        (game/'RainWorld_Data/resources.assets').touch()
        config = replace(config, game_dir=game, oracle=oracle)
        ProfileLibrary().export(config, 'prince', preset_id=PRINCE_PROFILE_ID)
        dialog = OracleSettingsDialog(config, SettingsStore(root/'settings.json'), first_run=True)
        try:
            dialog._migration_notice = False
            dialog.tabs.setCurrentWidget(dialog.pages['appearance'])
            dialog.show()
            dialog.resize(1000, 860)
            for _ in range(3):
                app.processEvents()
            assert dialog.bell_parameters.isHidden() and dialog.custom_parameters.isHidden()
            assert dialog.outfit_section.isHidden()
            assert dialog.pages['appearance'].horizontalScrollBar().maximum() == 0
            dialog.grab().save(str(directory/'prince-settings.png'))
        finally:
            dialog.shutdown()
            dialog.close()
    print(directory)


if __name__ == '__main__':
    main()
