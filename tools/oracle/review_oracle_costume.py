"""Bell 衣领/念珠的真实图集回放、收敛测量和调色窗口检查。"""
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
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QImage, QPainter
from PySide6.QtWidgets import QApplication
from rw_creature_pet.shared.atlas import Atlas, extract_atlas
from rw_creature_pet.config import AppConfig
from rw_creature_pet.shared.geometry import Vec2
from rw_creature_pet.oracle.scene import OracleScene
from rw_creature_pet.oracle.debug_window import OracleDebugWindow
from rw_creature_pet.oracle.render import OracleRenderer


def render(scene, renderer, tick):
    image = QImage(400, 400, QImage.Format.Format_RGBA8888)
    image.fill(QColor('#17232e'))
    p = QPainter(image)
    try:
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QColor('#d7e5ed'))
        p.drawText(12, 24, f'{tick/40:.1f}s / '+('moving' if not scene.arrived else 'rest')+' / 5x')
        p.save()
        p.translate(200, 140)
        p.scale(5, 5)
        p.translate(-scene.appearance.upper.x, -scene.appearance.upper.y)
        renderer.draw(p, scene)
        p.restore()
        p.save()
        p.translate(28-scene.appearance.upper.x, 350-scene.appearance.upper.y)
        renderer.draw(p, scene, cords=False)
        p.restore()
        p.setPen(QColor('#d7e5ed'))
        p.drawText(50, 360, '1x')
    finally:
        p.end()
    return Image.frombytes('RGBA', (400, 400), bytes(image.constBits())).convert('RGB')


def main():
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    font_id = QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')
    app.setFont(QFont(QFontDatabase.applicationFontFamilies(font_id)[0], 9))
    config = AppConfig.load(ROOT/'config.toml')
    renderer = OracleRenderer(Atlas(extract_atlas(config.game_dir)), config.oracle.colors)
    scene = OracleScene(config.oracle)
    scene.start_lap()
    samples, frames, poses = [], [], []
    metrics = dict(max_necklace_error=0., max_necklace_radius=0., max_necklace_step=0.,
                   config_sha256=hashlib.sha256((ROOT/'config.toml').read_bytes()).hexdigest())
    original = scene.appearance.step_necklace
    def timed():
        start = perf_counter()
        original()
        samples.append(perf_counter()-start)
    scene.appearance.step_necklace = timed
    for tick in range(2700):
        if tick == 600:
            scene.set_tilt(20)
        if tick == 1200:
            scene.set_tilt(-20)
        if tick == 1700:
            scene.set_tilt(0)
            scene.set_look_target(scene.appearance.upper+Vec2(100, -20))
        scene.step()
        a = scene.appearance
        for p in a.necklace:
            metrics['max_necklace_radius'] = max(metrics['max_necklace_radius'], (p.position-a.upper).length())
            metrics['max_necklace_step'] = max(metrics['max_necklace_step'], p.velocity.length())
        metrics['max_necklace_error'] = max(metrics['max_necklace_error'],
            max(abs((q.position-p.position).length()-a.NECKLACE_LINK_LENGTH)
                for p, q in zip(a.necklace, a.necklace[1:])))
        if tick % 15 == 0 or tick in (0, 360, 760, 1300, 1700, 2699):
            frame = render(scene, renderer, tick)
            if tick % 15 == 0:
                frames.append(frame)
            if tick in (0, 360, 760, 1300, 1700, 2699):
                poses.append(frame)
        if (tick+1) % 900 == 0:
            print('Costume replay:', tick+1, flush=True)
    metrics['sleeping'] = scene.appearance.sleeping
    metrics['final_necklace_speed'] = max(p.velocity.length() for p in scene.appearance.necklace)
    metrics['necklace_update_mean_ms'] = sum(samples)/len(samples)*1000
    sheet = Image.new('RGB', (1200, 800), '#17232e')
    for i, pose in enumerate(poses):
        sheet.paste(pose, (i % 3*400, i // 3*400))
    sheet.save(ROOT/'artifacts/oracle-costume-poses.png')
    frames[0].save(ROOT/'artifacts/oracle-costume-preview.gif', save_all=True,
                   append_images=frames[1:], duration=375, loop=0, optimize=False)

    window = OracleDebugWindow(config, ROOT/'config.toml')
    window.timer.stop()
    window.renderer = window.canvas.renderer = renderer
    window.scene = window.canvas.scene = scene
    window.show()
    window.refresh()
    app.processEvents()
    window.grab().save(str(ROOT/'artifacts/oracle-costume-window.png'))
    metrics['window_size'] = (window.width(), window.height())
    window.close()
    (ROOT/'artifacts/oracle-costume-metrics.json').write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(metrics, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
