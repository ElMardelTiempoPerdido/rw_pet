"""真实图集复核头颈：自动观察、边走边看、掉头、平地观察。"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
(Path(__file__).resolve().parents[2]/'artifacts').mkdir(exist_ok=True)
from PIL import Image
from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QColor, QFont, QFontDatabase, QImage, QPainter, QPen
from PySide6.QtWidgets import QApplication
from rw_creature_pet.shared.atlas import Atlas, extract_atlas
from rw_creature_pet.shared.paths import DEFAULT_GAME_DIR
from rw_creature_pet.lizard.config import DebugConfig
from rw_creature_pet.shared.geometry import Vec2
from rw_creature_pet.lizard.scene import DebugScene
from rw_creature_pet.lizard.render import LizardRenderer
from tests.lizard.test_wall_observation import placed
from tests.lizard.test_wall_rhythm import walking

root = Path(__file__).resolve().parents[2] / 'artifacts'
root.mkdir(exist_ok=True)
app = QApplication.instance() or QApplication([])
QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')
app.setFont(QFont('Microsoft YaHei UI', 10))
renderer = LizardRenderer(Atlas(extract_atlas(DEFAULT_GAME_DIR)))
floor = DebugScene(DebugConfig(world_width=1000, world_height=700, floor_y=650))
floor.gait.enabled = True
floor.gait.posture = 'raised'
scenes = [placed(), walking(), walking(tracking=True), floor]
for s in scenes:
    for _ in range(220): s.step()
scenes[1].appearance.observe(scenes[1].body.chunks[0].position+Vec2(160, -95), 600)
titles = ('趴墙停留 · 自动保持空间观察点', '直行 · 保持右键指定的观察点',
          '掉头 · 头颈连续跟随', '平地抬胸 · 自动观察 / 指定观察')


def panel(p, s, rect, title):
    p.save()
    p.setClipRect(rect)
    p.fillRect(rect, QColor('#17222d'))
    p.setPen(QColor('#dfeaf3'))
    p.setFont(QFont('Microsoft YaHei UI', 10))
    p.drawText(rect.adjusted(12, 8, -10, -5), 0, title)
    center = s.body.chunks[1].position
    p.translate(rect.center().x(), rect.center().y()+15)
    p.scale(2.1, 2.1)
    p.translate(-center.x, -center.y)
    p.setPen(QPen(QColor('#273c4d'), .3))
    for x in range(int(center.x-100)//20*20, int(center.x+100), 20):
        p.drawLine(x, int(center.y-100), x, int(center.y+100))
    for y in range(int(center.y-100)//20*20, int(center.y+100), 20):
        p.drawLine(int(center.x-100), y, int(center.x+100), y)
    if not s.background_mode:
        p.fillRect(QRectF(0, s.world.floor_y, s.world.width, 200), QColor('#283e36'))
    renderer.draw(p, s, 1)
    target = s.appearance.gaze.point
    if target is not None:
        head = s.appearance.head.position
        color = QColor('#75bbfa' if s.appearance.look_target is not None else '#e9c68a')
        p.setPen(QPen(color, .4))
        direction = target-head
        end = head+direction*(min(35, direction.length())/max(direction.length(), 1))
        p.drawLine(QPointF(head.x, head.y), QPointF(end.x, end.y))
        p.drawEllipse(QPointF(target.x, target.y), 2, 2)
    p.restore()


frames = []
for frame in range(180):
    if frame == 40:
        s = scenes[2]
        s.background.set_goal(s.body.chunks[1].position+Vec2(-170, 0), s.body, s.world)
    if frame == 85:
        floor.appearance.observe(floor.body.chunks[0].position+Vec2(60, -120), 130)
    img = QImage(1040, 680, QImage.Format.Format_RGBA8888)
    img.fill(QColor('#17222d'))
    p = QPainter(img)
    for i, s in enumerate(scenes):
        panel(p, s, QRectF((i%2)*520, (i//2)*340, 520, 340), titles[i])
    p.end()
    frames.append(Image.frombytes('RGBA', (1040, 680), bytes(img.constBits())).convert('RGB'))
    if frame in (0, 55, 100, 150):
        img.save(str(root/f'gaze-frame-{frame:03}.png'))
    for s in scenes:
        for _ in range(2): s.step()
frames[0].save(root/'gaze-preview.gif', save_all=True, append_images=frames[1:], duration=50, loop=0)
print('Created gaze-preview.gif and four review frames')
