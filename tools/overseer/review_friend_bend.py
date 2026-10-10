"""对照 S 形姿态、四边和快速换向，输出预览，不改用户配置"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'

from pathlib import Path
from math import sin, pi
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw
from PySide6.QtCore import QPointF
from PySide6.QtGui import QColor, QImage, QPainter, QPen

from rw_creature_pet.overseer.config import OverseerConfig
from rw_creature_pet.overseer.graphics.friend import body as friend
from rw_creature_pet.overseer.graphics.friend.body import FriendBend, body_centers
from rw_creature_pet.overseer.model import Anchor, Edge, Overseer
from rw_creature_pet.overseer.graphics.render import OverseerRenderer
from rw_creature_pet.shared.geometry import Bounds, Vec2

OUT = ROOT/'artifacts/overseer'


def model_at(edge=Edge.TOP):
    model = Overseer(Bounds(0, 0, 600, 600), OverseerConfig(color='#000000', observation_probability=0), seed=73)
    model.set_appearance('friend')
    model.show(anchor=Anchor(edge, .5))
    model.wander_wait = 10000
    return model


def paint(model, *, straight=False, guide=False):
    state = model.friend_bend
    if straight:
        model.friend_bend = FriendBend()
    image = QImage(200, 180, QImage.Format.Format_RGBA8888)
    image.fill(QColor('#dddddd'))
    painter = QPainter(image)
    try:
        center = model.root+model.normal*30
        painter.scale(2, 2)
        painter.translate(50-center.x, 45-center.y)
        painter.setPen(QPen(QColor('#aaaaaa'), .5))
        a, b = model.root-model.tangent*60, model.root+model.tangent*60
        painter.drawLine(QPointF(a.x, a.y), QPointF(b.x, b.y))
        OverseerRenderer().draw(painter, model, pixel_mode='adaptive', raster_scale=2.)
        if guide:
            painter.setPen(QPen(QColor('#36a885'), .5))
            centers = body_centers(model, 1.)
            for a, b in zip(centers, centers[1:]):
                painter.drawLine(QPointF(a.x, a.y), QPointF(b.x, b.y))
    finally:
        painter.end()
        model.friend_bend = state
    return Image.frombytes('RGBA', (200, 180), bytes(image.constBits()))


def review_gaze_follow():
    models = [model_at(Edge.BOTTOM), model_at(Edge.BOTTOM)]
    settings = (1., friend.BODY_GAZE_FOLLOW)
    frames = []
    for tick in range(300):
        frame = Image.new('RGB', (800, 390), '#dddddd') if tick % 3 == 0 else None
        for column, (model, influence) in enumerate(zip(models, settings)):
            with patch.object(friend, 'BODY_GAZE_FOLLOW', influence):
                side = 240*sin(max(0, tick-40)*pi/120)
                model.step(model.root+model.local_vector(Vec2(side, 200)))
                if frame is not None:
                    frame.paste(paint(model).resize((400, 360), Image.Resampling.NEAREST), (column*400, 30))
                    ImageDraw.Draw(frame).text((column*400+12, 10), f'Body follow {influence:g} / full head gaze', fill='#333333')
        if frame is not None:
            frames.append(frame)
            if tick == 99:
                frame.save(OUT/'friend-gaze-comparison.png')
    frames[0].save(OUT/'friend-gaze-motion.gif', save_all=True, append_images=frames[1:], duration=75, loop=0)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    sheet = Image.new('RGB', (1200, 1140), '#dddddd')
    for row, side in enumerate((-45, -140, -300)):
        model = model_at()
        for _ in range(180):
            model.step(model.root+model.local_vector(Vec2(side, 200)))
        for col, (straight, guide, label) in enumerate(((True, False, 'No bend'), (False, False, 'S bend'), (False, True, 'Centerline'))):
            image = paint(model, straight=straight, guide=guide).resize((400, 360), Image.Resampling.NEAREST)
            sheet.paste(image, (col*400, row*380+20))
            ImageDraw.Draw(sheet).text((col*400+8, row*380+5), f'{label} / side {abs(side)} / 2x raster enlarged 2x', fill='#333333')
    sheet.save(OUT/'friend-bend-comparison.png')
    frames = []
    models = [model_at(edge) for edge in Edge]
    for tick in range(260):
        for model in models:
            if tick == 150:
                model.request_withdraw()
            elif tick == 165:
                model.request_emerge()
            model.step(model.root+model.local_vector(Vec2(180 if tick < 70 or tick >= 170 else -180, 200)))
        if tick % 2 == 0:
            frame = Image.new('RGB', (800, 720), '#dddddd')
            for i, model in enumerate(models):
                image = paint(model).resize((400, 360), Image.Resampling.NEAREST)
                frame.paste(image, ((i % 2)*400, (i//2)*360))
            frames.append(frame)
    frames[0].save(OUT/'friend-bend-motion.gif', save_all=True, append_images=frames[1:], duration=50, loop=0)
    review_gaze_follow()
    print(f'Previews: {OUT}')


if __name__ == '__main__':
    main()
