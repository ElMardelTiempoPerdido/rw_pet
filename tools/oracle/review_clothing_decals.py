"""用测试 PNG 离屏检查服装贴图的姿态、遮挡、像素倍率和设置布局，不读取本机角色"""
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
from rw_creature_pet.oracle.clothing_config import ClothingDecal
from rw_creature_pet.oracle.graphics.appearance import rotate
from rw_creature_pet.oracle.graphics.render import OracleRenderer
from rw_creature_pet.oracle.ui.settings import OracleSettingsDialog
from rw_creature_pet.oracle.ui.settings_style import settings_font
from rw_creature_pet.presets.profile_library import ProfileLibrary
from rw_creature_pet.presets.startup import BELL_PROFILE_ID
from rw_creature_pet.settings_store import SettingsStore
from tools.oracle.review_cape import pose_scene


def test_pngs(directory):
    paths = []
    for name, w, h, color in (('robe', 20, 32, '#87bde8'),
                              ('left', 8, 20, '#e8be87'), ('right', 8, 20, '#c296e0')):
        image = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(0)
        painter = QPainter(image)
        for y in range(0, h, 4):
            for x in range(0, w, 4):
                painter.fillRect(x, y, 3, 3, QColor(color))
        painter.end()
        path = directory/(name+'.png')
        image.save(str(path))
        paths.append(path)
    return paths


def configured_scene(paths, pose='rest', angle=0, *, cape=False, outfit='normal'):
    scene, upper, direction = pose_scene(pose=pose, angle=angle)
    slots = {f'clothing_decal_{i}': ClothingDecal(enabled=True, part=part, image_path=str(path),
                image_name=path.name, offset_y=2.)
             for i, (part, path) in enumerate(zip(('robe', 'left_sleeve', 'right_sleeve'), paths), 1)}
    shape = replace(scene.config.custom_appearance, **slots,
                    cape=replace(scene.config.custom_appearance.cape, enabled=cape))
    scene.config = replace(scene.config, custom_appearance=shape, outfit=outfit)
    return scene, upper, direction


def inner_preview(directory, paths):
    sheet = QImage(1200, 620, QImage.Format.Format_ARGB32_Premultiplied)
    sheet.fill(QColor('#26333c'))
    canvas = QPainter(sheet)
    canvas.setFont(settings_font())
    poses = ((0, 0, 0, True, 'normal', 'Rest'), (0, .5, 0, True, 'normal', 'Head turns'),
             (0, -.4, .5, True, 'normal', 'Waist bends'), (90, .3, -.3, True, 'normal', 'Sideways'),
             (0, 0, 0, False, 'normal', 'Collar hidden'), (0, .3, 0, True, 'maid', 'Under outfit'))
    try:
        for i, (angle, neck, waist, collar, outfit, label) in enumerate(poses):
            scene, upper, direction = configured_scene(paths, 'single', angle, outfit=outfit)
            shape = replace(scene.config.custom_appearance,
                clothing_decal_1=ClothingDecal(enabled=True, part='inner_robe', image_path=str(paths[0])),
                clothing_decal_2=ClothingDecal(), clothing_decal_3=ClothingDecal(),
                inner_collar_enabled=collar, inner_collar_top_width=8., inner_collar_bottom_width=8.)
            scene.config = replace(scene.config, custom_appearance=shape)
            appearance = scene.appearance
            appearance.head.position = appearance.head.previous_position = upper+rotate(direction, neck)*14
            appearance.waist_angle = appearance.previous_waist_angle = waist
            appearance.lower = upper-rotate(direction, waist)*9
            renderer = OracleRenderer()
            renderer.colors = scene.config.active_colors
            tile = QImage(200, 140, QImage.Format.Format_ARGB32_Premultiplied)
            tile.fill(0)
            painter = QPainter(tile)
            try:
                painter.scale(2, 2)
                painter.translate(28-upper.x, 29-upper.y)
                renderer.draw_geometry(painter, scene, arm=False, cords=False, pearl=False,
                                       halo=False, cache_body=True, raster_scale=2.)
                painter.translate(49, 0)
                renderer.draw_inner_robe(painter, upper, appearance.lower, direction, appearance.head.position,
                    lower_direction=rotate(direction, waist), shape=shape, scene=scene)
            finally:
                painter.end()
            x, y = i%3*400, i//3*310
            canvas.drawImage(QRectF(x, y+30, 400, 280), tile)
            canvas.setPen(QColor('#e0e8ef'))
            canvas.drawText(x+16, y+25, label)
    finally:
        canvas.end()
    sheet.save(str(directory/'inner-poses.png'))


