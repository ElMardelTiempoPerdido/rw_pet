"""导出 Bell 胸肩移植前后、不同倍率与手臂姿态的对照，不修改用户配置"""
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
from rw_creature_pet.oracle.graphics.appearance import perpendicular, rotate
from rw_creature_pet.oracle.graphics.render import OracleRenderer
from rw_creature_pet.oracle.scene import OracleScene
from rw_creature_pet.oracle.ui.settings_style import settings_font
from rw_creature_pet.shared.atlas import Atlas, extract_atlas

CASES = (('Rest 1x', 1., 0, None), ('Rest 1.5x', 1.5, 0, None),
         ('Rest 2x', 2., 0, None), ('Raise 2x', 2., 0, (14., 6.)),
         ('Across chest 2x', 2., 30, (-1., -6.)), ('Inverted 2x', 2., 180, (14., 3.)))


def compose(output):
    # 原始截图独立保存，重新排版时无需重跑旧版本的渲染代码
    for stage in ('before', 'after'):
        if not (output/f'{stage}-normal-0.png').is_file():
            continue
        sheet = QImage(960, 720, QImage.Format.Format_ARGB32_Premultiplied)
        sheet.fill(QColor('#182630'))
        painter = QPainter(sheet)
        painter.setFont(settings_font())
        painter.setPen(QColor('#dce3e9'))
        for col, (label, *_rest) in enumerate(CASES):
            for row, outfit in enumerate(('normal', 'maid')):
                image = QImage(str(output/f'{stage}-{outfit}-{col}.png'))
                x, y = (col % 3)*320, (col//3)*360+row*180
                painter.drawText(x+10, y+18, f'{stage} / {label} / {outfit}')
                painter.drawImage(QRectF(x+84, y+24, 152, 152), image)
        painter.end()
        sheet.save(str(output/f'{stage}.png'))
    if not (output/'before-normal-0.png').is_file() or not (output/'after-normal-0.png').is_file():
        return
    # 正面放松、抬手和倒立的 2x 近景，每行左旧右新
    sheet = QImage(960, 750, QImage.Format.Format_ARGB32_Premultiplied)
    sheet.fill(QColor('#182630'))
    painter = QPainter(sheet)
    painter.setFont(settings_font())
    painter.setPen(QColor('#dce3e9'))
    for row, case in enumerate((2, 3, 5)):
        for outfit_index, outfit in enumerate(('normal', 'maid')):
            for version, stage in enumerate(('before', 'after')):
                x, y = (outfit_index*2+version)*240, row*250
                image = QImage(str(output/f'{stage}-{outfit}-{case}.png'))
                painter.drawText(x+8, y+20, f'{stage} / {outfit}')
                painter.drawImage(QRectF(x+8, y+30, 224, 216), image, QRectF(20, 18, 112, 108))
    painter.end()
    sheet.save(str(output/'comparison.png'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=('before', 'after', 'compose'))
    args = parser.parse_args()
    app = QApplication.instance() or QApplication([])
    output = ROOT/'artifacts/bell-shoulders'
    output.mkdir(parents=True, exist_ok=True)
    if args.stage == 'compose':
        compose(output)
        return
    config = AppConfig.load(ROOT/'config.toml')
    atlas = Atlas(extract_atlas(config.game_dir))
    for col, (label, density, angle, hand_pose) in enumerate(CASES):
        for row, outfit in enumerate(('normal', 'maid')):
            cfg = replace(config.oracle, body_appearance='bell', outfit=outfit,
                          hide_cords=True, physics_backend='python')
            scene = OracleScene(cfg)
            scene.set_autonomous(False)
            for _ in range(500):
                scene.step()
            a, turn = scene.appearance, radians(angle)
            origin = a.upper
            for node in [*scene.body.chunks, *a.body_points]:
                node.position = origin+rotate(node.position-origin, turn)
                node.previous_position = node.position
            a.lower = origin+rotate(a.lower-origin, turn)
            a.direction = rotate(a.direction, turn)
            if hand_pose is not None:
                across, rise = hand_pose
                for i, hand in enumerate(a.hands):
                    hand.pin(origin+perpendicular(a.direction)*((2*i-1)*across)+a.direction*rise)
            image = QImage(round(76*density), round(76*density), QImage.Format.Format_ARGB32_Premultiplied)
            image.fill(0)
            local = QPainter(image)
            try:
                local.scale(density, density)
                local.translate(38-origin.x, 38-origin.y)
                OracleRenderer(atlas, cfg.active_colors).draw_geometry(
                    local, scene, cache_body=True, arm=False, cords=False, pearl=False,
                    halo=False, raster_scale=density)
            finally:
                local.end()
            image.save(str(output/f'{args.stage}-{outfit}-{col}.png'))
    compose(output)
    print(output/f'{args.stage}.png')


if __name__ == '__main__':
    main()
