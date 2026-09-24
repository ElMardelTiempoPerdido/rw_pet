"""真实图集下的闭眼/睁眼与无细绳项链预览；只为对照强制眼睛端点。"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
(ROOT/'artifacts').mkdir(exist_ok=True)

from PySide6.QtCore import Qt
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
    config = AppConfig.load(ROOT/'config.toml')
    renderer = OracleRenderer(Atlas(extract_atlas(config.game_dir)), config.oracle.colors)
    sheet = QImage(960, 600, QImage.Format.Format_RGBA8888)
    sheet.fill(QColor('#17232e'))
    painter = QPainter(sheet)
    try:
        painter.setFont(QFont('Microsoft YaHei', 10))
        for row, openness in enumerate((0., 1.)):
            for column, (label, gaze) in enumerate((('正面', Vec2()), ('轻微侧视', Vec2(.4, 0)),
                                                    ('侧视', Vec2(1, 0)), ('抬眼', Vec2(0, -.7)),
                                                    ('低头', Vec2(0, .7)))):
                x, y = column*192, row*170
                painter.setPen(QColor('#e0e5e9'))
                painter.drawText(x+12, y+24, ('闭眼' if row == 0 else '睁眼')+' / '+label)
                painter.save()
                painter.translate(x+96, y+86)
                painter.scale(6, 6)
                renderer.draw_head(painter, Vec2(), Vec2(0, 14), Vec2(0, -1), gaze, openness)
                painter.restore()
                renderer.draw_head(painter, Vec2(x+25, y+145), Vec2(x+25, y+159), Vec2(0, -1), gaze, openness)
        scene = OracleScene(config.oracle)
        for _ in range(650):
            scene.step()
        for column, openness in enumerate((0., 1.)):
            scene.eyes.openness = scene.eyes.previous_openness = openness
            painter.setPen(QColor('#e0e5e9'))
            painter.drawText(40+column*460, 368, '完整外观 / 项链隐藏细绳 / 4×')
            painter.save()
            painter.setClipRect(10+column*460, 375, 440, 225)
            painter.translate(230+column*460, 458)
            painter.scale(4, 4)
            upper = scene.body.chunks[0].position
            painter.translate(-upper.x, -upper.y)
            renderer.draw(painter, scene, cords=False)
            painter.restore()
    finally:
        painter.end()
    assert sheet.save(str(ROOT/'artifacts/oracle-bell-eyes.png'))

    # 实际图集下检查不同视角与插值的缓存/直接绘制结果。
    checks = 0
    scene.appearance.step = lambda scene: None
    for gaze in (Vec2(550, 10), Vec2(450, 150), Vec2(350, 60)):
        scene.set_look_target(gaze)
        for _ in range(20):
            scene.step()
        scene.eyes.previous_openness, scene.eyes.openness = 0., 1.
        scene.appearance.sleeping = False
        scene.appearance.revision += 1
        for alpha in (0., .5, 1.):
            frames = []
            for direct in (False, True):
                image = QImage(960, 600, QImage.Format.Format_RGBA8888)
                image.fill(Qt.GlobalColor.transparent)
                p = QPainter(image)
                try:
                    (renderer.draw_geometry if direct else renderer.draw)(p, scene, alpha)
                finally:
                    p.end()
                frames.append(bytes(image.constBits()))
            assert frames[0] == frames[1], (gaze, alpha)
            checks += 1
    print(f'Saved oracle-bell-eyes.png; {checks} real-atlas cache comparisons passed.')


if __name__ == '__main__':
    main()
