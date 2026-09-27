"""使用当前效果参数预览边框电弧，以及桌面六按钮工具栏离屏截图。"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from dataclasses import replace
from math import ceil
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from PIL import Image, ImageDraw, ImageFont
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QImage, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from rw_creature_pet.config import AppConfig
from rw_creature_pet.oracle.desktop import OracleDesktopWindow
from rw_creature_pet.oracle.render import OracleRenderer, bezier
from rw_creature_pet.oracle.scene import OracleScene
from rw_creature_pet.shared.atlas import Atlas, extract_atlas


def main():
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    font_id = QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')
    app.setFont(QFont(QFontDatabase.applicationFontFamilies(font_id)[0], 9))
    config = AppConfig.load(ROOT/'config.toml')
    renderer = OracleRenderer(Atlas(extract_atlas(config.game_dir)), config.oracle.colors)
    # 用完整顶边展示长线和邻边落点，不再用仅覆盖人偶附近的窄裁图。
    scene = OracleScene(replace(config.oracle, world_width=960., world_height=600.,
                                base_side='top', base_fraction=.5))
    out = ROOT/'artifacts'
    out.mkdir(exist_ok=True)

    width, height = 984, 216

    def paint():
        image = QImage(width, height, QImage.Format.Format_RGBA8888)
        image.fill(QColor('#17232e'))
        p = QPainter(image)
        p.translate(12, 12)
        p.setPen(QColor('#3e525f'))
        p.drawLine(0, 0, round(scene.world.width), 0)
        p.drawLine(0, 0, 0, height)
        p.drawLine(round(scene.world.width), 0, round(scene.world.width), height)
        renderer.draw_geometry(p, scene, 1., arm=False, cords=False, pearl=False)
        p.end()
        return Image.frombytes('RGBA', (width, height), bytes(image.constBits())).convert('RGB')

    frames = [paint()]
    count = scene.trigger_halo_arcs()
    assert count > 0
    adjacent = sum(a.edge != a.source_edge for a in scene.halo_arcs.arcs)
    longest = max(sum((b-a).length() for a, b in zip(c, c[1:]))
                  for c in scene.halo_arcs.curves(scene.halo))
    bows = []
    for curve in scene.halo_arcs.curves(scene.halo):
        start, end = curve[0], curve[-1]
        chord = end-start
        bows.append(max(abs(chord.x*(p.y-start.y)-chord.y*(p.x-start.x))/chord.length()
                        for p in (bezier(*curve, i/100) for i in range(101))))
    duration = scene.halo_arcs.DURATION_TICKS/scene.halo_arcs.TICK_RATE
    # GIF 以 10 ms 计时：每两帧采样一次，50 ms，避免把 25 ms 截成 20 ms。
    steps = ceil(scene.halo_arcs.DURATION_TICKS/2)
    widths = []
    for _ in range(steps):
        widths.append(scene.halo_arcs.width_at())
        frames.append(paint())
        for _ in range(2):
            scene.halo_arcs.step(scene.halo)
    scene.halo_arcs.clear()
    frames.append(paint())
    frames[0].save(out/'oracle-halo-arcs-preview.gif', save_all=True, append_images=frames[1:],
                   duration=[600]+[50]*steps+[1000], loop=0, optimize=False)
    sheet = Image.new('RGB', (width, (height+32)*4), '#17232e')
    text = ImageDraw.Draw(sheet)
    font = ImageFont.truetype('C:/Windows/Fonts/arial.ttf', 17)
    peak = config.oracle.projection_opacity*scene.halo_arcs.OPACITY
    samples = (0, steps//4, steps*3//4, steps)
    for i, sample in enumerate(samples):
        stroke = widths[sample] if sample < steps else 0.
        label = (f'{sample*.05:g} s / width {stroke:.3f} / fixed opacity {peak:g} / '
                 + (f'{count} arcs ({adjacent} adjacent) / 1x' if sample < steps else 'disconnected'))
        y = i*(height+32)
        text.text((12, y+8), label, fill='#d7e5ed', font=font)
        sheet.paste(frames[sample+1], (0, y+32))
    sheet.save(out/'oracle-halo-arcs-preview.png')
    print('Sampled count:', count, 'Adjacent:', adjacent, 'Longest control polygon:', round(longest, 2),
          'Bows:', [round(b, 2) for b in bows], 'Duration:', duration,
          'Widths:', [round(w, 3) for w in widths], flush=True)

    with patch('rw_creature_pet.oracle.desktop.QSystemTrayIcon.isSystemTrayAvailable', return_value=True):
        window = OracleDesktopWindow(config, config_path=ROOT/'config.toml', renderer=renderer)
    try:
        window.timer.stop()
        window.toolbar_action.trigger()
        app.processEvents()
        toolbar = window.action_toolbar
        QTest.mouseClick(toolbar.buttons['arcs'], Qt.MouseButton.LeftButton)
        app.processEvents()
        toolbar.grab().save(str(out/'oracle-desktop-toolbar.png'))
        print('Toolbar:', toolbar.size(), 'Arcs:', count, flush=True)
    finally:
        window.close()


if __name__ == '__main__':
    main()
