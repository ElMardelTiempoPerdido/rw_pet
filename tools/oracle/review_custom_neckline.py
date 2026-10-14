"""导出自定义领口在不同像素密度、倾斜和衣袍摆动下的对照，不修改用户配置"""
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
from rw_creature_pet.oracle.config import CustomAppearance, OracleColors
from rw_creature_pet.oracle.graphics.appearance import OracleAppearance, perpendicular, rotate
from rw_creature_pet.oracle.graphics.render import OracleRenderer
from rw_creature_pet.oracle.scene import OracleScene
from rw_creature_pet.oracle.ui.settings_style import settings_font
from rw_creature_pet.shared.geometry import Vec2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--wide-shoulders', action='store_true', help='检查宽领口与袖根交叠处的皮肤和内搭')
    modes.add_argument('--high-neckline', action='store_true', help='检查高位领口两侧凸出的袖根')
    args = parser.parse_args()
    app = QApplication.instance() or QApplication([])
    config = AppConfig.load(ROOT/'config.toml')
    base = CustomAppearance()
    cases = (
        ('V - binding', base),
        ('Rounded V - gap 1', replace(base, neckline_tip_radius=1.5, neckline_trim_gap=1., neckline_trim_width=1.)),
        ('Curve - binding', replace(base, neckline_shape='arc', neckline_width=10., neckline_depth=5.)),
        ('Curve - gap 2', replace(base, neckline_shape='arc', neckline_width=10., neckline_depth=5.,
                                  neckline_trim_gap=2., neckline_trim_width=1.)),
    )
    if args.wide_shoulders or args.high_neckline:
        base = replace(base, chest_width=11., chest_height=7.5, shoulder_width=11.,
                       sleeve_root_width=12., sleeve_cuff_width=8.5, neckline_shape='arc',
                       neckline_depth=4., neckline_height=3., neckline_roundness=1.,
                       neckline_trim_enabled=False, inner_collar_enabled=False)
        if args.high_neckline:
            base = replace(base, neckline_height=8., neckline_depth=0.)
            colors = OracleColors(skin='#f8c7d7', inner_robe='#a48fd4',
                                  robe_top='#2a1f19', robe_bottom='#ff7045')
            config = replace(config, oracle=replace(config.oracle, custom_colors=colors))
        cases = tuple((f'Width {width:g} / '+('underlayer' if inner else 'skin'),
                       replace(base, neckline_width=width, inner_robe_enabled=inner))
                      for inner in (False, True) for width in ((10., 18.) if args.high_neckline else (12., 18.)))
    sheet = QImage(1040, 1060, QImage.Format.Format_ARGB32_Premultiplied)
    sheet.fill(QColor('#17232e'))
    painter = QPainter(sheet)
    painter.setFont(settings_font())
    try:
        for row, (density, angle, swing) in enumerate(((1., 0, 0), (1.5, 0, 0), (2., 0, 0), (2., 145, 7))):
            for col, (label, shape) in enumerate(cases):
                cfg = replace(config.oracle, body_appearance='custom', custom_appearance=shape,
                              outfit='normal', hide_cords=True, physics_backend='python')
                scene = OracleScene(cfg)
                origin = Vec2(400, 300)
                direction = rotate(Vec2(0, -1), radians(angle))
                for part, position in zip((*scene.body.chunks, scene.head),
                                          (origin, origin-direction*9, origin+direction*14)):
                    part.position = part.previous_position = position
                    part.velocity = Vec2()
                scene.look_direction = scene.previous_look_direction = Vec2()
                scene.appearance = OracleAppearance(scene)
                n = scene.appearance.CLOTH_DIVS
                for i, part in enumerate(scene.appearance.cloth):
                    part.position += perpendicular(direction)*(swing*(i//n)/(n-1))
                    part.previous_position = part.position
                renderer = OracleRenderer(colors=cfg.active_colors)
                size = round(72*density)
                image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
                image.fill(0)
                local = QPainter(image)
                try:
                    local.scale(density, density)
                    local.translate(36-origin.x, 36-origin.y)
                    renderer.draw_geometry(local, scene, arm=False, cords=False, pearl=False, halo=False,
                                           cache_body=True, raster_scale=density)
                finally:
                    local.end()
                painter.setPen(QColor('#dce3e9'))
                painter.drawText(col*260+10, row*265+20, label)
                painter.drawText(col*260+10, row*265+38, f'{density:g}x / {angle} deg')
                painter.drawImage(QRectF(col*260+22, row*265+45, 216, 216), image)
    finally:
        painter.end()
    name = 'high-neckline.png' if args.high_neckline else 'wide-shoulders.png' if args.wide_shoulders else 'neckline-preview.png'
    output = ROOT/'artifacts/custom-neckline'/name
    output.parent.mkdir(parents=True, exist_ok=True)
    if not sheet.save(str(output)):
        raise RuntimeError(f'Could not write {output}')
    print(output)


if __name__ == '__main__':
    main()
