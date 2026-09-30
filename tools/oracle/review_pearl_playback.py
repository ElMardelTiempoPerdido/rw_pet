"""预计算 Soft Gesture，并用正式珍珠绘制逻辑导出无声整曲 GIF。"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from dataclasses import replace
import json
from math import ceil
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw
from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QColor, QFont, QFontDatabase, QImage, QPainter
from PySide6.QtWidgets import QApplication
from rw_creature_pet.config import AppConfig
from rw_creature_pet.shared.atlas import Atlas, extract_atlas
from rw_creature_pet.oracle.behavior import Activity
from rw_creature_pet.oracle.glyphs import load_pearl_glyphs
from rw_creature_pet.oracle.pearl_playback_assets import load_pearl_playback
from rw_creature_pet.oracle.render import OracleRenderer
from rw_creature_pet.oracle.scene import OracleScene


def main():
    app = QApplication.instance() or QApplication([])
    font_id = QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')
    families = QFontDatabase.applicationFontFamilies(font_id)
    font = QFont(families[0] if families else app.font().family(), 10)
    app.setFont(font)
    config = AppConfig.load(ROOT/'config.toml')
    curve, cache = load_pearl_playback(config.game_dir)
    atlas = Atlas(extract_atlas(config.game_dir))
    renderer = OracleRenderer(atlas, config.oracle.colors,
        glyphs=load_pearl_glyphs(config.game_dir, atlas.root), playback_curve=curve)
    scene = OracleScene(replace(config.oracle, world_width=960, world_height=600,
        base_side='top', allowed_edges=('top', 'right', 'bottom', 'left'),
        pearl_matrix_enabled=True, pearl_matrix_count=7, pearl_playback_probability=1.,
        pearl_orbits_enabled=False, pearl_fixed_count=0, halo_enabled=False))
    scene.pearl_playback_curve = curve
    scene.observe_matrix_pearl()
    for _ in range(2500):
        scene.step()
        if scene.behavior.state == Activity.OBSERVE:
            break
    else:
        raise RuntimeError('矩阵珠未进入阅读阶段')
    pearl = scene.observed_pearl
    # 预览专用：从曲首展示一整首；正式播放从随机曲内起点循环 90～120 秒。
    duration = ceil(curve.duration*40)
    scene.behavior.duration = duration+60
    pearl.start_playback(curve, 0., duration)
    out = ROOT/'artifacts/pearl-playback'
    out.mkdir(parents=True, exist_ok=True)
    frames = []
    palette = None
    strongest, still = -1., None
    for tick in range(duration+20):
        scene.step()
        if tick % 2:
            continue
        image = QImage(640, 340, QImage.Format.Format_RGBA8888)
        image.fill(QColor('#17232e'))
        p = QPainter(image)
        try:
            p.setFont(font)
            p.setPen(QColor('#e7eeee'))
            p.drawText(QPointF(22, 29), 'Soft Gesture · 珍珠播放动画（无声）')
            p.setPen(QColor('#9db3c0'))
            p.drawText(QPointF(22, 54), f'{min(tick/40, curve.duration):05.2f} / {curve.duration:.2f} s · 原版 bubble 精灵')
            p.drawText(QPointF(30, 92), '人偶阅读 · 2×')
            p.drawText(QPointF(410, 92), '珍珠局部 · 8×')
            p.save()
            p.setClipRect(QRectF(10, 105, 350, 200))
            p.translate(165, 168)
            p.scale(2, 2)
            body = scene.body.chunks[0].position
            p.translate(-body.x, -body.y)
            renderer.draw(p, scene)
            p.restore()
            p.save()
            p.translate(482, 223)
            p.scale(8, 8)
            p.translate(-pearl.position.x, -pearl.position.y)
            color = QColor(config.oracle.colors.pearl_glyph)
            color.setAlphaF(config.oracle.projection_opacity)
            renderer.draw_pearl_at(p, pearl.position, pearl.glyph_id, color.name(QColor.NameFormat.HexArgb), pearl.color_slot)
            renderer.draw_pearl_playback(p, pearl, opacity=config.oracle.projection_opacity,
                                         max_size=config.oracle.pearl_bubble_max_size,
                                         color=config.oracle.pearl_bubble_color)
            p.restore()
            strength = pearl.playback.strength if pearl.playback else 0.
            p.setPen(QColor('#9db3c0'))
            p.drawText(QPointF(22, 321), f'投影不透明度 {config.oracle.projection_opacity:.0%} · 音乐强度 {strength:.2f}')
        finally:
            p.end()
        frame = Image.frombytes('RGBA', (640, 340), bytes(image.constBits())).convert('RGB')
        if strength > strongest:
            strongest, still = strength, frame.copy()
        if palette is None:
            # 固定调色板避免每帧重新量化使静止区域变色，同时缩小 GIF。
            swatches = frame.copy()
            brush = ImageDraw.Draw(swatches)
            for i in range(32):
                amount = i/31
                for row, base in enumerate(((23, 35, 46), (216, 205, 197))):
                    color = tuple(round(a+(b-a)*amount) for a, b in zip(base, (255, 0, 0)))
                    brush.rectangle((i*8, row*8, i*8+7, row*8+7), fill=color)
            palette = swatches.quantize(colors=256)
        frames.append(frame.quantize(palette=palette, dither=Image.Dither.NONE))
    frames[0].save(out/'soft-gesture-pearl.gif', save_all=True, append_images=frames[1:],
                   duration=50, loop=0, optimize=False, disposal=1)
    still.save(out/'soft-gesture-pearl.png')
    # 分享可复核的曲线和算法信息，不导出音乐本体。
    (out/'strength.npy').write_bytes((cache/'strength.npy').read_bytes())
    metadata = json.loads((cache/'manifest.json').read_text(encoding='utf-8'))
    metadata.update(preview_frames=len(frames), preview_fps=20, projection_opacity=config.oracle.projection_opacity)
    (out/'manifest.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8')
    print(out/'soft-gesture-pearl.gif')
    print(f'{len(frames)} frames; {(out/"soft-gesture-pearl.gif").stat().st_size} bytes')


if __name__ == '__main__':
    main()
