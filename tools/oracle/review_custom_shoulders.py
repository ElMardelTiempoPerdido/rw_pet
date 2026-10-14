"""导出自定义胸肩尺寸与抬臂、倒立姿态；不修改用户配置"""
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--shoulder-widths', action='store_true', help='对比独立肩宽，保持胸肩与袖宽一致')
    args = parser.parse_args()
    app = QApplication.instance() or QApplication([])
    config = AppConfig.load(ROOT/'config.toml')
    sheet = QImage(1040, 1300, QImage.Format.Format_ARGB32_Premultiplied)
    sheet.fill(QColor('#182630'))
    painter = QPainter(sheet)
    painter.setFont(settings_font())
    try:
        for row, (density, angle, raised) in enumerate(((1., 0, False), (1.5, 0, False),
                                                        (2., 0, False), (2., 35, True), (2., 180, True))):
            cases = ((14., 6.5, w) for w in (8., 10., 12., 16.)) if args.shoulder_widths else (
                (w, h, 8.) for w, h in ((12., 8.), (12., 6.), (16., 6.), (8., 4.)))
            for col, (width, height, shoulder_width) in enumerate(cases):
                sleeve = 12. if args.shoulder_widths else 8.
                shape = replace(config.oracle.custom_appearance, chest_width=width, chest_height=height,
                                shoulder_width=shoulder_width, sleeve_root_width=sleeve,
                                sleeve_cuff_width=8.5, inner_robe_enabled=False,
                                neckline_shape='arc', neckline_depth=0., neckline_height=7.5,
                                neckline_trim_enabled=False)
                cfg = replace(config.oracle, body_appearance='custom', custom_appearance=shape,
                              outfit='normal', hide_cords=True, physics_backend='python')
                scene = OracleScene(cfg)
                scene.set_autonomous(False)
                for _ in range(500):
                    scene.step()
                a = scene.appearance
                origin, turn = a.upper, radians(angle)
                for node in [*scene.body.chunks, *a.body_points]:
                    node.position = origin+rotate(node.position-origin, turn)
                    node.previous_position = node.position
                a.lower = origin+rotate(a.lower-origin, turn)
                a.direction = rotate(a.direction, turn)
                if raised:
                    for i, hand in enumerate(a.hands):
                        hand.pin(origin+perpendicular(a.direction)*((2*i-1)*15)+a.direction*3)
                renderer = OracleRenderer(colors=cfg.active_colors)
                image = QImage(round(72*density), round(72*density), QImage.Format.Format_ARGB32_Premultiplied)
                image.fill(0)
                local = QPainter(image)
                try:
                    local.scale(density, density)
                    local.translate(36-origin.x, 36-origin.y)
                    renderer.draw_geometry(local, scene, 1., arm=False, cords=False, pearl=False, halo=False,
                                           cache_body=True, raster_scale=density)
                finally:
                    local.end()
                painter.setPen(QColor('#dce3e9'))
                title = f'Shoulder {shoulder_width:g} px' if args.shoulder_widths else f'Chest {width:g} / rise {height:g}'
                painter.drawText(col*260+10, row*260+20, title)
                painter.drawText(col*260+10, row*260+39, f'{density:g}x / {angle} deg / sleeve {sleeve:g}')
                painter.drawImage(QRectF(col*260+22, row*260+42, 216, 216), image)
    finally:
        painter.end()
    path = ROOT/'artifacts/custom-shoulders'/('shoulder-widths.png' if args.shoulder_widths else 'preview.png')
    path.parent.mkdir(parents=True, exist_ok=True)
    if not sheet.save(str(path)):
        raise RuntimeError(f'Could not write {path}')
    print(path)


if __name__ == '__main__':
    main()
