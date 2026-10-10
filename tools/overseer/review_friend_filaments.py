"""双触须在四边、明暗背景、转头和缩回过程中的离屏预览"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'

from math import sin
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw
from PySide6.QtGui import QColor, QImage, QPainter

from rw_creature_pet.overseer.config import OverseerConfig
from rw_creature_pet.overseer import friend_filaments
from rw_creature_pet.overseer.model import Anchor, Edge, Overseer
from rw_creature_pet.overseer.render import OverseerRenderer
from rw_creature_pet.shared.geometry import Bounds, Vec2


OUT = ROOT/'artifacts/overseer'


def make_model(edge):
    model = Overseer(Bounds(0, 0, 640, 480), OverseerConfig(
        color='#000000', observation_probability=0), seed=73)
    model.set_appearance('friend')
    model.show(anchor=Anchor(edge, .5))
    return model


def paint(model, renderer, background, density=1.):
    size = round(112*density)
    image = QImage(size, size, QImage.Format.Format_RGBA8888)
    image.fill(QColor(background))
    p = QPainter(image)
    try:
        center = model.root+model.normal*35
        p.scale(density, density)
        p.translate(56-center.x, 56-center.y)
        renderer.draw(p, model, pixel_mode='adaptive', raster_scale=density)
    finally:
        p.end()
    return Image.frombytes('RGBA', (size, size), bytes(image.constBits()))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    visibility = Image.new('RGB', (1344, 720), '#888888')
    for row, gain in enumerate((1., friend_filaments.SIDE_VISIBILITY_GAIN)):
        with patch.object(friend_filaments, 'SIDE_VISIBILITY_GAIN', gain):
            for col, lateral in enumerate((-60., 0., 60., 400.)):
                model = make_model(Edge.TOP)
                for _ in range(400):
                    model.step(model.root+model.local_vector(Vec2(lateral, 240)))
                x, y = col*336, row*360
                native = paint(model, OverseerRenderer(), '#ffffff')
                visibility.paste(native.resize((336, 336), Image.Resampling.NEAREST), (x, y+24))
                ImageDraw.Draw(visibility).text((x+8, y+6),
                    f'Gain {gain:g} / gaze x={lateral:g} / 1x enlarged 3x', fill='white')
    visibility.save(OUT/'friend-filaments-side-visibility.png')
    # 连续模拟左视、正视、右视，观察共根连接点和两条柔性链跨过颈部
    model = make_model(Edge.TOP)
    renderer = OverseerRenderer()
    turns = Image.new('RGB', (1008, 360), '#888888')
    turn_frames = []
    for col, lateral in enumerate((-400., 0., 400.)):
        for tick in range(400):
            model.step(model.root+model.local_vector(Vec2(lateral, 240)))
            if tick % 4 == 0:
                frame = Image.new('RGB', (336, 360), '#888888')
                frame.paste(paint(model, renderer, '#ffffff').resize((336, 336), Image.Resampling.NEAREST), (0, 24))
                ImageDraw.Draw(frame).text((8, 6), f'Gaze x={lateral:g} / 1x enlarged 3x', fill='white')
                turn_frames.append(frame)
        turns.paste(paint(model, renderer, '#ffffff').resize((336, 336), Image.Resampling.NEAREST), (col*336, 24))
        ImageDraw.Draw(turns).text((col*336+8, 6), f'Gaze x={lateral:g} / 1x enlarged 3x', fill='white')
    turns.save(OUT/'friend-filaments-turn.png')
    turn_frames[0].save(OUT/'friend-filaments-turn.gif', save_all=True,
                        append_images=turn_frames[1:], duration=100, loop=0)
    comparison = Image.new('RGB', (672, 360), '#888888')
    for col, strength in enumerate((0., friend_filaments.CURVE_STRENGTH)):
        with patch.object(friend_filaments, 'CURVE_STRENGTH', strength):
            model = make_model(Edge.TOP)
            for _ in range(400):
                model.step(model.root+model.local_vector(Vec2(-180, 240)))
        native = paint(model, OverseerRenderer(), '#ffffff')
        comparison.paste(native.resize((336, 336), Image.Resampling.NEAREST), (col*336, 24))
        ImageDraw.Draw(comparison).text((col*336+8, 6),
            'Before / 1x enlarged 3x' if col == 0 else 'C + S bias / 1x enlarged 3x', fill='white')
    comparison.save(OUT/'friend-filaments-rest-curves.png')
    models = [make_model(edge) for edge in Edge]
    renderers = [OverseerRenderer() for _ in models]
    for _ in range(150):
        for model in models:
            model.step(model.root+model.local_vector(Vec2(-220, 240)))
    sheet = Image.new('RGB', (896, 496), '#888888')
    for row, bg in enumerate(('#ffffff', '#1c1e24')):
        for col, (model, renderer) in enumerate(zip(models, renderers)):
            sheet.paste(paint(model, renderer, bg, 2.), (col*224, row*248+24))
            ImageDraw.Draw(sheet).text((col*224+8, row*248+6), f'{model.anchor.edge.value} / 2x', fill='white')
    sheet.save(OUT/'friend-filaments-four-edges.png')

    frames = []
    for tick in range(280):
        for model in models:
            if tick == 160:
                model.request_withdraw()
            if tick == 210:
                model.request_emerge()
            model.step(model.root+model.local_vector(Vec2(250*sin(tick/45), 240)))
        if tick % 2:
            continue
        frame = Image.new('RGB', (672, 720), '#888888')
        for i, (model, renderer) in enumerate(zip(models, renderers)):
            x, y = (i % 2)*336, (i//2)*360
            native = paint(model, renderer, '#ffffff' if i % 2 == 0 else '#1c1e24')
            frame.paste(native.resize((336, 336), Image.Resampling.NEAREST), (x, y+24))
            ImageDraw.Draw(frame).text((x+8, y+6), f'{model.anchor.edge.value} / 1x enlarged 3x', fill='white')
        frames.append(frame)
    frames[0].save(OUT/'friend-filaments-motion.gif', save_all=True,
                   append_images=frames[1:], duration=50, loop=0)
    print('Previews:', OUT)


if __name__ == '__main__':
    main()
