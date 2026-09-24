"""Bell 头部真实图集预览：1 倍像素、六倍放大及连续转头；不改配置。"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'

from math import cos, radians, sin
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
(ROOT/'artifacts').mkdir(exist_ok=True)

from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QImage, QPainter
from PySide6.QtWidgets import QApplication

from rw_creature_pet.shared.atlas import Atlas, extract_atlas
from rw_creature_pet.config import AppConfig
from rw_creature_pet.shared.geometry import Vec2
from rw_creature_pet.oracle.render import OracleRenderer


def main():
    app = QApplication.instance() or QApplication([])
    font_id = QFontDatabase.addApplicationFont('C:/Windows/Fonts/arial.ttf')
    family = QFontDatabase.applicationFontFamilies(font_id)[0]
    config = AppConfig.load(ROOT/'config.toml')
    renderer = OracleRenderer(Atlas(extract_atlas(config.game_dir)), config.oracle.colors)
    sheet = QImage(960, 660, QImage.Format.Format_RGBA8888)
    sheet.fill(QColor('#17232e'))
    painter = QPainter(sheet)
    cases = [('Front', 0, 0, 0), ('Slight right', .4, 0, 0),
             ('Slight left', -.4, 0, 0), ('Right', 1, 0, 0),
             ('Left', -1, 0, 0), ('Look up', 0, -1, 0),
             ('Look down', 0, 1, 0), ('Upper right', .7, -.7, 0),
             ('Tilt left', 0, 0, -25), ('Tilt right', 0, 0, 25),
             ('Tilt + right', .4, 0, 25), ('Tilt + left', -.4, 0, -25)]
    try:
        for i, (label, lx, ly, tilt) in enumerate(cases):
            x, y = i % 4 * 240, i // 4 * 220
            painter.setPen(QColor('#e0e5e9'))
            painter.setFont(QFont(family, 10))
            painter.drawText(x+12, y+24, label+' / 6x')
            t = radians(tilt)
            direction = Vec2(sin(t), -cos(t))
            look = Vec2(lx, ly)
            painter.save()
            painter.translate(x+120, y+105)
            painter.scale(6, 6)
            renderer.draw_head(painter, Vec2(), direction*-9, direction, look)
            painter.restore()
            head = Vec2(x+28, y+185)
            renderer.draw_head(painter, head, head-direction*9, direction, look)
            painter.drawText(x+50, y+189, '1x')
    finally:
        painter.end()
    assert sheet.save(str(ROOT/'artifacts/oracle-bell-head-poses.png'))

    frames = []
    for frame in range(96):
        phase = frame/96*2*3.141592653589793
        look = Vec2(sin(phase)*.85, 0)
        image = QImage(240, 200, QImage.Format.Format_RGBA8888)
        image.fill(QColor('#17232e'))
        painter = QPainter(image)
        try:
            painter.translate(120, 92)
            painter.scale(8, 8)
            renderer.draw_head(painter, Vec2(), Vec2(0, 9), Vec2(0, -1), look)
        finally:
            painter.end()
        frames.append(Image.frombytes('RGBA', (240, 200), bytes(image.constBits())).convert('RGB'))
    frames[0].save(ROOT/'artifacts/oracle-bell-head-preview.gif', save_all=True,
                   append_images=frames[1:], duration=50, loop=0, optimize=False)
    print('Saved oracle-bell-head-poses.png and oracle-bell-head-preview.gif')


if __name__ == '__main__':
    main()
