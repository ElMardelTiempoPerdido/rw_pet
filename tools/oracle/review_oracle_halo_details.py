"""真实图集的光环细节回放；受控触发只用于截图，不写入用户配置。"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from dataclasses import replace
from math import floor
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from PIL import Image, ImageDraw
from PySide6.QtWidgets import QApplication
from rw_creature_pet.config import AppConfig
from rw_creature_pet.shared.atlas import Atlas, extract_atlas
from rw_creature_pet.oracle.glyphs import load_pearl_glyphs
from rw_creature_pet.oracle.scene import OracleScene
from rw_creature_pet.oracle.render import OracleRenderer
from tools.oracle.review_oracle_pixels import render


def main():
    app = QApplication.instance() or QApplication([])
    config = AppConfig.load(ROOT/'config.toml')
    atlas = Atlas(extract_atlas(config.game_dir))
    renderer = OracleRenderer(atlas, config.oracle.colors,
                              glyphs=load_pearl_glyphs(config.game_dir, atlas.root))
    scene = OracleScene(replace(config.oracle, world_width=1920, world_height=1080))
    for _ in range(700):
        scene.step()
    h = scene.halo
    # 回放用可重复的目标，隔离常驻随机事件，以清楚观察实心圆的中央挖空。
    h.random.random = lambda: 1.
    h.white = h.previous_white = h.target_white = 0.
    h.expand = h.previous_expand = h.target_expand = 1.
    h.push = h.previous_push = h.target_push = 0.
    frames, cards = [], []
    labels = {0: 'Rest', 150: 'Filled / expanded', 184: 'Opening from center', 240: 'Ring restored'}
    for tick in range(280):
        if tick == 20:
            h.flash_ring(2)
        if tick == 100:
            h.pulse_fill()
            h.target_expand, h.target_push = 1.5, 2.
        if tick == 180:
            # 仅此受控素材回放指定退出帧；实际按钮使用自然随机退出，不固定时长。
            h.target_white = 0.
        scene.step()
        if tick % 2:
            continue
        c = h.center
        frame = Image.new('RGB', (760, 470), '#19232d')
        near = render(renderer, scene, size=(460, 440), scale=2,
                      origin=(floor(c.x)-115, floor(c.y)-110))
        frame.paste(near, (0,30), near)
        actual = render(renderer, scene, size=(280, 340), scale=1,
                        origin=(floor(c.x)-140, floor(c.y)-125))
        frame.paste(actual, (480,70), actual)
        text = ImageDraw.Draw(frame)
        text.text((12, 8), f'2x / tick {tick} / fill {h.white:.2f}', fill='white')
        text.text((492, 45), '1x / transparent layer', fill='white')
        frames.append(frame)
        if tick in labels:
            card = frame.crop((0, 0, 470, 470))
            ImageDraw.Draw(card).text((12, 25), labels[tick], fill='white')
            cards.append(card)
    out = ROOT/'artifacts'
    out.mkdir(exist_ok=True)
    sheet = Image.new('RGB', (940, 940), '#19232d')
    for i, card in enumerate(cards):
        sheet.paste(card, ((i % 2)*470, (i//2)*470))
    sheet.save(out/'oracle-halo-details.png')
    frames[0].save(out/'oracle-halo-details.gif', save_all=True, append_images=frames[1:],
                   duration=50, loop=0, disposal=2)
    print('Saved artifacts/oracle-halo-details.png and .gif', flush=True)


if __name__ == '__main__':
    main()
