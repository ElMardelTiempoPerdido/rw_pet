"""真实图集矩阵四边近景、绕角回放、像素边界和休眠检查。"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QImage, QPainter
from PySide6.QtWidgets import QApplication
from rw_creature_pet.config import AppConfig
from rw_creature_pet.shared.atlas import Atlas, extract_atlas
from rw_creature_pet.oracle.debug_window import OracleDebugWindow
from rw_creature_pet.oracle.glyphs import load_pearl_glyphs
from rw_creature_pet.oracle.render import OracleRenderer
from rw_creature_pet.oracle.scene import OracleScene
from review_oracle_autonomy import check_pixels


def snapshot(renderer, scene, *, closeup=False, label=''):
    w, h = (480, 520) if closeup else (int(scene.world.width), int(scene.world.height))
    image = QImage(w, h, QImage.Format.Format_RGBA8888)
    image.fill(QColor('#17232e'))
    painter = QPainter(image)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if closeup:
            center = scene.body.chunks[0].position.lerp(scene.pearl_matrix.anchor.position, .5)
            painter.translate(w/2, h/2+20)
            painter.scale(2, 2)
            painter.translate(-center.x, -center.y)
        else:
            inner = scene.world.inner
            painter.fillRect(int(inner.left), int(inner.top), int(inner.right-inner.left),
                             int(inner.bottom-inner.top), QColor('#101922'))
        renderer.draw(painter, scene)
        painter.resetTransform()
        painter.setFont(QFont('Microsoft YaHei UI', 10))
        painter.setPen(QColor('#d6e1e8'))
        painter.drawText(12, 25, label)
    finally:
        painter.end()
    return Image.frombytes('RGBA', (w, h), bytes(image.constBits())).convert('RGB')


def main():
    app = QApplication.instance() or QApplication([])
    QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')
    app.setFont(QFont('Microsoft YaHei UI', 10))
    output = ROOT/'artifacts'
    output.mkdir(exist_ok=True)
    config = AppConfig.load(ROOT/'config.toml')
    digest = hashlib.sha256((ROOT/'config.toml').read_bytes()).hexdigest()
    settings = replace(config.oracle, pearl_matrix_enabled=True, world_width=960, world_height=600)
    atlas = Atlas(extract_atlas(config.game_dir))
    renderer = OracleRenderer(atlas, settings.colors, glyphs=load_pearl_glyphs(config.game_dir, atlas.root))
    poses = []
    for side in ('top', 'right', 'bottom', 'left'):
        scene = OracleScene(replace(settings, base_side=side, base_fraction=.5))
        for _ in range(650):
            scene.step()
        check_pixels(renderer, scene)
        poses.append(snapshot(renderer, scene, closeup=True, label=f'{side} / 2x / 14 matrix pearls'))
    sheet = Image.new('RGB', (960, 1040))
    for i, pose in enumerate(poses):
        sheet.paste(pose, ((i % 2)*480, (i//2)*520))
    sheet.save(output/'oracle-pearl-matrix-poses.png')
    results, frames = [], []
    for width, height, clockwise in ((960, 600, True), (640, 480, False)):
        scene = OracleScene(replace(settings, world_width=width, world_height=height, float_speed=2.))
        matrix = scene.pearl_matrix
        scene.start_lap(clockwise)
        route, replans, checks, peak = matrix.anchor.route, 0, 0, [0., 0.]
        for tick in range(7000):
            scene.step()
            if route is not matrix.anchor.route:
                replans += 1
                route = matrix.anchor.route
            center = scene.body.chunks[0].position
            peak = [max(peak[0], abs(center.x-matrix.anchor.position.x)),
                    max(peak[1], abs(center.y-matrix.anchor.position.y))]
            if tick % 60 == 0:
                check_pixels(renderer, scene)
                checks += 3
            if width == 960 and tick % 12 == 0:
                frames.append(snapshot(renderer, scene, label=f'Matrix migration / {tick/40:.1f}s'))
            if scene.arrived and scene.appearance.sleeping and scene.pearls_settled:
                break
        assert tick < 6999
        revision = scene.pearl_visual_revision, scene.appearance.revision
        for _ in range(200):
            scene.step()
        assert revision == (scene.pearl_visual_revision, scene.appearance.revision)
        start = perf_counter()
        for _ in range(10000):
            matrix.step(center)
        idle_us = (perf_counter()-start)*100
        results.append(dict(size=[width, height], clockwise=clockwise, ticks=tick+1,
                            layout_scale=matrix.layout_scale, spacing=17*matrix.layout_scale,
                            replans=replans, pixel_checks=checks, peak_anchor_offset=peak,
                            idle_matrix_microseconds=idle_us, idle_revision_changes=0))
    frames[0].save(output/'oracle-pearl-matrix-preview.gif', save_all=True,
                   append_images=frames[1:], duration=300, loop=0)
    window = OracleDebugWindow(replace(config, oracle=settings), load_atlas=False)
    window.timer.stop()
    window.renderer = window.canvas.renderer = renderer
    window.asset_message = '本机原版图集与缓存字形 · 珍珠矩阵'
    window.assets.setText(window.asset_message)
    window.zoom_box.setChecked(False)
    window.scale_input.setCurrentIndex(window.scale_input.findData(None))
    window.set_paused(True)
    window.show()
    app.processEvents()
    window.grab().save(str(output/'oracle-pearl-matrix-debug.png'))
    window.close()
    assert digest == hashlib.sha256((ROOT/'config.toml').read_bytes()).hexdigest()
    metrics = dict(config_sha256=digest, runs=results)
    (output/'oracle-pearl-matrix-metrics.json').write_text(json.dumps(metrics, indent=2), encoding='utf-8')
    print(json.dumps(metrics, indent=2))


if __name__ == '__main__':
    main()
