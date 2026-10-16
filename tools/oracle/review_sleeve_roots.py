"""宽袖根的放松、抬手与旋转对照，仅读取默认配置"""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import argparse
from dataclasses import replace
from math import radians
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication
from rw_creature_pet.config import AppConfig
from rw_creature_pet.oracle.config import CustomAppearance
from rw_creature_pet.oracle.graphics.appearance import perpendicular, rotate
from rw_creature_pet.oracle.graphics.render import OracleRenderer
from rw_creature_pet.oracle.scene import OracleScene
from rw_creature_pet.oracle.ui.settings_style import settings_font
from rw_creature_pet.shared.atlas import Atlas, extract_atlas

CASES = (('Rest', 5., -14., 0), ('Raise', 16., 2., 0), ('High', 12., 12., 0),
         ('Across chest', -1., -6., 0), ('Tilt', 16., 2., 40), ('Inverted', 16., 2., 180))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=('before', 'after'))
    parser.add_argument('--output', type=Path, default=ROOT/'artifacts/sleeve-roots')
    args = parser.parse_args()
    app = QApplication.instance() or QApplication([])
    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    config = AppConfig.load(ROOT/'config.toml')
    atlas = Atlas(extract_atlas(config.game_dir))
    shape = replace(CustomAppearance(), sleeve_root_width=12., sleeve_cuff_width=12.)
    colors = replace(config.oracle.custom_colors, robe_top='#ffbd97', robe_bottom='#ffbd97')
    cfg = replace(config.oracle, body_appearance='custom', custom_appearance=shape,
                  custom_colors=colors, outfit='maid', hide_cords=True, physics_backend='python')
    sheet = QImage(960, 640, QImage.Format.Format_ARGB32_Premultiplied)
    sheet.fill(QColor('#182630'))
    painter = QPainter(sheet)
    painter.setFont(settings_font())
    painter.setPen(QColor('#dce3e9'))
    for col, (label, across, rise, degrees) in enumerate(CASES):
        scene = OracleScene(cfg)
        scene.set_autonomous(False)
        for _ in range(350):
            scene.step()
        a, turn = scene.appearance, radians(degrees)
        origin = a.upper
        for node in [*scene.body.chunks, *a.body_points]:
            node.position = origin+rotate(node.position-origin, turn)
            node.previous_position = node.position
        a.lower = origin+rotate(a.lower-origin, turn)
        a.direction = rotate(a.direction, turn)
        for i, hand in enumerate(a.hands):
            hand.pin(origin+perpendicular(a.direction)*((2*i-1)*across)+a.direction*rise)
        image = QImage(152, 152, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(0)
        local = QPainter(image)
        local.scale(2, 2)
        local.translate(38-origin.x, 30-origin.y)
        OracleRenderer(atlas, colors).draw_geometry(local, scene, cache_body=True, arm=False, cords=False,
                                                   pearl=False, halo=False, raster_scale=2.)
        local.end()
        image.save(str(output/f'{args.stage}-{col}.png'))
        x, y = col%3*320, col//3*320
        painter.drawText(x+8, y+20, f'{args.stage} / {label}')
        painter.drawImage(QRectF(x+8, y+24, 304, 304), image)
    painter.end()
    sheet.save(str(output/f'{args.stage}.png'))
    if (output/'before.png').exists() and (output/'after.png').exists():
        comparison = QImage(640, 320*len(CASES), QImage.Format.Format_ARGB32_Premultiplied)
        comparison.fill(QColor('#182630'))
        p = QPainter(comparison)
        p.setFont(settings_font())
        p.setPen(QColor('#dce3e9'))
        for row, (label, *_) in enumerate(CASES):
            for column, version in enumerate(('before', 'after')):
                p.drawText(column*320+8, row*320+20, f'{version} / {label}')
                p.drawImage(QRectF(column*320+8, row*320+24, 304, 304),
                            QImage(str(output/f'{version}-{row}.png')))
        p.end()
        comparison.save(str(output/'comparison.png'))
        comparison.copy(0, 0, 640, 640).save(str(output/'rest-and-raised.png'))
    print(output/f'{args.stage}.png')


if __name__ == '__main__':
    main()
