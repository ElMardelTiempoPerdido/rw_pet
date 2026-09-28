"""真实素材的外发光对照及纯绘制耗时；不修改 TOML 或用户设置。"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from dataclasses import replace
import json
from pathlib import Path
from statistics import median
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
from tools.oracle.review_oracle_pixels import render


def benchmark(scene, factory, scale):
    renderers = [factory(), factory()]
    image = QImage(round(960*scale), round(600*scale), QImage.Format.Format_ARGB32_Premultiplied)
    rows = {}
    for state in ('rest_with_pearls', 'moving'):
        if state == 'moving':
            scene.start_lap()
        times = [[], []]
        for tick in range(65):
            scene.step()  # 物理不计入绘制耗时；两种配置使用相同姿态。
            for enabled in (False, True):
                scene.config = replace(scene.config, glow_enabled=enabled)
                image.fill(0)
                painter = QPainter(image)
                painter.setRenderHint(QPainter.RenderHint.Antialiasing)
                painter.scale(scale, scale)
                start = perf_counter()
                try:
                    renderers[enabled].draw(painter, scene, .5)
                finally:
                    painter.end()
                if tick >= 5:
                    times[enabled].append((perf_counter()-start)*1000)
        rows[state] = dict(zip(('off_median_ms', 'on_median_ms'),
                              (round(median(values), 3) for values in times)))
    return rows


def main():
    app = QApplication.instance() or QApplication([])
    config = AppConfig.load(ROOT/'config.toml')
    atlas = Atlas(extract_atlas(config.game_dir))
    glyphs = load_pearl_glyphs(config.game_dir, atlas.root)
    factory = lambda: OracleRenderer(atlas, config.oracle.colors, glyphs=glyphs)
    scene = OracleScene(replace(config.oracle, base_side='top',
                               allowed_edges=('top', 'right', 'bottom', 'left')))
    for _ in range(700):
        scene.step()
    out = ROOT/'artifacts'
    out.mkdir(exist_ok=True)
    sheet = Image.new('RGB', (1200, 810))
    renderer = factory()
    center = scene.appearance.upper
    for row, background in enumerate(('#19232d', '#c7ced4')):
        for column, enabled in enumerate((False, True)):
            panel = Image.new('RGB', (600, 405), background)
            grid = ImageDraw.Draw(panel)
            for x in range(0, 600, 30):
                grid.line((x, 30, x, 405), fill=('#293643', '#b2bbc4')[row])
            for y in range(30, 405, 30):
                grid.line((0, y, 600, y), fill=('#293643', '#b2bbc4')[row])
            scene.config = replace(scene.config, glow_enabled=enabled, glow_color='#ffffff', glow_radius=6.)
            pet = render(renderer, scene, size=(600, 375), scale=1.5,
                         origin=(center.x-200, 0))
            panel.paste(pet, (0, 30), pet)
            grid.text((12, 9), f'Glow {"ON / white / radius 6" if enabled else "OFF"} / 1.5x',
                      fill=('white', '#19232d')[row])
            sheet.paste(panel, (column*600, row*405))
    sheet.save(out/'oracle-glow-comparison.png')
    timings = {}
    for scale in (1., 1.5, 2.):
        scene = OracleScene(config.oracle)
        for _ in range(700):
            scene.step()
        timings[str(scale)] = benchmark(scene, factory, scale)
    (out/'oracle-glow-timings.json').write_text(json.dumps(timings, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(timings, indent=2), flush=True)
    print('Saved oracle-glow-comparison.png and oracle-glow-timings.json', flush=True)


if __name__ == '__main__':
    main()
