"""四边镜片闪断回放与四只监视者的离屏耗时，不修改用户配置"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'

from dataclasses import replace
import json
from pathlib import Path
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

from rw_creature_pet.config import AppConfig
from rw_creature_pet.overseer.config import OverseerConfig
from rw_creature_pet.overseer.hologram import noise_masks
from rw_creature_pet.overseer.model import Anchor, Edge, Overseer
from rw_creature_pet.overseer.render import OverseerRenderer
from rw_creature_pet.shared.atlas import Atlas, extract_atlas
from rw_creature_pet.shared.geometry import Bounds, Vec2


OUT = ROOT/'artifacts/overseer'


def profile():
    result = {}
    start = perf_counter()
    masks = noise_masks()
    result['mask_prepare_ms'] = (perf_counter()-start)*1000
    result['shared_mask_bytes'] = sum(image.sizeInBytes() for row in masks for image in row)
    result['four_ms_per_tick'] = timings = {}
    for mode, density in (('classic', 1.), ('adaptive', 2.)):
        for observing in (False, True):
            cfg = replace(OverseerConfig(), observation_probability=float(observing), observation_interval=.1)
            models = [Overseer(Bounds(0, 0, 640, 480), cfg, seed=s) for s in range(4)]
            renderers = [OverseerRenderer() for _ in models]
            for model, edge in zip(models, Edge):
                model.show(anchor=Anchor(edge, .5))
                for _ in range(100):
                    model.step(Vec2(320, 240))
            image = QImage(1280, 960, QImage.Format.Format_ARGB32_Premultiplied)
            image.fill(0)
            p = QPainter(image)
            start = perf_counter()
            try:
                for tick in range(400):
                    for model, renderer in zip(models, renderers):
                        model.step(Vec2(320, 240))
                        if observing:
                            model.lens.remaining = 10
                        renderer.draw(p, model, pixel_mode=mode, raster_scale=density)
            finally:
                p.end()
            timings[f'{mode}_{observing}'] = (perf_counter()-start)/400*1000
    result['scope'] = 'Four models, simulation + offscreen full drawing per tick; excludes native compositor; not Task Manager CPU percentage'
    (OUT/'lens-effects-performance.json').write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(result, indent=2))


def preview():
    config = AppConfig.load(ROOT/'config.toml')
    cfg = replace(config.overseer, observation_probability=1., observation_interval=.1)
    atlas = Atlas(extract_atlas(config.game_dir))
    models = [Overseer(Bounds(0, 0, 640, 480), cfg, seed=947+i) for i in range(4)]
    renderers = [OverseerRenderer(atlas) for _ in models]
    for model, edge in zip(models, Edge):
        model.show(anchor=Anchor(edge, .5))
        for _ in range(100):
            model.step(Vec2(320, 240))
        model.lens.reset(cfg)
    frames, stills = [], []
    for tick in range(130):
        frame = Image.new('RGB', (1120, 310), '#182129')
        for i, (model, renderer) in enumerate(zip(models, renderers)):
            if tick == 80:
                model.config = replace(cfg, observation_probability=0.)
            model.step(Vec2(320, 240))
            image = QImage(140, 140, QImage.Format.Format_RGBA8888)
            image.fill(QColor('#182129'))
            p = QPainter(image)
            try:
                center = model.root+model.normal*45
                p.translate(70-center.x, 70-center.y)
                p.setPen(QColor('#456072'))
                p.drawRect(0, 0, 640, 480)
                renderer.draw(p, model)
            finally:
                p.end()
            native = Image.frombytes('RGBA', (140, 140), bytes(image.constBits()))
            frame.paste(native.resize((280, 280), Image.Resampling.NEAREST), (i*280, 30))
            ImageDraw.Draw(frame).text((i*280+5, 5), f'{model.anchor.edge.value} / {model.lens.up:.0%}', fill='white')
        frames.append(frame)
        if tick in (79, 85, 93, 101, 110):
            stills.append(frame)
    frames[0].save(OUT/'lens-effects.gif', save_all=True, append_images=frames[1:], duration=25, loop=0)
    sheet = Image.new('RGB', (1120, 310*len(stills)))
    for i, frame in enumerate(stills):
        sheet.paste(frame, (0, 310*i))
    sheet.save(OUT/'lens-effects-closing.png')
    print('Previews:', OUT/'lens-effects.gif')


if __name__ == '__main__':
    app = QApplication.instance() or QApplication([])
    OUT.mkdir(parents=True, exist_ok=True)
    profile()
    preview()
