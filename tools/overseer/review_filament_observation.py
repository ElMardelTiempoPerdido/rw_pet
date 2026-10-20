"""观察前伸/恢复的离屏对照与动画，只使用临时模型，不修改用户设置"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw
from PySide6.QtGui import QColor, QImage, QPainter

from rw_creature_pet.overseer.config import OverseerConfig
from rw_creature_pet.overseer.graphics.render import OverseerRenderer
from rw_creature_pet.overseer.model import Anchor, Edge, Overseer
from rw_creature_pet.shared.geometry import Bounds, Vec2


def paint(model, renderer, density=2):
    image = QImage(160*density, 160*density, QImage.Format.Format_RGBA8888)
    image.fill(QColor('#20252b'))
    painter = QPainter(image)
    try:
        center = model.root+model.normal*55
        painter.scale(density, density)
        painter.translate(80-center.x, 80-center.y)
        renderer.draw(painter, model, pixel_mode='adaptive', raster_scale=density)
    finally:
        painter.end()
    return Image.frombytes('RGBA', (image.width(), image.height()), bytes(image.constBits()))


def main():
    output = ROOT/'artifacts/overseer'
    output.mkdir(parents=True, exist_ok=True)
    models, renderers = [], []
    for appearance in ('standard', 'friend'):
        model = Overseer(Bounds(0, 0, 640, 480), OverseerConfig(
            color='#000000' if appearance == 'friend' else '#72e6c4',
            observation_probability=1, observation_interval=999))
        model.set_appearance(appearance)
        model.show(anchor=Anchor(Edge.TOP, .5))
        for _ in range(200):
            model.step(model.root+model.local_vector(Vec2(-200, 180)))
        models.append(model)
        renderers.append(OverseerRenderer())
    sheet = Image.new('RGB', (960, 688), '#20252b')
    frames = []
    for tick in range(460):
        frame = Image.new('RGB', (640, 344), '#20252b') if tick % 4 == 0 else None
        for row, (model, renderer) in enumerate(zip(models, renderers)):
            if tick == 40:
                model.lens.remaining = 6
            if tick == 190:
                model.lens.remaining = 0
            model.step(model.root+model.local_vector(Vec2(-200, 180)))
            if frame is not None:
                frame.paste(paint(model, renderer), (row*320, 24))
                ImageDraw.Draw(frame).text((row*320+8, 6),
                    f'{model.appearance} / observing {model.lens.up:.0%} / 2x', fill='white')
            if tick in (0, 180, 459):
                col = {0: 0, 180: 1, 459: 2}[tick]
                sheet.paste(paint(model, renderer), (col*320, row*344+24))
                ImageDraw.Draw(sheet).text((col*320+8, row*344+6),
                    f'{model.appearance} / {("resting", "observing", "recovered")[col]}', fill='white')
        if frame is not None:
            frames.append(frame)
    sheet.save(output/'filament-observation.png')
    frames[0].save(output/'filament-observation.gif', save_all=True,
                   append_images=frames[1:], duration=100, loop=0)
    print(output/'filament-observation.png')


if __name__ == '__main__':
    main()
