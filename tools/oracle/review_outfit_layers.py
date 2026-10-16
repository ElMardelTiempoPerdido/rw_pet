"""保存套装重构前后的固定姿态图，并逐像素比较，不读取或修改用户设置"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import argparse
from dataclasses import replace
from math import radians
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication
from rw_creature_pet.oracle.config import OracleConfig
from rw_creature_pet.oracle.graphics.appearance import OracleAppearance, perpendicular, rotate
from rw_creature_pet.oracle.graphics.render import OracleRenderer
from rw_creature_pet.oracle.scene import OracleScene
from rw_creature_pet.shared.geometry import Vec2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=('before', 'after'))
    args = parser.parse_args()
    app = QApplication.instance() or QApplication([])
    output = ROOT/'artifacts/outfit-layers'
    (output/args.stage).mkdir(parents=True, exist_ok=True)
    count, differences = 0, []
    for body in ('bell', 'custom'):
        for outfit in ('normal', 'maid'):
            for pose, angle, swing in (('rest', 0, 0), ('tilt', 30, 12), ('inverted', 180, -10)):
                scene = OracleScene(OracleConfig(body_appearance=body, outfit=outfit, hide_cords=True,
                                                halo_enabled=False, projection_opacity=0., physics_backend='python'))
                origin = Vec2(400, 300)
                direction = rotate(Vec2(0, -1), radians(angle))
                for part, position in zip((*scene.body.chunks, scene.head),
                                         (origin, origin-direction*9, origin+direction*14)):
                    part.position = part.previous_position = position
                    part.velocity = Vec2()
                scene.look_direction = scene.previous_look_direction = direction*.35
                scene.appearance = OracleAppearance(scene)
                n = scene.appearance.CLOTH_DIVS
                for i, part in enumerate(scene.appearance.cloth):
                    part.position += perpendicular(direction)*(swing*(i//n)/(n-1))
                    part.previous_position = part.position
                for scale, coarse in ((1., False), (1.5, False), (2., False), (3., False), (4., False), (4., True)):
                    for glow in (False, True):
                        scene.config = replace(scene.config, coarse_pixels_4x=coarse, glow_enabled=glow)
                        renderer = OracleRenderer()
                        image = QImage(round(100*scale), round(100*scale), QImage.Format.Format_ARGB32_Premultiplied)
                        image.fill(0)
                        painter = QPainter(image)
                        try:
                            painter.scale(scale, scale)
                            painter.translate(50-origin.x, 50-origin.y)
                            renderer.draw(painter, scene, cords=False, raster_scale=scale)
                        finally:
                            painter.end()
                        name = f'{body}-{outfit}-{pose}-{scale:g}-{int(coarse)}-{int(glow)}.png'
                        assert image.save(str(output/args.stage/name))
                        baseline = QImage(str(output/'before'/name)).convertToFormat(image.format())
                        if args.stage == 'after' and image != baseline:
                            differences.append(name)
                        count += 1
    print(f'{args.stage}: {count} frames; differences: {differences}')
    if differences:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
