"""真实图集机械臂四角近景与外壳连续性测量，不修改配置。"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
(ROOT/'artifacts').mkdir(exist_ok=True)

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QColor, QFont, QFontDatabase, QImage, QPainter
from PySide6.QtWidgets import QApplication

from rw_creature_pet.shared.atlas import Atlas, extract_atlas
from rw_creature_pet.config import AppConfig
from rw_creature_pet.shared.geometry import Vec2
from rw_creature_pet.oracle.scene import OracleScene
from rw_creature_pet.oracle.arm_graphics import base_outline
from rw_creature_pet.oracle.render import OracleRenderer


def main():
    app = QApplication.instance() or QApplication([])
    QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')
    app.setFont(QFont('Microsoft YaHei UI', 10))
    config = AppConfig.load(ROOT/'config.toml')
    renderer = OracleRenderer(Atlas(extract_atlas(config.game_dir)), config.oracle.colors)
    scene = OracleScene(config.oracle)
    scene.start_lap()
    sheet = QImage(1200, 840, QImage.Format.Format_ARGB32_Premultiplied)
    sheet.fill(QColor('#17232e'))
    painter = QPainter(sheet)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    last, corners = None, []
    metrics = dict(max_shell_vertex_step=0., max_cog_turn_step=0.)
    for tick in range(1800):
        scene.step()
        frames = renderer.arm_frames(scene, 1.)
        vertices = [v for frame in frames for strip in frame.strips for v in strip.outline()]
        if last:
            metrics['max_shell_vertex_step'] = max(metrics['max_shell_vertex_step'],
                                                  max((a-b).length() for a, b in zip(vertices, last)))
        last = vertices
        metrics['max_cog_turn_step'] = max(metrics['max_cog_turn_step'],
            max(abs(a-b) for a, b in zip(scene.appearance.cog_turns, scene.appearance.previous_cog_turns)))
        normal = scene.base_normal()
        if abs(normal.x) > .60 and abs(normal.y) > .60 and (not corners or tick-corners[-1] > 80):
            i = len(corners)
            corners.append(tick)
            x, y = (i % 2)*600, (i//2)*420
            body = scene.body.chunks[0].position
            points = vertices+base_outline(scene.base, normal, scene.config.arm_scale)
            points += [body+Vec2(-36, -36), body+Vec2(36, 36)]
            left, right = min(v.x for v in points)-12, max(v.x for v in points)+12
            top, bottom = min(v.y for v in points)-12, max(v.y for v in points)+12
            scale = min(560/(right-left), 365/(bottom-top))
            painter.save()
            painter.setClipRect(QRectF(x, y, 600, 420))
            painter.setPen(QColor('#d7e5ed'))
            painter.drawText(QPointF(x+18, y+24), f'Corner {i+1} / tick {tick} / {scale:.1f}x')
            painter.translate(x+300, y+225)
            painter.scale(scale, scale)
            painter.translate(-(left+right)*.5, -(top+bottom)*.5)
            renderer.draw(painter, scene)
            painter.restore()
        if scene.arrived:
            metrics['arrived_tick'] = tick+1
            break
    painter.end()
    metrics['corner_ticks'] = corners
    sheet.save(str(ROOT/'artifacts/oracle-arm-corners.png'))
    (ROOT/'artifacts/oracle-arm-metrics.json').write_text(json.dumps(metrics, indent=2), encoding='utf-8')
    print(json.dumps(metrics, indent=2))


if __name__ == '__main__':
    main()
