"""生成真实图集步态预览和可重跑的 30 秒测量；在项目根目录执行。"""
import json
import os
from pathlib import Path
from statistics import mean
import sys

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
(Path(__file__).resolve().parents[2]/'artifacts').mkdir(exist_ok=True)
from PIL import Image
from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QFont, QFontDatabase, QImage, QPainter, QPen
from PySide6.QtWidgets import QApplication
from rw_creature_pet.shared.atlas import Atlas, extract_atlas
from rw_creature_pet.lizard.config import DebugConfig
from rw_creature_pet.shared.paths import DEFAULT_GAME_DIR
from rw_creature_pet.lizard.gait import FlatGait, FootPhase
from rw_creature_pet.lizard.render import LizardRenderer
from rw_creature_pet.lizard.scene import DebugScene

root = Path(__file__).resolve().parents[2] / 'artifacts'
root.mkdir(exist_ok=True)
app = QApplication.instance() or QApplication([])
QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')
app.setFont(QFont('Microsoft YaHei UI', 10))
renderer = LizardRenderer(Atlas(extract_atlas(DEFAULT_GAME_DIR)))


def scene(intent, direction=1):
    s = DebugScene(DebugConfig(world_width=10000, world_height=500, floor_y=450))
    s.gait.enabled = True
    s.gait.set_speed(direction * FlatGait.MAX_SPEED * intent)
    for _ in range(200): s.step()
    return s


def panel(p, s, rect, title, scale=3):
    p.save()
    p.setClipRect(rect)
    p.fillRect(rect, QColor('#17222d'))
    p.setPen(QColor('#dfebf3'))
    p.setFont(QFont('Microsoft YaHei UI', 10))
    p.drawText(rect.adjusted(12, 5, -10, -5), 0, title)
    floor = rect.bottom()-24
    center = s.body.chunks[1].position.x
    p.fillRect(QRectF(rect.left(), floor, rect.width(), 24), QColor('#294239'))
    p.translate(rect.center().x()+35, floor)
    p.scale(scale, scale)
    p.translate(-center, -s.world.floor_y)
    p.setPen(QPen(QColor('#50636a'), .4))
    for x in range(int(center-150)//10*10, int(center+150), 10):
        p.drawLine(x, 450, x, 455)
    renderer.draw(p, s, 1.0)
    p.restore()


results = []
for label, intent in (('slow', FlatGait.SLOW_INTENT), ('active', FlatGait.TRACK_INTENT)):
    for direction in (-1, 1):
        s = scene(intent, direction)
        start = s.body.chunks[1].position.x
        last = [None]*4
        strides = [[] for _ in s.feet]
        durations = [[] for _ in s.feet]
        minimum_grips, air_ticks, sliding = 4, 0, 0
        for _ in range(1200):
            old = [(f.phase, f.position) for f in s.feet]
            s.step()
            minimum_grips = min(minimum_grips, s.gait.grip_count)
            for i, (f, (phase, pos)) in enumerate(zip(s.feet, old)):
                air_ticks += f.phase == FootPhase.AIR
                sliding += f.phase == phase == FootPhase.STANCE and f.position != pos
                if f.phase == FootPhase.STANCE and phase == FootPhase.SWING:
                    if last[i] is not None: strides[i].append(abs(f.position.x-last[i]))
                    last[i] = f.position.x
                    durations[i].append(f.swing_tick)
        results.append(dict(pace=label, direction=direction,
                            body_units_per_second=abs(s.body.chunks[1].position.x-start)/30,
                            mean_stride=[mean(x) for x in strides],
                            steps_per_second=[len(x)/30 for x in durations],
                            swing_ticks=[sorted(set(x)) for x in durations],
                            minimum_grips=minimum_grips, air_ticks=air_ticks, sliding_ticks=sliding))
root.joinpath('flat-stride-metrics.json').write_text(json.dumps(results, indent=2), encoding='utf-8')

sheet = QImage(1260, 640, QImage.Format.Format_ARGB32)
sheet.fill(QColor('#17222d'))
p = QPainter(sheet)
for row, (title, intent, spacing) in enumerate((('慢行', FlatGait.SLOW_INTENT, 8), ('积极移动', FlatGait.TRACK_INTENT, 5))):
    s = scene(intent)
    for _ in range(100):
        old = s.feet[0].phase
        s.step()
        if old == FootPhase.STANCE and s.feet[0].phase == FootPhase.SWING: break
    for i in range(6):
        if i:
            for _ in range(spacing): s.step()
        rect = QRectF((i%3)*420, (row*2+i//3)*160, 420, 160)
        panel(p, s, rect, f'{title} · {i*spacing/40:.3f}s · 支撑 {s.gait.grip_count}/4', 2.8)
p.end()
sheet.save(str(root/'flat-stride-cycle.png'))

slow, active = scene(FlatGait.SLOW_INTENT), scene(FlatGait.TRACK_INTENT)
frames = []
for i in range(160):
    img = QImage(800, 400, QImage.Format.Format_RGBA8888)
    img.fill(QColor('#17222d'))
    p = QPainter(img)
    panel(p, slow, QRectF(0, 0, 800, 200), '慢行 · 约 31 单位/秒')
    panel(p, active, QRectF(0, 200, 800, 200), '积极移动 · 约 48 单位/秒')
    p.end()
    frames.append(Image.frombytes('RGBA', (800, 400), bytes(img.constBits())).convert('RGB'))
    for _ in range(2):
        slow.step()
        active.step()
frames[0].save(root/'flat-stride-preview.gif', save_all=True, append_images=frames[1:], duration=50, loop=0)
print(json.dumps(results, indent=2))
print('Created flat-stride-cycle.png, flat-stride-preview.gif, flat-stride-metrics.json')
