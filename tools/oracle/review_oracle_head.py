"""Bell 矢量头部预览：1 倍、精细像素和连续转头；不改配置。"""
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

from rw_creature_pet.config import AppConfig
from rw_creature_pet.shared.geometry import Vec2
from rw_creature_pet.oracle.render import OracleRenderer


def main():
    app = QApplication.instance() or QApplication([])
    font_id = QFontDatabase.addApplicationFont('C:/Windows/Fonts/arial.ttf')
    family = QFontDatabase.applicationFontFamilies(font_id)[0]
    config = AppConfig.load(ROOT/'config.toml')
    # 头部与耳机已无贴图依赖，此预览无需安装游戏也能生成。
    renderer = OracleRenderer(colors=config.oracle.colors)
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

    sheet = QImage(880, 1020, QImage.Format.Format_RGBA8888)
    sheet.fill(QColor('#17232e'))
    painter = QPainter(sheet)
    try:
        # 所有格子显示相同外形大小；放大的是各档已经生成的像素。
        poses = (('Closed', 0, 0, 0, 0), ('Open', 0, 0, 0, 1),
                 ('Side', 1, 0, 0, 1), ('Look up', .4, -1, 0, 0),
                 ('Tilt', -.5, 0, -25, .5), ('Floating', .4, .3, 90, 0))
        for row, (label, lx, ly, tilt, openness) in enumerate(poses):
            for column, density in enumerate((1., 1.5, 2., 4.)):
                x, y = column*220, row*170
                painter.setPen(QColor('#e0e5e9'))
                painter.setFont(QFont(family, 10))
                painter.drawText(x+12, y+24, f'{label} / raster {density:g}x')
                direction = Vec2(sin(radians(tilt)), -cos(radians(tilt)))
                painter.save()
                painter.translate(x+110, y+98)
                painter.scale(8, 8)
                renderer.draw_head(painter, Vec2(), direction*-14, direction, Vec2(lx, ly),
                                   openness, raster_scale=density)
                painter.restore()
    finally:
        painter.end()
    assert sheet.save(str(ROOT/'artifacts/oracle-head-vector-density.png'))

    frames = []
    for frame in range(96):
        phase = frame/96*2*3.141592653589793
        look = Vec2(sin(phase)*.85, 0)
        image = QImage(720, 200, QImage.Format.Format_RGBA8888)
        image.fill(QColor('#17232e'))
        painter = QPainter(image)
        try:
            for column, density in enumerate((1., 2., 4.)):
                painter.setPen(QColor('#e0e5e9'))
                painter.setFont(QFont(family, 10))
                painter.drawText(column*240+12, 24, f'Raster {density:g}x / 8x inspection')
                painter.save()
                painter.translate(column*240+120, 92)
                painter.scale(8, 8)
                renderer.draw_head(painter, Vec2(), Vec2(0, 9), Vec2(0, -1), look,
                                   raster_scale=density)
                painter.restore()
        finally:
            painter.end()
        frames.append(Image.frombytes('RGBA', (720, 200), bytes(image.constBits())).convert('RGB'))
    frames[0].save(ROOT/'artifacts/oracle-bell-head-preview.gif', save_all=True,
                   append_images=frames[1:], duration=50, loop=0, optimize=False)
    print('Saved oracle-bell-head-poses.png, oracle-head-vector-density.png and oracle-bell-head-preview.gif')


if __name__ == '__main__':
    main()
