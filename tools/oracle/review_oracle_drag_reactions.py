"""实际图集下对照自然惯性、随机扑腾、固定交替与抗议；不发出鼠标输入或声音。"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from dataclasses import replace
from math import sin
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from PIL import Image
from PySide6.QtGui import QColor, QFont, QFontDatabase, QImage, QPainter
from PySide6.QtWidgets import QApplication
from rw_creature_pet.config import AppConfig
from rw_creature_pet.oracle.config import DragReactionConfig
from rw_creature_pet.oracle.scene import OracleScene
from rw_creature_pet.oracle.render import OracleRenderer
from rw_creature_pet.shared.atlas import Atlas, extract_atlas
from rw_creature_pet.shared.geometry import Vec2


def main():
    app = QApplication.instance() or QApplication([])
    QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')
    config = AppConfig.load(ROOT/'config.toml')
    renderer = OracleRenderer(Atlas(extract_atlas(config.game_dir)), config.oracle.colors)
    kinds = (None, 'flutter', 'alternating', 'protest')
    scenes = []
    for kind in kinds:
        scene = OracleScene(replace(config.oracle, halo_enabled=False,
            pearl_matrix_enabled=False, pearl_orbits_enabled=False, pearl_fixed_count=0,
            drag_reactions=DragReactionConfig(enabled=kind is not None, gesture_probability=0.,
                eye_open_probability=1., voice_probability=0.)))
        scene.drag.set_enabled(True)
        for _ in range(650):
            scene.step()
        scene.drag.press(scene.head.position, lambda _: True)
        scenes.append(scene)
    start = scenes[0].drag.controller.pointer
    frames, cards = [], []
    for tick in range(220):
        for index, scene in enumerate(scenes):
            # 前半段静止抓住，之后快速牵拉，最后松手；手势仅为 QA 固定抽签。
            if tick in (0, 90) and kinds[index] is not None:
                scene.drag_reactions.start_gesture(kinds[index], scene)
            if 80 <= tick < 165:
                scene.drag.move(start+Vec2(65*sin((tick-80)*.035), 35*sin((tick-80)*.06)))
            if tick == 165:
                scene.drag.release()
            scene.step()
        if tick % 2:
            continue
        frame = QImage(320*len(scenes), 360, QImage.Format.Format_RGBA8888)
        frame.fill(QColor('#18212c'))
        painter = QPainter(frame)
        painter.setFont(QFont('Microsoft YaHei', 10))
        for index, scene in enumerate(scenes):
            painter.save()
            painter.setClipRect(index*320, 35, 320, 300)
            painter.translate(index*320+160, 155)
            painter.scale(4, 4)
            upper = scene.body.chunks[0].position
            painter.translate(-upper.x, -upper.y)
            renderer.draw(painter, scene, cords=False)
            painter.restore()
            painter.setPen(QColor('#e0e5e9'))
            painter.drawText(index*320+16, 24, ('Natural inertia', 'Flutter', 'Alternating', 'Protest')[index]+' / 4x')
        phase = 'Held still' if tick < 80 else ('Pulled' if tick < 165 else 'Released')
        painter.drawText(16, 350, f'{phase}  {tick/40:.2f}s')
        painter.end()
        pil = Image.frombytes('RGBA', (frame.width(), frame.height()), bytes(frame.constBits())).convert('RGB')
        frames.append(pil)
        if tick in (20, 44, 68, 114, 152, 212):
            cards.append(pil)
    output = ROOT/'artifacts'
    frames[0].save(output/'oracle-drag-reactions.gif', save_all=True, append_images=frames[1:],
                   duration=50, loop=0)
    sheet = Image.new('RGB', (320*len(scenes), 360*len(cards)))
    for i, card in enumerate(cards):
        sheet.paste(card, (0, i*360))
    sheet.save(output/'oracle-drag-reactions.png')
    print('Saved artifacts/oracle-drag-reactions.gif and .png')


if __name__ == '__main__':
    main()
