"""阶段 5：真实配色的移动/停止/观察近景和可复现的收敛测量。"""
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
from PySide6.QtCore import QPointF
from PySide6.QtGui import QColor, QFont, QFontDatabase, QImage, QPainter
from PySide6.QtWidgets import QApplication

from rw_creature_pet.shared.atlas import Atlas, extract_atlas
from rw_creature_pet.config import AppConfig
from rw_creature_pet.shared.geometry import Vec2
from rw_creature_pet.oracle.scene import OracleScene
from rw_creature_pet.oracle.render import OracleRenderer


def main():
    app = QApplication.instance() or QApplication([])
    QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')
    app.setFont(QFont('Microsoft YaHei UI', 10))
    config = AppConfig.load(ROOT/'config.toml')
    renderer = OracleRenderer(Atlas(extract_atlas(config.game_dir)), config.oracle.colors)
    scene = OracleScene(config.oracle)
    scene.set_target(Vec2(760, 65))
    frames, poses, observations = [], [], []
    metrics = dict(config_sha256=hashlib.sha256((ROOT/'config.toml').read_bytes()).hexdigest(),
                   max_cloth_offset=0., max_cloth_step=0., max_cloth_radius=0.,
                   max_cloth_link_error=0., max_sway_degrees=0., max_secondary_step=0.,
                   max_hand_reach=0., max_hand_step=0.)
    physics_time = 0.
    for tick in range(1100):
        if tick == 100:
            scene.stop()
        if tick == 720:
            scene.set_look_target(scene.body.chunks[0].position+Vec2(100, -30))
        if tick == 870:
            scene.set_look_target(scene.body.chunks[0].position+Vec2(-100, -30))
        start = perf_counter()
        scene.step()
        physics_time += perf_counter()-start
        appearance = scene.appearance
        goals = appearance.cloth_goals()
        offset = max((p.position-g).length() for p, g in zip(appearance.cloth, goals))
        cloth_speed = max(p.velocity.length() for p in appearance.cloth)
        metrics['max_cloth_offset'] = max(metrics['max_cloth_offset'], offset)
        metrics['max_cloth_step'] = max(metrics['max_cloth_step'], cloth_speed)
        metrics['max_cloth_radius'] = max(metrics['max_cloth_radius'],
                                         *( (p.position-appearance.upper).length() for p in appearance.cloth))
        metrics['max_cloth_link_error'] = max(metrics['max_cloth_link_error'],
            *(abs((appearance.cloth[b].position-appearance.cloth[a].position).length()-(goals[b]-goals[a]).length())
              for a, b in appearance.cloth_links))
        metrics['max_sway_degrees'] = max(metrics['max_sway_degrees'], abs(appearance.sway)*180/3.141592653589793)
        metrics['max_secondary_step'] = max(metrics['max_secondary_step'], appearance.maximum_speed)
        hand_offsets = [p.position-appearance.upper for p in appearance.hands]
        metrics['max_hand_reach'] = max(metrics['max_hand_reach'], *(p.length() for p in hand_offsets))
        metrics['max_hand_step'] = max(metrics['max_hand_step'], *(p.velocity.length() for p in appearance.hands))
        if tick in (99, 140, 200, 400, 650, 1099):
            n = appearance.CLOTH_DIVS
            hem = appearance.cloth[(n-1)*n+n//2].position-appearance.upper
            observations.append(dict(tick=tick, cloth_offset=offset, cloth_speed=cloth_speed,
                                     hem_center_down=hem.y,
                                     hem_width=(appearance.cloth[-1].position-appearance.cloth[-n].position).length(),
                                     speed=appearance.maximum_speed,
                                     sleeping=appearance.sleeping,
                                     hand_offsets=[[p.x, p.y] for p in hand_offsets]))
        if tick % 4 == 0 or tick in (0, 60, 101, 140, 650, 850, 1050):
            image = QImage(400, 340, QImage.Format.Format_RGBA8888)
            image.fill(QColor('#17232e'))
            painter = QPainter(image)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(QColor('#d7e5ed'))
            painter.setFont(QFont('Microsoft YaHei UI', 10))
            painter.drawText(QPointF(12, 24), f'{tick/40:.2f}s / '+('move' if tick < 100 else 'stop / look'))
            painter.translate(200, 160)
            painter.scale(5, 5)
            upper = scene.body.chunks[0].position
            painter.translate(-upper.x, -upper.y)
            renderer.draw(painter, scene)
            painter.end()
            frame = Image.frombytes('RGBA', (400, 340), bytes(image.constBits())).convert('RGB')
            if tick % 4 == 0:
                frames.append(frame)
            if tick in (0, 60, 101, 140, 650, 850, 1050):
                poses.append(frame)
    frames[0].save(ROOT/'artifacts/oracle-appearance-preview.gif', save_all=True,
                   append_images=frames[1:], duration=100, loop=0, optimize=False)
    # 最后一格查看原版默认 Moon 调色，避免只检查用户自定义粉色衣袍。
    from rw_creature_pet.oracle.config import OracleColors
    renderer.colors = OracleColors()
    painter = QPainter(image)
    painter.fillRect(image.rect(), QColor('#17232e'))
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QColor('#d7e5ed'))
    painter.drawText(QPointF(12, 24), 'Moon default colors')
    painter.translate(200, 160)
    painter.scale(5, 5)
    painter.translate(-upper.x, -upper.y)
    renderer.draw(painter, scene)
    painter.end()
    poses.append(Image.frombytes('RGBA', (400, 340), bytes(image.constBits())).convert('RGB'))
    sheet = Image.new('RGB', (1600, 680), '#17232e')
    for i, frame in enumerate(poses):
        sheet.paste(frame, ((i % 4)*400, (i//4)*340))
    sheet.save(ROOT/'artifacts/oracle-appearance-poses.png')
    metrics.update(observations=observations, mean_step_ms=physics_time/1.1)
    (ROOT/'artifacts/oracle-appearance-metrics.json').write_text(json.dumps(metrics, indent=2), encoding='utf-8')
    print(json.dumps(metrics, indent=2))


if __name__ == '__main__':
    main()
