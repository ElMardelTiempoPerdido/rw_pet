"""Prince 双层下摆的比例、分层和运动预览，不读取或修改用户配置"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from math import sin
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from PIL import Image
from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication
from rw_creature_pet.oracle.graphics.render import OracleRenderer
from rw_creature_pet.oracle.graphics.raster import local_canvas, pixel_density
from rw_creature_pet.oracle.graphics.prince_robe import robe_image
from rw_creature_pet.oracle.prince_assets import ROBE_FRONT, ROBE_BACK
from rw_creature_pet.oracle.ui.settings_style import settings_font
from rw_creature_pet.shared.geometry import Vec2
from tools.oracle.review_prince_posture import advance, make_scene


def render(renderer, scene, scale, width=400, height=480):
    # 使用正式像素密度，3x/4x 与桌面保持一致
    density = pixel_density('adaptive', scale)
    origin = scene.body.chunks[0].position
    bounds = QRectF(origin.x-width/(2*scale), origin.y-150/scale, width/scale, height/scale)
    layer, rect = local_canvas(bounds, density)
    painter = QPainter(layer)
    painter.scale(density, density)
    painter.translate(-rect.x(), -rect.y())
    renderer.draw_geometry(painter, scene, cache_body=True, arm=False, cords=False,
                           pearl=False, halo=False, raster_scale=scale)
    painter.end()
    image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor('#e8e5df'))
    painter = QPainter(image)
    painter.drawImage(QRectF(0., 0., width, height), layer)
    painter.end()
    return image


def main():
    app = QApplication.instance() or QApplication([])
    directory = ROOT/'artifacts/prince'
    directory.mkdir(parents=True, exist_ok=True)
    scene = make_scene()
    for _ in range(500):
        scene.step()
    renderer = OracleRenderer(colors=scene.config.active_colors)
    sheet = QImage(1200, 620, QImage.Format.Format_ARGB32_Premultiplied)
    sheet.fill(QColor('#e8e5df'))
    painter = QPainter(sheet)
    painter.setFont(settings_font())
    for i, scale in enumerate((1., 1.5, 2., 3., 4.)):
        painter.drawImage(i*240, 0, render(renderer, scene, scale, 240, 480))
        painter.setPen(QColor('#34313f'))
        painter.drawText(i*240+20, 28, f'Prince / {scale:g}x')
    for i, (path, title) in enumerate(((ROBE_FRONT, '_1 / front'), (ROBE_BACK, '_2 / back'))):
        image = robe_image(path)
        painter.drawImage(QRectF(30+i*230, 500, image.width()*2, image.height()*2), image)
        painter.drawText(90+i*230, 540, title)
    painter.end()
    sheet.save(str(directory/'prince-robe-scales.png'))

    origin = scene.body.chunks[0].position
    frames = []
    for tick in range(440):
        active = 60 <= tick < 280
        phase = (tick-60)/220*6.283185
        offset = Vec2(10*sin(phase), 0.) if active else Vec2()
        angle = .65*sin(phase) if active else 0.
        advance(scene, origin+offset, angle, Vec2(.6*sin(phase), 0.) if active else Vec2())
        if tick%2 == 0:
            frame = render(renderer, scene, 4., 480, 500).convertToFormat(QImage.Format.Format_RGBA8888)
            frames.append(Image.frombytes('RGBA', (frame.width(), frame.height()), bytes(frame.constBits())).convert('RGB'))
    frames[0].save(directory/'prince-robe-motion.gif', save_all=True, append_images=frames[1:],
                   duration=50, loop=0, disposal=2)
    # 取运动过程中四个时刻，方便直接检查回摆与接缝
    strip = Image.new('RGB', (480*4, 500))
    for i, index in enumerate((40, 75, 110, 145)):
        strip.paste(frames[index], (480*i, 0))
    strip.save(directory/'prince-robe-motion-frames.png')
    print(directory/'prince-robe-scales.png')
    print(directory/'prince-robe-motion.gif')


if __name__ == '__main__':
    main()
