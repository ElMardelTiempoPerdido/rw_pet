"""Compare warmed Qt glyph drawing; excludes loading and initial rasterization."""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import json
from pathlib import Path
import statistics
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
(ROOT/'artifacts').mkdir(exist_ok=True)

import UnityPy
from PySide6.QtCore import QPointF, Qt, qVersion
from PySide6.QtGui import QColor, QFont, QFontDatabase, QImage, QPainter
from PySide6.QtWidgets import QApplication
from rw_creature_pet.config import AppConfig


app = QApplication([])
fid = QFontDatabase.addApplicationFont('D:/CODES/front/msg_loom_front/public/fonts/rw-karma.ttf')
font = QFont(QFontDatabase.applicationFontFamilies(fid)[0])
font.setPixelSize(15)
font.setStyleStrategy(QFont.StyleStrategy.NoAntialias | QFont.StyleStrategy.NoFontMerging)
config = AppConfig.load(ROOT/'config.toml')
env = UnityPy.load(str(config.game_dir/'RainWorld_Data/resources.assets'))
for obj in env.objects:
    if obj.type.name == 'Texture2D':
        data = obj.read()
        if data.m_Name == 'glyphs':
            # Atlas glyph 4 and font A use the same general symbol.
            source = data.image.convert('RGB').crop((60, 0, 75, 15))
            break
atlas = QImage(15, 15, QImage.Format.Format_ARGB32_Premultiplied)
atlas.fill(Qt.GlobalColor.transparent)
for y in range(15):
    for x in range(15):
        if source.getpixel((x, y))[0] < 128:
            atlas.setPixelColor(x, y, QColor('#d8e5ed'))
cached_font = QImage(15, 15, QImage.Format.Format_ARGB32_Premultiplied)
cached_font.fill(Qt.GlobalColor.transparent)
p = QPainter(cached_font)
p.setFont(font)
p.setPen(QColor('#d8e5ed'))
p.setRenderHint(QPainter.RenderHint.TextAntialiasing, False)
p.drawText(QPointF(0, 13), 'A')
p.end()

positions = [QPointF((i*7) % 240, (i*11) % 140) for i in range(200)]
baselines = [QPointF(p.x(), p.y()+13) for p in positions]
result = dict(qt=qVersion(), count_per_sample=60000, rounds=7,
              note='Warmed offscreen QImage painter; one 15px glyph, precomputed positions, no loading/cache construction or whole-frame rendering in timings.',
              cached_image_bytes=atlas.sizeInBytes(), cases={})
for scale in (1, 4):
    target = QImage(1280, 720, QImage.Format.Format_ARGB32_Premultiplied)
    target.fill(QColor('#17232e'))
    p = QPainter(target)
    p.scale(scale, scale)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing, False)
    p.setFont(font)
    p.setPen(QColor('#d8e5ed'))
    methods = [('atlas_cache', atlas, positions, p.drawImage),
               ('font_image_cache', cached_font, positions, p.drawImage),
               ('font_draw_text', 'A', baselines, p.drawText)]
    samples = {name: [] for name, *_ in methods}
    for _, item, points, draw in methods:
        for _ in range(15):
            for point in points:
                draw(point, item)
    for trial in range(result['rounds']):
        order = methods[trial % 3:]+methods[:trial % 3]
        if trial % 2:
            order = list(reversed(order))
        for name, item, points, draw in order:
            start = perf_counter()
            for _ in range(result['count_per_sample']//len(points)):
                for point in points:
                    draw(point, item)
            samples[name].append((perf_counter()-start)/result['count_per_sample']*1e6)
    p.end()
    result['cases'][str(scale)+'x'] = {name: dict(median_us=statistics.median(values),
        min_us=min(values), max_us=max(values)) for name, values in samples.items()}
    print(scale, result['cases'][str(scale)+'x'], flush=True)
(ROOT/'artifacts/oracle-glyph-benchmark.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
