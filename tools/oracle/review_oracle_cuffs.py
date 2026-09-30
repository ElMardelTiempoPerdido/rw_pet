"""真实素材袖口圆角对照：按实际倍率生成像素，再等尺寸放大供检查。"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import argparse
from dataclasses import replace
from math import floor
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication
from rw_creature_pet.config import AppConfig
from rw_creature_pet.oracle.appearance import perpendicular
from rw_creature_pet.oracle.render import OracleRenderer, mixed
from rw_creature_pet.oracle.scene import OracleScene
from rw_creature_pet.shared.atlas import Atlas, extract_atlas


class PuppetRenderer(OracleRenderer):
    def draw_arm(self, *args):
        pass  # 近景中只看人偶，避免机械臂遮住袖口。


class SquareCuffRenderer(PuppetRenderer):
    SLEEVE_CUFF_RADIUS = 0.

    def draw_sleeve(self, painter, edges):
        c = self.colors
        self.transverse_strip(painter, edges, mixed(c.robe_top, c.robe_bottom, .4**2), c.robe_top)


class CenteredCuffRenderer(PuppetRenderer):
    SLEEVE_CUFF_DROP = 0.


def paint(renderer, scene, scale):
    image = QImage(round(60*scale), round(60*scale), QImage.Format.Format_RGBA8888)
    image.fill(0)
    painter = QPainter(image)
    try:
        painter.scale(scale, scale)
        upper = scene.appearance.upper
        painter.translate(30-floor(upper.x), 22-floor(upper.y))
        renderer.draw(painter, scene, 1., cords=False)
    finally:
        painter.end()
    return Image.frombytes('RGBA', (image.width(), image.height()), bytes(image.constBits()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--effect', choices=('rounding', 'drape'), default='rounding')
    args = parser.parse_args()
    before_cls = CenteredCuffRenderer if args.effect == 'drape' else SquareCuffRenderer
    prefix = 'oracle-cuff-drape' if args.effect == 'drape' else 'oracle-cuffs'
    app = QApplication.instance() or QApplication([])
    config = AppConfig.load(ROOT/'config.toml')
    oracle = replace(config.oracle, halo_enabled=False, glow_enabled=False,
                     pearl_matrix_enabled=False, pearl_orbits_enabled=False, pearl_fixed_count=0)
    atlas = Atlas(extract_atlas(config.game_dir))
    output = ROOT/'artifacts'
    output.mkdir(exist_ok=True)
    poses = []
    for label, raised, tilt in (('Rest', False, 0), ('Raised', True, 0), ('Tilted', True, 25)):
        scene = OracleScene(oracle)
        scene.set_tilt(tilt)
        for _ in range(650):
            scene.step()
        if raised:
            a = scene.appearance
            for i, hand in enumerate(a.hands):
                sign = -1 if i == 0 else 1
                shoulder = hand.shoulder(a.upper, a.direction, i)
                hand.pin(shoulder+perpendicular(a.direction)*(sign*14)+a.direction*(5 if i else -3))
        poses.append((label, scene))
    for mode in ('adaptive', 'classic'):
        sheet = Image.new('RGB', (1080, 690), '#19232d')
        labels = ImageDraw.Draw(sheet)
        for row, (pose, scene) in enumerate(poses):
            scene.config = replace(scene.config, pixel_mode=mode)
            for column, scale in enumerate((1., 1.5, 2.)):
                x, y = column*360, row*230
                labels.text((x+10, y+6), f'{pose} / {mode} / display {scale:g}x', fill='white')
                for side, cls in enumerate((before_cls, PuppetRenderer)):
                    native = paint(cls(atlas, oracle.colors), scene, scale)
                    native.save(output/f'{prefix}-{mode}-{pose.lower()}-{scale:g}x-{side}.png')
                    view = native.resize((180, 180), Image.Resampling.NEAREST)
                    sheet.paste(view, (x+side*180, y+40), view)
                    labels.text((x+side*180+10, y+23), 'Before' if side == 0 else args.effect.title(), fill='white')
        sheet.save(output/f'{prefix}-{mode}.png')
    print(f'Saved artifacts/{prefix}-adaptive.png and {prefix}-classic.png')


if __name__ == '__main__':
    main()
