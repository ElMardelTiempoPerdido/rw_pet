"""真实图集下，独立观察/倾斜时的内搭与完整衣领对照。"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
(ROOT/'artifacts').mkdir(exist_ok=True)

from PySide6.QtGui import QColor, QFont, QFontDatabase, QImage, QPainter
from PySide6.QtWidgets import QApplication
from rw_creature_pet.shared.atlas import Atlas, extract_atlas
from rw_creature_pet.config import AppConfig
from rw_creature_pet.shared.geometry import Vec2
from rw_creature_pet.oracle.scene import OracleScene
from rw_creature_pet.oracle.render import OracleRenderer


def main():
    app = QApplication.instance() or QApplication([])
    font_id = QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')
    app.setFont(QFont(QFontDatabase.applicationFontFamilies(font_id)[0], 9))
    config = AppConfig.load(ROOT/'config.toml')
    renderer = OracleRenderer(Atlas(extract_atlas(config.game_dir)), config.oracle.colors)
    image = QImage(1200, 700, QImage.Format.Format_RGBA8888)
    image.fill(QColor('#17232e'))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    poses = [('look up', Vec2(0, -100), 0), ('look left', Vec2(-100, 0), 0),
             ('look right', Vec2(100, 0), 0), ('look down', Vec2(0, 100), 0),
             ('tilt -25', Vec2(-100, -30), -25), ('tilt +25', Vec2(100, -30), 25)]
    try:
        for i, (label, target, tilt) in enumerate(poses):
            scene = OracleScene(config.oracle)
            scene.set_tilt(tilt)
            scene.set_look_target(scene.appearance.upper+target)
            for _ in range(260):
                scene.step()
            a = scene.appearance
            x, y = i % 3*400, i//3*350
            painter.setPen(QColor('#d7e5ed'))
            painter.drawText(x+12, y+24, label+' / 5x')
            painter.drawText(x+30, y+320, 'body tint only')
            painter.drawText(x+250, y+320, 'full costume')
            for column in range(2):
                painter.save()
                painter.translate(x+100+column*200, y+130)
                painter.scale(5, 5)
                painter.translate(-a.upper.x, -a.upper.y)
                args = (painter, scene, 1., a.upper, a.lower, a.direction,
                        a.head.position, scene.look_direction)
                if column == 0:
                    renderer.draw_inner_robe(painter, a.upper, a.lower, a.direction, a.head.position)
                    renderer.draw_head(painter, a.head.position, a.upper, a.direction, scene.look_direction)
                else:
                    renderer.draw_body(*args)
                    renderer.draw_necklace(painter, scene, 1.)
                    renderer.draw_body_front(*args)
                painter.restore()
    finally:
        painter.end()
    image.save(str(ROOT/'artifacts/oracle-collar-poses.png'))
    print('Saved oracle-collar-poses.png', flush=True)


if __name__ == '__main__':
    main()
