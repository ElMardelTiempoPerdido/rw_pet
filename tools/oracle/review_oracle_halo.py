"""用当前配色及真实图集回放光环，保存静态/扩张/四边运动预览。"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from math import floor
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont, QFontDatabase
from rw_creature_pet.config import AppConfig
from rw_creature_pet.shared.atlas import Atlas, extract_atlas
from rw_creature_pet.oracle.glyphs import load_pearl_glyphs
from rw_creature_pet.oracle.scene import OracleScene
from rw_creature_pet.oracle.render import OracleRenderer
from rw_creature_pet.oracle.debug_window import OracleDebugWindow
from tools.oracle.review_oracle_pixels import render


def main():
    app = QApplication.instance() or QApplication([])
    app.setStyle('Fusion')
    font_id = QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')
    if font_id >= 0:
        app.setFont(QFont(QFontDatabase.applicationFontFamilies(font_id)[0], 9))
    config = AppConfig.load(ROOT/'config.toml')
    atlas = Atlas(extract_atlas(config.game_dir))
    renderer = OracleRenderer(atlas, config.oracle.colors,
                              glyphs=load_pearl_glyphs(config.game_dir, atlas.root))
    scene = OracleScene(config.oracle)
    out = ROOT/'artifacts'
    out.mkdir(exist_ok=True)
    frames, cards = [], []
    for tick in range(0 if '--window-only' in sys.argv else 2700):
        if tick == 720:
            scene.pulse_halo(1.25, 2.)
        if tick == 1000:
            scene.start_lap()
        scene.step()
        center = scene.halo.center
        if tick in (700, 770, 930):
            pic = render(renderer, scene, size=(600, 600), scale=4,
                         origin=(floor(center.x)-75, floor(center.y)-60))
            card = Image.new('RGB', (600, 625), '#19232d')
            card.paste(pic, (0,25), pic)
            ImageDraw.Draw(card).text((12, 8), ('Rest', 'Pulse', 'Returned')[len(cards)]+' / 4x', fill='white')
            cards.append(card)
        if tick % 12 == 0:
            frame = Image.new('RGB', (1440, 600), '#19232d')
            world = render(renderer, scene)
            frame.paste(world, (0,0), world)
            near = render(renderer, scene, size=(480, 580), scale=4,
                          origin=(floor(center.x)-60, floor(center.y)-60))
            frame.paste(near, (960,20), near)
            ImageDraw.Draw(frame).text((970,6), f'1x + 4x / tick {tick}', fill='white')
            frames.append(frame)
    if cards:
        sheet = Image.new('RGB', (1800,625), '#19232d')
        for i, card in enumerate(cards):
            sheet.paste(card, (600*i,0))
        sheet.save(out/'oracle-halo-poses.png')
        frames[0].save(out/'oracle-halo-preview.gif', save_all=True, append_images=frames[1:],
                       duration=300, loop=0, disposal=2)
    window = OracleDebugWindow(config, ROOT/'config.toml', load_atlas=False)
    window.timer.stop()
    window.set_paused(True)
    window.canvas.renderer = window.renderer = renderer
    window.assets.setText('本机原版图集 · 光环 1× 像素化预览')
    window.show()
    app.processEvents()
    window.grab().save(str(out/'oracle-halo-debug.png'))
    window.close()
    print('Saved oracle-halo-debug.png' if '--window-only' in sys.argv else
          'Saved oracle-halo-poses.png, oracle-halo-preview.gif, oracle-halo-debug.png', flush=True)


if __name__ == '__main__':
    main()
