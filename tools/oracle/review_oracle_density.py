"""真实素材的原始/精细像素对照，以及相同运动下的逐帧绘制耗时。"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from dataclasses import replace
from math import floor
from pathlib import Path
from statistics import median
import json
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from PIL import Image, ImageDraw
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication
from rw_creature_pet.config import AppConfig
from rw_creature_pet.shared.atlas import Atlas, extract_atlas
from rw_creature_pet.oracle.glyphs import load_pearl_glyphs
from rw_creature_pet.oracle.render import OracleRenderer
from rw_creature_pet.oracle.scene import OracleScene


def paint(renderer, scene, scale, origin=(0, 0), size=(960, 600), halo_only=False):
    image = QImage(round(size[0]*scale), round(size[1]*scale), QImage.Format.Format_RGBA8888)
    image.fill(0)
    painter = QPainter(image)
    try:
        painter.scale(scale, scale)
        painter.translate(-origin[0], -origin[1])
        if halo_only:
            renderer.draw_halo(painter, scene, .5)
        else:
            renderer.draw(painter, scene, .5)
    finally:
        painter.end()
    return image


def main(*, benchmark=True):
    app = QApplication.instance() or QApplication([])
    config = AppConfig.load(ROOT/'config.toml')
    atlas = Atlas(extract_atlas(config.game_dir))
    glyphs = load_pearl_glyphs(config.game_dir, atlas.root)

    def renderer():
        return OracleRenderer(atlas, config.oracle.colors, glyphs=glyphs)

    scene = OracleScene(config.oracle)
    scene.start_lap()
    for _ in range(180):
        scene.step()
    out = ROOT/'artifacts'
    out.mkdir(exist_ok=True)
    for part in ('body', 'halo'):
        size = (120, 120) if part == 'halo' else (120, 90)
        row_height = size[1]*4+32
        sheet = Image.new('RGB', (960, row_height*3), '#19232d')
        labels = ImageDraw.Draw(sheet)
        scene.config = replace(scene.config, halo_enabled=part == 'halo')
        center = scene.halo.center_at(.5) if part == 'halo' else scene.appearance.upper
        origin = (floor(center.x)-60, floor(center.y)-32)
        if part == 'halo':
            origin = (floor(center.x)-60, floor(center.y)-60)
        for row, scale in enumerate((1, 2, 4)):
            for column, mode in enumerate(('classic', 'adaptive')):
                scene.config = replace(scene.config, pixel_mode=mode)
                image = paint(renderer(), scene, scale, origin, size, part == 'halo')
                pil = Image.frombytes('RGBA', (image.width(), image.height()), bytes(image.constBits()))
                # 只放大已生成的屏幕像素，保证各行最终外形大小相同、方便比较阶梯。
                pil = pil.resize((size[0]*4, size[1]*4), Image.Resampling.NEAREST)
                x, y = column*480, row*row_height
                labels.text((x+12, y+10), f'{part} / {mode} / display {scale}x / inspect {4/scale:g}x', fill='white')
                sheet.paste(pil, (x, y+30), pil)
        sheet.save(out/f'oracle-density-{part}.png')

    if not benchmark:
        return
    metrics = {}
    for scale in (1, 2, 4):
        for mode in ('classic', 'adaptive'):
            scene = OracleScene(replace(config.oracle, pixel_mode=mode))
            scene.start_lap()
            r = renderer()
            times = []
            for tick in range(150):
                scene.step()
                start = perf_counter()
                paint(r, scene, scale)
                if tick >= 30:
                    times.append((perf_counter()-start)*1000)
            # 同一已绘制的插值帧重复显示，检查缓存命中的合成开销。
            repeated = []
            for _ in range(60):
                start = perf_counter()
                paint(r, scene, scale)
                repeated.append((perf_counter()-start)*1000)
            metrics[f'{mode}_{scale}x'] = {
                'moving_render_median_ms': round(median(times), 3),
                'moving_render_p95_ms': round(sorted(times)[int(len(times)*.95)], 3),
                'cached_render_median_ms': round(median(repeated), 3),
                'body_canvas_mib': round(r._raster_image.sizeInBytes()/1024**2, 3),
            }
    (out/'oracle-density-metrics.json').write_text(json.dumps(metrics, indent=2), encoding='utf-8')
    print(json.dumps(metrics, indent=2))
    print('Saved oracle-density-body.png, oracle-density-halo.png and oracle-density-metrics.json')


if __name__ == '__main__':
    main()
