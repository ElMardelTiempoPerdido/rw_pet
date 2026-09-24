"""可重现的真实图集预览；不启动常驻窗口，不修改配置或游戏资源。"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'

from dataclasses import replace
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
(ROOT/'artifacts').mkdir(exist_ok=True)

from PIL import Image
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QImage, QPainter
from PySide6.QtWidgets import QApplication

from rw_creature_pet.config import AppConfig
from rw_creature_pet.shared.geometry import Vec2
from rw_creature_pet.oracle.scene import OracleScene, RailSide
from rw_creature_pet.oracle.debug_window import OracleDebugWindow


def main():
    app = QApplication.instance() or QApplication([])
    app.setStyle('Fusion')
    QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')
    app.setFont(QFont('Microsoft YaHei UI', 10))
    config = AppConfig.load(ROOT / 'config.toml')
    window = OracleDebugWindow(config, ROOT / 'config.toml')
    window.timer.stop()
    window.pause_button.setChecked(True)
    for _ in range(300):
        window.scene.step()
    window.show()
    window.refresh()
    app.processEvents()
    output = ROOT / 'artifacts'
    window.grab().save(str(output / 'oracle-debug.png'))

    frames = []
    # 连续移动再停下观察；每帧包含完整机械臂与四倍人偶局部。
    for tick in range(480):
        if tick == 0:
            window.scene.set_target(Vec2(280, 65))
        if tick == 150:
            window.scene.set_target(Vec2(650, 70))
        if tick == 300:
            window.scene.stop()
            window.scene.set_look_target(Vec2(750, 300))
        if tick == 390:
            window.scene.set_look_target(Vec2(100, 0))
        window.scene.step()
        if tick % 6 == 0:
            window.refresh()
            app.processEvents()
            image = window.canvas.grab().toImage().convertToFormat(QImage.Format.Format_RGBA8888)
            frames.append(Image.frombytes('RGBA', (image.width(), image.height()), bytes(image.constBits())).convert('RGB'))
    frames[0].save(output / 'oracle-preview.gif', save_all=True, append_images=frames[1:],
                   duration=150, loop=0, optimize=False)

    # 同一批四边、两个角落及调色姿态，检查缩放后是否裁切或遮挡异常。
    sheet = QImage(1200, 800, QImage.Format.Format_ARGB32_Premultiplied)
    sheet.fill(QColor('#17232e'))
    painter = QPainter(sheet)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    cases = [('top', .5, 0), ('right', .5, 0), ('bottom', .5, 0), ('left', .5, 0),
             ('top', 0, -20), ('bottom', 1, 20), ('left', 0, 0), ('right', 1, 0)]
    for i, (side, fraction, tilt) in enumerate(cases):
        scene = OracleScene(replace(config.oracle, base_side=side, base_fraction=fraction))
        scene.set_tilt(tilt)
        scene.set_look_target(scene.body.chunks[0].position + Vec2(100 if i % 2 else -100, -30))
        for _ in range(400):
            scene.step()
        x, y = (i % 4) * 300, (i // 4) * 400
        painter.save()
        painter.setClipRect(QRectF(x, y, 300, 400))
        painter.setPen(QColor('#c9d8e6'))
        painter.drawText(QPointF(x + 15, y + 26), f'{side} / {fraction:.0%} / {tilt} deg')
        painter.translate(x + 150, y + 155)
        painter.scale(4, 4)
        upper = scene.body.chunks[0].position
        painter.translate(-upper.x, -upper.y)
        if i >= 6:
            window.renderer.colors = replace(config.oracle.colors, skin='#b799d4', robe_top='#5e8893', robe_bottom='#293e5d')
        else:
            window.renderer.colors = config.oracle.colors
        window.renderer.draw(painter, scene, 1)
        painter.restore()
    painter.end()
    sheet.save(str(output / 'oracle-poses.png'))
    print('atlas_loaded=', window.renderer.atlas is not None)
    print('saved oracle-debug.png / oracle-preview.gif / oracle-poses.png')
    window.close()


if __name__ == '__main__':
    main()
