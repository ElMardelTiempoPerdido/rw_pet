"""真实场景的 Prince 触手移动预览，不读取或写入用户设置/角色文件"""
import argparse
import os
from pathlib import Path
import sys

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from PIL import Image
from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import QApplication

from rw_creature_pet.oracle.config import OracleConfig
from rw_creature_pet.oracle.graphics.render import OracleRenderer
from rw_creature_pet.oracle.motion.prince_tentacles import PrinceTentacles
from rw_creature_pet.oracle.prince_tentacles import DEFAULT_CONFIG, load_study
from rw_creature_pet.oracle.scene import OracleScene
from rw_creature_pet.shared.geometry import Vec2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=DEFAULT_CONFIG)
    parser.add_argument('--scenario', choices=('walk', 'corner', 'drag', 'stretch'), default='walk')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--scale', type=float, choices=(1, 1.5, 2, 3, 4), default=2)
    args = parser.parse_args()
    app = QApplication.instance() or QApplication([])
    scene = OracleScene(OracleConfig(body_appearance='prince', physics_backend='python',
        world_width=640, world_height=480, edge_fraction=.35, base_side='right',
        base_fraction=.6, halo_enabled=False, pearl_matrix_enabled=False,
        pearl_orbits_enabled=False, pearl_fixed_count=0))
    scene.prince_tentacles = PrinceTentacles(scene, load_study(args.config))
    scene.behavior.enabled = False
    renderer = OracleRenderer(colors=scene.config.active_colors)
    for _ in range(200):
        scene.step()
    start = scene.body.chunks[0].position
    frames = []
    scale = args.scale
    camera = (QRectF(400, 40, 240, 400) if args.scenario == 'walk'
              else QRectF(0, 0, scene.world.width, scene.world.height))
    width, height = round(camera.width()*scale), round(camera.height()*scale)
    output = args.output or ROOT/f'artifacts/prince/tentacles-{args.scenario}.gif'
    peak = None
    for tick in range(900):
        if args.scenario == 'walk':
            if tick == 40:
                scene.set_target(start+Vec2(0, -120))
            elif tick == 460:
                scene.set_target(start+Vec2(0, 40))
        elif args.scenario == 'corner':
            if tick == 40:
                scene.set_target(Vec2(390, 420))
        else:
            if tick == 40:
                scene.drag.set_enabled(True)
                scene.drag.press(scene.head.position, lambda _: True)
                pointer = scene.head.position
            if 40 < tick <= 180:
                offset = Vec2(-900, -45) if args.scenario == 'stretch' else Vec2(-90, -45)
                scene.drag.move(pointer+offset*((tick-40)/140))
            if tick == 300:
                scene.drag.release()
        if not scene.drag.active:
            scene.look_target = scene.body.chunks[0].position+Vec2(-60, 0)
        scene.step()
        if tick % 4:
            continue
        image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(QColor('#E8E5DF'))
        painter = QPainter(image)
        try:
            painter.scale(scale, scale)
            painter.translate(-camera.x(), -camera.y())
            painter.setPen(QPen(QColor('#AEA9A2'), 1.))
            painter.drawRect(QRectF(.5, .5, scene.world.width-1, scene.world.height-1))
            renderer.draw(painter, scene, raster_scale=scale)
        finally:
            painter.end()
        rgba = image.convertToFormat(QImage.Format.Format_RGBA8888)
        frame = Image.frombytes('RGBA', (width, height), bytes(rgba.constBits())).convert('RGB')
        frames.append(frame)
        if peak is None and any(p.transferring for p in scene.prince_tentacles.parts):
            peak = frame.copy()
    output.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(output, save_all=True, append_images=frames[1:], duration=100, loop=0, disposal=2)
    (peak or frames[0]).save(output.with_suffix('.png'))
    print(output)
    return app


if __name__ == '__main__':
    main()
