"""真实图集的像素效果及中英文设置行离屏检查，不写用户配置"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from dataclasses import replace
from contextlib import ExitStack
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QColor, QFont, QFontDatabase, QImage, QPainter
from PySide6.QtWidgets import QApplication
from rw_creature_pet.config import AppConfig
from rw_creature_pet.oracle.graphics.render import OracleRenderer
from rw_creature_pet.oracle.scene import OracleScene
from rw_creature_pet.oracle.ui.settings import OracleSettingsDialog
from rw_creature_pet.settings_store import SettingsStore
from rw_creature_pet.presets.profile_library import ProfileLibrary
from rw_creature_pet.presets.startup import BELL_PROFILE_ID
from rw_creature_pet.shared.atlas import Atlas, extract_atlas


def main():
    app = QApplication.instance() or QApplication([])
    app.setStyle('Fusion')
    font_id = QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')
    app.setFont(QFont(QFontDatabase.applicationFontFamilies(font_id)[0], 10))
    config = AppConfig.load(ROOT/'config.toml')
    renderer = OracleRenderer(Atlas(extract_atlas(config.game_dir)), config.oracle.colors)
    scene = OracleScene(replace(config.oracle, halo_enabled=False, pearl_fixed_count=0,
                                pearl_satellite_count=0, pearl_matrix_enabled=False,
                                pearl_orbits_enabled=False, pixel_mode='adaptive'))
    for _ in range(700):
        scene.step()
    sheet = QImage(1440, 560, QImage.Format.Format_ARGB32_Premultiplied)
    sheet.fill(QColor('#182630'))
    painter = QPainter(sheet)
    try:
        for row, outfit in enumerate(('normal', 'maid')):
            for col, (scale, coarse) in enumerate(((1., False), (2., False), (2., True), (3., False),
                                                  (4., False), (4., True))):
                scene.config = replace(scene.config, outfit=outfit, coarse_pixels_4x=coarse)
                x, y = col*240, row*280
                painter.setPen(QColor('#ffffff'))
                label = f'{outfit} / {scale:g}x' + (' / coarse' if coarse else '')
                painter.drawText(QPointF(x+12, y+22), label)
                painter.save()
                painter.setClipRect(QRectF(x, y+30, 240, 250))
                painter.translate(x+120, y+110)
                painter.scale(scale, scale)
                center = scene.appearance.upper
                painter.translate(-round(center.x), -round(center.y))
                renderer.draw(painter, scene, cords=False)
                painter.restore()
    finally:
        painter.end()
    output = ROOT/'artifacts'
    output.mkdir(exist_ok=True)
    sheet.save(str(output/'oracle-large-scales.png'))
    with tempfile.TemporaryDirectory() as temp, ExitStack() as stack:
        root = Path(temp)
        stack.enter_context(patch('rw_creature_pet.presets.profile_library.default_profile_directory',
                                  return_value=root/'profiles'))
        stack.enter_context(patch('rw_creature_pet.presets.library.default_appearance_directory',
                                  return_value=root/'appearances'))
        ProfileLibrary().export(config, 'Pixel preview', preset_id=BELL_PROFILE_ID)
        for language in ('zh', 'en'):
            cfg = replace(config, ui=replace(config.ui, language=language),
                          desktop=replace(config.desktop, scale=4.))
            dialog = OracleSettingsDialog(cfg, SettingsStore(Path(temp)/'settings.json'))
            try:
                dialog._migration_notice = False
                dialog.preset_workflow.set_autosave(False)
                dialog.show()
                app.processEvents()
                for scale in (2., 4., 3.):
                    control = dialog.controls['desktop.scale']
                    control.setCurrentIndex(control.findData(scale))
                    app.processEvents()
                    dialog.grab().save(str(output/f'oracle-large-scales-settings-{language}-{scale:g}x.png'))
            finally:
                dialog.shutdown()
    print('Saved scale comparison and Chinese/English settings previews to artifacts')


if __name__ == '__main__':
    main()
