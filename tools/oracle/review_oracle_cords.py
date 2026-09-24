"""真实图集线缆预览：完整绕行、近景与绳段/静置测量。"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import hashlib
import json
from pathlib import Path
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
(ROOT/'artifacts').mkdir(exist_ok=True)

from PIL import Image
from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QColor, QFont, QFontDatabase, QImage, QPainter
from PySide6.QtWidgets import QApplication
from rw_creature_pet.shared.atlas import Atlas, extract_atlas
from rw_creature_pet.config import AppConfig
from rw_creature_pet.oracle.scene import OracleScene
from rw_creature_pet.oracle.render import OracleRenderer


def render(scene, renderer, tick, close=False):
    size = (400, 340) if close else (960, 600)
    image = QImage(*size, QImage.Format.Format_RGBA8888)
    image.fill(QColor('#17232e'))
    p = QPainter(image)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(QColor('#d7e5ed'))
    p.setFont(QFont('Microsoft YaHei UI', 10))
    p.drawText(QPointF(12, 24), f'{tick/40:.1f}s / '+('停留' if scene.arrived else '绕行'))
    if close:
        upper = scene.appearance.upper
        p.translate(200, 140)
        p.scale(4, 4)
        p.translate(-upper.x, -upper.y)
    else:
        p.scale(960/scene.world.width, 600/scene.world.height)
        h = scene.world.inner
        p.fillRect(QRectF(h.left,h.top,h.right-h.left,h.bottom-h.top), QColor('#111923'))
    renderer.draw(p, scene)
    p.end()
    return Image.frombytes('RGBA', size, bytes(image.constBits())).convert('RGB')


def main():
    app = QApplication.instance() or QApplication([])
    QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')
    config = AppConfig.load(ROOT/'config.toml')
    scene = OracleScene(config.oracle)
    renderer = OracleRenderer(Atlas(extract_atlas(config.game_dir)), config.oracle.colors)
    scene.start_lap()
    metrics = dict(config_sha256=hashlib.sha256((ROOT/'config.toml').read_bytes()).hexdigest(),
                   max_main_step=0., max_main_link_error=0., max_fine_link_error=0.,
                   max_junction_radius=0., max_fine_radius=0., observations=[])
    frames, poses = [], []
    elapsed = 0.
    for tick in range(2150):
        start = perf_counter()
        scene.step()
        elapsed += perf_counter()-start
        a = scene.appearance
        metrics['max_main_step'] = max(metrics['max_main_step'], *(p.velocity.length() for p in a.main_cord))
        metrics['max_junction_radius'] = max(metrics['max_junction_radius'], (a.main_cord[-1].position-a.upper).length())
        metrics['max_fine_radius'] = max(metrics['max_fine_radius'],
            *((p.position-a.upper).length() for c in a.small_cords for p in c))
        for key, ropes in (('max_main_link_error', [a.cords.main]), ('max_fine_link_error', a.cords.fine)):
            metrics[key] = max(metrics[key], *(abs((q.position-p.position).length()-rest)
                for rope in ropes for p,q,rest in zip(rope.points,rope.points[1:],rope.rest)))
        if scene.arrived and 'arrived_tick' not in metrics:
            metrics['arrived_tick'] = tick+1
        if tick % 10 == 0:
            frames.append(render(scene, renderer, tick))
        if tick in (120, 440, 800, 1200, 1600, 2149):
            poses.append(render(scene, renderer, tick, close=True))
            metrics['observations'].append(dict(tick=tick, speed=a.maximum_speed, sleeping=a.sleeping))
    metrics['mean_step_ms'] = elapsed/2150*1000
    metrics['fine_lengths'] = scene.appearance.cords.fine_lengths
    sheet = Image.new('RGB', (1200, 680))
    for i, pose in enumerate(poses):
        sheet.paste(pose, ((i%3)*400, (i//3)*340))
    out = ROOT/'artifacts'
    sheet.save(out/'oracle-cords-poses.png')
    frames[0].save(out/'oracle-cords-preview.gif', save_all=True, append_images=frames[1:],
                   duration=250, loop=0, optimize=False)
    frames[-1].save(out/'oracle-cords-overview.png')
    (out/'oracle-cords-metrics.json').write_text(json.dumps(metrics, indent=2), encoding='utf-8')
    print(json.dumps(metrics, indent=2))
    assert app is not None


if __name__ == '__main__':
    main()
