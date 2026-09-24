"""实际图集离屏复核：固定抓点、不等距四肢，以及行走后保持的停留姿态。"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
(Path(__file__).resolve().parents[2]/'artifacts').mkdir(exist_ok=True)
from math import pi
from PIL import Image
from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QColor, QFont, QFontDatabase, QImage, QPainter, QPen
from PySide6.QtWidgets import QApplication
from rw_creature_pet.shared.atlas import Atlas, extract_atlas
from rw_creature_pet.shared.paths import DEFAULT_GAME_DIR
from rw_creature_pet.lizard.footholds import spatial_candidates
from rw_creature_pet.shared.geometry import Vec2
from rw_creature_pet.lizard.render import LizardRenderer
from tests.lizard.test_wall_observation import placed
from tests.lizard.test_wall_rhythm import walking

root = Path(__file__).resolve().parents[2] / 'artifacts'
root.mkdir(exist_ok=True)
app = QApplication.instance() or QApplication([])
QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')
app.setFont(QFont('Microsoft YaHei UI', 10))
renderer = LizardRenderer(Atlas(extract_atlas(DEFAULT_GAME_DIR)))


def panel(p, s, rect, title, candidates=False):
    p.save()
    p.setClipRect(rect)
    p.fillRect(rect, QColor('#17222d'))
    p.setPen(QColor('#dfeaf3'))
    p.setFont(QFont('Microsoft YaHei UI', 10))
    p.drawText(rect.adjusted(12, 8, -10, -5), 0, title)
    center = s.body.chunks[1].position
    p.translate(rect.center().x(), rect.center().y()+10)
    p.scale(2.7, 2.7)
    p.translate(-center.x, -center.y)
    if candidates:
        p.setPen(QPen(QColor('#455669'), .6))
        for point in spatial_candidates(center, 100):
            p.drawPoint(QPointF(point.x, point.y))
    renderer.draw(p, s, 1)
    if candidates:
        p.setPen(QPen(QColor('#67d5b7'), .5))
        for foot in s.feet:
            p.drawEllipse(QPointF(foot.position.x, foot.position.y), 1.6, 1.6)
    p.restore()


sheet = QImage(1200, 700, QImage.Format.Format_ARGB32)
sheet.fill(QColor('#17222d'))
p = QPainter(sheet)
for i, angle in enumerate((0, pi/4, -pi/2)):
    s = placed(angle)
    for _ in range(80): s.step()
    panel(p, s, QRectF(i*400, 0, 400, 350), f'首次抓附 · {int(angle*180/pi)}° · 绿圈为固定抓点', True)
    s = walking(angle, tracking=True)
    for _ in range(237): s.step()
    s.background.set_direction(Vec2())
    for _ in range(160): s.step()
    panel(p, s, QRectF(i*400, 350, 400, 350), '行走后停止 · 保留各脚实际抓点', True)
p.end()
sheet.save(str(root/'spatial-grips-rest.png'))

scenes = [walking(0), walking(-pi/2, True)]
for s in scenes:
    for _ in range(100): s.step()
frames = []
for frame in range(140):
    if frame == 100:
        for s in scenes: s.background.set_direction(Vec2())
    img = QImage(840, 400, QImage.Format.Format_RGBA8888)
    img.fill(QColor('#17222d'))
    p = QPainter(img)
    for i, s in enumerate(scenes):
        title = ('慢行' if i == 0 else '积极追踪') if frame < 100 else '停止 · 保持落脚位置'
        panel(p, s, QRectF(i*420, 0, 420, 400), title)
    p.end()
    frames.append(Image.frombytes('RGBA', (840, 400), bytes(img.constBits())).convert('RGB'))
    for s in scenes:
        for _ in range(2): s.step()
frames[0].save(root/'spatial-grips-preview.gif', save_all=True, append_images=frames[1:], duration=50, loop=0)
print('Created spatial-grips-rest.png and spatial-grips-preview.gif')
