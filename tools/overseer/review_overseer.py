"""生成使用本机图集的四边预览、鼠标目标扫描动画和调试窗口截图。"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'

from math import cos, sin
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw
from PySide6.QtGui import QColor, QFont, QFontDatabase, QImage, QPainter
from PySide6.QtWidgets import QApplication

from rw_creature_pet.config import AppConfig
from rw_creature_pet.shared.atlas import Atlas, extract_atlas
from rw_creature_pet.shared.geometry import Bounds, Vec2
from rw_creature_pet.overseer.model import Anchor, Edge, Overseer
from rw_creature_pet.overseer.render import OverseerRenderer
from rw_creature_pet.oracle.debug_window import OracleDebugWindow


def paint(renderer, model, guides=False):
    image = QImage(100, 100, QImage.Format.Format_RGBA8888)
    image.fill(QColor('#182129'))
    painter = QPainter(image)
    try:
        center = model.root+model.normal*40
        painter.translate(50-center.x, 50-center.y)
        b = model.bounds
        painter.setPen(QColor('#456072'))
        painter.drawRect(b.left, b.top, b.right-b.left, b.bottom-b.top)
        renderer.draw(painter, model, guides=guides)
    finally:
        painter.end()
    return Image.frombytes('RGBA', (100, 100), bytes(image.constBits()))


def main():
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    # Windows 的 offscreen 插件可能不枚举系统字体，显式载入以检查中文控件。
    font = Path(os.environ.get('WINDIR', 'C:/Windows'))/'Fonts'/'msyh.ttc'
    if font.exists():
        QFontDatabase.addApplicationFont(str(font))
    app.setFont(QFont('Microsoft YaHei UI', 10))
    config = AppConfig.load(ROOT/'config.toml')
    atlas = Atlas(extract_atlas(config.game_dir))
    renderer = OverseerRenderer(atlas)
    output = ROOT/'artifacts'/'overseer'
    output.mkdir(parents=True, exist_ok=True)
    sheet = Image.new('RGB', (1200, 1380), '#182129')
    labels = ImageDraw.Draw(sheet)
    poses = (('near / front', Vec2(0, 24)), ('far / side', Vec2(400, 60)),
             ('far / inward', Vec2(0, 500)))
    for row, edge in enumerate(Edge):
        for col, (name, local_target) in enumerate(poses):
            model = Overseer(Bounds(0, 0, 640, 480), config.overseer)
            model.show(anchor=Anchor(edge, .5))
            for _ in range(180):
                model.step(model.root+model.local_vector(local_target))
            native = paint(renderer, model)
            native.save(output/f'{edge.value}-{col}-1x.png')
            sheet.paste(native.resize((300, 300), Image.Resampling.NEAREST), (col*400, row*345+25))
            sheet.paste(native, (col*400+300, row*345+125))
            labels.text((col*400+8, row*345+8), f'{edge.value} / {name} / 3x + 1x', fill='white')
    sheet.save(output/'four-edges.png')

    models = []
    for edge in Edge:
        model = Overseer(Bounds(0, 0, 640, 480), config.overseer)
        model.show(anchor=Anchor(edge, .5))
        models.append(model)
    frames = []
    for tick in range(320):
        for model in models:
            target = Vec2(sin(tick/35)*330, 40+(1+cos(tick/41))*120)
            model.step(model.root+model.local_vector(target))
        if tick % 2 == 0:
            frame = Image.new('RGB', (800, 240), '#182129')
            labels = ImageDraw.Draw(frame)
            for i, model in enumerate(models):
                frame.paste(paint(renderer, model).resize((200, 200), Image.Resampling.NEAREST), (i*200, 25))
                labels.text((i*200+10, 6), model.anchor.edge.value+' / 2x', fill='white')
            frames.append(frame)
    frames[0].save(output/'gaze-sweep.gif', save_all=True, append_images=frames[1:], duration=50, loop=0)

    # 同一根部完整循环，保存过渡帧用于检查中途收拢和隐藏残留。
    model = Overseer(Bounds(0, 0, 640, 480), config.overseer)
    model.show(anchor=Anchor(Edge.BOTTOM, .5))
    frames, samples = [], []
    for tick in range(180):
        if tick < 50:
            distance = 180
        elif tick < 80:
            distance = 30
        elif tick < 100:
            distance = 80  # 位于滞回区间，保持隐藏。
        else:
            distance = 180
        model.step(model.root+model.normal*180, threat=model.root+model.normal*distance)
        frame = Image.new('RGB', (400, 440), '#182129')
        frame.paste(paint(renderer, model).resize((400, 400), Image.Resampling.NEAREST), (0, 40))
        labels = ImageDraw.Draw(frame)
        labels.text((8, 6), f'{model.state.value} / extended {model.extended:.3f}', fill='white')
        labels.text((8, 23), f'mouse-root {distance}px / safe {model.safe_time:.2f}s', fill='white')
        frames.append(frame)
        if tick in (0, 3, 7, 15, 49, 50, 52, 54, 58, 70, 120, 130):
            samples.append(frame)
    frames[0].save(output/'emerge-withdraw.gif', save_all=True, append_images=frames[1:], duration=25, loop=0)
    sheet = Image.new('RGB', (1600, 1320), '#182129')
    for i, frame in enumerate(samples):
        sheet.paste(frame, ((i % 4)*400, (i//4)*440))
    sheet.save(output/'extension-stages.png')

    window = OracleDebugWindow(config, load_atlas=False)
    window.timer.stop()
    window.pause_button.setChecked(True)
    window.renderer.atlas = atlas
    window.canvas.overseer_renderer.atlas = atlas
    window.show()
    window.open_overseer_debug()
    panel = window.overseer_panel
    panel.show_button.click()
    panel.look_mode.setCurrentIndex(panel.look_mode.findData('idle'))
    for _ in range(80):
        window.step_scene()
    window.refresh()
    app.processEvents()
    window.grab().save(str(output/'debug-window.png'))
    panel.grab().save(str(output/'debug-panel.png'))
    window.close()
    app.processEvents()
    print(f'Saved {output}')


if __name__ == '__main__':
    main()
