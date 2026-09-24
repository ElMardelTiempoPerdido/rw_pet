"""真实游戏图集复核：直角转弯、保持曲率的短距离移动、连续掉头。"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
(Path(__file__).resolve().parents[2]/'artifacts').mkdir(exist_ok=True)
from math import degrees
from PIL import Image
from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QColor, QFont, QFontDatabase, QImage, QPainter, QPen
from PySide6.QtWidgets import QApplication

from rw_creature_pet.shared.atlas import Atlas, extract_atlas
from rw_creature_pet.shared.paths import DEFAULT_GAME_DIR
from rw_creature_pet.shared.geometry import Vec2
from rw_creature_pet.lizard.render import LizardRenderer
from tests.lizard.test_body_following import bend
from tests.lizard.test_wall_observation import placed
from tests.lizard.test_wall_rhythm import walking

root = Path(__file__).resolve().parents[2] / 'artifacts'
root.mkdir(exist_ok=True)
app = QApplication.instance() or QApplication([])
QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')
font = QFont('Microsoft YaHei UI', 10)
app.setFont(font)
renderer = LizardRenderer(Atlas(extract_atlas(DEFAULT_GAME_DIR)))
short = placed()
short.background.set_direction(Vec2(1, 0))
for _ in range(90): short.step()
short.background.set_direction(Vec2(0, 1))
for _ in range(23): short.step()
short.background.set_direction(Vec2())
for _ in range(200): short.step()
scenes = [walking(tracking=True), short, walking(tracking=True)]
for s in (scenes[0], scenes[2]):
    for _ in range(160): s.step()
titles = ('直角转弯 · 前身先转，中后身跟随', '短距移动 5 单位 · 保留已有弯曲', '连续掉头 · 保持抓附和质点身份')
colors = ('#77d6ed', '#edc877', '#ed9a99')
trails = [[[] for _ in range(3)] for s in scenes]
width, height = 420, 320


def panel(p, s, trail, rect, title, time):
    p.save()
    p.setClipRect(rect)
    p.fillRect(rect, QColor('#17222d'))
    p.setFont(font)
    p.setPen(QColor('#e4ecf4'))
    p.drawText(rect.adjusted(12, 10, -10, -5), 0, title)
    status = '已到点' if s.background.arrived else ('停留' if not s.background.was_moving else '移动中')
    p.setPen(QColor('#a1b5c8'))
    p.drawText(rect.adjusted(12, 33, -10, -5), 0,
               f'{time:.2f} 秒  |  {status}  |  躯干折角 {abs(degrees(bend(s))):.1f}°')
    p.drawText(rect.adjusted(12, height-27, -10, -5), 0, '青：前身   黄：中身   红：后身  ·  世界坐标轨迹')
    p.setClipRect(rect.adjusted(0, 58, 0, -32))
    center = s.body.chunks[1].position
    p.translate(rect.center().x(), rect.center().y()+12)
    p.scale(2.05, 2.05)
    p.translate(-center.x, -center.y)
    p.setPen(QPen(QColor('#263d4d'), .3))
    for x in range(int(center.x-110)//20*20, int(center.x+110), 20):
        p.drawLine(x, int(center.y-100), x, int(center.y+100))
    for y in range(int(center.y-100)//20*20, int(center.y+100), 20):
        p.drawLine(int(center.x-110), y, int(center.x+110), y)
    for points, color in zip(trail, colors):
        tint = QColor(color)
        tint.setAlpha(135)
        p.setPen(QPen(tint, .55))
        for a, b in zip(points, points[1:]):
            p.drawLine(QPointF(a.x, a.y), QPointF(b.x, b.y))
    renderer.draw(p, s, 1)
    for chunk, color in zip(s.body.chunks, colors):
        p.setBrush(QColor(color))
        p.setPen(QPen(QColor('#17222d'), .3))
        p.drawEllipse(QPointF(chunk.position.x, chunk.position.y), 1.25, 1.25)
    p.restore()


frames, snapshots = [], []
for frame in range(180):
    if frame == 20:
        s = scenes[0]
        s.background.set_goal(s.body.chunks[1].position+Vec2(0, -130), s.body, s.world)
        s = scenes[1]
        direction = s.body.chunks[0].position-s.body.chunks[1].position
        s.background.set_goal(s.body.chunks[1].position+direction*(5/direction.length()), s.body, s.world)
        s = scenes[2]
        s.background.set_goal(s.body.chunks[1].position+Vec2(-120, 0), s.body, s.world)
    image = QImage(width*3, height, QImage.Format.Format_RGBA8888)
    image.fill(QColor('#17222d'))
    painter = QPainter(image)
    for i, s in enumerate(scenes):
        for trail, chunk in zip(trails[i], s.body.chunks):
            trail.append(chunk.position)
            del trail[:-100]
        panel(painter, s, trails[i], QRectF(width*i, 0, width, height), titles[i], frame*.05)
    painter.end()
    picture = Image.frombytes('RGBA', (width*3, height), bytes(image.constBits())).convert('RGB')
    frames.append(picture)
    if frame in (15, 34, 65, 155): snapshots.append(picture)
    for s in scenes:
        for _ in range(2): s.step()
frames[0].save(root/'front-led-body.gif', save_all=True, append_images=frames[1:], duration=50, loop=0)
sheet = Image.new('RGB', (width*3, height*len(snapshots)))
for row, picture in enumerate(snapshots): sheet.paste(picture, (0, height*row))
sheet.save(root/'front-led-body.png')
print('Created front-led-body.gif and front-led-body.png')
