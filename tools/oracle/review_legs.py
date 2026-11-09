"""离屏预览腿长、跟随和设置入口；只使用临时角色，不修改本机预设"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'

from contextlib import ExitStack
from dataclasses import replace
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch
from PIL import Image

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
from rw_creature_pet.shared.atlas import Atlas, extract_atlas
from rw_creature_pet.shared.geometry import Vec2


def motion_preview(base, atlas, output):
    scene = OracleScene(replace(base, custom_appearance=CustomAppearance(robe_length=.7, leg_length=20.)))
    renderer = OracleRenderer(atlas, base.custom_colors)
    for _ in range(500):
        scene.step()
    scene.drag.set_enabled(True)
    origin = scene.body.chunks[0].position
    frames, samples = [], []
    for tick in range(401):
        if tick == 20:
            scene.drag.press(origin, lambda _: True)
        if tick in (20, 60, 100):
            scene.drag.move(origin+{20: Vec2(65, 35), 60: Vec2(-60, 10), 100: Vec2(35, 60)}[tick])
        if tick == 140:
            scene.drag.release()
        scene.step()
        if tick % 2:
            continue
        frame = QImage(360, 270, QImage.Format.Format_ARGB32_Premultiplied)
        frame.fill(QColor('#26333c'))
        painter = QPainter(frame)
        try:
            painter.setPen(QColor('#e0e8ef'))
            painter.setFont(settings_font())
            painter.drawText(10, 20, f'{tick/40:.2f}s / {"drag" if 20 <= tick < 140 else "rest"}')
            appearance = scene.appearance
            painter.save()
            painter.translate(85, 105)
            painter.scale(3, 3)
            upper = scene.body.chunks[0].position
            painter.translate(-upper.x, -upper.y)
            renderer.draw_geometry(painter, scene, cords=False, pearl=False, halo=False,
                                   arm=False, cache_body=True, raster_scale=1.)
            painter.restore()
            painter.save()
            painter.translate(270, 110)
            painter.scale(4, 4)
            painter.translate(-appearance.lower.x, -appearance.lower.y)
            renderer.draw_limbs(painter, scene, 1., upper, appearance.lower,
                                appearance.waist_direction(appearance.direction), hands=False)
            painter.restore()
        finally:
            painter.end()
        rgba = frame.convertToFormat(QImage.Format.Format_RGBA8888)
        frames.append(Image.frombytes('RGBA', (rgba.width(), rgba.height()), bytes(rgba.constBits())))
        if tick in (0, 26, 38, 66, 78, 108, 144, 180, 260, 400):
            samples.append(frame.copy())
    frames[0].save(output/'two-segment-motion.gif', save_all=True, append_images=frames[1:],
                   duration=50, loop=0, disposal=2)
    sheet = QImage(1800, 540, QImage.Format.Format_ARGB32_Premultiplied)
    sheet.fill(QColor('#26333c'))
    painter = QPainter(sheet)
    for i, frame in enumerate(samples):
        painter.drawImage(i%5*360, i//5*270, frame)
    painter.end()
    sheet.save(str(output/'two-segment-motion.png'))


def main():
    app = QApplication.instance() or QApplication([])
    output = ROOT/'artifacts/legs'
    output.mkdir(parents=True, exist_ok=True)
    config = AppConfig.load(ROOT/'config.toml')
    atlas = Atlas(extract_atlas(config.game_dir))
    base = OracleConfig(body_appearance='custom', hide_cords=True, physics_backend='python')
    sheet = QImage(1000, 1200, QImage.Format.Format_ARGB32_Premultiplied)
    sheet.fill(QColor('#26333c'))
    canvas = QPainter(sheet)
    canvas.setFont(settings_font())
    try:
        for i, length in enumerate((4., 8.5, 14., 20.)):
            scene = OracleScene(replace(base, custom_appearance=CustomAppearance(
                robe_length=.7, leg_length=length)))
            renderer = OracleRenderer(atlas, base.custom_colors)
            for _ in range(500):
                scene.step()
            for row in range(3):
                if row == 2:
                    scene.drag.set_enabled(True)
                    scene.drag.press(scene.body.chunks[0].position, lambda _: True)
                    scene.drag.move(scene.body.chunks[0].position+Vec2(45, 25))
                    for _ in range(12):
                        scene.step()
                tile = QImage(70, 85, QImage.Format.Format_ARGB32_Premultiplied)
                tile.fill(0)
                painter = QPainter(tile)
                try:
                    upper = scene.body.chunks[0].position
                    painter.translate(35-upper.x, 25-upper.y)
                    if row == 0:
                        appearance = scene.appearance
                        renderer.draw_limbs(painter, scene, 1., upper, appearance.lower,
                                            appearance.waist_direction(appearance.direction), hands=False)
                    else:
                        renderer.draw_geometry(painter, scene, cords=False, pearl=False, halo=False,
                                               arm=False, cache_body=True, raster_scale=1.)
                finally:
                    painter.end()
                x, y = i*250, row*400
                canvas.setPen(QColor('#e0e8ef'))
                canvas.drawText(x+12, y+24, f'{length:g}px / {("legs", "rest", "drag")[row]}')
                canvas.drawImage(QRectF(x+10, y+30, 210, 255), tile)
                canvas.drawImage(x+90, y+300, tile)
    finally:
        canvas.end()
    sheet.save(str(output/'leg-lengths.png'))
    motion_preview(base, atlas, output)

    with tempfile.TemporaryDirectory() as temporary, ExitStack() as stack:
        root = Path(temporary)
        stack.enter_context(patch('rw_creature_pet.presets.profile_library.default_profile_directory',
                                  return_value=root/'profiles'))
        stack.enter_context(patch('rw_creature_pet.presets.library.default_appearance_directory',
                                  return_value=root/'appearances'))
        ui_config = replace(config, oracle=base)
        ProfileLibrary().export(ui_config, 'Leg review', preset_id=BELL_PROFILE_ID)
        dialog = OracleSettingsDialog(ui_config, SettingsStore(root/'settings.json'), first_run=True)
        try:
            dialog.controls['oracle.body_appearance'].setValue('custom')
            assert dialog.controls['oracle.custom_appearance.leg_length'].isEnabled()
            page = dialog.pages['appearance']
            dialog.tabs.setCurrentWidget(page)
            section = next(s for s in page.findChildren(CollapsibleSection) if s.heading.text() == '基础体型')
            section.set_expanded(True)
            dialog.show()
            for language in ('zh', 'en'):
                language_manager().set_language(language)
                dialog.resize(960, 900)
                for _ in range(3):
                    app.processEvents()
                page.verticalScrollBar().setValue(section.mapTo(page.widget(), QPoint()).y()-12)
                app.processEvents()
                assert page.horizontalScrollBar().maximum() == 0
                section.grab().save(str(output/f'settings-{language}.png'))
        finally:
            dialog.shutdown()
            dialog.close()
    print(output)


if __name__ == '__main__':
    main()
