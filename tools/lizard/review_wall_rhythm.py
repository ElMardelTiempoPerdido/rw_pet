"""渲染真实图集的墙面步态；动画每帧 50 ms 对应两个物理 tick。"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from pathlib import Path
from math import pi
from PIL import Image
from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QFont, QFontDatabase, QImage, QPainter, QPen
from PySide6.QtWidgets import QApplication
from measure_wall_rhythm import scene
from rw_creature_pet.shared.atlas import Atlas, extract_atlas
from rw_creature_pet.shared.paths import DEFAULT_GAME_DIR
from rw_creature_pet.lizard.render import LizardRenderer

root = Path(__file__).resolve().parents[2] / 'artifacts'
root.mkdir(exist_ok=True)
app = QApplication.instance() or QApplication([])
QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')
app.setFont(QFont('Microsoft YaHei UI', 10))
renderer = LizardRenderer(Atlas(extract_atlas(DEFAULT_GAME_DIR)))


def panel(p, s, rect, title, scale=2.4):
    p.save()
    p.setClipRect(rect)
    p.fillRect(rect, QColor('#17222d'))
    p.setPen(QColor('#dfeaf3'))
    p.setFont(QFont('Microsoft YaHei UI', 10))
    p.drawText(rect.adjusted(12, 8, -10, -5), 0, title)
    center = s.body.chunks[1].position
    p.translate(rect.center().x(), rect.center().y()+20)
    p.scale(scale, scale)
    p.translate(-center.x, -center.y)
    p.setPen(QPen(QColor('#243746'), .4))
    for x in range(int(center.x-150)//10*10, int(center.x+150), 10):
        p.drawLine(x, int(center.y-150), x, int(center.y+150))
    for y in range(int(center.y-150)//10*10, int(center.y+150), 10):
        p.drawLine(int(center.x-150), y, int(center.x+150), y)
    renderer.draw(p, s, 1.0)
    p.restore()


sheet = QImage(1440, 640, QImage.Format.Format_ARGB32)
sheet.fill(QColor('#17222d'))
p = QPainter(sheet)
for i in range(8):
    s = scene(i*pi/4, True)
    for _ in range(260): s.step()
    panel(p, s, QRectF((i%4)*360, (i//4)*320, 360, 320), f'{i*45}° · 积极追踪 · 抓地 {s.background.grip_count}/4', 2.1)
p.end()
sheet.save(str(root/'wall-rhythm-directions.png'))

scenes = [scene(angle, tracking) for tracking in (False, True) for angle in (0, -pi/2)]
for s in scenes:
    for _ in range(200): s.step()
frames = []
for tick in range(160):
    img = QImage(880, 640, QImage.Format.Format_RGBA8888)
    img.fill(QColor('#17222d'))
    p = QPainter(img)
    for i, s in enumerate(scenes):
        title = ('慢行 · 约 32 单位/秒' if i<2 else '积极追踪 · 约 52 单位/秒')
        panel(p, s, QRectF((i%2)*440, (i//2)*320, 440, 320), title)
    p.end()
    frames.append(Image.frombytes('RGBA', (880, 640), bytes(img.constBits())).convert('RGB'))
    for s in scenes:
        for _ in range(2): s.step()
frames[0].save(root/'wall-rhythm-preview.gif', save_all=True, append_images=frames[1:], duration=50, loop=0)
print('Created wall-rhythm-directions.png and wall-rhythm-preview.gif')
