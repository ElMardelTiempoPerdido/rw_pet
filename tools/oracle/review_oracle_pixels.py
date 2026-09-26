"""真实图集的矢量/逻辑像素对照、四边回放和 1×/4× 局部预览。"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from math import floor
from dataclasses import replace
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from PIL import Image, ImageDraw
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication
from rw_creature_pet.config import AppConfig
from rw_creature_pet.shared.atlas import Atlas, extract_atlas
from rw_creature_pet.oracle.glyphs import load_pearl_glyphs
from rw_creature_pet.oracle.render import OracleRenderer
from rw_creature_pet.oracle.scene import OracleScene


def render(renderer, scene, *, pixelated=True, size=(960, 600), scale=1, origin=(0, 0)):
    image = QImage(*size, QImage.Format.Format_RGBA8888)
    image.fill(0)
    painter = QPainter(image)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.scale(scale, scale)
        painter.translate(-origin[0], -origin[1])
        renderer.draw(painter, scene, .5, pixelated=pixelated)
    finally:
        painter.end()
    return Image.frombytes('RGBA', size, bytes(image.constBits()))


def main():
    app = QApplication.instance() or QApplication([])
    config = AppConfig.load(ROOT/'config.toml')
    atlas = Atlas(extract_atlas(config.game_dir))
    renderer = OracleRenderer(atlas, config.oracle.colors,
                              glyphs=load_pearl_glyphs(config.game_dir, atlas.root))
    scene = OracleScene(replace(config.oracle, pixel_mode='classic'))
    scene.start_lap()
    out = ROOT/'artifacts'
    out.mkdir(exist_ok=True)
    # 每张对照：上方人偶 4×，下方身体/线束/机械臂的 1× 区域。
    sheet = Image.new('RGB', (1280, 1060), '#19232d')
    labels = ImageDraw.Draw(sheet)
    poses, frames = 0, []
    for tick in range(2500):
        scene.step()
        upper = scene.appearance.upper
        if tick in (150, 600, 1050, 2400):
            x0, y0 = (poses % 2)*640, (poses // 2)*530
            for column, pixelated in enumerate((False, True)):
                x = x0+column*320
                labels.text((x+12, y0+8), f'{"Pixel" if pixelated else "Vector"} / tick {tick}', fill='white')
                near = render(renderer, scene, pixelated=pixelated, size=(300, 280), scale=4,
                              origin=(floor(upper.x)-37, floor(upper.y)-28))
                sheet.paste(near, (x+10, y0+28), near)
                wide = render(renderer, scene, pixelated=pixelated, size=(300, 210), scale=1,
                              origin=(floor(upper.x)-150, floor(upper.y)-45))
                sheet.paste(wide, (x+10, y0+312), wide)
            poses += 1
        if tick % 16 == 0:
            world = render(renderer, scene)
            panel = Image.new('RGB', (1220, 600), '#19232d')
            panel.paste(world, (0, 0), world)
            near = render(renderer, scene, size=(260, 380), scale=4,
                          origin=(floor(upper.x)-32, floor(upper.y)-30))
            panel.paste(near, (960, 25), near)
            ImageDraw.Draw(panel).text((970, 10), '4x nearest / same frame', fill='white')
            frames.append(panel)
    sheet.save(out/'oracle-pixel-comparison.png')
    frames[0].save(out/'oracle-pixel-preview.gif', save_all=True, append_images=frames[1:],
                   duration=400, loop=0, disposal=2)
    print('Saved oracle-pixel-comparison.png and oracle-pixel-preview.gif', flush=True)


if __name__ == '__main__':
    main()