def main():
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    directory = ROOT/'artifacts/clothing-decals'
    directory.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as temporary, ExitStack() as stack:
        root = Path(temporary)
        paths = test_pngs(root)
        inner_preview(directory, paths)
        sheet = QImage(960, 640, QImage.Format.Format_ARGB32_Premultiplied)
        sheet.fill(QColor('#26333c'))
        canvas = QPainter(sheet)
        canvas.setFont(settings_font())
        poses = (('rest', 0, False, 'normal', 'Arms down'), ('both', 0, False, 'normal', 'Arms raised'),
                 ('single', 0, False, 'normal', 'One arm raised'), ('single', 155, False, 'normal', 'Rotated'),
                 ('both', 0, True, 'normal', 'Under cape'), ('single', 0, False, 'maid', 'With maid outfit'))
        for i, (pose, angle, cape, outfit, label) in enumerate(poses):
            scene, upper, _ = configured_scene(paths, pose, angle, cape=cape, outfit=outfit)
            renderer = OracleRenderer()
            renderer.colors = scene.config.active_colors
            tile = QImage(160, 140, QImage.Format.Format_ARGB32_Premultiplied)
            tile.fill(0)
            painter = QPainter(tile)
            painter.scale(2., 2.)
            painter.translate(40-upper.x, 33-upper.y)
            renderer.draw_geometry(painter, scene, arm=False, cords=False, pearl=False,
                                   halo=False, cache_body=True, raster_scale=2.)
            painter.end()
            x, y = i%3*320, i//3*320
            canvas.drawImage(QRectF(x, y+30, 320, 280), tile)
            canvas.setPen(QColor('#e0e8ef'))
            canvas.drawText(x+16, y+25, label)
        canvas.end()
        sheet.save(str(directory/'poses.png'))

        stack.enter_context(patch('rw_creature_pet.presets.profile_library.default_profile_directory',
                                  return_value=root/'profiles'))
        stack.enter_context(patch('rw_creature_pet.presets.library.default_appearance_directory',
                                  return_value=root/'appearances'))
        game = root/'game'
        (game/'RainWorld_Data').mkdir(parents=True)
        (game/'RainWorld_Data/resources.assets').touch()
        scene, _, _ = configured_scene(paths)
        config = AppConfig(game_dir=game, oracle=scene.config)
        ProfileLibrary().export(config, 'Clothing review', preset_id=BELL_PROFILE_ID)
        dialog = OracleSettingsDialog(config, SettingsStore(root/'settings.json'), first_run=True)
        try:
            dialog._migration_notice = False
            page = dialog.pages['appearance']
            dialog.tabs.setCurrentWidget(page)
            dialog.show()
            for language, width in (('zh', 960), ('en', 800)):
                language_manager().set_language(language)
                dialog.resize(width, 1100)
                for _ in range(3):
                    app.processEvents()
                first = dialog.clothing_editors['clothing_decal_1']
                first.part.setCurrentIndex(first.part.findData('inner_robe'))
                page.verticalScrollBar().setValue(first.mapTo(page.widget(), QPoint()).y()-12)
                app.processEvents()
                assert page.horizontalScrollBar().maximum() == 0
                for editor in dialog.clothing_editors.values():
                    assert editor.height() >= editor.minimumSizeHint().height()
                    assert editor.rect().contains(editor.part.geometry())
                dialog.grab().save(str(directory/f'settings-{language}.png'))
        finally:
            dialog.shutdown()
            dialog.close()
    print(directory)


if __name__ == '__main__':
    main()
