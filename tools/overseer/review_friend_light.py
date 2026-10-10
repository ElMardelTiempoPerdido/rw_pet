"""预览朋友？观察光、四边转向与退场，不写入用户配置"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'

from math import cos, pi, sin
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw
from PySide6.QtGui import QColor, QImage, QPainter

from rw_creature_pet.overseer.config import OverseerConfig
from rw_creature_pet.overseer.friend_light import light_images
from rw_creature_pet.overseer.friend_light_pixels import SPARK_FRAMES
from rw_creature_pet.overseer.model import Anchor, Edge, Overseer
from rw_creature_pet.overseer.render import OverseerRenderer
from rw_creature_pet.shared.geometry import Bounds, Vec2

OUT = ROOT/'artifacts/overseer'


def make_model(edge=Edge.BOTTOM):
    model = Overseer(Bounds(0, 0, 960, 600), OverseerConfig(
        color='#000000', observation_interval=.1, observation_probability=1.), seed=73)
    model.set_appearance('friend')
    model.show(anchor=Anchor(edge, .5))
    return model


def paint(model, background='#1c1e24', density=2.):
    side = round(128*density)
    image = QImage(side, side, QImage.Format.Format_RGBA8888)
    image.fill(QColor(background))
    p = QPainter(image)
    try:
        center = model.root+model.normal*35
        p.scale(density, density)
        p.translate(64-center.x, 64-center.y)
        OverseerRenderer().draw(p, model, pixel_mode='adaptive', raster_scale=density)
    finally:
        p.end()
    return Image.frombytes('RGBA', (side, side), bytes(image.constBits()))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    model = make_model()
    for _ in range(120):
        model.step(model.root+model.local_vector(Vec2(220, 300)))
    sheet = Image.new('RGB', (1024, 560), '#888888')
    views = (('Resting', 45, 0.), ('Front', 0, 1.), ('Tilted', 45, 1.), ('Side', 90, 1.))
    for row, bg in enumerate(('#1c1e24', '#e0e0e0')):
        for col, (label, angle, opening) in enumerate(views):
            model.lens.up = model.lens.previous_up = opening
            planar, depth = sin(angle*pi/180), cos(angle*pi/180)
            gaze = model.local_vector(Vec2(.6, .8))*planar
            with patch.object(model, 'head_gaze', return_value=(gaze, depth)):
                sheet.paste(paint(model, bg), (col*256, row*280+24))
            ImageDraw.Draw(sheet).text((col*256+10, row*280+6), f'{label} / 2x raster', fill='#ffffff')
    sheet.save(OUT/'friend-observation-light.png')

    models = [make_model(edge) for edge in Edge]
    frames = []
    for tick in range(320):
        for model in models:
            if tick == 200:
                model.request_withdraw()
            if tick == 235:
                model.request_emerge()
            model.step(model.root+model.local_vector(Vec2(380*sin(tick/90), 350)))
        if tick % 2 == 0:
            frame = Image.new('RGB', (512, 560), '#333333')
            for i, model in enumerate(models):
                x, y = (i % 2)*256, (i//2)*280
                frame.paste(paint(model), (x, y+24))
                ImageDraw.Draw(frame).text((x+8, y+6), f'{model.anchor.edge.value} / light {model.lens.up:.2f}', fill='#ffffff')
            frames.append(frame)
    frames[0].save(OUT/'friend-observation-motion.gif', save_all=True, append_images=frames[1:], duration=50, loop=0)

    # 同一观察状态同时比较明暗底色和三个花冠视角，按 2x 显示逻辑像素
    model = make_model(Edge.TOP)
    for _ in range(100):
        model.step(model.root+model.local_vector(Vec2(-180, 350)))
    frames = []
    for tick in range(200):
        model.step(model.root+model.local_vector(Vec2(-260+100*sin(tick/60), 400)))
        if tick % 2:
            continue
        frame = Image.new('RGB', (768, 560), '#777777')
        for row, bg in enumerate(('#ffffff', '#1c1e24')):
            for col, angle in enumerate((0, 45, 80)):
                gaze = model.local_vector(Vec2(-.45, .9))*sin(angle*pi/180)
                with patch.object(model, 'head_gaze', return_value=(gaze, cos(angle*pi/180))):
                    frame.paste(paint(model, bg), (256*col, 280*row+24))
                ImageDraw.Draw(frame).text((256*col+8, 280*row+6), f'{angle} deg / 2x pixels', fill='white')
        frames.append(frame)
    frames[0].save(OUT/'friend-observation-pixels.gif', save_all=True,
                   append_images=frames[1:], duration=50, loop=0)
    frames[20].save(OUT/'friend-observation-pixels.png')

    strip = Image.new('RGB', (320, 80), '#ffffff')
    drawing = ImageDraw.Draw(strip)
    for frame, offsets in enumerate(SPARK_FRAMES):
        for dx, dy in offsets:
            x, y = frame*80+35+dx*6, 35+dy*6
            drawing.rectangle((x, y, x+5, y+5), fill='#ffb000')
    strip.save(OUT/'friend-light-spark-frames.png')
    print('Previews:', OUT)
    print('Light image cache:', light_images.cache_info())


if __name__ == '__main__':
    main()
